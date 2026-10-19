#!/usr/bin/env python3
"""Adapt a graded Xingce report without rejudging or guessing modules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import estimate


def grade_input(report):
    if report.get("type") != "exam-grade-report":
        raise estimate.EstimateError("invalid_grade_report", "输入不是批改报告")
    metadata = report.get("exam", {})
    if metadata.get("examType") != "xingce":
        raise estimate.EstimateError("not_xingce", "仅接收明确标注为行测的批改报告")
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        raise estimate.EstimateError("empty_questions", "批改报告没有题目记录")
    questions = []
    seen = set()
    for index, row in enumerate(rows, start=1):
        identity = row.get("questionId")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise estimate.EstimateError("invalid_question_identity", "题目身份缺失或重复", {"record": index})
        seen.add(identity)
        state = row.get("result")
        if state not in {"correct", "wrong", "unanswered"}:
            raise estimate.EstimateError("unresolved_grade", "存在缺参考答案或无法判定的题目，暂不估分",
                                         {"questionId": identity, "result": state})
        # Keep the explicit displayed number for gap detection; the source ID
        # remains separately available instead of competing as an ID alias.
        number = row.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise estimate.EstimateError("invalid_question_number", "批改报告题号必须是正整数", {"questionId": identity})
        module = row.get("module") or row.get("section")
        if not module:
            raise estimate.EstimateError("missing_module", "题目缺少所属模块，暂不估分", {"questionId": identity, "number": number})
        questions.append({"id": number, "module": module, "status": state})
    payload = {key: metadata[key] for key in ("name", "year", "category", "total_questions", "scope", "complete") if metadata.get(key) is not None}
    payload.update({"paperId": report["paperId"], "paperVersion": report["paperVersion"],
                    "attemptId": report.get("attemptId"), "batchId": report.get("batchId"),
                    "source_question_ids": [row["questionId"] for row in rows], "questions": questions})
    return payload


def score_report(report):
    payload = grade_input(report)
    questions, warnings = [], []
    for index, row in enumerate(payload["questions"], start=1):
        question, notices = estimate.canonicalize_question(row, index, None)
        questions.append(question)
        warnings.extend(notices)
    cli = argparse.Namespace(exam=None, paper_name=None, category=None, year=None, total_questions=None)
    metadata = estimate.derive_metadata(payload, {}, cli, "exam-grade-report", len(questions))
    metadata["requested_scope"] = "auto"
    weights = estimate.load_weights(Path(__file__).resolve().parents[1] / "references/weights.json")
    result = estimate.calculate_report(questions, metadata, metadata, weights, "auto", warnings)
    result["grading_source"] = {key: payload.get(key) for key in ("paperId", "paperVersion", "attemptId", "batchId", "source_question_ids")}
    return payload, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("exam", {}).get("examType") != "xingce":
        print(json.dumps({"status": "skipped", "reason": "未明确是行测试卷"}, ensure_ascii=False))
        return
    try:
        payload, result = score_report(report)
    except estimate.EstimateError as error:
        print(json.dumps({"status": "pending", "reason": error.message, "error": estimate.error_payload(error)["error"]}, ensure_ascii=False))
        return
    output = args.output_dir.resolve()
    names = ("estimate-input.json", "estimate.json", "estimate.md")
    if any((output / name).exists() for name in names):
        raise ValueError("估分输出已存在，请使用新的批次目录")
    output.mkdir(parents=True, exist_ok=True)
    (output / names[0]).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / names[1]).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / names[2]).write_text(estimate.markdown_report(result), encoding="utf-8")
    print(json.dumps({"status": "complete", "files": list(names), "scores": result["scores"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
