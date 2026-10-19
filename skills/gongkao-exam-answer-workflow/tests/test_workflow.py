import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "answer_workflow.py"
sys.path.insert(0, str(ROOT / "scripts"))
import answer_workflow


class WorkflowCliTest(unittest.TestCase):
    def run_cli(self, *args: str) -> str:
        result = subprocess.run([sys.executable, str(SCRIPT), *args], check=True, capture_output=True, text=True)
        return result.stdout.strip()

    def test_mixed_types_public_config_and_json_grade(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            source = work / "answers.txt"
            source.write_text("41 single C\n42 multiple A、C\n43 boolean 错\n", encoding="utf-8")
            private = work / "private"
            self.run_cli("prepare", str(source), "--output", str(private), "--paper-id", "paper", "--paper-version", "v1", "--name", "示例",)
            answer_set = json.loads((private / "answer-set.json").read_text(encoding="utf-8"))
            self.assertFalse(answer_set["issues"])
            config_path = work / "config.json"
            self.run_cli("generate-config", str(private / "answer-set.json"), "--output", str(config_path))
            config = config_path.read_text(encoding="utf-8")
            self.assertNotIn("referenceAnswer", config)
            self.assertNotIn('"source"', config)
            attempt = {
                "schemaVersion": 2,
                "type": "answer-recorder-attempt",
                "exportedAt": "2026-10-16T00:00:00Z",
                "exercise": {
                    "id": "local", "paperId": "paper", "paperVersion": "v1", "attemptId": "attempt-1", "name": "示例", "status": "active", "startNumber": 41, "questionCount": 3, "questions": [
                        {"id": "1", "questionId": "paper:q:default:41", "number": 41, "type": "single", "options": ["A", "B", "C", "D"], "answer": "C", "uncertainOptions": ["B"], "review": False},
                        {"id": "2", "questionId": "paper:q:default:42", "number": 42, "type": "multiple", "options": ["A", "B", "C", "D"], "answer": ["A"], "uncertainOptions": ["A", "C"], "review": False},
                        {"id": "3", "questionId": "paper:q:default:43", "number": 43, "type": "boolean", "options": ["对", "错"], "answer": False, "uncertainOptions": ["错"], "review": False},
                    ],
                },
            }
            attempt_path = work / "attempt.json"
            attempt_path.write_text(json.dumps(attempt, ensure_ascii=False), encoding="utf-8")
            report_dir = work / "report"
            self.run_cli("grade", str(private / "answer-set.json"), str(attempt_path), "--output", str(report_dir))
            report = json.loads((report_dir / "grade-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["correct"], 2)
            self.assertEqual(report["counts"]["wrong"], 1)
            self.assertEqual(report["rows"][1]["missingOptions"], ["C"])
            csv_path = work / "attempt.csv"
            csv_path.write_text("\ufeffschema_version,paper_id,paper_version,attempt_id,exercise_id,exercise_name,exercise_status,question_id,section,question_number,question_type,answer,answered,review_flag,uncertain_options\n"
                                "2,paper,v1,attempt-csv,local,示例,active,paper:q:default:41,,41,single,C,true,false,B\n"
                                "2,paper,v1,attempt-csv,local,示例,active,paper:q:default:42,,42,multiple,A,true,false,A|C\n"
                                "2,paper,v1,attempt-csv,local,示例,active,paper:q:default:43,,43,boolean,false,true,false,错\n", encoding="utf-8")
            csv_report_dir = work / "csv-report"
            self.run_cli("grade", str(private / "answer-set.json"), str(csv_path), "--output", str(csv_report_dir))
            csv_report = json.loads((csv_report_dir / "grade-report.json").read_text(encoding="utf-8"))
            self.assertEqual(csv_report["counts"]["correct"], 2)
            no_mark_csv = work / "attempt-no-mark.csv"
            no_mark_csv.write_text("\ufeffschema_version,paper_id,paper_version,attempt_id,exercise_id,exercise_name,exercise_status,question_id,section,question_number,question_type,answer,answered,review_flag\n"
                                   "2,paper,v1,attempt-csv,local,示例,active,paper:q:default:41,,41,single,C,true,false\n"
                                   "2,paper,v1,attempt-csv,local,示例,active,paper:q:default:42,,42,multiple,A,true,false\n"
                                   "2,paper,v1,attempt-csv,local,示例,active,paper:q:default:43,,43,boolean,false,true,false\n", encoding="utf-8")
            no_mark_report_dir = work / "csv-no-mark-report"
            self.run_cli("grade", str(private / "answer-set.json"), str(no_mark_csv), "--output", str(no_mark_report_dir))
            no_mark_report = json.loads((no_mark_report_dir / "grade-report.json").read_text(encoding="utf-8"))
            self.assertEqual(csv_report["counts"], no_mark_report["counts"])
            self.assertEqual(
                [(row["questionId"], row["myAnswer"], row["result"]) for row in csv_report["rows"]],
                [(row["questionId"], row["myAnswer"], row["result"]) for row in no_mark_report["rows"]],
            )

    def test_conflict_blocks_config_and_csv_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            source = work / "answers.txt"
            source.write_text("41 C\n41 D\n", encoding="utf-8")
            private = work / "private"
            self.run_cli("prepare", str(source), "--output", str(private), "--paper-id", "paper", "--paper-version", "v1", "--name", "冲突", "--question-type", "single")
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_cli("generate-config", str(private / "answer-set.json"), "--output", str(work / "config.json"))

    def test_conflicting_answer_set_cannot_be_graded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            source = work / "answers.txt"
            source.write_text("41 C\n41 D\n", encoding="utf-8")
            private = work / "private"
            self.run_cli("prepare", str(source), "--output", str(private), "--paper-id", "paper", "--paper-version", "v1", "--name", "冲突", "--question-type", "single")
            attempt = work / "attempt.json"
            attempt.write_text(json.dumps({
                "schemaVersion": 2,
                "type": "answer-recorder-attempt",
                "exercise": {
                    "paperId": "paper", "paperVersion": "v1", "attemptId": "attempt-1",
                    "questions": [{"questionId": "paper:q:default:41", "number": 41,
                                   "type": "single", "answer": "C"}],
                },
            }, ensure_ascii=False), encoding="utf-8")
            output = work / "report"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "grade", str(private / "answer-set.json"), str(attempt),
                 "--output", str(output)], capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("conflict", result.stderr)
            self.assertFalse(output.exists())

            resolved = json.loads((private / "answer-set.json").read_text(encoding="utf-8"))
            resolved["issues"] = []
            (private / "resolved-answer-set.json").write_text(json.dumps(resolved, ensure_ascii=False), encoding="utf-8")
            output = work / "resolved-report"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "grade", str(private / "resolved-answer-set.json"), str(attempt),
                 "--output", str(output)], capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "grade-report.json").exists())

    def test_csv_allows_cross_attempt_rows_but_rejects_mixed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            source = work / "answers.txt"
            source.write_text("41 C\n42 D\n", encoding="utf-8")
            private = work / "private"
            self.run_cli("prepare", str(source), "--output", str(private), "--paper-id", "paper", "--paper-version", "v1", "--name", "跨次作答", "--question-type", "single")
            header = "\ufeffschema_version,paper_id,paper_version,attempt_id,exercise_id,exercise_name,exercise_status,question_id,section,question_number,question_type,answer,answered,review_flag\n"
            rows = (
                "2,paper,v1,attempt-a,local,示例,active,paper:q:default:41,,41,single,C,true,false\n"
                "2,paper,v1,attempt-b,local,示例,active,paper:q:default:42,,42,single,D,true,false\n"
            )
            csv_path = work / "cross-attempt.csv"
            csv_path.write_text(header + rows, encoding="utf-8")
            report = work / "cross-report"
            self.run_cli("grade", str(private / "answer-set.json"), str(csv_path), "--output", str(report))
            csv_report = json.loads((report / "grade-report.json").read_text())
            self.assertEqual(csv_report["counts"]["correct"], 2)
            self.assertEqual(csv_report["attemptId"], "mixed")

            mixed_path = work / "mixed.csv"
            mixed_path.write_text(header + rows.replace("2,paper,v1,attempt-b", "2,other,v9,attempt-b"), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "grade", str(private / "answer-set.json"), str(mixed_path),
                 "--output", str(work / "mixed-report")], capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CSV 第 3 行", result.stderr)
            self.assertIn("paper_id", result.stderr)

            invalid_schema = work / "invalid-schema.csv"
            invalid_schema.write_text(header + rows.replace("2,paper,v1,attempt-b", "3,paper,v1,attempt-b"), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "grade", str(private / "answer-set.json"), str(invalid_schema),
                 "--output", str(work / "invalid-schema-report")], capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("schema_version", result.stderr)

            wrong_number = work / "wrong-number.csv"
            wrong_number.write_text(header + rows.replace(",42,single,D,", ",99,single,D,"), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "grade", str(private / "answer-set.json"), str(wrong_number),
                 "--output", str(work / "wrong-number-report")], capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("题号或题型", result.stderr)

    def test_pdf_extraction_keeps_blank_pages_and_reports_page_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            pdf = Path(temp) / "answers.pdf"
            pdf.write_bytes(b"placeholder")
            with patch.object(answer_workflow.subprocess, "run", return_value=SimpleNamespace(stdout="第一页\f\f第三页\f")):
                text, pages, warnings = answer_workflow.extract_pdf(pdf)
            self.assertEqual([page["page"] for page in pages], [1, 2, 3])
            self.assertEqual([page["textLength"] for page in pages], [3, 0, 3])
            self.assertIn("第 2 页", warnings[0])
            self.assertIn("## 第 1 页", text)
            self.assertIn("## 第 3 页", text)

            with patch.object(answer_workflow.subprocess, "run", return_value=SimpleNamespace(stdout="第一页\f")):
                _, one_page, one_page_warnings = answer_workflow.extract_pdf(pdf)
            self.assertEqual([page["page"] for page in one_page], [1])
            self.assertEqual(one_page_warnings, [])

            with patch.object(answer_workflow.subprocess, "run", return_value=SimpleNamespace(stdout="\f\f")):
                _, blank_pages, blank_warnings = answer_workflow.extract_pdf(pdf)
            self.assertEqual([page["page"] for page in blank_pages], [1, 2])
            self.assertEqual([page["textLength"] for page in blank_pages], [0, 0])
            self.assertEqual(len(blank_warnings), 2)

            output = work / "extracted"
            with patch.object(answer_workflow.subprocess, "run", return_value=SimpleNamespace(stdout="第一页\f\f第三页\f")):
                answer_workflow.command_extract(SimpleNamespace(input=str(pdf), output=str(output)))
            extraction = json.loads((output / "extraction.json").read_text(encoding="utf-8"))
            self.assertEqual(extraction["sources"][0]["page"], 1)
            self.assertIn("第 2 页", "\n".join(extraction["warnings"]))
            self.assertIn("第 2 页", (output / "extracted.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
