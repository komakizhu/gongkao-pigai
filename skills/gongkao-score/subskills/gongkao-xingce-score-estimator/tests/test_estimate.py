from __future__ import annotations

import csv
import json
import subprocess
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "estimate.py"
WEIGHTS = SKILL_DIR / "references" / "weights.json"
sys.path.insert(0, str(SCRIPT.parent))
import estimate  # noqa: E402


TEST_ROOT = Path("/Volumes/T7_1T/Agent/work/gongkao-xingce-score-estimator-tests")


def options(**overrides):
    values = {
        "exam": None,
        "paper_name": None,
        "category": None,
        "year": None,
        "total_questions": None,
        "scope": "auto",
    }
    values.update(overrides)
    return Namespace(**values)


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def module_records(counts, correct_total=None, all_status=None):
    records = []
    current = 0
    target = correct_total if correct_total is not None else sum(counts.values())
    for module, count in counts.items():
        for _ in range(count):
            if all_status is not None:
                status = all_status
            else:
                status = current < target
            records.append({"id": len(records) + 1, "module": module, "is_correct": status})
            current += 1
    return records


class EstimateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.temp = TemporaryDirectory(dir=str(TEST_ROOT))
        self.work = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def report(self, records, **meta):
        source = self.work / "input.json"
        write_json(source, {"questions": records, **{key: value for key, value in meta.items() if value is not None}})
        return estimate.report_from_file(
            source,
            WEIGHTS,
            cli_options=options(**meta),
            requested_scope=meta.get("scope", "auto"),
        )

    def test_all_correct_and_all_wrong_are_extremes(self):
        counts = {module: 1 for module in estimate.SIX_MODULES}
        all_correct = self.report(module_records(counts, all_status=True))
        all_wrong = self.report(module_records(counts, all_status=False))
        self.assertEqual(all_correct["scores"]["equal_weight"], 100.0)
        self.assertEqual(all_correct["scores"]["weighted"], 100.0)
        self.assertEqual(all_wrong["scores"]["equal_weight"], 0.0)
        self.assertEqual(all_wrong["scores"]["weighted"], 0.0)

    def test_all_unanswered_and_status_counts(self):
        records = [{"id": index, "module": module, "user_answer": ""} for index, module in enumerate(estimate.SIX_MODULES, 1)]
        report = self.report(records)
        self.assertEqual(report["counts"], {"total": 6, "correct": 0, "wrong": 0, "unanswered": 6, "accuracy": 0.0})

    def test_different_question_counts_keep_weighted_full_score_at_100(self):
        profiles = [
            {"政治理论": 10, "常识判断": 10, "言语理解与表达": 20, "数量关系": 10, "判断推理": 30, "资料分析": 20},
            {"政治理论": 15, "常识判断": 15, "言语理解与表达": 25, "数量关系": 10, "判断推理": 35, "资料分析": 20},
            {"政治理论": 20, "常识判断": 15, "言语理解与表达": 30, "数量关系": 10, "判断推理": 35, "资料分析": 20},
            {"政治理论": 20, "常识判断": 15, "言语理解与表达": 30, "数量关系": 15, "判断推理": 35, "资料分析": 20},
        ]
        for counts in profiles:
            report = self.report(module_records(counts, all_status=True), total_questions=sum(counts.values()))
            self.assertEqual(report["scores"]["weighted"], 100.0)
            self.assertLessEqual(abs(sum(item["weighted_contribution"] for item in report["modules"]) - 100.0), 0.02)

    def test_mixed_130_questions_equal_score_and_contributions(self):
        counts = {"政治理论": 20, "常识判断": 15, "言语理解与表达": 30, "数量关系": 10, "判断推理": 35, "资料分析": 20}
        report = self.report(
            module_records(counts, correct_total=90),
            exam="2026国考市地级",
            category="市地级",
            year=2026,
            total_questions=130,
        )
        self.assertEqual(report["scores"]["equal_weight"], 69.23)
        self.assertEqual(report["scores"]["weighted_model_id"], "huatu-six-v1")
        self.assertAlmostEqual(sum(item["equal_contribution"] for item in report["modules"]), 69.23, places=2)
        self.assertAlmostEqual(sum(item["weighted_contribution"] for item in report["modules"]), report["scores"]["weighted"], places=2)

    def test_json_and_csv_are_consistent(self):
        records = [
            {"题号": 1, "所属模块": "政治理论", "用户答案": "A", "标准答案": "A"},
            {"题号": 2, "所属模块": "常识判断", "用户答案": "", "标准答案": "B"},
            {"题号": 3, "所属模块": "资料分析", "是否正确": "正确"},
        ]
        json_path = self.work / "answers.json"
        write_json(json_path, {"questions": records})
        csv_path = self.work / "answers.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["题号", "所属模块", "用户答案", "标准答案", "是否正确"])
            writer.writeheader()
            writer.writerows(records)
        json_report = estimate.report_from_file(json_path, WEIGHTS, cli_options=options(exam="一致性测试"))
        csv_report = estimate.report_from_file(csv_path, WEIGHTS, cli_options=options(exam="一致性测试"))
        self.assertEqual(json_report["counts"], csv_report["counts"])
        self.assertEqual(json_report["scores"], csv_report["scores"])
        self.assertEqual(json_report["modules"], csv_report["modules"])

    def test_field_mapping_and_candidate_array(self):
        source = self.work / "mapped.json"
        mapping_path = self.work / "mapping.json"
        write_json(source, {"payload": [{"qid": "01", "section_name": "data", "mine": "A", "key": "A"}]})
        write_json(mapping_path, {"questions_path": "payload", "fields": {"id": "qid", "module": "section_name", "user_answer": "mine", "correct_answer": "key"}})
        report = estimate.report_from_file(source, WEIGHTS, mapping_path=mapping_path, cli_options=options())
        self.assertEqual(report["counts"]["correct"], 1)
        self.assertEqual(report["modules"][-1]["module"], "资料分析")

    def test_top_level_array_and_ambiguous_arrays(self):
        top_level = self.work / "top-level.json"
        write_json(top_level, [{"id": 1, "module": "政治理论", "is_correct": True}])
        report = estimate.report_from_file(top_level, WEIGHTS, cli_options=options())
        self.assertEqual(report["counts"]["correct"], 1)
        ambiguous = self.work / "ambiguous.json"
        write_json(ambiguous, {"questions": [{"id": 1}], "data": [{"id": 1}]})
        with self.assertRaises(estimate.EstimateError) as error:
            estimate.report_from_file(ambiguous, WEIGHTS, cli_options=options())
        self.assertEqual(error.exception.code, "ambiguous_questions_array")

    def test_missing_unknown_duplicate_and_conflicting_inputs_fail(self):
        with self.assertRaises(estimate.EstimateError) as missing:
            self.report([{"id": 1, "module": "政治理论", "correct_answer": "A"}])
        self.assertEqual(missing.exception.code, "missing_user_answer")
        with self.assertRaises(estimate.EstimateError) as unknown:
            self.report([{"id": 1, "module": "未知模块", "is_correct": True}])
        self.assertEqual(unknown.exception.code, "unknown_module")
        with self.assertRaises(estimate.EstimateError) as duplicate:
            self.report([{"id": 1, "module": "政治理论", "is_correct": True}, {"id": 1, "module": "常识判断", "is_correct": False}])
        self.assertEqual(duplicate.exception.code, "duplicate_question_id")
        with self.assertRaises(estimate.EstimateError) as conflict:
            self.report([{"id": 1, "module": "政治理论", "is_correct": True, "correct": False}])
        self.assertEqual(conflict.exception.code, "conflicting_status")

    def test_partial_scope_and_number_gap_are_explicit(self):
        report = self.report(
            [{"id": 1, "module": "政治理论", "is_correct": True}, {"id": 3, "module": "常识判断", "is_correct": False}],
            total_questions=3,
        )
        self.assertFalse(report["completeness"]["is_full"])
        self.assertEqual(report["completeness"]["scope"], "partial")
        self.assertIn("题号存在缺口", report["completeness"]["basis"])
        self.assertEqual(report["counts"]["total"], 2)

    def test_explicit_status_has_priority_and_warns_on_answer_conflict(self):
        report = self.report([{"id": 1, "module": "政治理论", "user_answer": "A", "correct_answer": "B", "is_correct": True}])
        self.assertEqual(report["counts"]["correct"], 1)
        self.assertTrue(any("批改结果优先" in warning for warning in report["warnings"]))

    def test_custom_weight_file_is_used(self):
        custom = self.work / "weights.json"
        data = json.loads(WEIGHTS.read_text(encoding="utf-8"))
        data["default_model"] = "custom"
        data["models"].append(
            {
                "id": "custom",
                "version": "1",
                "name": "测试权重",
                "official": False,
                "weights": {module: (10 if module == "资料分析" else 1) for module in estimate.SIX_MODULES},
                "source": [],
                "uncertainty": "测试模型",
            }
        )
        write_json(custom, data)
        records = [
            {"id": 1, "module": "政治理论", "is_correct": True},
            {"id": 2, "module": "资料分析", "is_correct": False},
        ]
        source = self.work / "custom-input.json"
        write_json(source, {"questions": records})
        report = estimate.report_from_file(source, custom, requested_model="custom", cli_options=options())
        self.assertEqual(report["scores"]["weighted_model_id"], "custom")
        self.assertEqual(report["scores"]["weighted"], 9.09)

    def test_invalid_weights_and_unknown_model_fail(self):
        invalid = self.work / "invalid-weights.json"
        data = json.loads(WEIGHTS.read_text(encoding="utf-8"))
        data["models"][0]["weights"]["政治理论"] = 0
        write_json(invalid, data)
        source = self.work / "invalid-input.json"
        write_json(source, {"questions": [{"id": 1, "module": "政治理论", "is_correct": True}]})
        with self.assertRaises(estimate.EstimateError) as invalid_error:
            estimate.report_from_file(source, invalid, cli_options=options())
        self.assertEqual(invalid_error.exception.code, "invalid_weight")
        with self.assertRaises(estimate.EstimateError) as unknown_error:
            estimate.report_from_file(source, WEIGHTS, requested_model="missing-model", cli_options=options())
        self.assertEqual(unknown_error.exception.code, "unknown_model")

    def test_cli_both_writes_json_and_markdown(self):
        source = self.work / "cli.json"
        write_json(source, {"questions": [{"id": 1, "module": "政治理论", "is_correct": True}]})
        original = source.read_bytes()
        output_dir = self.work / "output"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(source), "--format", "both", "--output-dir", str(output_dir)],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output_dir / "estimate.json").is_file())
        self.assertTrue((output_dir / "estimate.md").is_file())
        self.assertIn("等权估分", (output_dir / "estimate.md").read_text(encoding="utf-8"))
        self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
