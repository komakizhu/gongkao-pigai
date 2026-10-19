"""Compatibility adapter for the shared Gongkao Score router."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROUTER_DIR = Path(__file__).resolve().parents[2] / "gongkao-score/scripts"
if str(ROUTER_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTER_DIR))
from score_router import exam_type as shared_exam_type


def exam_type(key, override="auto"):
    return shared_exam_type(key, override)


def estimate_after_grade(report_path, kind):
    if kind in {"other", "unknown"}:
        return {"status": "skipped", "reason": "非公考估分科目" if kind == "other" else "未明确考试科目"}
    script = Path(__file__).resolve().parents[2] / "gongkao-score/scripts/score_router.py"
    result = subprocess.run(
        [sys.executable, str(script), "--report", str(report_path), "--output-dir", str(report_path.parent), "--exam-type", kind],
        capture_output=True, text=True,
    )
    if result.returncode:
        return {"status": "failed", "reason": "公考估分未完成，批改报告已保留", "details": result.stderr.strip()}
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "failed", "reason": "公考估分返回了无法读取的结果，批改报告已保留"}
    if not isinstance(value, dict) or value.get("status") not in {"complete", "pending", "skipped"}:
        return {"status": "failed", "reason": "公考估分返回格式无效，批改报告已保留"}
    return value
