"""Conservative, offline context-first-v1 composition (standard library only).

compose_pages(canonical_pages, mineru_pages) -> (pages, provenance)
Inputs are lists of {page: positive int, text: str}, or objects with such a
``pages`` list. Page identity, never list position, joins the two sources.
Canonical means the *already J-adjudicated* PDF text, not a fresh WPS reading.

Provenance schema 1 uses Python Unicode code-point, half-open offsets. ``spans``
partition every output character. Each span has source, page, start/end and
output_start/output_end; copy spans reproduce the exact source slice.
``alignment`` additionally maps canonical non-whitespace characters to MinerU
visible text, including immutable table text. ``whitespace`` explicitly records
the only normalization used for alignment. Original source strings are retained
in each page report so a report is independently auditable and JSON serializable.

``ok`` means all pages composed without a degradation/error, not that OCR was
verified against a PDF. Small substitutions require unique surrounding anchors;
this is a conservative textual placement policy, not a claim of semantic proof.
Unknown syntax, ambiguous placement and table disagreement return ``degraded``.
The fallback keeps canonical verbatim and every material span, with explicit
placement/duplication issues. It does not silently choose MinerU body text.
Consumers MUST inspect ok/status/issues before treating the result as final.
No I/O, OCR, agents, third-party parsers, or layout exclusion decisions occur.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from html.parser import HTMLParser
import re


SCHEMA_VERSION = 1
WORKFLOW = "context-first-v1"
ANCHOR = 8
MAX_EDIT = 4
_TAG = re.compile(r"<!--.*?-->|<(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.S)
_ENTITY = re.compile(r"&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);")
_DEF = re.compile(r"(?m)^ {0,3}\[([^\]\n]+)\]:[^\n]*(?:\n|$)")


@dataclass(frozen=True)
class Region:
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class Letter:
    char: str
    start: int
    end: int
    kind: str
    region: int


def _issue(code, **details):
    return {"code": code, **details}


def _compact(text):
    """Normalize layout runs while retaining whether a separator exists.

    Removing every whitespace character made ``中国`` and ``中 国`` compare
    equal, so J/S4 corrections could be lost during composition.  A run is
    now one alignment token: line wrapping is normalized, but a missing or
    added separator remains a real textual difference.
    """
    result, in_space = [], False
    for char in text:
        if char.isspace():
            if not in_space:
                result.append(" ")
            in_space = True
        else:
            result.append(char)
            in_space = False
    return "".join(result)


def _token_values(raw, offset=0):
    """Return visible alignment tokens with exact source spans."""
    values, index = [], 0
    while index < len(raw):
        if raw[index].isspace():
            start = index
            index += 1
            while index < len(raw) and raw[index].isspace():
                index += 1
            values.append((" ", offset + start, offset + index))
        else:
            values.append((raw[index], offset + index, offset + index + 1))
            index += 1
    return values


def _label(text):
    return " ".join(text.split()).casefold()


def _balanced(text, start, opening, closing):
    """Balanced Markdown brackets/URLs, including escaped punctuation."""
    depth, i = 0, start
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == opening:
            depth += 1
        elif text[i] == closing:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


class _TableText(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=False)
        self.offsets = [0]
        self.offsets.extend(m.end() for m in re.finditer("\n", raw))
        self.letters = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def _data(self, raw, decoded):
        if self.hidden:
            return
        line, column = self.getpos()
        start = self.offsets[line - 1] + column
        if raw == decoded:
            self.letters.extend((c, start + i, start + i + 1)
                                for i, c in enumerate(raw) if not c.isspace())
        else:
            self.letters.extend((c, start, start + len(raw))
                                for c in decoded if not c.isspace())

    def handle_data(self, data):
        self._data(data, data)

    def handle_entityref(self, name):
        raw = "&" + name + ";"
        self._data(raw, unescape(raw))

    def handle_charref(self, name):
        raw = "&#" + name + ";"
        self._data(raw, unescape(raw))


def _parse(text, *, allow_tables=True):
    """A deliberately bounded Markdown dialect; uncertain constructs are issues.

    Images use balanced brackets/parentheses, HTML tags use quote-aware spans.
    Unlike ocr_review's regex fallback this preserves multiline img tags and
    '>' inside attributes. No optional markdown-it installation changes behavior.
    """
    regions, issues = [], []
    definitions = {_label(m.group(1)) for m in _DEF.finditer(text)}

    def add(start, end, kind):
        if end > start:
            regions.append(Region(start, end, kind))

    def inline(start, end):
        i = start
        while i < end:
            if text.startswith("![", i) or text[i] == "[":
                image = text.startswith("![", i)
                bracket = i + int(image)
                close = _balanced(text, bracket, "[", "]")
                finish = None
                if close and close <= end:
                    cursor = close
                    while cursor < end and text[cursor] in " \t":
                        cursor += 1
                    if cursor < end and text[cursor] == "(":
                        finish = _balanced(text, cursor, "(", ")")
                    elif cursor < end and text[cursor] == "[":
                        ref_end = _balanced(text, cursor, "[", "]")
                        if ref_end:
                            ref = text[cursor + 1:ref_end - 1] or text[bracket + 1:close - 1]
                            if _label(ref) in definitions:
                                finish = ref_end
                            else:
                                issues.append(_issue("unresolved_reference", start=i))
                                finish = ref_end if image else None
                    elif _label(text[bracket + 1:close - 1]) in definitions:
                        finish = close
                if finish and finish <= end:
                    if image:
                        add(i, finish, "image")
                    else:
                        add(i, bracket + 1, "syntax")
                        inline(bracket + 1, close - 1)
                        add(close - 1, finish, "syntax")
                    i = finish
                    continue
                if image:
                    issues.append(_issue("unparsed_image", start=i))
                    add(i, end, "opaque")
                    return
            tag = _TAG.match(text, i) if text[i] == "<" else None
            if tag and tag.end() <= end:
                raw = tag.group()
                if re.match(r"<img\b", raw, re.I):
                    kind = "image"
                elif raw.startswith("<!--") or re.match(r"<br\s*/?>", raw, re.I):
                    kind = "syntax"
                else:
                    kind = "opaque"
                    issues.append(_issue("unsupported_html", start=i, end=tag.end()))
                add(i, tag.end(), kind)
                i = tag.end()
                continue
            if text[i] == "\\" and i + 1 < end and text[i + 1] in r"\`*_{}[]()#+-.!|>":
                add(i, i + 1, "syntax")
                add(i + 1, i + 2, "body")
                i += 2
                continue
            entity = _ENTITY.match(text, i)
            if entity and entity.end() <= end:
                add(i, entity.end(), "encoding")
                i = entity.end()
                continue
            if text[i] in "*_~`$":
                delimiter = re.match(r"(\*+|_+|~+|`+|\$+)", text[i:end]).group()
                close = text.find(delimiter, i + len(delimiter), end)
                if delimiter in {"*", "**", "_", "__", "~~"} and close > i + len(delimiter):
                    add(i, i + len(delimiter), "syntax")
                    inline(i + len(delimiter), close)
                    add(close, close + len(delimiter), "syntax")
                    i = close + len(delimiter)
                    continue
                # Code/math require a different visible-text model. Preserve them
                # as material on degradation; never feed their syntax to matching.
                if text[i] in "`$" and close >= i + len(delimiter):
                    finish = close + len(delimiter)
                    add(i, finish, "opaque")
                    issues.append(_issue("unsupported_code_or_math", start=i, end=finish))
                    i = finish
                    continue
                issues.append(_issue("ambiguous_delimiter", start=i))
            add(i, i + 1, "whitespace" if text[i].isspace() else "body")
            i += 1

    # Discover whole tables first; inline image parsing cannot swallow a table.
    tables, depth, table_start = [], 0, None
    if allow_tables:
        for tag in _TAG.finditer(text):
            if re.match(r"<table\b", tag.group(), re.I):
                if depth == 0:
                    table_start = tag.start()
                depth += 1
            elif re.match(r"</table\s*>", tag.group(), re.I) and depth:
                depth -= 1
                if depth == 0:
                    tables.append((table_start, tag.end(), "html_table"))
        if depth:
            tables.append((table_start, len(text), "opaque"))
            issues.append(_issue("unclosed_table", start=table_start))
        lines = list(re.finditer(r"[^\n]*(?:\n|$)", text))
        for n in range(1, len(lines)):
            delimiter = lines[n].group().strip().strip("|").strip()
            cells = [cell.strip() for cell in delimiter.split("|")]
            if ("|" not in lines[n].group() or not cells
                    or not all(re.fullmatch(r":?-{3,}:?", c) for c in cells)
                    or "|" not in lines[n - 1].group()):
                continue
            start, end = lines[n - 1].start(), lines[n].end()
            for row in lines[n + 1:]:
                if "|" not in row.group() or not row.group().strip():
                    break
                end = row.end()
            if not any(start < b and end > a for a, b, _ in tables):
                tables.append((start, end, "markdown_table"))
    table_at = {a: (b, k) for a, b, k in tables}
    definition_at = {m.start(): m.end() for m in _DEF.finditer(text)}
    i = 0
    while i < len(text):
        if i in table_at:
            end, kind = table_at[i]
            add(i, end, kind)
            i = end
            continue
        if i in definition_at:
            add(i, definition_at[i], "definition")
            i = definition_at[i]
            continue
        # Stop at the next table even when an HTML table starts mid-line.
        end = text.find("\n", i)
        end = len(text) if end < 0 else end + 1
        end = min([end] + [a for a in table_at if i < a < end])
        line = text[i:end]
        # Multiline image markup is a single immutable source region.
        img = re.search(r"<img\b", line, re.I)
        if img:
            tag = _TAG.match(text, i + img.start())
            if tag and tag.end() > end:
                end = tag.end()
                line = text[i:end]
        prefix = re.match(r" {0,3}(?:#{1,6}[ \t]+|>[ \t]?|[-+*][ \t]+|\d{1,9}[.)][ \t]+)", line)
        if prefix:
            add(i, i + prefix.end(), "syntax")
            inline(i + prefix.end(), end)
        elif re.fullmatch(r"[ \t]*(?:[-*_][ \t]*){3,}\r?\n?", line):
            add(i, end, "syntax")
        elif re.match(r"\s*(?:```|~~~)", line):
            fence = re.match(r"\s*(`{3,}|~{3,})", line).group(1)
            closing = re.search(r"(?m)^ {0,3}" + re.escape(fence) + r"[ \t]*$", text[end:])
            finish = end + closing.end() if closing else len(text)
            add(i, finish, "opaque")
            issues.append(_issue("unsupported_fence", start=i, end=finish))
            end = finish
        else:
            inline(i, end)
        i = end

    # Coalesce only plain runs. Material identity and ordering stay explicit.
    merged = []
    for region in regions:
        if (merged and region.kind in {"body", "whitespace", "syntax"}
                and merged[-1].kind == region.kind and merged[-1].end == region.start):
            merged[-1] = Region(merged[-1].start, region.end, region.kind)
        else:
            merged.append(region)
    letters = []
    for index, region in enumerate(merged):
        raw = text[region.start:region.end]
        values = []
        if region.kind in {"body", "whitespace"}:
            values = _token_values(raw)
        elif region.kind == "encoding":
            values = [(c, 0, len(raw)) for c in unescape(raw) if not c.isspace()]
        elif region.kind == "html_table":
            parser = _TableText(raw)
            parser.feed(raw)
            parser.close()
            values = parser.letters
        elif region.kind == "markdown_table":
            offset = 0
            for row_number, row in enumerate(raw.splitlines(keepends=True)):
                if row_number != 1:
                    # Escaped pipes belong to cell text; unescaped ones are syntax.
                    for cell in re.finditer(r"(?:\\.|[^|])+", row):
                        _, child_letters, child_issues = _parse(cell.group(), allow_tables=False)
                        issues.extend(_issue("unsupported_table_cell", start=region.start + offset + cell.start(), detail=e)
                                      for e in child_issues)
                        values.extend((c.char, offset + cell.start() + c.start,
                                       offset + cell.start() + c.end) for c in child_letters)
                offset += len(row)
        letters.extend(Letter(c, region.start + a, region.start + b, region.kind, index)
                       for c, a, b in values)
    return merged, letters, issues


class _Output:
    def __init__(self, page, canonical, mineru):
        self.page, self.sources = page, {"canonical": canonical, "mineru": mineru}
        self.parts, self.spans, self.size = [], [], 0

    def add(self, source, start, end, kind, *, whitespace=None):
        value = self.sources[source][start:end] if whitespace is None else whitespace
        if not value:
            return
        span = {"output_start": self.size, "output_end": self.size + len(value),
                "source": source, "page": self.page, "start": start, "end": end,
                "kind": kind, "transform": "copy" if whitespace is None else "whitespace"}
        if (self.spans and whitespace is None and self.spans[-1]["transform"] == "copy"
                and all(self.spans[-1][key] == span[key] for key in ("source", "page", "kind"))
                and self.spans[-1]["end"] == start):
            self.spans[-1]["end"] = end
            self.spans[-1]["output_end"] = span["output_end"]
        else:
            self.spans.append(span)
        self.parts.append(value)
        self.size += len(value)

    def separator(self, offset):
        # A zero-width canonical boundary is the source of inserted layout space.
        self.add("canonical", offset, offset, "layout", whitespace="\n\n")

    def finish(self):
        return "".join(self.parts)


def _unique_anchor(op, a, b):
    if op is None or op[0] != "equal" or op[2] - op[1] < ANCHOR:
        return False
    fragment = a[op[1]:op[2]]
    return (a.find(fragment) == a.rfind(fragment)
            and b.find(fragment) == b.rfind(fragment))


def _alignment(canonical, mineru, regions, letters):
    canonical_tokens = _token_values(canonical)
    positions = [start for _, start, _ in canonical_tokens]
    ends = [end for _, _, end in canonical_tokens]
    a, b = _compact(canonical), "".join(c.char for c in letters)
    opcodes = SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    mapping, edits, issues = {}, [], []
    for index, op in enumerate(opcodes):
        tag, a0, a1, b0, b1 = op
        if tag == "equal":
            mapping.update((j, a0 + j - b0) for j in range(b0, b1))
            continue
        before = opcodes[index - 1] if index else None
        after = opcodes[index + 1] if index + 1 < len(opcodes) else None
        anchored = ((a0 == b0 == 0 or _unique_anchor(before, a, b))
                    and (a1 == len(a) and b1 == len(b) or _unique_anchor(after, a, b)))
        start = letters[b0].start if b0 < len(letters) else len(mineru)
        end = letters[b1 - 1].end if b1 > b0 else start
        ca = positions[a0] if a0 < len(positions) else len(canonical)
        cb = ends[a1 - 1] if a1 > a0 else ca
        # Canonical-only opening/closing *lines* have a known page-edge location.
        # Keep a missing document title outside the first MinerU heading markup.
        if tag == "delete" and anchored and a0 == 0 and b0 == 0:
            boundary = positions[a1] if a1 < len(positions) else len(canonical)
            if "\n" in canonical[:boundary]:
                edits.append((0, 0, 0, boundary))
                continue
        if tag == "delete" and anchored and a1 == len(a) and b1 == len(b):
            boundary = ends[a0 - 1] if a0 else 0
            if "\n" in canonical[boundary:]:
                edits.append((len(mineru), len(mineru), boundary, len(canonical)))
                continue
        body_only = all(r.kind in {"body", "whitespace"} for r in regions
                        if r.start < end and r.end > start)
        if b0 == b1:
            # Inserting across a heading, image, emphasis or block break is not
            # a safe character edit, even if SequenceMatcher picked one side.
            left = letters[b0 - 1].end if b0 else 0
            right = letters[b0].start if b0 < len(letters) else len(mineru)
            gap = mineru[left:right]
            body_only = (not gap.strip() and "\n" not in gap
                         and (b0 == 0 or letters[b0 - 1].kind in {"body", "whitespace"})
                         and (b0 == len(letters) or letters[b0].kind in {"body", "whitespace"}))
        if (anchored and body_only and max(a1 - a0, b1 - b0) <= MAX_EDIT
                and sum(x[2] - x[1] for x in opcodes if x[0] == "equal")
                >= .85 * max(len(a), len(b))):
            edits.append((start, end, ca, cb))
        else:
            issues.append(_issue("unreliable_alignment", canonical_start=ca, canonical_end=cb,
                                 mineru_start=start, mineru_end=end,
                                 reason="table_or_syntax_conflict" if not body_only else "weak_or_ambiguous_anchors"))
    return positions, ends, opcodes, mapping, edits, issues


_MATERIAL = {"image", "definition", "html_table", "markdown_table", "opaque"}


def _visible_characters(text):
    """Compare table content without treating Markdown delimiters as OCR text."""
    parsed_regions, parsed_letters, parsed_issues = _parse(text)
    if parsed_issues:
        return None
    if any(region.kind in {"html_table", "markdown_table"} for region in parsed_regions):
        return "".join(letter.char for letter in parsed_letters if not letter.char.isspace())
    return "".join(char for char in text if not char.isspace())


def _fallback(page, canonical, mineru, regions, letters, opcodes, mapping, positions, ends, issues):
    out = _Output(page, canonical, mineru)
    a, b = _compact(canonical), "".join(c.char for c in letters)
    trusted = set()
    for op in opcodes:
        if a == b or _unique_anchor(op, a, b):
            trusted.update(range(op[3], op[4]))
    placements = []
    last_position = 0
    for region in regions:
        if region.kind not in _MATERIAL:
            continue
        left = next((j for j in range(len(letters) - 1, -1, -1)
                     if letters[j].end <= region.start and j in trusted), None)
        right = next((j for j in range(len(letters))
                      if letters[j].start >= region.end and j in trusted), None)
        lower = ends[mapping[left]] if left is not None else 0
        upper = positions[mapping[right]] if right is not None else len(canonical)
        if lower <= upper and not canonical[lower:upper].strip() and upper >= last_position:
            position = upper
            placement = "anchored"
        else:
            position = len(canonical)
            placement = "unplaced_at_end"
            issues.append(_issue("material_position_unknown", mineru_start=region.start,
                                 mineru_end=region.end, placement=placement))
        if region.kind in {"html_table", "markdown_table"}:
            issues.append(_issue("table_preserved_unreconciled", mineru_start=region.start,
                                 mineru_end=region.end, possible_duplicate_canonical_text=True))
        last_position = position
        placements.append((position, region, placement))
    cursor = 0
    materials = []
    for position, region, placement in placements:
        out.add("canonical", cursor, position, "body")
        out.separator(position)
        output_start = out.size
        out.add("mineru", region.start, region.end, region.kind)
        materials.append({"start": region.start, "end": region.end, "kind": region.kind,
                          "output_start": output_start, "output_end": out.size, "placement": placement})
        out.separator(position)
        cursor = position
    out.add("canonical", cursor, len(canonical), "body")
    return out, materials


def _compose(page, canonical, mineru, missing):
    regions, letters, issues = _parse(mineru)
    issues.extend(_issue(code) for code in missing)
    has_table = any(region.kind in {"html_table", "markdown_table"} for region in regions)
    if not issues and has_table:
        canonical_visible = _visible_characters(canonical)
        mineru_visible = "".join(letter.char for letter in letters if not letter.char.isspace())
        if canonical_visible is not None and canonical_visible == mineru_visible:
            out = _Output(page, canonical, mineru)
            out.add("mineru", 0, len(mineru), "structural")
            materials = []
            for region in regions:
                if region.kind in _MATERIAL:
                    materials.append({"start": region.start, "end": region.end, "kind": region.kind,
                                      "output_start": out.size - len(mineru) + region.start,
                                      "output_end": out.size - len(mineru) + region.end,
                                      "placement": "table_visible_match"})
            rendered = out.finish()
            expected = [(r.start, r.end, r.kind) for r in regions if r.kind in _MATERIAL]
            actual = [(r["start"], r["end"], r["kind"]) for r in materials]
            if expected != actual:
                raise AssertionError("table material mapping failure")
            return {"page": page, "text": rendered}, {
                "page": page, "status": "composed", "format": "markdown",
                "issues": [], "sources": {"canonical": canonical, "mineru": mineru},
                "spans": out.spans, "alignment": [], "materials": materials, "edits": [],
                "whitespace": {"policy": "table visible text matched; preserve MinerU table syntax",
                               "canonical_ranges": [[m.start(), m.end()] for m in re.finditer(r"\s+", canonical)],
                               "fallback": "canonical verbatim; table syntax remains MinerU structural source"},
                "canonical_token_count": len(_token_values(canonical)), "materials_preserved": True,
                "table_visible_match": True,
            }
    positions, ends, opcodes, mapping, edits, alignment_issues = _alignment(canonical, mineru, regions, letters)
    issues.extend(alignment_issues)
    alignment = [{"canonical_start": positions[ci], "canonical_end": ends[ci],
                  "mineru_start": letters[j].start, "mineru_end": letters[j].end,
                  "kind": letters[j].kind} for j, ci in sorted(mapping.items())]
    if issues:
        out, materials = _fallback(page, canonical, mineru, regions, letters, opcodes, mapping,
                                    positions, ends, issues)
        status = "degraded"
    else:
        out = _Output(page, canonical, mineru)
        # Convert aligned body letters and bounded edits into non-overlapping
        # replacements. Everything else is copied from the structural source.
        replacements = [(letters[j].start, letters[j].end, positions[ci], ends[ci])
                        for j, ci in mapping.items() if letters[j].kind == "body"] + edits
        replacements.sort(key=lambda x: (x[0], x[1]))
        cursor = 0
        materials = []
        region_starts = [r.start for r in regions]

        def copy_mineru(start, end):
            n = max(0, bisect_left(region_starts, start) - 1)
            for r in regions[n:]:
                if r.start >= end:
                    break
                lo, hi = max(start, r.start), min(end, r.end)
                if lo < hi:
                    output_start = out.size
                    out.add("mineru", lo, hi, r.kind)
                    if r.kind in _MATERIAL:
                        materials.append({"start": lo, "end": hi, "kind": r.kind,
                                          "output_start": output_start, "output_end": out.size,
                                          "placement": "aligned"})

        for start, end, ca, cb in replacements:
            if start < cursor:
                raise AssertionError("overlapping internal alignment edits")
            copy_mineru(cursor, start)
            out.add("canonical", ca, cb, "body")
            cursor = end
        copy_mineru(cursor, len(mineru))
        status = "composed"
    rendered = out.finish()
    # Exact span checks, not media signatures: alt, attributes, URLs and tables
    # are protected byte-for-byte in Unicode strings, including duplicates.
    expected = [(r.start, r.end, r.kind) for r in regions if r.kind in _MATERIAL]
    actual = [(r["start"], r["end"], r["kind"]) for r in materials]
    if expected != actual or any(mineru[r["start"]:r["end"]] != rendered[r["output_start"]:r["output_end"]]
                                 for r in materials):
        raise AssertionError("internal material preservation failure")
    return {"page": page, "text": rendered}, {
        "page": page, "status": status, "format": "markdown" if status == "composed" else "canonical_with_assets",
        "issues": issues, "sources": {"canonical": canonical, "mineru": mineru},
        "spans": out.spans, "alignment": alignment, "materials": materials,
        "edits": [{"mineru_start": s, "mineru_end": e, "canonical_start": a, "canonical_end": b}
                  for s, e, a, b in edits],
        "whitespace": {"policy": "collapse consecutive Unicode whitespace to one alignment token; retain MinerU layout",
                       "canonical_ranges": [[m.start(), m.end()] for m in re.finditer(r"\s+", canonical)],
                       "fallback": "canonical verbatim; inserted separators have zero-width source anchors"},
        "canonical_token_count": len(positions),
        "materials_preserved": True,
    }


def _pages(value, name):
    rows = value.get("pages") if isinstance(value, dict) else value
    if not isinstance(rows, (list, tuple)):
        raise ValueError(f"{name} must be a page list or an object with pages")
    result = {}
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("page")) is not int
                or row["page"] < 1 or not isinstance(row.get("text"), str)):
            raise ValueError(f"{name} requires positive integer page and string text")
        if row["page"] in result:
            raise ValueError(f"{name} has duplicate page {row['page']}")
        result[row["page"]] = row["text"]
    return result


def compose_pages(canonical_pages, mineru_pages):
    """Compose without mutating inputs; invalid schemas raise ValueError.

    Missing/extra pages are retained in sorted union order and marked degraded.
    Return ``([{page, text}, ...], {schema_version, workflow, ok, status, pages})``.
    Every report includes exact source maps, issues and immutable material spans.
    This function never applies layout exclusions or re-adjudicates canonical.
    """
    canonical, mineru = _pages(canonical_pages, "canonical"), _pages(mineru_pages, "mineru")
    rendered, reports = [], []
    for page in sorted(canonical.keys() | mineru.keys()):
        missing = ([] if page in canonical else ["missing_canonical_page"])
        missing += ([] if page in mineru else ["missing_mineru_page"])
        result, report = _compose(page, canonical.get(page, ""), mineru.get(page, ""), missing)
        rendered.append(result)
        reports.append(report)
    ok = all(p["status"] == "composed" for p in reports)
    return rendered, {"schema_version": SCHEMA_VERSION, "workflow": WORKFLOW,
                      "ok": ok, "status": "composed" if ok else "degraded", "pages": reports}
