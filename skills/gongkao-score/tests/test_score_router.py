import json
import tempfile
import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from score_router import exam_type, route


class ScoreRouterTests(unittest.TestCase):
    def test_subject_detection_has_explicit_shenlun_and_negative_paths(self):
        self.assertEqual(exam_type({"name": "2026国考行测"}), "xingce")
        self.assertEqual(exam_type({"name": "2026国考申论"}), "shenlun")
        self.assertEqual(exam_type({"name": "非行测练习"}), "other")
        self.assertEqual(exam_type({"name": "2026国考"}), "unknown")

    def test_shenlun_is_pending_without_creating_score_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "report.json"
            report.write_text(json.dumps({"type": "exam-grade-report", "exam": {"name": "申论", "examType": "shenlun"}}), encoding="utf-8")
            result = route(report, root / "output")
            self.assertEqual(result["status"], "pending")
            self.assertIn("尚未实现", result["reason"])
            self.assertFalse((root / "output").exists())

    def test_xingce_uses_the_shared_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "report.json"
            rows = [
                {"questionId": "q1", "number": 1, "section": "政治理论", "result": "correct"},
                {"questionId": "q2", "number": 2, "section": "资料分析", "result": "wrong"},
            ]
            report.write_text(json.dumps({
                "type": "exam-grade-report", "paperId": "paper", "paperVersion": "v1",
                "attemptId": "attempt", "batchId": "batch", "exam": {"name": "行测", "examType": "xingce"},
                "rows": rows,
            }), encoding="utf-8")
            result = route(report, root / "output")
            self.assertEqual(result["status"], "complete")
            self.assertTrue((root / "output/estimate.json").is_file())


if __name__ == "__main__":
    unittest.main()
