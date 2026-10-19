#!/usr/bin/env python3
"""Deterministic JSON/CSV scoring for the gongkao-xingce-score-estimator skill."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SIX_MODULES = [
    "政治理论",
    "常识判断",
    "言语理解与表达",
    "数量关系",
    "判断推理",
    "资料分析",
]

MISSING = object()


class EstimateError(Exception):
    """An expected input or configuration error with machine-readable details."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class Question:
    question_id: Any
    module: str
    status: str
    source_index: int
    user_answer: Any = None
    correct_answer: Any = None
    time_spent: Any = None


FIELD_ALIASES: Dict[str, List[str]] = {
    "id": [
        "id",
        "question_id",
        "questionid",
        "question_no",
        "question_number",
        "number",
        "seq",
        "sequence",
        "index",
        "题号",
        "题目编号",
        "编号",
        "序号",
    ],
    "module": [
        "module",
        "module_name",
        "subject",
        "section",
        "part",
        "question_module",
        "模块",
        "所属模块",
        "模块名称",
        "科目",
        "板块",
        "部分",
    ],
    "user_answer": [
        "user_answer",
        "useranswer",
        "answer",
        "selected_answer",
        "selectedanswer",
        "response",
        "my_answer",
        "myanswer",
        "choice",
        "user_choice",
        "用户答案",
        "考生答案",
        "作答",
        "选择",
        "选择答案",
    ],
    "correct_answer": [
        "correct_answer",
        "correctanswer",
        "standard_answer",
        "standardanswer",
        "expected_answer",
        "expectedanswer",
        "answer_key",
        "answerkey",
        "key",
        "correct",
        "标准答案",
        "正确答案",
        "参考答案",
    ],
    "status": [
        "is_correct",
        "iscorrect",
        "correctness",
        "right",
        "correct",
        "is_right",
        "correct_status",
        "correctstatus",
        "result",
        "status",
        "judge",
        "judgement",
        "是否正确",
        "是否答对",
        "答对",
        "正误",
        "对错",
        "批改结果",
        "判断结果",
    ],
    "time_spent": [
        "time",
        "elapsed",
        "elapsed_time",
        "duration",
        "spent_seconds",
        "seconds",
        "time_spent",
        "用时",
        "耗时",
        "答题用时",
    ],
    "exam": [
        "exam",
        "exam_name",
        "exam_title",
        "考试",
        "考试名称",
    ],
    "paper_name": ["paper_name", "paper", "试卷", "试卷名称", "test_name"],
    "category": [
        "exam_type",
        "exam_category",
        "category",
        "paper_type",
        "卷别",
        "考试类别",
        "试卷类型",
        "类别",
    ],
    "year": ["year", "exam_year", "年份", "考试年份"],
    "total_questions": [
        "total_questions",
        "totalquestion",
        "question_count",
        "questioncount",
        "total",
        "total_count",
        "题数",
        "总题数",
        "题目总数",
        "题量",
    ],
    "complete": [
        "is_complete",
        "iscomplete",
        "complete",
        "full_test",
        "fulltest",
        "completed",
        "是否完整",
        "完整试卷",
        "完整",
    ],
    "scope": ["scope", "test_scope", "范围", "测验范围"],
}


def normalize_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)


ALIAS_TO_CANONICAL: Dict[str, str] = {}
for _canonical, _aliases in FIELD_ALIASES.items():
    for _alias in _aliases:
        ALIAS_TO_CANONICAL[normalize_key(_alias)] = _canonical


MODULE_ALIASES: Dict[str, str] = {}
for _module, _aliases in {
    "政治理论": [
        "政治理论",
        "政治",
        "political theory",
        "political",
        "politics",
    ],
    "常识判断": ["常识判断", "常识", "common sense", "general knowledge"],
    "言语理解与表达": [
        "言语理解与表达",
        "言语理解",
        "言语",
        "verbal comprehension",
        "verbal",
        "language comprehension",
    ],
    "数量关系": [
        "数量关系",
        "数量",
        "数学运算",
        "quantitative reasoning",
        "quantitative",
        "math",
    ],
    "判断推理": [
        "判断推理",
        "推理判断",
        "判断",
        "推理",
        "reasoning",
        "logical reasoning",
    ],
    "资料分析": [
        "资料分析",
        "资料",
        "data analysis",
        "data interpretation",
        "data",
    ],
}.items():
    for _alias in _aliases:
        MODULE_ALIASES[normalize_key(_alias)] = _module


TRUE_VALUES = {"true", "yes", "y", "1", "correct", "right", "对", "正确", "是", "√", "ok"}
FALSE_VALUES = {"false", "no", "n", "0", "wrong", "incorrect", "错", "错误", "否", "×", "x", "不完整"}
TRUE_VALUES.add("完整")
UNANSWERED_VALUES = {
    "unanswered",
    "notanswered",
    "blank",
    "empty",
    "未作答",
    "未答",
    "空白",
    "空",
    "未填写",
    "无",
}


def _display_location(index: int, field: Optional[str] = None) -> str:
    return "第 {} 条记录{}".format(index, "的字段 " + field if field else "")


def get_path(value: Any, path: str) -> Any:
    current = value
    for part in str(path).split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            raise EstimateError(
                "mapping_path_not_found",
                "字段映射路径不存在",
                {"path": path, "missing_part": part},
            )
    return current


def _mapping_fields(mapping: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not mapping:
        return {}
    fields = mapping.get("fields")
    if fields is None:
        return mapping
    if not isinstance(fields, Mapping):
        raise EstimateError("invalid_mapping", "字段映射的 fields 必须是对象")
    return fields


def _values_for_canonical(
    record: Mapping[str, Any], canonical: str, mapping: Optional[Mapping[str, Any]] = None
) -> List[Tuple[str, Any]]:
    fields = _mapping_fields(mapping)
    mapped = fields.get(canonical, MISSING)
    if mapped is not MISSING:
        names = mapped if isinstance(mapped, list) else [mapped]
        result: List[Tuple[str, Any]] = []
        for name in names:
            if not isinstance(name, str):
                raise EstimateError("invalid_mapping", "字段映射值必须是字符串或字符串数组", {"field": canonical})
            try:
                value = get_path(record, name) if "." in name else record.get(name, MISSING)
            except EstimateError:
                raise
            if value is MISSING:
                normalized_name = normalize_key(name)
                for actual_key, actual_value in record.items():
                    if normalize_key(actual_key) == normalized_name:
                        value = actual_value
                        break
            if value is not MISSING:
                result.append((name, value))
        if result:
            return result

    aliases = {normalize_key(alias) for alias in FIELD_ALIASES.get(canonical, [])}
    result = []
    for key, value in record.items():
        if normalize_key(key) in aliases:
            result.append((str(key), value))
    return result


def _nonempty_values(values: Iterable[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
    result = []
    for key, value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        result.append((key, value))
    return result


def _single_field_value(
    record: Mapping[str, Any],
    canonical: str,
    index: int,
    mapping: Optional[Mapping[str, Any]],
    required: bool = False,
    keep_empty: bool = False,
) -> Any:
    values = _values_for_canonical(record, canonical, mapping) if keep_empty else _nonempty_values(_values_for_canonical(record, canonical, mapping))
    if keep_empty:
        values = [(key, value) for key, value in values if value is not MISSING]
    if not values:
        if required:
            raise EstimateError(
                "missing_field",
                "缺少必要字段",
                {"location": _display_location(index), "field": canonical},
            )
        return MISSING
    first = values[0][1]
    normalized_first = normalize_key(first) if isinstance(first, str) else first
    for key, value in values[1:]:
        normalized = normalize_key(value) if isinstance(value, str) else value
        if normalized != normalized_first:
            raise EstimateError(
                "conflicting_fields",
                "同一字段的多个别名值相互矛盾",
                {"location": _display_location(index), "field": canonical, "values": [first, value]},
            )
    return first


def parse_status(value: Any, location: str) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "correct" if value else "wrong"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise EstimateError("invalid_status", "批改状态不是有限值", {"location": location})
        if value == 1:
            return "correct"
        if value == 0:
            return "wrong"
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    if not text:
        return None
    normalized = normalize_key(text)
    if text in TRUE_VALUES or normalized in {normalize_key(v) for v in TRUE_VALUES}:
        return "correct"
    if text in FALSE_VALUES or normalized in {normalize_key(v) for v in FALSE_VALUES}:
        return "wrong"
    if text in UNANSWERED_VALUES or normalized in {normalize_key(v) for v in UNANSWERED_VALUES}:
        return "unanswered"
    raise EstimateError(
        "invalid_status",
        "无法识别批改状态",
        {"location": location, "value": value, "allowed": ["正确", "错误", "未作答"]},
    )


def normalize_answer(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip().upper()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^(?:选项|答案|OPTION)", "", text, flags=re.IGNORECASE)
    return text


def canonical_module(value: Any, index: int) -> str:
    if value is MISSING or value is None or (isinstance(value, str) and not value.strip()):
        raise EstimateError("missing_module", "题目缺少所属模块", {"location": _display_location(index)})
    key = normalize_key(value)
    if key not in MODULE_ALIASES:
        raise EstimateError(
            "unknown_module",
            "无法识别模块名称，不能按题号猜测模块",
            {"location": _display_location(index), "module": value, "allowed": SIX_MODULES},
        )
    return MODULE_ALIASES[key]


def canonical_question_id(value: Any, index: int) -> Any:
    if value is MISSING or value is None or (isinstance(value, str) and not value.strip()):
        raise EstimateError("missing_question_id", "题目缺少题号", {"location": _display_location(index)})
    if isinstance(value, bool):
        raise EstimateError("invalid_question_id", "题号不能是布尔值", {"location": _display_location(index)})
    if isinstance(value, int):
        if value <= 0:
            raise EstimateError("invalid_question_id", "题号必须为正数", {"location": _display_location(index)})
        return value
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if re.fullmatch(r"\d+", text):
        number = int(text)
        if number <= 0:
            raise EstimateError("invalid_question_id", "题号必须为正数", {"location": _display_location(index)})
        return number
    return text


def canonicalize_question(
    record: Any, index: int, mapping: Optional[Mapping[str, Any]] = None
) -> Tuple[Question, List[str]]:
    if not isinstance(record, Mapping):
        raise EstimateError("invalid_record", "题目记录必须是对象", {"location": _display_location(index)})

    question_id = canonical_question_id(_single_field_value(record, "id", index, mapping, required=True), index)
    module = canonical_module(_single_field_value(record, "module", index, mapping, required=True), index)

    status_values = _values_for_canonical(record, "status", mapping)
    statuses: List[str] = []
    for field_name, value in status_values:
        try:
            parsed = parse_status(value, _display_location(index, field_name))
        except EstimateError:
            # Some exports use a bare `correct` column for the answer key.
            # Treat an option-like value as an answer-key field; other unknown
            # status values remain hard errors.
            if normalize_key(field_name) == "correct" and normalize_answer(value) in {"A", "B", "C", "D", "E", "F"}:
                continue
            raise
        if parsed is not None:
            statuses.append(parsed)
    if len(set(statuses)) > 1:
        raise EstimateError(
            "conflicting_status",
            "多个批改字段给出了相互矛盾的结果",
            {"location": _display_location(index), "statuses": statuses},
        )
    status = statuses[0] if statuses else None

    user_value = _single_field_value(record, "user_answer", index, mapping, keep_empty=True)
    correct_value = _single_field_value(record, "correct_answer", index, mapping)
    warnings: List[str] = []
    if status is None:
        if user_value is MISSING:
            raise EstimateError(
                "missing_user_answer",
                "没有批改结果时必须提供用户答案；字段缺失不能当作未作答",
                {"location": _display_location(index), "field": "user_answer"},
            )
        if user_value is None or (isinstance(user_value, str) and not user_value.strip()):
            status = "unanswered"
        else:
            if correct_value is MISSING or correct_value is None or (isinstance(correct_value, str) and not correct_value.strip()):
                raise EstimateError(
                    "missing_correct_answer",
                    "没有批改结果时，非空用户答案必须有标准答案",
                    {"location": _display_location(index), "field": "correct_answer"},
                )
            status = "correct" if normalize_answer(user_value) == normalize_answer(correct_value) else "wrong"
    else:
        if user_value is not MISSING and correct_value is not MISSING:
            compared = "correct" if normalize_answer(user_value) == normalize_answer(correct_value) else "wrong"
            if compared != status and status != "unanswered":
                warnings.append("{} 的批改结果优先于答案比较结果".format(_display_location(index)))

    time_value = _single_field_value(record, "time_spent", index, mapping)
    return (
        Question(
            question_id=question_id,
            module=module,
            status=status,
            source_index=index,
            user_answer=None if user_value is MISSING else user_value,
            correct_answer=None if correct_value is MISSING else correct_value,
            time_spent=None if time_value is MISSING else time_value,
        ),
        warnings,
    )


def decode_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise EstimateError("decode_error", "输入文件不是可识别的 UTF-8 或 GB18030 文本", {"path": str(path)})


def load_mapping(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    try:
        data = json.loads(decode_text(path))
    except json.JSONDecodeError as exc:
        raise EstimateError("invalid_mapping", "字段映射文件不是有效 JSON", {"path": str(path), "error": str(exc)})
    if not isinstance(data, Mapping):
        raise EstimateError("invalid_mapping", "字段映射文件必须是 JSON 对象")
    return dict(data)


def load_metadata_file(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(decode_text(path))
    except json.JSONDecodeError as exc:
        raise EstimateError("invalid_metadata", "考试元数据文件不是有效 JSON", {"path": str(path), "error": str(exc)})
    if not isinstance(data, Mapping):
        raise EstimateError("invalid_metadata", "考试元数据文件必须是 JSON 对象")
    return dict(data)


def extract_questions(data: Any, mapping: Optional[Mapping[str, Any]]) -> Tuple[List[Any], Dict[str, Any]]:
    if isinstance(data, list):
        return data, {}
    if not isinstance(data, Mapping):
        raise EstimateError("invalid_json_shape", "JSON 必须是题目数组或包含题目数组的对象")

    if mapping and mapping.get("questions_path"):
        value = get_path(data, str(mapping["questions_path"]))
        if not isinstance(value, list):
            raise EstimateError("invalid_questions_array", "字段映射指定的题目路径不是数组", {"path": mapping["questions_path"]})
        return value, dict(data)

    candidates = []
    for key, value in data.items():
        if normalize_key(key) in {"questions", "items", "records", "data"} and isinstance(value, list):
            candidates.append((str(key), value))
    if len(candidates) > 1:
        raise EstimateError(
            "ambiguous_questions_array",
            "JSON 中存在多个候选题目数组，请使用字段映射明确指定",
            {"candidates": [item[0] for item in candidates]},
        )
    if candidates:
        return candidates[0][1], dict(data)
    # A single question object is useful for exports containing one record.
    if any(normalize_key(key) in {normalize_key("id"), normalize_key("题号")} for key in data.keys()):
        return [dict(data)], dict(data)
    raise EstimateError(
        "missing_questions_array",
        "JSON 中没有找到 questions、items、records 或 data 题目数组",
    )


def load_input(path: Path, mapping: Optional[Mapping[str, Any]]) -> Tuple[List[Any], Dict[str, Any], str]:
    if not path.is_file():
        raise EstimateError("input_not_found", "输入文件不存在", {"path": str(path)})
    suffix = path.suffix.casefold()
    text = decode_text(path)
    if suffix == ".json" or (suffix not in {".csv", ".tsv"} and text.lstrip().startswith(("{", "["))):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise EstimateError("invalid_json", "输入文件不是有效 JSON", {"path": str(path), "error": str(exc)})
        questions, metadata = extract_questions(data, mapping)
        return questions, metadata, "json"

    if suffix not in {".csv", ".tsv"} and not text.lstrip():
        raise EstimateError("empty_input", "输入文件为空", {"path": str(path)})
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample else ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    if not reader.fieldnames:
        raise EstimateError("missing_csv_header", "CSV 缺少表头", {"path": str(path)})
    normalized_headers = [normalize_key(header) for header in reader.fieldnames if header is not None]
    duplicates = [key for key, count in Counter(normalized_headers).items() if count > 1 and key]
    if duplicates:
        raise EstimateError("duplicate_csv_header", "CSV 表头存在重复字段", {"headers": duplicates})
    rows = [dict(row) for row in reader]
    if not rows:
        raise EstimateError("empty_input", "CSV 没有题目记录", {"path": str(path)})
    return rows, dict(rows[0]), "csv"


def parse_int(value: Any, field: str) -> Optional[int]:
    if value is MISSING or value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise EstimateError("invalid_metadata", "元数据字段必须是整数", {"field": field, "value": value})
    text = str(value).strip()
    if not re.fullmatch(r"\d+", text):
        raise EstimateError("invalid_metadata", "元数据字段必须是非负整数", {"field": field, "value": value})
    result = int(text)
    if result < 0:
        raise EstimateError("invalid_metadata", "元数据字段不能为负数", {"field": field, "value": value})
    return result


def metadata_value(metadata: Mapping[str, Any], canonical: str) -> Any:
    values = _nonempty_values(_values_for_canonical(metadata, canonical))
    if not values:
        return MISSING
    return values[0][1]


def parse_boolish(value: Any, field: str) -> Optional[bool]:
    status = parse_status(value, field)
    if status is None:
        return None
    if status == "correct":
        return True
    if status == "wrong":
        return False
    raise EstimateError("invalid_metadata", "完整性字段不能表示未作答", {"field": field, "value": value})


def derive_metadata(
    raw_metadata: Mapping[str, Any],
    metadata_override: Mapping[str, Any],
    cli: argparse.Namespace,
    source_format: str,
    record_count: int,
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(raw_metadata)
    merged.update(metadata_override)

    exam = cli.exam or metadata_value(merged, "exam")
    paper_name = cli.paper_name or metadata_value(merged, "paper_name")
    if paper_name is MISSING:
        paper_name = exam
    if exam is MISSING:
        exam = paper_name if paper_name is not MISSING else None
    category = cli.category or metadata_value(merged, "category")
    category = None if category is MISSING else str(category).strip() or None
    exam_text = "" if exam is None else str(exam)
    if category is None:
        for candidate in ("副省级", "市地级", "行政执法"):
            if normalize_key(candidate) in normalize_key(exam_text):
                category = candidate
                break

    year_value = cli.year if cli.year is not None else metadata_value(merged, "year")
    year = parse_int(year_value, "year")
    if year is None:
        year_match = re.search(r"(20\d{2})", exam_text)
        year = int(year_match.group(1)) if year_match else None

    total_value = cli.total_questions if cli.total_questions is not None else metadata_value(merged, "total_questions")
    declared_total = parse_int(total_value, "total_questions")
    complete_value = metadata_value(merged, "complete")
    explicit_complete = parse_boolish(complete_value, "complete") if complete_value is not MISSING else None
    scope_value = metadata_value(merged, "scope")
    input_scope = None if scope_value is MISSING else normalize_key(scope_value)
    return {
        "name": None if exam is None or exam is MISSING else str(exam),
        "paper_name": None if paper_name is None or paper_name is MISSING else str(paper_name),
        "category": category,
        "year": year,
        "declared_total": declared_total,
        "explicit_complete": explicit_complete,
        "input_scope": input_scope,
        "source_format": source_format,
        "records_read": record_count,
    }


def validate_completeness(
    questions: Sequence[Question], metadata: Mapping[str, Any], requested_scope: str
) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    partial_reasons: List[str] = []
    declared_total = metadata.get("declared_total")
    if requested_scope == "partial":
        partial_reasons.append("命令行指定局部范围")
    if metadata.get("explicit_complete") is False:
        partial_reasons.append("输入明确标记为非完整试卷")
    if metadata.get("input_scope") in {"partial", "local", "局部", "局部测验"}:
        partial_reasons.append("输入范围字段标记为局部测验")
    if declared_total is not None and declared_total > len(questions):
        partial_reasons.append("声明总题数大于读取记录数")
        warnings.append("声明总题数为 {}，但只读取到 {} 条记录".format(declared_total, len(questions)))
    if declared_total is not None and declared_total < len(questions):
        raise EstimateError(
            "too_many_questions",
            "读取记录数超过声明总题数",
            {"declared_total": declared_total, "records_read": len(questions)},
        )

    numeric_ids = [item.question_id for item in questions if isinstance(item.question_id, int)]
    all_numeric = len(numeric_ids) == len(questions)
    gap_count = 0
    if all_numeric and numeric_ids:
        unique_ids = set(numeric_ids)
        upper = declared_total or max(unique_ids)
        if min(unique_ids) != 1:
            gap_count += min(unique_ids) - 1
        if upper >= 1:
            gap_count += len(set(range(1, upper + 1)) - unique_ids)
        if gap_count:
            partial_reasons.append("数值题号存在缺口")
            warnings.append("数值题号存在 {} 个缺口，未自动补题".format(gap_count))

    if not partial_reasons:
        basis = "按文件记录视为完整" if requested_scope == "auto" else "命令行指定完整范围"
        scope = "full"
        is_full = True
    else:
        basis = "；".join(partial_reasons)
        scope = "partial"
        is_full = False
    missing_count = max(gap_count, (declared_total or len(questions)) - len(questions))
    return (
        {
            "scope": scope,
            "is_full": is_full,
            "basis": basis,
            "records_read": len(questions),
            "declared_total": declared_total,
            "missing_count": missing_count,
        },
        warnings,
    )


def parse_fraction(value: Any, field: str) -> Fraction:
    if isinstance(value, bool) or value is None:
        raise EstimateError("invalid_weight", "权重必须是正数", {"field": field, "value": value})
    if isinstance(value, float) and not math.isfinite(value):
        raise EstimateError("invalid_weight", "权重必须是有限数", {"field": field, "value": value})
    try:
        result = Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError, InvalidOperation) as exc:
        raise EstimateError("invalid_weight", "无法解析权重", {"field": field, "value": value, "error": str(exc)})
    if result <= 0:
        raise EstimateError("invalid_weight", "权重必须大于零", {"field": field, "value": value})
    return result


def fraction_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else "{}/{}".format(value.numerator, value.denominator)


def load_weights(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise EstimateError("weights_not_found", "权重配置文件不存在", {"path": str(path)})
    try:
        data = json.loads(decode_text(path))
    except json.JSONDecodeError as exc:
        raise EstimateError("invalid_weights", "权重配置不是有效 JSON", {"path": str(path), "error": str(exc)})
    if not isinstance(data, Mapping) or not isinstance(data.get("models"), list):
        raise EstimateError("invalid_weights", "权重配置必须包含 models 数组")
    models: Dict[str, Dict[str, Any]] = {}
    for raw_model in data["models"]:
        if not isinstance(raw_model, Mapping) or not raw_model.get("id"):
            raise EstimateError("invalid_weights", "每个权重模型必须是带 id 的对象")
        model = dict(raw_model)
        model_id = str(model["id"])
        if model_id in models:
            raise EstimateError("invalid_weights", "权重模型 id 重复", {"id": model_id})
        raw_weights = model.get("weights")
        if not isinstance(raw_weights, Mapping):
            raise EstimateError("invalid_weights", "权重模型缺少 weights 对象", {"id": model_id})
        missing = [module for module in SIX_MODULES if module not in raw_weights]
        extra = [str(key) for key in raw_weights.keys() if key not in SIX_MODULES]
        if missing or extra:
            raise EstimateError("invalid_weights", "权重模型的模块键不完整或包含未知模块", {"id": model_id, "missing": missing, "extra": extra})
        parsed = {module: parse_fraction(raw_weights[module], "{}.weights.{}".format(model_id, module)) for module in SIX_MODULES}
        model["parsed_weights"] = parsed
        models[model_id] = model
    default_model = str(data.get("default_model") or "")
    if default_model not in models:
        raise EstimateError("invalid_weights", "default_model 不存在于 models", {"default_model": default_model})
    return {"schema_version": data.get("schema_version"), "default_model": default_model, "models": models}


def model_matches(model: Mapping[str, Any], metadata: Mapping[str, Any], counts: Mapping[str, int]) -> bool:
    applicability = model.get("applicability") or {}
    if not isinstance(applicability, Mapping):
        return False
    exam_keywords = applicability.get("exam_keywords") or []
    exam_text = " ".join(str(metadata.get(key) or "") for key in ("name", "paper_name", "category"))
    if exam_keywords and not any(str(keyword) in exam_text for keyword in exam_keywords):
        return False
    years = applicability.get("years") or []
    if years and metadata.get("year") not in years:
        return False
    categories = applicability.get("categories") or []
    actual_category = normalize_key(metadata.get("category") or "")
    if categories and not any(normalize_key(category) in actual_category for category in categories):
        return False
    profiles = applicability.get("module_count_profiles") or []
    if profiles:
        return any(all(int(profile.get(module, -1)) == counts.get(module, 0) for module in SIX_MODULES) for profile in profiles if isinstance(profile, Mapping))
    return True


def choose_model(
    weights: Mapping[str, Any], model_id: str, metadata: Mapping[str, Any], counts: Mapping[str, int]
) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    models = weights["models"]
    if model_id != "auto":
        if model_id not in models:
            raise EstimateError("unknown_model", "指定的权重模型不存在", {"model": model_id, "available": sorted(models)})
        selected = models[model_id]
        if not model_matches(selected, metadata, counts):
            warnings.append("指定模型 {} 超出其标注适用范围，仍按用户选择计算".format(model_id))
    else:
        reference = models.get("huatu-six-v1")
        if reference and model_matches(reference, metadata, counts):
            selected = reference
        else:
            selected = models[weights["default_model"]]
            warnings.append("考试信息或模块题量未可靠匹配公开方案，使用假设性模型 {}".format(selected["id"]))
    public_model = {key: value for key, value in selected.items() if key != "parsed_weights"}
    public_model["weights"] = {module: fraction_text(selected["parsed_weights"][module]) for module in SIX_MODULES}
    public_model["weight_values"] = {module: float(selected["parsed_weights"][module]) for module in SIX_MODULES}
    return {"model": public_model, "parsed_weights": selected["parsed_weights"]}, warnings


def rounded_fraction(value: Fraction, digits: int = 2) -> float:
    quantum = Decimal("1").scaleb(-digits)
    decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
    rounded = decimal_value.quantize(quantum, rounding=ROUND_HALF_UP)
    return float(rounded)


def calculate_report(
    questions: Sequence[Question],
    metadata: Mapping[str, Any],
    completeness: Mapping[str, Any],
    weights: Mapping[str, Any],
    requested_model: str,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    report_warnings = list(warnings or [])
    counts = {module: 0 for module in SIX_MODULES}
    correct_counts = {module: 0 for module in SIX_MODULES}
    status_counts = Counter(item.status for item in questions)
    seen_ids = set()
    for question in questions:
        id_key = (type(question.question_id).__name__, question.question_id)
        if id_key in seen_ids:
            raise EstimateError("duplicate_question_id", "题号重复", {"question_id": question.question_id, "location": _display_location(question.source_index)})
        seen_ids.add(id_key)
        counts[question.module] += 1
        if question.status == "correct":
            correct_counts[question.module] += 1

    completeness_result, completeness_warnings = validate_completeness(questions, metadata, metadata.get("requested_scope", "auto"))
    report_warnings.extend(completeness_warnings)
    selected, model_warnings = choose_model(weights, requested_model, metadata, counts)
    report_warnings.extend(model_warnings)
    parsed_weights = selected["parsed_weights"]
    total = len(questions)
    if total <= 0:
        raise EstimateError("empty_questions", "没有可计算的题目记录")
    correct = sum(1 for item in questions if item.status == "correct")
    wrong = sum(1 for item in questions if item.status == "wrong")
    unanswered = sum(1 for item in questions if item.status == "unanswered")
    equal_raw = Fraction(correct * 100, total)
    weighted_denominator = sum(Fraction(counts[module]) * parsed_weights[module] for module in SIX_MODULES)
    weighted_numerator = sum(Fraction(correct_counts[module]) * parsed_weights[module] for module in SIX_MODULES)
    weighted_raw = weighted_numerator * 100 / weighted_denominator
    difference_raw = weighted_raw - equal_raw

    modules: List[Dict[str, Any]] = []
    for module in SIX_MODULES:
        module_total = counts[module]
        module_correct = correct_counts[module]
        accuracy_raw = Fraction(module_correct, module_total) if module_total else None
        equal_contribution_raw = Fraction(module_correct * 100, total)
        weighted_contribution_raw = Fraction(module_correct) * parsed_weights[module] * 100 / weighted_denominator
        modules.append(
            {
                "module": module,
                "total": module_total,
                "correct": module_correct,
                "wrong": sum(1 for item in questions if item.module == module and item.status == "wrong"),
                "unanswered": sum(1 for item in questions if item.module == module and item.status == "unanswered"),
                "accuracy": rounded_fraction(accuracy_raw * 100) if accuracy_raw is not None else None,
                "equal_contribution": rounded_fraction(equal_contribution_raw),
                "weighted_contribution": rounded_fraction(weighted_contribution_raw),
                "_accuracy_raw": accuracy_raw,
                "_equal_raw": equal_contribution_raw,
                "_weighted_raw": weighted_contribution_raw,
            }
        )

    active_modules = [item for item in modules if item["total"] > 0]
    highest_accuracy = []
    lowest_accuracy = []
    if active_modules:
        max_accuracy = max(item["_accuracy_raw"] for item in active_modules)
        min_accuracy = min(item["_accuracy_raw"] for item in active_modules)
        highest_accuracy = [item["module"] for item in active_modules if item["_accuracy_raw"] == max_accuracy]
        lowest_accuracy = [item["module"] for item in active_modules if item["_accuracy_raw"] == min_accuracy]
        max_contribution = max(item["_weighted_raw"] for item in active_modules)
        contribution_leaders = [item["module"] for item in active_modules if item["_weighted_raw"] == max_contribution]
    else:
        contribution_leaders = []

    positive_drivers = [item for item in active_modules if item["_weighted_raw"] > item["_equal_raw"]]
    negative_drivers = [item for item in active_modules if item["_weighted_raw"] < item["_equal_raw"]]
    if difference_raw > 0:
        drivers = sorted(positive_drivers, key=lambda item: item["_weighted_raw"] - item["_equal_raw"], reverse=True)
        names = [item["module"] for item in drivers[:3]]
        difference_explanation = "加权估分高于等权估分，主要因为{}的加权贡献高于等权贡献。".format("、".join(names) if names else "高系数模块")
    elif difference_raw < 0:
        drivers = sorted(negative_drivers, key=lambda item: item["weighted_contribution"] - item["equal_contribution"])
        names = [item["module"] for item in drivers[:3]]
        difference_explanation = "加权估分低于等权估分，主要因为{}的加权贡献低于等权贡献。".format("、".join(names) if names else "低系数模块")
    else:
        difference_explanation = "两种估分相同：各模块正确率与按模块系数归一化后的整体结果没有形成净差异。"

    for item in modules:
        for key in ("_accuracy_raw", "_equal_raw", "_weighted_raw"):
            item.pop(key, None)

    report = {
        "schema_version": "1.0",
        "exam": {
            "name": metadata.get("name") or "未提供",
            "paper_name": metadata.get("paper_name") or metadata.get("name") or "未提供",
            "year": metadata.get("year"),
            "category": metadata.get("category"),
            "source_format": metadata.get("source_format"),
        },
        "completeness": completeness_result,
        "counts": {
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "unanswered": unanswered,
            "accuracy": rounded_fraction(Fraction(correct * 100, total)),
        },
        "scores": {
            "equal_weight": rounded_fraction(equal_raw),
            "weighted": rounded_fraction(weighted_raw),
            "difference": rounded_fraction(difference_raw),
            "difference_definition": "加权估分 - 等权估分",
            "weighted_model_id": selected["model"]["id"],
            "weighted_model_name": selected["model"].get("name", selected["model"]["id"]),
            "weighted_is_official": False,
            "interpretation": "局部测验结果，仅代表纳入题目" if not completeness_result["is_full"] else "按完整试卷口径计算",
        },
        "modules": modules,
        "model": selected["model"],
        "analysis": {
            "highest_accuracy_modules": highest_accuracy,
            "lowest_accuracy_modules": lowest_accuracy,
            "largest_weighted_contribution_modules": contribution_leaders,
            "difference_explanation": difference_explanation,
        },
        "warnings": report_warnings,
    }
    return report


def report_from_file(
    input_path: Path,
    weights_path: Path,
    requested_model: str = "auto",
    mapping_path: Optional[Path] = None,
    metadata_path: Optional[Path] = None,
    cli_options: Optional[argparse.Namespace] = None,
    requested_scope: str = "auto",
) -> Dict[str, Any]:
    mapping = load_mapping(mapping_path)
    raw_questions, raw_metadata, source_format = load_input(input_path, mapping)
    override = load_metadata_file(metadata_path)
    if cli_options is None:
        cli_options = argparse.Namespace(exam=None, category=None, year=None, paper_name=None, total_questions=None)
    cli_options.scope = requested_scope
    questions: List[Question] = []
    warnings: List[str] = []
    for index, record in enumerate(raw_questions, start=1):
        question, question_warnings = canonicalize_question(record, index, mapping)
        questions.append(question)
        warnings.extend(question_warnings)
    seen: Dict[Tuple[str, Any], int] = {}
    for question in questions:
        key = (type(question.question_id).__name__, question.question_id)
        if key in seen:
            raise EstimateError(
                "duplicate_question_id",
                "题号重复",
                {"question_id": question.question_id, "first_record": seen[key], "second_record": question.source_index},
            )
        seen[key] = question.source_index
    metadata = derive_metadata(raw_metadata, override, cli_options, source_format, len(questions))
    metadata["requested_scope"] = requested_scope
    weights = load_weights(weights_path)
    return calculate_report(questions, metadata, metadata, weights, requested_model, warnings)


def _score_text(value: Optional[float]) -> str:
    return "—" if value is None else "{:.2f}".format(value)


def _percent_text(value: Optional[float]) -> str:
    return "—" if value is None else "{:.2f}%".format(value)


def _signed_text(value: float) -> str:
    return "+{:.2f}".format(value) if value > 0 else "{:.2f}".format(value)


def markdown_report(report: Mapping[str, Any]) -> str:
    full = bool(report["completeness"]["is_full"])
    title = "行测双轨估分报告" if full else "行测双轨估分报告（局部测验）"
    counts = report["counts"]
    scores = report["scores"]
    exam = report["exam"]
    lines = [
        "# {}".format(title),
        "",
        "> 加权模型：{}（非官方估算）".format(scores["weighted_model_name"]),
        "> 完整性依据：{}".format(report["completeness"]["basis"]),
        "",
        "## {}".format("总成绩" if full else "局部测验成绩（不代表整卷）"),
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        "| 试卷名称 | {} |".format(exam["paper_name"]),
        "| 总题数 | {} |".format(counts["total"]),
        "| 正确题数 | {} |".format(counts["correct"]),
        "| 错误题数 | {} |".format(counts["wrong"]),
        "| 未作答题数 | {} |".format(counts["unanswered"]),
        "| 总正确率 | {} |".format(_percent_text(counts["accuracy"])),
        "| 等权估分 | {} |".format(_score_text(scores["equal_weight"])),
        "| 加权估分 | {} |".format(_score_text(scores["weighted"])),
        "| 两种估分差异（加权−等权） | {} |".format(_signed_text(scores["difference"])),
        "",
        "## 六大模块成绩",
        "",
        "| 模块 | 题数 | 正确 | 正确率 | 等权贡献分 | 加权贡献分 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["modules"]:
        lines.append(
            "| {module} | {total} | {correct} | {accuracy} | {equal} | {weighted} |".format(
                module=item["module"],
                total=item["total"],
                correct=item["correct"],
                accuracy=_percent_text(item["accuracy"]),
                equal=_score_text(item["equal_contribution"]),
                weighted=_score_text(item["weighted_contribution"]),
            )
        )
    analysis = report["analysis"]
    lines.extend(
        [
            "",
            "## 简短分析",
            "",
            "1. 正确率最高：{}；最低：{}。".format(
                "、".join(analysis["highest_accuracy_modules"]) or "无",
                "、".join(analysis["lowest_accuracy_modules"]) or "无",
            ),
            "2. 按加权贡献分计算，贡献最大：{}。".format("、".join(analysis["largest_weighted_contribution_modules"]) or "无"),
            "3. {}".format(analysis["difference_explanation"]),
            "",
            "模型来源：{}".format("；".join(source.get("url", "") for source in report["model"].get("source", [])) or "配置文件未提供"),
        ]
    )
    if report.get("warnings"):
        lines.extend(["", "## 校验提示", ""])
        lines.extend("- {}".format(warning) for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    default_weights = Path(__file__).resolve().parent.parent / "references" / "weights.json"
    parser = argparse.ArgumentParser(description="计算行测等权与非官方经验加权估分")
    parser.add_argument("input", type=Path, help="JSON 或 CSV 答题文件")
    parser.add_argument("--format", choices=("json", "markdown", "both"), default="json", dest="output_format")
    parser.add_argument("--output-dir", type=Path, help="both 格式的输出目录")
    parser.add_argument("--weights", type=Path, default=default_weights, help="权重配置 JSON")
    parser.add_argument("--model", default="auto", help="权重模型 id，默认 auto")
    parser.add_argument("--mapping", type=Path, help="字段映射 JSON")
    parser.add_argument("--metadata", type=Path, help="考试元数据 JSON")
    parser.add_argument("--exam", help="试卷或考试名称")
    parser.add_argument("--paper-name", help="试卷名称")
    parser.add_argument("--category", help="考试类别，例如副省级、市地级、行政执法")
    parser.add_argument("--year", type=int, help="考试年份")
    parser.add_argument("--total-questions", type=int, help="整卷总题数")
    parser.add_argument("--scope", choices=("auto", "full", "partial"), default="auto", help="完整性口径")
    return parser


def error_payload(error: EstimateError) -> Dict[str, Any]:
    return {"error": {"code": error.code, "message": error.message, "details": error.details}}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_path = args.input.resolve()
    weights_path = args.weights.resolve()
    try:
        report = report_from_file(
            input_path=input_path,
            weights_path=weights_path,
            requested_model=args.model,
            mapping_path=args.mapping.resolve() if args.mapping else None,
            metadata_path=args.metadata.resolve() if args.metadata else None,
            cli_options=args,
            requested_scope=args.scope,
        )
        if args.output_format == "both":
            if args.output_dir is None:
                raise EstimateError("missing_output_dir", "both 格式必须指定 --output-dir")
            output_dir = args.output_dir.resolve()
            json_path = output_dir / "estimate.json"
            markdown_path = output_dir / "estimate.md"
            if input_path in {json_path.resolve(), markdown_path.resolve()} or weights_path in {json_path.resolve(), markdown_path.resolve()}:
                raise EstimateError("unsafe_output_path", "输出路径不能覆盖输入或权重配置文件")
            output_dir.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            markdown_path.write_text(markdown_report(report), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.output_format == "markdown":
            print(markdown_report(report), end="")
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except EstimateError as error:
        print(json.dumps(error_payload(error), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except OSError as error:
        wrapped = EstimateError("io_error", "读写文件失败", {"error": str(error)})
        print(json.dumps(error_payload(wrapped), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
