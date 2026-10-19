import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/answer_workflow.py"
sys.path.insert(0, str(ROOT / "scripts"))
from score_routing import estimate_after_grade, exam_type


class ScoreIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.key = {
            "schemaVersion": 2, "type": "answer-key", "paperId": "paper", "paperVersion": "v1",
            "name": "2026国考行测市地级", "examType": "xingce", "questions": [
                {"questionId": f"q{i}", "number": i, "section": module, "type": "single",
                 "options": ["A", "B", "C", "D"], "referenceAnswer": "A", "source": None}
                for i, module in enumerate(["政治理论", "资料分析", "判断推理"], 1)
            ],
        }
        self.attempt = {"schemaVersion": 2, "type": "answer-recorder-attempt", "exercise": {
            "paperId": "paper", "paperVersion": "v1", "attemptId": "attempt-1", "questions": [
                {"questionId": f"q{i}", "number": i, "type": "single", "answer": answer}
                for i, answer in enumerate(["A", "B", None], 1)
            ]}}

    def tearDown(self):
        self.temp.cleanup()

    def grade(self, *extra, output="report", check=True):
        key = self.work / "key.json"
        attempt = self.work / "attempt.json"
        key.write_text(json.dumps(self.key, ensure_ascii=False))
        attempt.write_text(json.dumps(self.attempt, ensure_ascii=False))
        before = key.read_bytes(), attempt.read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), "grade", str(key), str(attempt),
                                 "--output", str(self.work / output), *extra], capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, (key.read_bytes(), attempt.read_bytes()))
        return result

    def report(self):
        return json.loads((self.work / "report/grade-report.json").read_text())

    def test_xingce_automatically_scores_and_retains_grading_denominator(self):
        self.grade()
        report = self.report()
        estimate = json.loads((self.work / "report/estimate.json").read_text())
        self.assertEqual(report["scoreEstimate"]["status"], "complete")
        self.assertEqual(report["counts"]["accuracy"], .5)
        self.assertEqual(estimate["counts"]["accuracy"], 33.33)
        self.assertEqual(estimate["scores"]["equal_weight"], 33.33)
        self.assertEqual(estimate["scores"]["weighted"], 29.17)
        self.assertFalse(estimate["scores"]["weighted_is_official"])
        self.assertEqual(estimate["grading_source"]["attemptId"], "attempt-1")
        self.assertEqual(estimate["grading_source"]["source_question_ids"], ["q1", "q2", "q3"])
        self.assertIn("estimate.md", (self.work / "report/grade-report.md").read_text())

    def test_uncertain_options_do_not_change_grade_or_estimate(self):
        self.grade(output="without-uncertainty")
        baseline_report = json.loads((self.work / "without-uncertainty/grade-report.json").read_text())
        baseline_estimate = json.loads((self.work / "without-uncertainty/estimate.json").read_text())
        for question, options in zip(self.attempt["exercise"]["questions"], (["A"], ["B"], ["A", "D"])):
            question["uncertainOptions"] = options
        self.grade(output="with-uncertainty")
        marked_report = json.loads((self.work / "with-uncertainty/grade-report.json").read_text())
        marked_estimate = json.loads((self.work / "with-uncertainty/estimate.json").read_text())
        self.assertEqual(marked_report["counts"], baseline_report["counts"])
        self.assertEqual(
            [(row["questionId"], row["myAnswer"], row["result"]) for row in marked_report["rows"]],
            [(row["questionId"], row["myAnswer"], row["result"]) for row in baseline_report["rows"]],
        )
        self.assertEqual(marked_estimate["scores"], baseline_estimate["scores"])

    def test_other_and_unknown_never_invoke_subskill(self):
        with patch("score_routing.subprocess.run") as run:
            self.assertEqual(estimate_after_grade(Path("missing"), "other")["status"], "skipped")
            self.assertEqual(estimate_after_grade(Path("missing"), "unknown")["status"], "skipped")
            run.assert_not_called()
        self.key["examType"] = "other"
        self.grade()
        self.assertEqual(self.report()["scoreEstimate"]["status"], "skipped")
        self.assertFalse((self.work / "report/estimate.json").exists())

    def test_name_detection_respects_declared_subject_and_negative_names(self):
        for name in ("2026国考行测", "2025行政职业能力测验", "Xingce practice"):
            self.assertEqual(exam_type({"name": name}), "xingce")
        self.assertEqual(exam_type({"name": "申论"}), "shenlun")
        for name in ("非行测练习", "不是行测", "非行政职业能力测验"):
            self.assertEqual(exam_type({"name": name}), "other")
        self.assertEqual(exam_type({"name": "2026国考"}), "unknown")
        self.assertEqual(exam_type({"name": "行测", "examType": "other"}), "other")

    def test_cli_can_confirm_xingce_or_disable_scoring(self):
        self.key["name"] = "练习"
        self.key.pop("examType")
        self.grade("--exam-type", "xingce")
        self.assertEqual(self.report()["scoreEstimate"]["status"], "complete")
        self.grade("--exam-type", "other", output="other")
        report = json.loads((self.work / "other/grade-report.json").read_text())
        self.assertEqual(report["scoreEstimate"]["status"], "skipped")

    def test_unknown_subject_preserves_grade_without_score(self):
        self.key["examType"] = "unknown"
        self.key["name"] = "单选练习"
        self.grade()
        self.assertEqual(self.report()["scoreEstimate"]["status"], "skipped")
        self.assertFalse((self.work / "report/estimate-input.json").exists())

    def test_shenlun_uses_placeholder_without_score_files(self):
        self.key["examType"] = "shenlun"
        self.key["name"] = "2026国考申论"
        self.grade()
        report = self.report()
        self.assertEqual(report["exam"]["examType"], "shenlun")
        self.assertEqual(report["scoreEstimate"]["status"], "pending")
        self.assertIn("尚未实现", report["scoreEstimate"]["reason"])
        self.assertFalse((self.work / "report/estimate.json").exists())

    def test_missing_module_blocks_score_but_retains_grade(self):
        self.key["questions"][0]["section"] = None
        self.grade()
        self.assertEqual(self.report()["scoreEstimate"]["status"], "pending")
        self.assertEqual(self.report()["scoreEstimate"]["error"]["code"], "missing_module")
        self.assertFalse((self.work / "report/estimate.json").exists())

    def test_unknown_module_does_not_infer_from_number(self):
        self.key["questions"][0]["section"] = "第一部分"
        self.grade()
        self.assertEqual(self.report()["scoreEstimate"]["error"]["code"], "unknown_module")

    def test_explicit_module_overrides_non_module_section(self):
        self.key["questions"][0].update(section="第一部分", module="政治理论")
        self.grade()
        self.assertEqual(self.report()["scoreEstimate"]["status"], "complete")

    def test_missing_reference_is_pending_not_wrong(self):
        self.key["questions"][0]["referenceAnswer"] = None
        self.grade()
        report = self.report()
        self.assertEqual(report["counts"]["reference_missing"], 1)
        self.assertEqual(report["counts"]["wrong"], 1)
        self.assertEqual(report["scoreEstimate"]["status"], "pending")
        self.assertFalse((self.work / "report/estimate.json").exists())

    def test_declared_partial_remains_partial(self):
        self.key.update(total_questions=130, scope="partial")
        self.grade()
        score = json.loads((self.work / "report/estimate.json").read_text())
        self.assertFalse(score["completeness"]["is_full"])
        self.assertIn("局部测验", score["scores"]["interpretation"])
        self.assertIn("局部测验", (self.work / "report/grade-report.md").read_text())

    def test_duplicate_id_or_wrong_version_rejected_before_scoring(self):
        self.attempt["exercise"]["questions"].append(copy.deepcopy(self.attempt["exercise"]["questions"][0]))
        result = self.grade(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.work / "report").exists())
        self.attempt["exercise"]["questions"].pop()
        self.attempt["exercise"]["paperVersion"] = "v2"
        self.assertNotEqual(self.grade(check=False).returncode, 0)

    def test_archives_score_alongside_report(self):
        self.grade("--archive-dir", str(self.work / "archive"))
        archive = self.work / "archive/paper/v1" / self.report()["batchId"]
        for name in ("grade-report.json", "grade-report.md", "estimate-input.json", "estimate.json", "estimate.md"):
            self.assertEqual((archive / name).read_bytes(), (self.work / "report" / name).read_bytes())

    def test_reusing_directory_refused_without_replacing_report(self):
        self.grade()
        before = (self.work / "report/grade-report.json").read_bytes()
        self.assertNotEqual(self.grade(check=False).returncode, 0)
        self.assertEqual(before, (self.work / "report/grade-report.json").read_bytes())

    def test_subskill_failure_has_explicit_status(self):
        with patch("score_routing.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "failure")):
            result = estimate_after_grade(Path("report.json"), "xingce")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["details"], "failure")

    def test_prepare_keeps_subject_private(self):
        source = self.work / "source.txt"
        source.write_text("1 A\n")
        private = self.work / "private"
        result = subprocess.run([sys.executable, str(SCRIPT), "prepare", str(source), "--output", str(private),
                                 "--paper-id", "paper", "--paper-version", "v1", "--name", "行测",
                                 "--question-type", "single", "--section", "政治理论", "--exam-type", "xingce",
                                 "--total-questions", "130", "--scope", "partial"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        key = json.loads((private / "answer-set.json").read_text())
        self.assertEqual(key["examType"], "xingce")
        config = self.work / "public.json"
        subprocess.run([sys.executable, str(SCRIPT), "generate-config", str(private / "answer-set.json"), "--output", str(config)], check=True, capture_output=True)
        public = config.read_text()
        self.assertNotIn("referenceAnswer", public)
        self.assertNotIn("examType", public)


if __name__ == "__main__":
    unittest.main()
