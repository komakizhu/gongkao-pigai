#!/usr/bin/env python3
"""Material extraction, answer-card generation, and deterministic grading.

The script deliberately uses explicit answer-line formats. It never executes
text found in a document and never copies private reference answers into a
public answer-recorder configuration.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from score_routing import exam_type, estimate_after_grade


QUESTION_TYPES = {"single", "multiple", "boolean"}
FORMATS = {".txt", ".md", ".pdf", ".docx", ".doc"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def fail(message: str) -> None:
    raise SystemExit(message)


def extract_docx(path: Path) -> tuple[str, list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    pages: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    blocks: list[str] = []
    for child in root.findall(".//w:body/*", ns):
        if child.tag.endswith("}p"):
            text = "".join(node.text or "" for node in child.findall(".//w:t", ns)).strip()
            if text:
                blocks.append(text)
        elif child.tag.endswith("}tbl"):
            rows: list[str] = []
            for row in child.findall(".//w:tr", ns):
                cells = ["".join(node.text or "" for node in cell.findall(".//w:t", ns)).strip() for cell in row.findall("./w:tc", ns)]
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                blocks.extend(rows)
    if not blocks:
        warnings.append("needs_review: DOCX 没有提取到正文或表格文字。")
    text = "\n\n".join(blocks)
    pages.append({"source": str(path), "paragraphs": len(blocks)})
    return text, pages, warnings


def extract_pdf(path: Path) -> tuple[str, list[dict[str, Any]], list[str]]:
    try:
        result = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True)
    except FileNotFoundError:
        fail("未找到 pdftotext；请安装 PDF 文本提取工具，或先将 PDF 转成文字。")
    except subprocess.CalledProcessError as exc:
        fail(f"PDF 提取失败：{exc.stderr.strip() or '文件可能是加密或损坏的。'}")
    raw_pages = result.stdout.split("\f")
    # pdftotext normally appends one final form-feed. Drop only that
    # delimiter-produced empty segment so a real blank page in the middle or
    # at the end remains visible in the extraction metadata.
    if len(raw_pages) > 1 and not raw_pages[-1].strip():
        raw_pages = raw_pages[:-1]
    pages = [{"source": str(path), "page": index + 1, "textLength": len(page.strip())} for index, page in enumerate(raw_pages)]
    blank_pages = [index + 1 for index, page in enumerate(raw_pages) if not page.strip()]
    warnings = [
        f"needs_review: PDF 第 {page} 页没有提取到文字，请对照原 PDF 核实；程序未将其认定为扫描页或漏题。"
        for page in blank_pages
    ]
    text = "\n\n".join(f"## 第 {index + 1} 页\n{page.strip()}" for index, page in enumerate(raw_pages))
    return text, pages, warnings


def extract_doc(path: Path) -> tuple[str, list[dict[str, Any]], list[str]]:
    try:
        result = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)], check=True, capture_output=True, text=True)
    except FileNotFoundError:
        fail("未找到 textutil；请先将旧版 DOC 转换为 DOCX 或纯文本。")
    except subprocess.CalledProcessError as exc:
        fail(f"DOC 转换失败：{exc.stderr.strip() or '格式无法读取。'}")
    text = result.stdout.strip()
    return text, [{"source": str(path), "paragraphs": len(text.splitlines())}], ([] if text else ["needs_review: DOC 没有提取到文字。"])


def extract_material(path: Path) -> tuple[str, list[dict[str, Any]], list[str]]:
    if path.suffix.lower() not in FORMATS:
        fail(f"不支持的材料格式：{path.suffix or '无扩展名'}。支持 TXT、Markdown、PDF、DOCX 和 DOC。")
    if not path.is_file():
        fail(f"材料不存在：{path}")
    if path.suffix.lower() in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8")
        return text, [{"source": str(path), "lines": len(text.splitlines())}], ([] if text.strip() else ["needs_review: 材料为空。"])
    if path.suffix.lower() == ".docx":
        return extract_docx(path)
    if path.suffix.lower() == ".pdf":
        return extract_pdf(path)
    return extract_doc(path)


def command_extract(args: argparse.Namespace) -> None:
    source = Path(args.input).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    text, sources, warnings = extract_material(source)
    original_copy = output / f"original{source.suffix.lower()}"
    if source != original_copy.resolve():
        shutil.copy2(source, original_copy)
    extraction = {"schemaVersion": 1, "type": "exam-material-extraction", "extractedAt": now_iso(), "source": str(source), "sources": sources, "warnings": warnings, "text": text}
    warning_text = ""
    if warnings:
        warning_text = "\n\n## 待核实\n\n" + "\n".join(f"- {warning}" for warning in warnings)
    (output / "extracted.md").write_text(f"# 提取稿：{source.name}\n\n{text}{warning_text}\n", encoding="utf-8")
    (output / "extraction.json").write_text(json.dumps(extraction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output / "extracted.md")


def parse_range(value: str | None) -> list[int]:
    if not value:
        return []
    match = re.fullmatch(r"(\d+)\s*[-—]\s*(\d+)", value.strip())
    if not match or int(match.group(1)) > int(match.group(2)):
        fail("--range 必须是例如 41-60 的题号范围。")
    start, end = map(int, match.groups())
    if start < 1 or end > 9999 or end - start + 1 > 500:
        fail("题号范围必须在 1—9999 内且不超过 500 题。")
    return list(range(start, end + 1))


def normalize_answer(raw: str, question_type: str, options: list[str]) -> str | list[str] | bool | None:
    value = raw.strip().replace("，", ",").replace("、", ",")
    if question_type == "boolean":
        if value in {"对", "正确", "true", "True", "T"}:
            return True
        if value in {"错", "错误", "false", "False", "F"}:
            return False
        return None
    values = [item.strip().upper() for item in value.split(",") if item.strip()] if "," in value else list(value.upper())
    if any(item not in options for item in values):
        return None
    if question_type == "single":
        return values[0] if len(values) == 1 else None
    return sorted(set(values), key=options.index) or None


def answer_pattern(line: str) -> tuple[int, str, str | None] | None:
    # Deliberately narrow: only a line that consists of a number, an optional
    # explicit type, and a short answer token is a candidate.
    match = re.fullmatch(r"\s*(\d{1,4})\s*(?:[、.．)）:：\-]\s*|\s+)(?:(single|multiple|boolean)\s+)?([A-Za-z对错正确错误,，、]+)\s*", line, re.IGNORECASE)
    return (int(match.group(1)), match.group(3), match.group(2).lower() if match.group(2) else None) if match else None


def command_prepare(args: argparse.Namespace) -> None:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        fail(f"提取稿不存在：{input_path}")
    type_map: dict[int, str] = {}
    if args.type_map:
        for pair in args.type_map.split(","):
            if ":" not in pair:
                fail("--type-map 必须是例如 41:single,42:multiple 的格式。")
            number_text, mapped_type = pair.split(":", 1)
            if not number_text.isdigit() or mapped_type not in QUESTION_TYPES:
                fail("--type-map 中的题号或题型无效。")
            type_map[int(number_text)] = mapped_type
    if args.question_type and args.question_type not in QUESTION_TYPES:
        fail("--question-type 必须是 single、multiple 或 boolean，不能根据答案字母猜测题型。")
    section = args.section or ""
    raw_text = input_path.read_text(encoding="utf-8")
    issues: list[dict[str, Any]] = []
    answers: dict[int, dict[str, Any]] = {}
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        candidate = answer_pattern(line)
        if not candidate:
            continue
        number, raw_answer, inline_type = candidate
        question_type = inline_type or type_map.get(number) or args.question_type
        if question_type not in QUESTION_TYPES:
            issues.append({"code": "unclear_type", "severity": "blocking", "line": line_number, "questionNumber": number, "message": "题型未明确；请使用 --question-type、--type-map 或在答案行写明 single/multiple/boolean。"})
            continue
        options = [item.strip() for item in (args.options.split(",") if args.options else (["对", "错"] if question_type == "boolean" else ["A", "B", "C", "D"])) if item.strip()]
        if question_type == "boolean": options = ["对", "错"]
        if len(options) < 2:
            fail("选项范围至少需要两个选项。")
        normalized = normalize_answer(raw_answer, question_type, options)
        if normalized is None:
            issues.append({"code": "invalid_answer", "severity": "blocking", "line": line_number, "questionNumber": number, "value": raw_answer, "message": "答案不符合明确的题型或选项范围。"})
            continue
        question_id = f"{args.paper_id}:q:{section or 'default'}:{number}"
        item = {"questionId": question_id, "number": number, "section": section or None, "type": question_type, "options": options, "referenceAnswer": normalized, "source": {"file": str(input_path), "line": line_number}}
        if number in answers:
            if answers[number]["referenceAnswer"] != normalized or answers[number]["type"] != question_type:
                issues.append({"code": "conflict", "severity": "blocking", "line": line_number, "questionNumber": number, "message": "同一题号出现冲突参考答案。"})
            else:
                issues.append({"code": "duplicate_question", "severity": "blocking", "line": line_number, "questionNumber": number, "message": "同一题号重复出现。"})
            continue
        answers[number] = item
    for number in parse_range(args.range):
        if number not in answers:
            range_type = args.question_type or type_map.get(number)
            if range_type not in QUESTION_TYPES:
                issues.append({"code": "unclear_type", "severity": "blocking", "questionNumber": number, "message": "范围补题的题型未明确。"})
                continue
            range_options = ["对", "错"] if range_type == "boolean" else ([item.strip() for item in args.options.split(",") if item.strip()] if args.options else ["A", "B", "C", "D"])
            answers[number] = {"questionId": f"{args.paper_id}:q:{section or 'default'}:{number}", "number": number, "section": section or None, "type": range_type, "options": range_options, "referenceAnswer": None, "source": None}
            issues.append({"code": "missing_reference", "severity": "warning", "questionNumber": number, "message": "题目清单明确，但没有参考答案。"})
    questions = [answers[number] for number in sorted(answers)]
    if not questions:
        issues.append({"code": "empty_question_set", "severity": "blocking", "message": "没有找到明确答案行；请补充整理稿或题号范围。"})
    answer_set = {"schemaVersion": 2, "type": "answer-key", "paperId": args.paper_id, "paperVersion": args.paper_version, "name": args.name, "createdAt": now_iso(), "questions": questions, "issues": issues}
    answer_set["examType"] = args.exam_type
    for field in ("year", "category", "total_questions", "scope"):
        value = getattr(args, field)
        if value is not None:
            answer_set[field] = value
    output = Path(args.output).expanduser().resolve(); output.mkdir(parents=True, exist_ok=True)
    (output / "answer-set.json").write_text(json.dumps(answer_set, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# 参考答案整理：{args.name}", "", f"- 试卷：`{args.paper_id}`", f"- 答案版本：`{args.paper_version}`", "", "## 题目", "", "| 题号 | 题型 | 参考答案 | 来源 |", "| --- | --- | --- | --- |"]
    for item in questions:
        answer = item["referenceAnswer"]
        answer_text = "" if answer is None else ("|".join(answer) if isinstance(answer, list) else ("对" if answer is True else "错" if answer is False else str(answer)))
        source = "" if not item["source"] else f"{item['source']['file']}:{item['source']['line']}"
        lines.append(f"| {item['number']} | {item['type']} | {answer_text} | {source} |")
    if issues:
        lines.extend(["", "## 待核实问题", ""])
        lines.extend(f"- `{issue['code']}`：{issue['message']}" for issue in issues)
    (output / "answers.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output / "answer-set.json")


def command_generate_config(args: argparse.Namespace) -> None:
    path = Path(args.input).expanduser().resolve(); data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 2 or data.get("type") != "answer-key": fail("不是 schemaVersion 2 的私有答案集合。")
    blocking = [issue for issue in data.get("issues", []) if issue.get("severity") == "blocking"]
    if blocking: fail("答案集合存在阻断问题，请先处理 issues，未生成答题卡配置。")
    questions = []
    for item in data.get("questions", []):
        questions.append({key: item[key] for key in ("questionId", "number", "section", "type", "options") if key in item and item[key] is not None})
    config = {"schemaVersion": 2, "type": "answer-recorder-config", "paperId": data["paperId"], "paperVersion": data["paperVersion"], "name": data["name"], "questions": questions}
    serialized = json.dumps(config, ensure_ascii=False, indent=2)
    if any(token in serialized for token in ("referenceAnswer", "answer-set", "source")): fail("安全检查失败：公开配置含有私有答案字段。")
    output = Path(args.output).expanduser().resolve(); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(serialized + "\n", encoding="utf-8")
    print(output)


def canonical(value: Any, question_type: str) -> Any:
    if question_type == "multiple": return set(value or []) if isinstance(value, list) else set()
    return value


def display_answer(value: Any) -> str:
    if value is None: return ""
    if isinstance(value, list): return "|".join(sorted(value))
    if isinstance(value, bool): return "true" if value else "false"
    return str(value)


def load_attempt(path: Path) -> dict[str, Any]:
    """Load either the web JSON export or its UTF-8-BOM CSV equivalent."""
    if path.suffix.lower() != ".csv":
        return json.loads(path.read_text(encoding="utf-8"))
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    if not rows:
        fail("CSV 作答文件没有题目行。")
    required = {"schema_version", "paper_id", "paper_version", "attempt_id", "question_id", "question_number", "question_type", "answer", "review_flag"}
    missing = required - set(fieldnames)
    if missing:
        fail(f"CSV 缺少字段：{', '.join(sorted(missing))}。")
    def cell(row: dict[str, str | None], name: str) -> str:
        value = row.get(name)
        return value.strip() if isinstance(value, str) else ""

    first = rows[0]
    expected_schema = cell(first, "schema_version")
    expected_paper_id = cell(first, "paper_id")
    expected_paper_version = cell(first, "paper_version")
    if expected_schema != "2":
        fail(f"CSV 第 2 行 schema_version 无效：{expected_schema or '为空'}，当前只支持 2。")
    if not expected_paper_id or not expected_paper_version:
        fail("CSV 第 2 行 paper_id 和 paper_version 不能为空。")
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        row_schema = cell(row, "schema_version")
        if row_schema != expected_schema:
            fail(f"CSV 第 {line_number} 行 schema_version 与首行不一致：{row_schema or '为空'}。")
        row_paper_id = cell(row, "paper_id")
        if row_paper_id != expected_paper_id:
            fail(f"CSV 第 {line_number} 行 paper_id 与首行不一致：{row_paper_id or '为空'}。")
        row_paper_version = cell(row, "paper_version")
        if row_paper_version != expected_paper_version:
            fail(f"CSV 第 {line_number} 行 paper_version 与首行不一致：{row_paper_version or '为空'}。")
        question_id = cell(row, "question_id")
        if not question_id:
            fail(f"CSV 第 {line_number} 行 question_id 不能为空。")
        if question_id in seen:
            fail(f"CSV 第 {line_number} 行 question_id 重复：{question_id}。")
        seen.add(question_id)
        question_type = cell(row, "question_type")
        raw_answer = cell(row, "answer")
        if not raw_answer:
            answer: Any = None
        elif question_type == "multiple":
            answer = [item for item in raw_answer.split("|") if item]
        elif question_type == "boolean":
            if raw_answer not in {"true", "false"}:
                fail(f"CSV 第 {line_number} 行第 {cell(row, 'question_number')} 题判断答案无效。")
            answer = raw_answer == "true"
        else:
            answer = raw_answer
        try:
            question_number = int(cell(row, "question_number"))
        except (TypeError, ValueError):
            fail(f"CSV 第 {line_number} 行 question_number 无效：{cell(row, 'question_number')}。")
        questions.append({
            "id": f"csv:{question_id}", "questionId": question_id,
            "number": question_number, "type": question_type,
            "options": ["对", "错"] if question_type == "boolean" else ["A", "B", "C", "D"],
            "answer": answer, "review": cell(row, "review_flag").lower() == "true",
        })
    attempt_ids = {cell(row, "attempt_id") for row in rows}
    exercise = {"id": first.get("exercise_id", "csv-exercise"), "paperId": first["paper_id"], "paperVersion": first["paper_version"], "attemptId": first["attempt_id"] if len(attempt_ids) == 1 else "mixed", "name": first.get("exercise_name", "CSV 作答"), "status": first.get("exercise_status", "active"), "startNumber": min(item["number"] for item in questions), "questionCount": len(questions), "createdAt": "", "updatedAt": "", "revision": 0, "scrollTop": 0, "questions": questions}
    return {"schemaVersion": 2, "type": "answer-recorder-attempt", "exportedAt": now_iso(), "exercise": exercise}


def command_grade(args: argparse.Namespace) -> None:
    key_path = Path(args.answer_set).expanduser().resolve(); attempt_path = Path(args.attempt).expanduser().resolve()
    key = json.loads(key_path.read_text(encoding="utf-8")); attempt_root = load_attempt(attempt_path)
    if key.get("schemaVersion") != 2 or key.get("type") != "answer-key": fail("私有答案集合版本或类型无效。")
    blocking = [issue for issue in key.get("issues", []) if issue.get("severity") == "blocking"]
    if blocking:
        details = "; ".join(
            f"{issue.get('code', 'unknown')}" + (f"（第 {issue['questionNumber']} 题）" if issue.get("questionNumber") is not None else "")
            for issue in blocking
        )
        fail(f"答案集合存在未解决的阻断问题，已拒绝批改：{details}。")
    if attempt_root.get("schemaVersion") != 2 or attempt_root.get("type") != "answer-recorder-attempt": fail("作答文件不是网页 schemaVersion 2 导出。")
    attempt = attempt_root.get("exercise") or {}
    if attempt.get("paperId") != key.get("paperId") or attempt.get("paperVersion") != key.get("paperVersion"):
        fail("试卷身份或参考答案版本不匹配，已拒绝静默批改。")
    key_questions = key.get("questions", []); attempt_questions = {item.get("questionId"): item for item in attempt.get("questions", [])}
    expected_ids = {item.get("questionId") for item in key_questions}; actual_ids = set(attempt_questions)
    if len(expected_ids) != len(key_questions) or len(attempt_questions) != len(attempt.get("questions", [])):
        fail("参考答案或作答记录存在重复题目身份，已拒绝批改。")
    if expected_ids != actual_ids: fail("题目身份集合不匹配，已拒绝按题数猜测对应关系。")
    rows: list[dict[str, Any]] = []
    counts = {"correct": 0, "wrong": 0, "unanswered": 0, "reference_missing": 0, "ungradable": 0}
    for item in key_questions:
        attempt_item = attempt_questions[item["questionId"]]; reference = item.get("referenceAnswer"); mine = attempt_item.get("answer"); result = ""
        if attempt_item.get("number") != item.get("number") or attempt_item.get("type") != item.get("type"):
            fail(f"题目 {item['number']} 的题号或题型与参考答案不一致，已拒绝静默批改。")
        options = item.get("options", [])
        if mine is not None:
            if item["type"] == "single" and (not isinstance(mine, str) or mine not in options):
                fail(f"题目 {item['number']} 的单选作答值无效。")
            if item["type"] == "multiple" and (not isinstance(mine, list) or any(not isinstance(option, str) or option not in options for option in mine)):
                fail(f"题目 {item['number']} 的多选作答值无效。")
            if item["type"] == "boolean" and not isinstance(mine, bool):
                fail(f"题目 {item['number']} 的判断作答值无效。")
        if reference is None: result = "reference_missing"; counts["reference_missing"] += 1
        elif mine is None or (item["type"] == "multiple" and mine == []): result = "unanswered"; counts["unanswered"] += 1
        elif item["type"] not in QUESTION_TYPES or attempt_item.get("type") != item["type"]: result = "ungradable"; counts["ungradable"] += 1
        elif canonical(mine, item["type"]) == canonical(reference, item["type"]): result = "correct"; counts["correct"] += 1
        else: result = "wrong"; counts["wrong"] += 1
        row = {"questionId": item["questionId"], "number": item["number"], "section": item.get("section"), "type": item["type"], "myAnswer": mine, "referenceAnswer": reference, "result": result, "source": item.get("source")}
        if item.get("module") is not None:
            row["module"] = item["module"]
        if item["type"] == "multiple" and isinstance(reference, list) and isinstance(mine, list): row["missingOptions"] = sorted(set(reference) - set(mine)); row["extraOptions"] = sorted(set(mine) - set(reference))
        rows.append(row)
    judged = counts["correct"] + counts["wrong"]; report = {"schemaVersion": 1, "type": "exam-grade-report", "gradedAt": now_iso(), "batchId": new_id("grade"), "paperId": key["paperId"], "paperVersion": key["paperVersion"], "attemptId": attempt.get("attemptId"), "answerSetFile": str(key_path), "attemptFile": str(attempt_path), "counts": {**counts, "judged": judged, "accuracy": (counts["correct"] / judged if judged else None)}, "rows": rows}
    kind = exam_type(key, args.exam_type)
    report["exam"] = {"name": key.get("name"), "examType": kind,
                      **{field: key[field] for field in ("year", "category", "total_questions", "scope", "complete") if field in key}}
    output = Path(args.output).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        fail("批改输出目录已有文件，请为本次批改使用新的空目录。")
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "grade-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["scoreEstimate"] = estimate_after_grade(report_path, kind)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    accuracy_text = "—" if judged == 0 else f"{counts['correct'] / judged:.1%}"
    lines = [f"# 批改报告：{key.get('name', key['paperId'])}", "", f"- 试卷：`{key['paperId']}`", f"- 答案版本：`{key['paperVersion']}`", f"- 作答：`{attempt.get('attemptId', '')}`", "", "## 统计", "", "| 正确 | 错误 | 未答 | 缺参考答案 | 无法判定 | 已判题正确率 |", "| ---: | ---: | ---: | ---: | ---: | ---: |", f"| {counts['correct']} | {counts['wrong']} | {counts['unanswered']} | {counts['reference_missing']} | {counts['ungradable']} | {accuracy_text} |", "", "## 逐题结果", "", "| 题号 | 题型 | 我的答案 | 参考答案 | 结果 | 来源 |", "| --- | --- | --- | --- | --- | --- |"]
    for row in rows: lines.append(f"| {row['number']} | {row['type']} | {display_answer(row['myAnswer'])} | {display_answer(row['referenceAnswer'])} | {row['result']} | {json.dumps(row['source'], ensure_ascii=False) if row['source'] else ''} |")
    score = report["scoreEstimate"]
    if score["status"] == "complete":
        scores = score["scores"]
        scope = "局部测验" if "局部" in scores["interpretation"] else "整卷"
        lines.extend(["", "## 行测估分", "",
                      f"{scope}等权估分：{scores['equal_weight']:.2f}；加权估分：{scores['weighted']:.2f}（非官方估算）。",
                      "", "详见 [估分报告](estimate.md)，包含模型、六模块统计和差异分析。"])
    elif kind == "xingce":
        lines.extend(["", "## 行测估分", "", f"暂未生成估分：{score['reason']}。批改结果已保留。"])
    elif kind == "shenlun":
        lines.extend(["", "## 申论估分", "", f"暂未生成估分：{score['reason']}。批改结果已保留。"])
    (output / "grade-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.archive_dir:
        archive = Path(args.archive_dir).expanduser().resolve() / key["paperId"] / key["paperVersion"] / report["batchId"]
        archive.mkdir(parents=True, exist_ok=False)
        shutil.copy2(key_path, archive / key_path.name); shutil.copy2(attempt_path, archive / attempt_path.name); shutil.copy2(output / "grade-report.json", archive / "grade-report.json"); shutil.copy2(output / "grade-report.md", archive / "grade-report.md")
        if score["status"] == "complete":
            for name in score["files"]:
                shutil.copy2(output / name, archive / name)
        source_dir = archive / "sources"; source_dir.mkdir()
        copied_sources: set[Path] = set()
        for item in key_questions:
            source = item.get("source") or {}
            source_path = Path(source.get("file", "")) if source.get("file") else None
            if source_path and source_path.is_file() and source_path.resolve() not in copied_sources:
                target = source_dir / source_path.name
                if target.exists(): target = source_dir / f"{len(copied_sources)}-{source_path.name}"
                shutil.copy2(source_path, target); copied_sources.add(source_path.resolve())
    print(output / "grade-report.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="答题助手：材料整理、答题卡生成和确定性批改")
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="提取 Word/PDF/文本材料"); extract.add_argument("input"); extract.add_argument("--output", required=True); extract.set_defaults(func=command_extract)
    prepare = sub.add_parser("prepare", help="从明确答案行生成私有答案集合"); prepare.add_argument("input"); prepare.add_argument("--output", required=True); prepare.add_argument("--paper-id", required=True); prepare.add_argument("--paper-version", required=True); prepare.add_argument("--name", required=True); prepare.add_argument("--question-type", choices=sorted(QUESTION_TYPES)); prepare.add_argument("--type-map", help="例如 41:single,42:multiple,43:boolean"); prepare.add_argument("--options"); prepare.add_argument("--section"); prepare.add_argument("--range"); prepare.set_defaults(func=command_prepare)
    config = sub.add_parser("generate-config", help="生成不含参考答案的公开答题卡配置"); config.add_argument("input"); config.add_argument("--output", required=True); config.set_defaults(func=command_generate_config)
    grade = sub.add_parser("grade", help="核对网页导出的作答记录并保存报告"); grade.add_argument("answer_set"); grade.add_argument("attempt"); grade.add_argument("--output", required=True); grade.add_argument("--archive-dir"); grade.set_defaults(func=command_grade)
    prepare.add_argument("--exam-type", choices=("xingce", "shenlun", "other", "unknown"), default="unknown", help="试卷科目；未知时不凭题型判断为行测")
    prepare.add_argument("--year", type=int)
    prepare.add_argument("--category", help="考试类别，如市地级或行政执法")
    prepare.add_argument("--total-questions", type=int, help="已知整卷题量")
    prepare.add_argument("--scope", choices=("full", "partial"), help="明确标记整卷或局部测验")
    grade.add_argument("--exam-type", choices=("auto", "xingce", "shenlun", "other"), default="auto", help="默认按答案集合的科目或明确试卷名称分流")
    return parser


if __name__ == "__main__":
    try:
        parsed = build_parser().parse_args()
        parsed.func(parsed)
    except BrokenPipeError:
        pass
