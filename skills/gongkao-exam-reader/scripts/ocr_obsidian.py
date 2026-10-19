#!/usr/bin/env python3
"""Export an accepted exam-lite candidate as an Obsidian question notebook.

The exporter is deliberately deterministic and conservative.  It packages the
accepted candidate into question/material callouts, but never changes the
candidate in-place and never invents a question boundary when the source is
ambiguous.  The source-map describes the generated snapshot, not later user
edits made in Obsidian.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
from pathlib import Path

from ocr_review import (  # script-local module
    EXAM_LITE_PROTOCOL_REVISION,
    EXAM_LITE_TOPOLOGY,
    EXAM_LITE_WORKFLOW,
    dump,
    media_nodes,
    pages_of,
    validate_source_map,
)


PROTOCOL_REVISION = 1
_QUESTION_RE = re.compile(
    r"(?<![A-Za-z0-9.])(?P<open>\*{0,2})(?P<number>[1-9]\d{0,2})\.(?P<close>\*{0,2})(?!\d)"
)
_QUESTION_YEAR_RE = re.compile(
    r"(?<![A-Za-z0-9.])(?P<open>\*{0,2})(?P<number>[1-9]\d{0,2})\.(?P<close>\*{0,2})(?=(?:19|20)\d{2}(?:[-—年]))"
)
_OPTION_RE = re.compile(r"(?<![A-Za-z0-9])([A-D])\.(?=[^\n])")
_CIRCLE_MARKS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_DATA_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(data:image/(?P<mime>[A-Za-z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=\s]+)\)",
    re.I,
)
_HTML_DATA_IMAGE_RE = re.compile(
    r"<img\b(?P<attrs>[^>]*?\bsrc\s*=\s*[\"'])(?P<data>data:image/(?P<mime>[A-Za-z0-9.+-]+);base64,(?P<payload>[A-Za-z0-9+/=\s]+))([\"'][^>]*)>",
    re.I,
)
_MATERIAL_HEADING_RE = re.compile(r"^\s*#{1,6}\s*(?P<title>（[一二三四五六七八九十]+）)\s*$")
_DATA_HEADING_RE = re.compile(r"^\s*#{1,6}\s*(?P<title>\d{4}[-—]\d{4}年.*)$")
_FIGURE_HEADING_RE = re.compile(r"^\s*(?P<title>图\s*\d+.*)$")
_SUBJECT_HEADING_RE = re.compile(r"^\s*(?P<title>[一二三四五六七八九十]+[.．、]\s*[^\n]+)$")


def _safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", str(value)).strip(" .")
    return value or "exam"


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _page_stream(pages):
    """Join pages while retaining a reversible page-local offset index."""
    chunks = []
    spans = []
    cursor = 0
    for index, page in enumerate(pages):
        text = str(page.get("text", "")).replace("\r\n", "\n").replace("\r", "\n")
        start = cursor
        chunks.append(text)
        cursor += len(text)
        spans.append({"page": int(page["page"]), "start": start, "end": cursor, "text": text})
        if index != len(pages) - 1:
            chunks.append("\n\n")
            cursor += 2
    return "".join(chunks), spans


def _source_ranges(spans, start, end):
    ranges = []
    for item in spans:
        left = max(start, item["start"])
        right = min(end, item["end"])
        if left < right or (start == end and item["start"] <= start <= item["end"]):
            ranges.append({"page": item["page"], "start": max(0, left - item["start"]), "end": max(0, right - item["start"])})
    return ranges


def _page_for_offset(spans, offset):
    for item in spans:
        if item["start"] <= offset <= item["end"]:
            return item["page"]
    return spans[-1]["page"] if spans else 1


def _question_section_key(stream, offset):
    headings = list(re.finditer(r"(?m)^\s*#{1,3}\s+(?P<title>[^\n]+)", stream[:offset]))
    title = headings[-1].group("title").strip() if headings else "section"
    return f"s-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:8]}"


def _protected_global_ranges(pages, spans):
    result = []
    for page, item in zip(pages, spans):
        try:
            _nodes, protected, _signature = media_nodes(page.get("text", ""))
        except (TypeError, ValueError):
            protected = []
        result.extend((item["start"] + left, item["start"] + right) for left, right in protected)
    return result


def _inside_ranges(offset, ranges):
    return any(left <= offset < right for left, right in ranges)


def _question_markers(stream, protected):
    occurrences = []
    matches = list(_QUESTION_RE.finditer(stream)) + list(_QUESTION_YEAR_RE.finditer(stream))
    for match in sorted(matches, key=lambda item: item.start()):
        if _inside_ranges(match.start(), protected):
            continue
        number = int(match.group("number"))
        if number > 300:
            continue
        before = stream[match.start() - 1] if match.start() else ""
        embedded = bool(before and (before.isalnum() or "\u3400" <= before <= "\u9fff"))
        occurrences.append({
            "number": number,
            "start": match.start(),
            "end": match.end(),
            "raw": match.group(0),
            "embedded": embedded,
        })
    unique = {}
    for occurrence in occurrences:
        unique[(occurrence["start"], occurrence["end"])] = occurrence
    return [unique[key] for key in sorted(unique)]


def _select_markers(occurrences, boundaries=None, stream=""):
    """Select a monotonic question sequence and report skipped numbers.

    The sequence check is important for OCR pages containing decimal values or
    years.  It is not a claim that every omitted number is absent from the PDF;
    it is an explicit unresolved item for a human to verify.
    """
    overrides = {}
    for row in (boundaries or {}).get("questions", []) if isinstance(boundaries, dict) else []:
        if not isinstance(row, dict) or type(row.get("number")) is not int:
            continue
        if type(row.get("offset")) is int:
            overrides[row["number"]] = row
    selected = []
    unresolved = []
    expected = 1
    last = -1
    for occurrence in occurrences:
        number = occurrence["number"]
        override = overrides.get(number)
        if occurrence.get("embedded") and not (
            isinstance(override, dict)
            and type(override.get("offset")) is int
            and override.get("offset") == occurrence["start"]
            and override.get("evidence")
        ):
            unresolved.append({"kind": "embedded_question_marker", "number": number,
                               "offset": occurrence["start"], "raw": occurrence["raw"],
                               "message": "题号嵌入正文且没有经核实的边界证据，保留原位，不猜测题目边界。"})
            continue
        has_section_reset = False
        if selected:
            between = stream[selected[-1]["end"]:occurrence["start"]]
            has_section_reset = bool(re.search(r"(?m)^\s*(?:#{1,3}\s+|（[一二三四五六七八九十]+）\s*$)", between))
        if number <= last and not (has_section_reset or override):
            continue
        if number < expected and not (has_section_reset or override):
            continue
        if has_section_reset and number <= last:
            expected = number
        if number != expected:
            unresolved.append({"kind": "missing_question_marker", "expected": expected, "observed": number,
                               "message": "未找到可可靠确认的连续题号，未猜测题目边界。"})
        selected.append(occurrence)
        last = number
        expected = number + 1
        if override:
            occurrence["boundary_override"] = {key: override.get(key) for key in ("page", "offset", "evidence") if key in override}
        if expected > 300:
            break
    return selected, unresolved


def _line_offsets(text):
    cursor = 0
    for line in text.splitlines(keepends=True):
        yield cursor, cursor + len(line), line.rstrip("\r\n")
        cursor += len(line)


def _find_material_boundary(body):
    """Find an explicit material/section boundary inside a question span."""
    candidates = []
    offset = 0
    for line_start, line_end, line in _line_offsets(body):
        stripped = line.strip()
        if not stripped:
            offset = line_end
            continue
        # Source candidates sometimes lose the Markdown heading marker around
        # a shared-material label, or leave it wrapped in bold.  The standalone
        # parenthesized label is still reliable as a structural boundary.
        boundary_line = re.sub(r"^\s*\*{2}|\*{2}\s*$", "", line).strip()
        match = _MATERIAL_HEADING_RE.match(line) or re.match(r"^（[一二三四五六七八九十]+）$", boundary_line)
        if match:
            title = match.groupdict().get("title") if hasattr(match, "groupdict") else None
            candidates.append((line_start, line_end, "material", title or boundary_line, ""))
        match = _SUBJECT_HEADING_RE.match(line)
        if match and "资料分析" in match.group("title"):
            candidates.append((line_start, line_end, "subject", match.group("title"), match.group("title")))
        match = _DATA_HEADING_RE.match(line)
        if match:
            candidates.append((line_start, line_end, "material", "数据材料", line.strip().lstrip("#").strip()))
        match = _FIGURE_HEADING_RE.match(line)
        if match:
            candidates.append((line_start, line_end, "material", match.group("title"), ""))
        offset = line_end
    # A boundary at the first line is part of the question's own content, not
    # a material tail.  Require a little question text before it.
    candidates = [item for item in candidates if item[0] > 0 and body[:item[0]].strip()]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])


def _inline_protected_ranges(line):
    """Return spans where layout regexes must not inspect source characters."""
    ranges = []
    patterns = (
        r"`[^`]*`",
        r"\$[^$\n]+\$",
        r"\\\([^\n]*?\\\)",
        r"\\\[[\s\S]*?\\\]",
        r"!\[[^\]]*\]\([^)]*\)",
        r"<img\b[^>]*>",
    )
    for pattern in patterns:
        ranges.extend((match.start(), match.end()) for match in re.finditer(pattern, line, re.I))
    return sorted(ranges)


def _remove_structural_bold(text):
    lines = []
    fenced = False
    html_table = False
    for line in text.split("\n"):
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
            lines.append(line)
            continue
        if re.search(r"<table\b", line, re.I):
            html_table = True
        if fenced or html_table or line.lstrip().startswith(("|", "<tr", "<td", "<th")):
            lines.append(line)
            if html_table and re.search(r"</table\s*>", line, re.I):
                html_table = False
            continue
        protected = _inline_protected_ranges(line)
        if not protected:
            line = re.sub(r"(?<!\*)\*{4}(?!\*)", "", line)
        stripped = line.strip()
        if re.match(r"^\*{2}[A-D]\.", stripped):
            line = line.replace("**", "", 1)
            if line.rstrip().endswith("**"):
                line = line.rstrip()[:-2]
        elif re.match(r"^[A-D]\.", stripped) and stripped.endswith("**"):
            line = line.rstrip()[:-2]
        lines.append(line)
    return "\n".join(lines)


def _split_compact_options(text):
    output = []
    fenced = False
    html_table = False
    for raw_line in text.split("\n"):
        line = raw_line
        stripped = line.strip()
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
            output.append(line)
            continue
        if re.search(r"<table\b", line, re.I):
            html_table = True
        protected = []
        try:
            _nodes, protected, _signature = media_nodes(line)
        except (TypeError, ValueError):
            pass
        protected = list(protected) + _inline_protected_ranges(line)
        option_matches = [match for match in _OPTION_RE.finditer(line) if not _inside_ranges(match.start(), protected)]
        labels = [match.group(1) for match in option_matches]
        ordered_labels = labels == list("ABCD")[:len(labels)]
        prefix = line[:option_matches[0].start()].rstrip() if option_matches else ""
        prefix_boundary = not prefix or bool(re.search(r"[\s:：；;,，。！？]$", prefix))
        four_option_run = len(labels) == 4 and ordered_labels
        if (not fenced and not html_table and len(option_matches) >= 2 and ordered_labels
                and (prefix_boundary or four_option_run)
                and not stripped.startswith(("|", "<tr", "<td", "<th"))):
            if prefix:
                output.append(prefix)
            for index, match in enumerate(option_matches):
                end = option_matches[index + 1].start() if index + 1 < len(option_matches) else len(line)
                value = line[match.start():end].strip()
                if value:
                    output.append(value)
        else:
            output.append(line)
        if html_table and re.search(r"</table\s*>", line, re.I):
            html_table = False
    return "\n".join(output)


def _split_circle_items(text):
    output = []
    for line in text.split("\n"):
        stripped = line.strip()
        if re.match(r"^[A-D]\.", stripped) or stripped.startswith(("![](", "![", "|", "<table", "<tr", "<td", "<th")):
            output.append(line)
            continue
        protected = _inline_protected_ranges(line)
        breaks = []
        for index, mark in enumerate(line):
            if mark not in _CIRCLE_MARKS or index == 0 or line[index - 1] == "\n":
                continue
            if not _inside_ranges(index, protected):
                breaks.append(index)
        value = line
        for index in reversed(breaks):
            value = value[:index] + "\n" + value[index:]
        output.extend(value.split("\n"))
    return "\n".join(output)


def normalize_question_body(text):
    """Normalize only question layout; do not rewrite prose or media."""
    value = str(text).replace("\r\n", "\n").replace("\r", "\n")
    value = _remove_structural_bold(value)
    value = _split_compact_options(value)
    value = _split_circle_items(value)
    # A circle-item split can expose a compact option run that was originally
    # on the same line.  Run the conservative option splitter once more; a
    # single ``A.①②`` line still remains untouched.
    value = _split_compact_options(value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    lines = value.split("\n") if value else []
    first_option = next((index for index, line in enumerate(lines) if re.match(r"^\s*[A-D]\.", line)), None)
    if first_option is not None and first_option > 0:
        if first_option > 0 and lines[first_option - 1].strip():
            lines.insert(first_option, "")
    return "\n".join(lines).strip()


def normalize_material_body(text):
    value = str(text).replace("\r\n", "\n").replace("\r", "\n")
    value = _remove_structural_bold(value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    return value


def _quote_callout(title, body, kind):
    lines = [f"> [!{kind}] {title}"]
    for line in body.split("\n") if body else [""]:
        lines.append(">" if not line else f"> {line}")
    return "\n".join(lines)


def _folded_callout(title, kind, body=""):
    lines = [f"> [!{kind}]- {title}"]
    if body:
        lines.extend(f"> {line}" if line else ">" for line in body.split("\n"))
    else:
        lines.append(">")
    return "\n".join(lines)


def _block_id(prefix, value, used):
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-").lower() or prefix
    candidate = f"{prefix}{base}"
    index = 2
    while candidate in used:
        candidate = f"{prefix}{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def _image_extension(mime):
    return {"jpeg": "jpg", "jpg": "jpg", "png": "png", "gif": "gif", "webp": "webp", "svg+xml": "svg"}.get(mime.lower(), mime.lower().replace("/", "-"))


def _extract_images(text, attachments_dir, page, state):
    attachments = state.setdefault("attachments", [])
    by_digest = state.setdefault("by_digest", {})

    def write_payload(mime, encoded, alt=""):
        payload = base64.b64decode(re.sub(r"\s+", "", encoded), validate=False)
        digest = hashlib.sha256(payload).hexdigest()
        path = by_digest.get(digest)
        if path is None:
            index = len(attachments) + 1
            name = f"p{int(page):03d}-{index:03d}-{digest[:10]}.{_image_extension(mime)}"
            path = Path("attachments") / name
            (attachments_dir / name).write_bytes(payload)
            by_digest[digest] = path.as_posix()
            attachments.append({"path": path.as_posix(), "sha256": digest, "bytes": len(payload), "first_page": int(page), "alt": alt})
        return path.as_posix()

    def markdown_replace(match):
        path = write_payload(match.group("mime"), match.group("data"), match.group("alt"))
        return f"![[{path}]]"

    text = _DATA_IMAGE_RE.sub(markdown_replace, text)

    def html_replace(match):
        path = write_payload(match.group("mime"), match.group("payload"), "")
        return f"![[{path}]]"

    return _HTML_DATA_IMAGE_RE.sub(html_replace, text)


def _extract_subject_prefix(prefix):
    """Keep source subject/type headings as H2 and preserve other prose."""
    result = []
    for line in prefix.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if re.match(r"^\s*#{1,2}\s+", line):
            value = re.sub(r"^\s*#{1,6}\s+", "", line).strip()
            if value:
                result.append(f"## {value}")
            continue
        if line.strip():
            result.append(line.rstrip())
    return "\n".join(result).strip()


def _layout_regions(layout, source_range):
    if not isinstance(layout, dict):
        return []
    page = source_range["page"]
    start, end = source_range["start"], source_range["end"]
    result = []
    for page_row in layout.get("pages", []):
        if page_row.get("page") != page:
            continue
        for region in page_row.get("regions", []):
            rstart, rend = region.get("start"), region.get("end")
            if type(rstart) is not int or type(rend) is not int:
                continue
            if start < rend and rstart < end:
                result.append({key: region.get(key) for key in ("id", "type", "bbox", "start", "end") if key in region})
    return result


def _mapping_entries(chunks, spans, layout):
    entries = []
    cursor = 0
    for chunk in chunks:
        text = chunk["text"]
        start, end = cursor, cursor + len(text)
        cursor = end
        for source_range in chunk.get("source_ranges", []):
            entries.append({
                "output_start": start,
                "output_end": end,
                "pdf_page": int(source_range["page"]),
                "source_start": int(source_range["start"]),
                "source_end": int(source_range["end"]),
                "regions": _layout_regions(layout, source_range),
                "precision": "region_fallback",
                "mapping_warning": "Obsidian 包装、块编号和可折叠区块为导出生成内容；source-map 只对应本次导出快照。",
                "kind": chunk.get("kind", "generated"),
                "question_id": chunk.get("question_id"),
                "material_id": chunk.get("material_id"),
            })
    return entries


def _render_question(number, question_id, body, source_pages, material_ids, used_ids):
    block_id = _block_id("q", question_id, used_ids)
    lines = [f"<!-- source-pages: {','.join(map(str, source_pages))} -->"]
    lines.append(_quote_callout(f"第 {number} 题", body, "exam-question"))
    lines.extend(["", f"^{block_id}", "", "标签：", "关联："])
    if material_ids:
        links = "、".join(f"[[#^{item}|共享材料]]" for item in material_ids)
        lines.append(f"材料：{links}")
    lines.extend(["", _folded_callout("答案与解析", "success", "待补充。"), "", _folded_callout("我的笔记", "note"), ""])
    return "\n".join(lines), block_id


def _render_material(title, body, source_pages, used_ids, material_key=None):
    material_id = _block_id("m-", material_key or title, used_ids)
    lines = [f"<!-- source-pages: {','.join(map(str, source_pages))} -->", _quote_callout(title, body, "exam-material"), "", f"^{material_id}", ""]
    return "\n".join(lines), material_id


def _parse_boundaries(path):
    if not path:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("questions", []), list):
        raise ValueError("boundary file must contain a questions list")
    return value


def export_exam_bundle(candidate, output_dir, exam_id, *, layout=None, source_pdf=None, boundaries=None,
                       source_candidate=None, allow_uncertain=True, draft=False):
    """Write a new Obsidian bundle and return its manifest.

    ``candidate`` may be either the candidate object or a JSON path.  The
    function is also the test seam used by the Python unit tests; all files are
    written below ``output_dir`` and an existing non-empty directory is never
    overwritten.
    """
    if isinstance(candidate, (str, Path)):
        candidate_path = Path(candidate).resolve(strict=True)
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        source_candidate = source_candidate or str(candidate_path)
    else:
        candidate = copy.deepcopy(candidate)
    pages = pages_of(candidate)
    if candidate.get("workflow") != EXAM_LITE_WORKFLOW:
        raise ValueError("Obsidian export requires workflow=exam-lite-v1")
    if candidate.get("review_topology") not in {None, EXAM_LITE_TOPOLOGY}:
        raise ValueError("candidate topology is not exam-lite-v1 revision 2")
    if candidate.get("protocol_revision") not in {None, EXAM_LITE_PROTOCOL_REVISION}:
        raise ValueError("candidate protocol revision is not supported")
    candidate_topology = candidate.get("review_topology")
    candidate_protocol = candidate.get("protocol_revision")
    output = Path(output_dir).absolute()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Obsidian export output directory must be new or empty")
    attachments_dir = output / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    safe_id = _safe_name(exam_id)
    stream, spans = _page_stream(pages)
    protected = _protected_global_ranges(pages, spans)
    occurrences = _question_markers(stream, protected)
    selected, unresolved = _select_markers(occurrences, boundaries, stream)
    if not selected:
        unresolved.append({"kind": "no_question_markers", "message": "没有找到可可靠确认的题号；保留原文作为待整理内容。"})

    chunks = []
    used_ids = set()
    state = {}
    prefix_end = selected[0]["start"] if selected else len(stream)
    prefix = _extract_subject_prefix(stream[:prefix_end])
    if prefix:
        prefix = _extract_images(prefix, attachments_dir, _page_for_offset(spans, 0), state)
        chunks.append({"kind": "prefix", "text": f"{prefix}\n\n", "source_ranges": _source_ranges(spans, 0, prefix_end)})

    question_records = []
    material_records = []
    current_material = None
    number_counts = {}
    for marker in selected:
        number_counts[marker["number"]] = number_counts.get(marker["number"], 0) + 1
    for index, marker in enumerate(selected):
        next_start = selected[index + 1]["start"] if index + 1 < len(selected) else len(stream)
        body_start = marker["end"]
        body = stream[body_start:next_start]
        boundary = _find_material_boundary(body)
        trailing_material = None
        if boundary:
            boundary_start, boundary_end, boundary_kind, boundary_title, section_text = boundary
            question_body = body[:boundary_start]
            material_body = body[boundary_end:]
            trailing_material = {
                "title": boundary_title,
                "body": material_body,
                "start": body_start + boundary_start,
                "boundary_end": body_start + boundary_end,
                "end": next_start,
                "kind": boundary_kind,
                "section_text": section_text,
            }
        else:
            question_body = body
        question_body = normalize_question_body(question_body)
        if not question_body:
            unresolved.append({"kind": "empty_question_body", "number": marker["number"], "page": _page_for_offset(spans, marker["start"]),
                               "message": "题号存在但题干/选项为空，未补造内容。"})
        source_start = marker["start"]
        source_end = body_start + len(question_body)
        # Source ranges must refer to the candidate, not the normalized text;
        # use the complete original span for auditability.
        source_end = next_start if trailing_material is None else trailing_material["start"]
        source_ranges = _source_ranges(spans, source_start, source_end)
        source_pages = sorted({row["page"] for row in source_ranges})
        if marker.get("embedded") and not marker.get("boundary_override"):
            unresolved.append({"kind": "embedded_question_marker", "number": marker["number"],
                               "page": _page_for_offset(spans, marker["start"]), "offset": marker["start"],
                               "raw": marker["raw"], "message": "题号不在自然段边界，保留原顺序并标为待核实。"})
        question_id = str(marker["number"])
        if number_counts[marker["number"]] > 1:
            marker_context = stream[marker["start"]:min(next_start, marker["start"] + 160)]
            suffix = hashlib.sha1(marker_context.encode("utf-8")).hexdigest()[:8]
            question_id = f"{_question_section_key(stream, marker['start'])}-{marker['number']}-{suffix}"
        rendered_body = _extract_images(question_body, attachments_dir, source_pages[0] if source_pages else 1, state)
        rendered, block_id = _render_question(marker["number"], question_id, rendered_body, source_pages, [current_material["id"]] if current_material else [], used_ids)
        chunks.append({"kind": "question", "text": rendered, "source_ranges": source_ranges, "question_id": question_id})
        question_record = {
            "question_id": question_id,
            "number": marker["number"],
            "block_id": block_id,
            "source_pages": source_pages,
            "source_ranges": source_ranges,
            "material_ids": [current_material["id"]] if current_material else [],
            "boundary_status": "embedded-marker" if marker.get("embedded") else "reliable-sequence",
            "candidate_marker": {key: marker[key] for key in ("start", "end", "raw", "embedded")},
            "_body": rendered_body,
            "_stream_start": source_start,
            "_stream_end": source_end,
        }
        question_records.append(question_record)
        if trailing_material:
            material_text = trailing_material["body"]
            if trailing_material["section_text"]:
                section = trailing_material["section_text"]
                chunks.append({"kind": "subject", "text": f"## {section}\n\n", "source_ranges": _source_ranges(spans, trailing_material["start"], trailing_material["boundary_end"])})
            material_body = normalize_material_body(material_text)
            material_body = _extract_images(material_body, attachments_dir, _page_for_offset(spans, trailing_material["start"]), state)
            material_source_ranges = _source_ranges(spans, trailing_material["start"], trailing_material["end"])
            material_pages = sorted({row["page"] for row in material_source_ranges})
            material_key = f"material-{len(material_records) + 1:02d}"
            material_rendered, material_id = _render_material(trailing_material["title"] or "共享材料", material_body, material_pages, used_ids, material_key)
            chunks.append({"kind": "material", "text": material_rendered, "source_ranges": material_source_ranges, "material_id": material_id})
            current_material = {"id": material_id, "title": trailing_material["title"], "pages": material_pages}
            material_records.append({"material_id": material_id, "title": trailing_material["title"], "block_id": material_id,
                                     "source_pages": material_pages, "source_ranges": material_source_ranges,
                                     "linked_from_questions": [], "_stream_start": trailing_material["start"],
                                     "_stream_end": trailing_material["end"]})
        if current_material:
            # Linkage is populated after all question records exist so that a
            # material emitted after q105 can still be linked by q106.
            pass

    if selected:
        tail_start = selected[-1]["end"]
        # The final question span is already consumed above.  Any text before
        # the first marker or after the final marker that could not be attached
        # is kept as an explicit, non-question block instead of being guessed.
        if not question_records:
            tail_start = 0
    elif stream.strip():
        raw = _extract_images(stream, attachments_dir, _page_for_offset(spans, 0), state)
        chunks.append({"kind": "unresolved", "text": _quote_callout("待整理原文", raw, "warning") + "\n\n", "source_ranges": _source_ranges(spans, 0, len(stream))})

    # Re-link materials to the following question(s).  A material belongs to
    # every question until the next explicit material boundary.
    for record in material_records:
        next_material_start = min((item["_stream_start"] for item in material_records if item is not record and item["_stream_start"] > record["_stream_start"]), default=None)
        for question in question_records:
            qstart = question["_stream_start"]
            mstart = record["_stream_start"]
            if qstart > mstart and (next_material_start is None or qstart < next_material_start):
                record["linked_from_questions"].append(question["question_id"])
                if record["material_id"] not in question["material_ids"]:
                    question["material_ids"].append(record["material_id"])

    # Re-render questions after linkage is known.  This keeps the generated
    # block ids stable and avoids mutating the candidate text.
    material_for_question = {}
    for material in material_records:
        for number in material["linked_from_questions"]:
            material_for_question.setdefault(number, []).append(material["material_id"])
    rebuilt = []
    q_index = 0
    for chunk in chunks:
        if chunk.get("kind") != "question":
            rebuilt.append(chunk)
            continue
        question = question_records[q_index]
        q_index += 1
        ids = material_for_question.get(question["question_id"], question["material_ids"])
        rendered, _unused_block_id = _render_question(question["number"], question["question_id"], question["_body"], question["source_pages"], ids, used_ids=set())
        # _render_question uses the stable question number for its first
        # allocation.  Replace the complete generated block line, not a
        # prefix, so duplicate question numbers keep their disambiguated id.
        rendered = re.sub(r"(?m)^\^q[^\n]+$", f"^{question['block_id']}", rendered, count=1)
        for material_id in ids:
            if f"[[#^{material_id}|共享材料]]" not in rendered:
                rendered = rendered.replace("关联：\n", f"关联：\n材料：[[#^{material_id}|共享材料]]\n", 1)
        chunk["text"] = rendered
        rebuilt.append(chunk)
    chunks = rebuilt

    # A generated note-level header keeps source metadata visible without
    # adding question headings to the outline.
    source_line = str(source_pdf or candidate.get("source_pdf") or "未记录")
    note_header = "\n".join([
        f"# {exam_id}",
        "",
        "> [!info]- 导出信息",
        f"> workflow: {EXAM_LITE_WORKFLOW}",
        "> export_target: obsidian-exam-notes",
        f"> status: {'draft' if draft else 'accepted'}",
        f"> source: {source_line}",
        f"> pages: {len(pages)}",
        "> source-map: 本文件快照；用户编辑后偏移不自动保持有效。",
        "",
    ])
    chunks.insert(0, {"kind": "metadata", "text": note_header, "source_ranges": []})
    text = "".join(chunk["text"] if chunk["text"].endswith("\n\n") else chunk["text"] + "\n\n" for chunk in chunks).rstrip() + "\n"
    mapping_entries = _mapping_entries(chunks, spans, layout)
    # Ensure every non-empty source page has an output entry.  A page that is
    # only represented by a generated wrapper still receives a coarse entry.
    mapped = {entry["pdf_page"] for entry in mapping_entries}
    for page in pages:
        if str(page.get("text", "")).strip() and int(page["page"]) not in mapped:
            mapping_entries.append({"output_start": 0, "output_end": min(len(text), 1), "pdf_page": int(page["page"]),
                                    "source_start": 0, "source_end": len(page.get("text", "")), "regions": [],
                                    "precision": "region_fallback", "mapping_warning": "页面仅能建立页级回退映射。", "kind": "page-fallback"})
    mapping_entries.sort(key=lambda item: (item["output_start"], item["pdf_page"], item["output_end"]))
    source_map = {
        "schema_version": 1,
        "workflow": EXAM_LITE_WORKFLOW,
        "review_topology": candidate_topology,
        "protocol_revision": candidate_protocol,
        "export_target": "obsidian-exam-notes",
        "export_protocol_revision": PROTOCOL_REVISION,
        "draft": bool(draft),
        "exam_id": exam_id,
        "candidate": str(source_candidate) if source_candidate else None,
        "candidate_digest": _digest(candidate),
        "source_pdf": source_line,
        "snapshot": {"kind": "exported-markdown", "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
        "pages": [{"page": int(page["page"]), "has_text": bool(str(page.get("text", "")).strip())} for page in pages],
        "entries": mapping_entries,
    }
    # validate_source_map only requires page/output ranges and explicit
    # warnings for fallback mappings.  It also catches accidental drops.
    validate_source_map(source_map, text, pages)
    public_question_records = [{key: value for key, value in question.items() if not key.startswith("_")}
                               for question in question_records]
    public_material_records = [{key: value for key, value in material.items() if not key.startswith("_")}
                               for material in material_records]
    index = {
        "schema_version": 1,
        "workflow": EXAM_LITE_WORKFLOW,
        "review_topology": candidate_topology,
        "protocol_revision": candidate_protocol,
        "export_target": "obsidian-exam-notes",
        "draft": bool(draft),
        "exam_id": exam_id,
        "markdown": f"{safe_id}.md",
        "questions": public_question_records,
        "materials": public_material_records,
        "pages": [{"page": int(page["page"]), "text_length": len(page.get("text", ""))} for page in pages],
    }
    unresolved_report = {
        "workflow": EXAM_LITE_WORKFLOW,
        "export_target": "obsidian-exam-notes",
        "draft": bool(draft),
        "exam_id": exam_id,
        "status": "complete_with_unresolved" if unresolved else "complete",
        "items": unresolved,
        "semantic_accuracy": "not_measured",
    }
    manifest = {
        "schema_version": 1,
        "workflow": EXAM_LITE_WORKFLOW,
        "review_topology": candidate_topology,
        "protocol_revision": candidate_protocol,
        "export_target": "obsidian-exam-notes",
        "draft": bool(draft),
        "exam_id": exam_id,
        "output_dir": str(output),
        "markdown": f"{safe_id}.md",
        "source_map": f"{safe_id}.source-map.json",
        "question_index": f"{safe_id}.questions.json",
        "unresolved": f"{safe_id}.unresolved.json",
        "attachments": state.get("attachments", []),
        "question_count": len(question_records),
        "material_count": len(material_records),
        "unresolved_count": len(unresolved),
        "candidate_digest": _digest(candidate),
    }
    (output / f"{safe_id}.md").write_text(text, encoding="utf-8")
    dump(output / f"{safe_id}.source-map.json", source_map)
    dump(output / f"{safe_id}.questions.json", index)
    dump(output / f"{safe_id}.unresolved.json", unresolved_report)
    dump(output / "export-manifest.json", manifest)
    return {"manifest": manifest, "text": text, "source_map": source_map, "index": index, "unresolved": unresolved_report}


__all__ = ["export_exam_bundle", "normalize_question_body"]
