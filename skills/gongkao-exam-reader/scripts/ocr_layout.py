#!/usr/bin/env python3
"""Layout provenance, conservative classification, and clean Markdown export.

This module deliberately keeps classification separate from exclusion.  A model
or a later review decision may approve an exclusion, but a repeated string at a
page edge is never removed merely because a heuristic proposed a label.
"""
from __future__ import annotations

import copy
import re
from html.parser import HTMLParser
from typing import Any


LAYOUT_SCHEMA_VERSION = 2
EXCLUSION_TYPES = {"header", "footer", "page_number", "watermark"}
NOTE_TYPES = {"footnote", "page_footnote", "endnote"}
FOOTNOTE_TYPES = {"footnote", "page_footnote"}
HEADING_TYPES = {"doc_title", "paragraph_title", "title", "heading"}

_PAGE_NUMBER_RE = re.compile(r"^\s*(?:[—–-]\s*)?(?:第\s*)?\d+(?:\s*页)?\s*(?:[—–-])?\s*$")
_CHAPTER_RE = re.compile(
    r"^\s*(?:第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[章节篇部卷]|"
    r"[0-9零〇一二三四五六七八九十百千万两]+[、.．]\s*.+|"
    r"Chapter\s+[0-9A-Za-z]+)"
)
_REFERENCE_RE = re.compile(r"(?:参考文献|参考书目|bibliography|references)", re.I)
_NOTE_MARKER_RE = re.compile(r"^\s*([0-9]{1,3}|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]|[*†‡§])")


def normalize_bbox(bbox: Any) -> list[float] | None:
    """Return a finite normalized ``[x0, y0, x1, y1]`` or ``None``."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        values = [float(item) for item in bbox]
    except (TypeError, ValueError):
        return None
    if not all(0.0 <= value <= 1.0 for value in values):
        return None
    if values[2] <= values[0] or values[3] <= values[1]:
        return None
    return values


def normalize_external_bbox(bbox: Any, width: Any = None, height: Any = None) -> list[float] | None:
    """Normalize either MinerU pixel boxes or already-normalized boxes."""
    if isinstance(bbox, dict):
        bbox = [bbox.get(key) for key in ("x0", "y0", "x1", "y1")]
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        values = [float(item) for item in bbox]
        page_width = float(width) if width is not None else None
        page_height = float(height) if height is not None else None
    except (TypeError, ValueError):
        return None
    if all(0.0 <= value <= 1.0 for value in values):
        return normalize_bbox(values)
    if page_width and page_height and page_width > 0 and page_height > 0:
        return normalize_bbox([values[0] / page_width, values[1] / page_height,
                               values[2] / page_width, values[3] / page_height])
    return None


def flatten_block_text(value: Any) -> str:
    """Extract readable text from MinerU/docvortex block content."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "".join(flatten_block_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("content", "text", "value", "html"):
            if key in value:
                text = flatten_block_text(value[key])
                if text:
                    return text
    return ""


def normalize_region_type(raw: Any) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    aliases = {
        "pagefootnote": "page_footnote",
        "pagenumber": "page_number",
        "image_footnote": "footnote",
        "table_footnote": "footnote",
        "chart_footnote": "footnote",
        "code_footnote": "footnote",
        "doc_title": "title",
        "paragraph_title": "heading",
        "aside_text": "margin",
    }
    return aliases.get(value, value or "body")


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _find_span(page_text: str, fragment: str, cursor: int = 0) -> tuple[int | None, int | None]:
    if not fragment:
        return None, None
    start = page_text.find(fragment, max(0, cursor))
    if start >= 0:
        return start, start + len(fragment)
    compact_fragment = _compact(fragment)
    if compact_fragment:
        # The OCR and bbox exporters may disagree only about whitespace.
        compact_page = re.sub(r"\s+", " ", page_text)
        compact_start = compact_page.find(compact_fragment)
        if compact_start >= 0:
            raw_index = 0
            compact_index = 0
            while raw_index < len(page_text) and compact_index < compact_start:
                if page_text[raw_index].isspace():
                    while raw_index < len(page_text) and page_text[raw_index].isspace():
                        raw_index += 1
                else:
                    raw_index += 1
                    compact_index += 1
            start = raw_index
            consumed = 0
            while raw_index < len(page_text) and consumed < len(compact_fragment):
                if page_text[raw_index].isspace():
                    raw_index += 1
                else:
                    raw_index += 1
                    consumed += 1
            return start, raw_index
    return None, None


def _heuristic_type(text: str, bbox: list[float] | None, repeated: bool) -> tuple[str, list[str]]:
    evidence: list[str] = []
    compact = _compact(text)
    if _PAGE_NUMBER_RE.match(compact) and bbox and (bbox[1] <= 0.12 or bbox[3] >= 0.88):
        evidence.append("page-number-pattern")
        return "page_number", evidence
    if bbox:
        y0, y1 = bbox[1], bbox[3]
        if y0 <= 0.12 and repeated:
            evidence.append("repeated-top-margin")
            return "header", evidence
        if y1 >= 0.88 and repeated:
            evidence.append("repeated-bottom-margin")
            return "footer", evidence
        if y1 >= 0.72 and _NOTE_MARKER_RE.match(compact):
            evidence.append("bottom-note-marker")
            return "footnote", evidence
    if _CHAPTER_RE.match(compact):
        evidence.append("chapter-heading-pattern")
        return "heading", evidence
    return "body", evidence


def _region_id(source: str, page: int, index: int) -> str:
    return f"{source}-p{page:04d}-r{index:04d}"


def build_layout(
    pages: list[dict[str, Any]],
    *,
    source: str,
    block_records: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build a conservative layout record while retaining every page string."""
    block_records = block_records or {}
    all_records = [record for records in block_records.values() for record in records]
    counts: dict[str, int] = {}
    for record in all_records:
        key = _compact(str(record.get("text", "")))
        if key:
            counts[key] = counts.get(key, 0) + 1

    result: dict[str, Any] = {
        "schema_version": LAYOUT_SCHEMA_VERSION,
        "source": source,
        "classification_status": "needs_review",
        "chapters": [],
        "pages": [],
    }
    cursor_by_page: dict[int, int] = {}
    for page_row in pages:
        page = int(page_row["page"])
        text = str(page_row.get("text", ""))
        records = block_records.get(page)
        if not records:
            records = [{"text": text, "type": "body", "bbox": None, "index": 0}]
        regions: list[dict[str, Any]] = []
        cursor = 0
        for index, record in enumerate(records):
            fragment = flatten_block_text(record.get("text", ""))
            raw_type = normalize_region_type(record.get("type"))
            explicit = raw_type not in {"", "body", "text", "image", "table"}
            compact = _compact(fragment)
            proposed, evidence = _heuristic_type(fragment, normalize_bbox(record.get("bbox")), counts.get(compact, 0) >= 2)
            if explicit:
                proposed = raw_type
                evidence = ["source-block-type"]
            start, end = _find_span(text, fragment, cursor)
            if start is not None:
                cursor = end or cursor
            region_type = proposed if proposed else "body"
            regions.append(
                {
                    "id": _region_id(source, page, index),
                    "type": region_type,
                    "proposed_type": region_type,
                    "status": "keep",
                    "text": fragment,
                    "start": start,
                    "end": end,
                    "bbox": normalize_bbox(record.get("bbox")),
                    "block_index": record.get("index", index),
                    "evidence": evidence,
                    "chapter_id": None,
                }
            )
        result["pages"].append({"page": page, "regions": regions})
        cursor_by_page[page] = cursor
    assign_chapters(result, pages)
    return result


def assign_chapters(layout: dict[str, Any], pages: list[dict[str, Any]]) -> None:
    """Assign stable chapter ids without moving or deleting any content."""
    chapter_number = 0
    current = None
    page_text = {int(row["page"]): str(row.get("text", "")) for row in pages}
    for page_row in layout.get("pages", []):
        page = int(page_row["page"])
        for region in page_row.get("regions", []):
            sample = _compact(str(region.get("text", "")))
            is_chapter = region.get("type") == "chapter" or bool(_CHAPTER_RE.match(sample))
            if is_chapter:
                chapter_number += 1
                current = f"chapter-{chapter_number:04d}"
                layout.setdefault("chapters", []).append(
                    {"id": current, "start_page": page, "title": sample[:200]}
                )
            if current is None:
                chapter_number = 1
                current = "chapter-0001"
                layout.setdefault("chapters", []).append(
                    {"id": current, "start_page": page, "title": "未命名章节"}
                )
            region["chapter_id"] = current
        if not page_row.get("regions") and page_text.get(page):
            chapter_number += 1
            current = f"chapter-{chapter_number:04d}"

    chapters = layout.get("chapters", [])
    for index, chapter in enumerate(chapters):
        next_start = chapters[index + 1]["start_page"] if index + 1 < len(chapters) else None
        chapter["end_page"] = (next_start - 1) if next_start else max(
            (int(row["page"]) for row in layout.get("pages", [])), default=chapter["start_page"]
        )


def extract_mineru_blocks(middle: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    records: dict[int, list[dict[str, Any]]] = {}
    for page in middle.get("pages", []) if isinstance(middle, dict) else []:
        page_idx = page.get("page_idx")
        if not isinstance(page_idx, int):
            continue
        page_info = page.get("page_info") if isinstance(page.get("page_info"), dict) else {}
        width = page.get("width") or page.get("image_width") or page_info.get("width") or page_info.get("image_width")
        height = page.get("height") or page.get("image_height") or page_info.get("height") or page_info.get("image_height")
        rows: list[dict[str, Any]] = []
        for index, block in enumerate(page.get("blocks", []) or []):
            if not isinstance(block, dict):
                continue
            content = flatten_block_text(block.get("content"))
            if not content:
                content = flatten_block_text(block.get("text"))
            rows.append(
                {
                    "index": block.get("index", index),
                    "type": block.get("type", "body"),
                    "bbox": normalize_external_bbox(block.get("bbox"), width, height),
                    "text": content,
                }
            )
        records[page_idx + 1] = rows
    return records


class _BBoxParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pages: list[dict[str, Any]] = []
        self._page: dict[str, Any] | None = None
        self._line: dict[str, Any] | None = None
        self._word: dict[str, Any] | None = None

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "page":
            self._page = {"width": self._number(values.get("width")), "height": self._number(values.get("height")), "lines": []}
        elif tag == "line" and self._page is not None:
            self._line = {"words": [], "bbox": [self._number(values.get(k)) for k in ("xMin", "yMin", "xMax", "yMax")]}
        elif tag == "word" and self._line is not None:
            self._word = {"text": [], "bbox": [self._number(values.get(k)) for k in ("xMin", "yMin", "xMax", "yMax")]}

    def handle_data(self, data: str) -> None:
        if self._word is not None:
            self._word["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "word" and self._word is not None and self._line is not None:
            self._word["text"] = "".join(self._word["text"])
            self._line["words"].append(self._word)
            self._word = None
        elif tag == "line" and self._line is not None and self._page is not None:
            self._page["lines"].append(self._line)
            self._line = None
        elif tag == "page" and self._page is not None:
            self.pages.append(self._page)
            self._page = None


def parse_bbox_layout(html_text: str) -> dict[int, list[dict[str, Any]]]:
    parser = _BBoxParser()
    parser.feed(html_text)
    result: dict[int, list[dict[str, Any]]] = {}
    for page_number, page in enumerate(parser.pages, 1):
        width = page.get("width") or 1.0
        height = page.get("height") or 1.0
        rows: list[dict[str, Any]] = []
        for index, line in enumerate(page.get("lines", [])):
            words = [word for word in line.get("words", []) if word.get("text")]
            if not words:
                continue
            text = " ".join(str(word["text"]) for word in words)
            x0 = min((word["bbox"][0] for word in words if word.get("bbox") and word["bbox"][0] is not None), default=0.0)
            y0 = min((word["bbox"][1] for word in words if word.get("bbox") and word["bbox"][1] is not None), default=0.0)
            x1 = max((word["bbox"][2] for word in words if word.get("bbox") and word["bbox"][2] is not None), default=width)
            y1 = max((word["bbox"][3] for word in words if word.get("bbox") and word["bbox"][3] is not None), default=height)
            rows.append({"index": index, "type": "body", "text": text, "bbox": [x0 / width, y0 / height, x1 / width, y1 / height]})
        result[page_number] = rows
    return result


def build_wps_layout(pages: list[dict[str, Any]], bbox_html: str) -> dict[str, Any]:
    """Build WPS layout records from Poppler bbox output without re-OCR."""
    return build_layout(pages, source="wps", block_records=parse_bbox_layout(bbox_html))


def build_mineru_layout(pages: list[dict[str, Any]], middle: dict[str, Any]) -> dict[str, Any]:
    """Build a layout from MinerU's unfiltered MiddleJson blocks."""
    return build_layout(pages, source="mineru", block_records=extract_mineru_blocks(middle))


def _regions(layout: dict[str, Any]) -> list[dict[str, Any]]:
    return [region for page in layout.get("pages", []) for region in page.get("regions", [])]


def apply_region_decisions(layout: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply only explicit J-approved region decisions to a copied layout."""
    result = copy.deepcopy(layout)
    by_id = {region.get("id"): region for region in _regions(result)}
    for decision in decisions:
        region_id = decision.get("region_id")
        action = decision.get("action") or decision.get("decision")
        region = by_id.get(region_id)
        if region is None or action not in {"exclude", "keep"}:
            raise ValueError("invalid region decision")
        if not decision.get("reason") or not decision.get("evidence"):
            raise ValueError("region decision needs reason and evidence")
        if action == "exclude":
            exclusion_type = normalize_region_type(decision.get("type") or region.get("type"))
            if exclusion_type not in EXCLUSION_TYPES:
                raise ValueError("only header/footer/page_number/watermark regions may be excluded")
            region["type"] = exclusion_type
            region["status"] = "approved_exclude"
        else:
            region["status"] = "keep"
    result["classification_status"] = "reviewed"
    return result


def _remove_spans(text: str, regions: list[dict[str, Any]]) -> str:
    spans = sorted(
        [(region.get("start"), region.get("end")) for region in regions if isinstance(region.get("start"), int) and isinstance(region.get("end"), int)],
        reverse=True,
    )
    result = text
    for start, end in spans:
        if 0 <= start <= end <= len(result):
            result = result[:start] + result[end:]
    return result


def render_clean_markdown(
    pages: list[dict[str, Any]],
    layout: dict[str, Any] | None = None,
    *,
    relocate_footnotes: bool = True,
    include_page_markers: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Render clean Markdown and a character-range source map."""
    layout = layout or build_layout(pages, source="unknown")
    by_page = {int(page["page"]): page for page in layout.get("pages", [])}
    rendered_pages: list[dict[str, Any]] = []
    chapter_notes: dict[str, list[dict[str, Any]]] = {}
    for page_row in pages:
        page_number = int(page_row["page"])
        page_layout = by_page.get(page_number, {"regions": []})
        regions = page_layout.get("regions", [])
        excluded = [region for region in regions if region.get("status") == "approved_exclude" and region.get("type") in EXCLUSION_TYPES]
        notes = [region for region in regions if relocate_footnotes and region.get("status") == "keep" and region.get("type") in FOOTNOTE_TYPES and region.get("chapter_id")]
        body = _remove_spans(str(page_row.get("text", "")), excluded + notes)
        for index, note in enumerate(notes, 1):
            chapter = str(note["chapter_id"])
            note = copy.deepcopy(note)
            note["footnote_id"] = f"footnote-{chapter}-{index:03d}"
            note["pdf_page"] = page_number
            marker_match = _NOTE_MARKER_RE.match(str(note.get("text", "")))
            note["marker"] = marker_match.group(1) if marker_match else "注"
            chapter_notes.setdefault(chapter, []).append(note)
        page_chapter = page_layout.get("chapter_id") or next(
            (region.get("chapter_id") for region in regions if region.get("chapter_id")), None
        )
        rendered_pages.append({"page": page_number, "text": body,
                               "original_text": str(page_row.get("text", "")),
                               "regions": regions, "chapter_id": page_chapter})

    # Add a visible, semantics-preserving link only to a standalone marker that
    # occurs before that note's source region. Do not replace the first digit in
    # a date, heading, or body sentence merely because a footnote is numbered.
    for page in rendered_pages:
        text = page["text"]
        page_regions = page.get("regions", [])
        page_notes = [note for notes in chapter_notes.values() for note in notes
                      if note.get("pdf_page") == page.get("page")]
        removed_regions = [region for region in page_regions
                           if (region.get("status") == "approved_exclude" and region.get("type") in EXCLUSION_TYPES)
                           or region.get("type") in FOOTNOTE_TYPES]
        # Some MinerU regions intentionally have no character offsets (for
        # example image-only footnotes). Keep them in the output, but sort
        # missing offsets after precisely located notes instead of comparing
        # None with integers during export.
        def note_sort_key(item):
            start = item.get("start")
            end = item.get("end")
            return (
                start if isinstance(start, int) else 10**18,
                end if isinstance(end, int) else 10**18,
            )

        for note in sorted(page_notes, key=note_sort_key):
            marker = str(note.get("marker", ""))
            start = note.get("start")
            if not marker or not isinstance(start, int):
                continue
            prior = [region for region in removed_regions
                     if isinstance(region.get("start"), int) and region.get("start") < start]
            prefix = _remove_spans(page.get("original_text", ""), prior)
            pattern = re.compile(rf"(?<!\w){re.escape(marker)}(?!\w)")
            matches = list(pattern.finditer(text[:len(prefix)]))
            if not matches:
                continue
            match = matches[-1]
            replacement = f"[{marker}](#{note['footnote_id']})"
            text = text[:match.start()] + replacement + text[match.end():]
            note["linked"] = True
        page["text"] = text

    chapter_end: dict[str, int] = {}
    for page in rendered_pages:
        for region in page.get("regions", []):
            chapter = region.get("chapter_id")
            if chapter:
                chapter_end[str(chapter)] = max(chapter_end.get(str(chapter), 0), int(page["page"]))
    chapter_headings = {}
    reference_headings = {}
    for page in rendered_pages:
        for region in page.get("regions", []):
            if region.get("chapter_id") and (_CHAPTER_RE.match(str(region.get("text", "")).strip()) or region.get("type") == "chapter"):
                chapter_headings.setdefault(str(region["chapter_id"]), (int(page["page"]), str(region.get("text", "")).strip()))
            if region.get("chapter_id") and _REFERENCE_RE.search(str(region.get("text", "")).strip()):
                reference_headings.setdefault(str(region["chapter_id"]), (int(page["page"]), str(region.get("text", "")).strip()))
    note_sections: dict[int, list[dict[str, str | None]]] = {}
    chapters = layout.get("chapters", [])
    for chapter, notes in chapter_notes.items():
        lines = ["## 脚注"]
        for note in notes:
            lines.append(f"- <a id=\"{note['footnote_id']}\"></a>{note.get('text', '').strip()}")
        section = "\n".join(lines)
        next_chapter = None
        for index, item in enumerate(chapters):
            if item.get("id") == chapter and index + 1 < len(chapters):
                next_chapter = str(chapters[index + 1].get("id"))
                break
        target = reference_headings.get(chapter)
        if target is None and next_chapter:
            target = chapter_headings.get(next_chapter)
        insert_page = target[0] if target else chapter_end.get(chapter)
        if insert_page is not None:
            note_sections.setdefault(insert_page, []).append({"text": section, "before": target[1] if target else None,
                                                              "notes": notes})

    output_parts: list[str] = []
    mapping: list[dict[str, Any]] = []
    for page in rendered_pages:
        part = page["text"]
        for section in note_sections.get(page["page"], []):
            before = section.get("before")
            value = str(section["text"])
            if before and before in part:
                part = part.replace(before, value + "\n\n" + before, 1)
            else:
                part = (part.rstrip() + "\n\n" + value).strip()
        part = re.sub(r"\n{3,}", "\n\n", part).strip()
        if include_page_markers:
            part = f"<!-- pdf-page:{page['page']} -->\n\n{part}"
        start_offset = sum(len(item) + 2 for item in output_parts)
        output_parts.append(part)
        if part:
            mapping.append({"output_start": start_offset, "output_end": start_offset + len(part), "pdf_page": page["page"], "region_id": None, "precision": "page"})
            for region in page.get("regions", []):
                if region.get("status") == "approved_exclude":
                    continue
                if relocate_footnotes and region.get("type") in FOOTNOTE_TYPES:
                    continue
                fragment = str(region.get("text", "")).strip()
                if not fragment:
                    continue
                local = part.find(fragment)
                if local >= 0:
                    mapping.append({"output_start": start_offset + local, "output_end": start_offset + local + len(fragment), "pdf_page": page["page"], "region_id": region.get("id"), "bbox": region.get("bbox"), "precision": "region"})
                else:
                    # Formatting or an exact approved patch may change the
                    # literal fragment while its source region remains valid.
                    # Keep the region id and bbox at page precision instead of
                    # silently dropping the source-map relationship.
                    mapping.append({"output_start": start_offset,
                                    "output_end": start_offset + len(part),
                                    "pdf_page": page["page"], "region_id": region.get("id"),
                                    "bbox": region.get("bbox"), "precision": "region_fallback",
                                    "mapping_warning": "fragment_not_found_after_transform"})
            for section in note_sections.get(page["page"], []):
                for note in section.get("notes", []):
                    fragment = str(note.get("text", "")).strip()
                    if not fragment:
                        continue
                    local = part.find(fragment)
                    if local >= 0:
                        mapping.append({"output_start": start_offset + local,
                                        "output_end": start_offset + local + len(fragment),
                                        "pdf_page": note.get("pdf_page", page["page"]),
                                        "region_id": note.get("id"), "bbox": note.get("bbox"),
                                        "precision": "region"})

    output = "\n\n".join(output_parts)
    if output and not output.endswith("\n"):
        output += "\n"
    source_map = {"schema_version": LAYOUT_SCHEMA_VERSION, "entries": mapping, "page_markers": include_page_markers}
    return output, source_map
