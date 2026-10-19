#!/usr/bin/env python3
"""Route a graded public-exam report to the subject scoring subskill."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def exam_type(metadata: dict[str, Any], override: str = "auto") -> str:
    """Return xingce, shenlun, other, or unknown without guessing from question shape."""
    if override != "auto":
        return override
    declared = metadata.get("examType")
    if declared in {"xingce", "行测", "行政职业能力测验"}:
        return "xingce"
    if declared in {"shenlun", "申论"}:
        return "shenlun"
    if declared in {"other", "非行测"}:
        return "other"
    if declared not in {None, "", "unknown"}:
        return "unknown"
    name = str(metadata.get("name", ""))
    if re.search(r"申论", name):
        return "shenlun"
    if re.search(r"非行测|不是行测|非行政职业能力测验", name):
        return "other"
    if re.search(r"行测|行政职业能力测验|\bxingce\b", name, re.IGNORECASE):
        return "xingce"
    return "unknown"


def route(report_path: Path, output_dir: Path, override: str = "auto") -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    metadata = report.get("exam") if isinstance(report.get("exam"), dict) else report
    kind = exam_type(metadata, override)
    if kind == "other":
        return {"status": "skipped", "examType": kind, "reason": "非公考估分科目"}
    if kind == "unknown":
        return {"status": "skipped", "examType": kind, "reason": "未明确考试科目"}
    if kind == "shenlun":
        return {"status": "pending", "examType": kind, "reason": "公考申论估分子技能尚未实现"}

    adapter = Path(__file__).resolve().parents[1] / "subskills/gongkao-xingce-score-estimator/scripts/grade_estimate.py"
    result = subprocess.run(
        [sys.executable, str(adapter), "--report", str(report_path), "--output-dir", str(output_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return {
            "status": "failed",
            "examType": kind,
            "reason": "公考行测估分未完成，批改报告已保留",
            "details": result.stderr.strip(),
        }
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "failed", "examType": kind, "reason": "估分子技能返回了无法读取的结果"}
    if not isinstance(value, dict) or value.get("status") not in {"complete", "pending", "skipped"}:
        return {"status": "failed", "examType": kind, "reason": "估分子技能返回格式无效"}
    value.setdefault("examType", kind)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--exam-type", choices=("auto", "xingce", "shenlun", "other", "unknown"), default="auto")
    args = parser.parse_args()
    try:
        value = route(args.report.resolve(), args.output_dir.resolve(), args.exam_type)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        value = {"status": "failed", "reason": "无法读取估分报告", "details": str(error)}
    print(json.dumps(value, ensure_ascii=False))
    return 0 if value.get("status") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
