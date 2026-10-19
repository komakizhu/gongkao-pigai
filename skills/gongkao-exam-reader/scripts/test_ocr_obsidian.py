import json
import tempfile
import unittest
from pathlib import Path

from ocr_obsidian import export_exam_bundle, normalize_question_body


class ObsidianExportTests(unittest.TestCase):
    def candidate(self):
        image = "![](data:image/png;base64,iVBORw0KGgo=)"
        return {
            "workflow": "exam-lite-v1",
            "review_topology": "text-a-sharded-b-change-c",
            "protocol_revision": 2,
            "schema_version": 2,
            "lane": "exam-lite",
            "round": 1,
            "revision": 3,
            "pages": [
                {"page": 1, "text": "## 一. 选择题\n\n**66.**题干①第一项②第二项A.甲 B.乙 C.丙 D.丁\n"},
                {"page": 2, "text": "跨页续文。\n\n## （一）\n\n共享材料第一段。\n\n**67.**跨页题干\nA.选项一\nB.选项二\nC.选项三\nD.选项四\n\n图表如下：\n" + image + "\n<table><tr><td rowspan=\"2\">表</td><td>值</td></tr></table>\n"},
            ],
        }

    def test_layout_and_media(self):
        result = normalize_question_body("题干①甲②乙A.a B.b C.c D.d")
        self.assertIn("题干\n①甲\n②乙", result)
        self.assertIn("\nA.a\nB.b\nC.c\nD.d", result)
        self.assertEqual(normalize_question_body("题干\n\n\nA.a\nB.b"), "题干\n\nA.a\nB.b")
        self.assertEqual(normalize_question_body("选择A.1 B.2"), "选择A.1 B.2")
        self.assertEqual(normalize_question_body("公式 `$A.1 B.2$`"), "公式 `$A.1 B.2$`")
        self.assertEqual(normalize_question_body("A.①②"), "A.①②")
        protected = "```\n**** A.代码 B.代码\n```\n<table><tr><td>****</td></tr></table>"
        self.assertEqual(normalize_question_body(protected), protected)

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = export_exam_bundle(self.candidate(), first, "sample-exam")
            two = export_exam_bundle(self.candidate(), second, "sample-exam")
            text = one["text"]
            self.assertIn("> [!exam-question] 第 66 题", text)
            self.assertIn("> [!exam-question] 第 67 题", text)
            self.assertNotIn("###", text)
            self.assertIn("^q66", text)
            self.assertIn("^m-material-01", text)
            self.assertIn("[[#^m-material-01|共享材料]]", text)
            self.assertIn("> [!success]- 答案与解析", text)
            self.assertIn("> [!note]- 我的笔记", text)
            self.assertIn("![[attachments/", text)
            self.assertIn("<table>", text)
            self.assertEqual(text, two["text"])
            attachments = list((Path(first) / "attachments").iterdir())
            self.assertEqual(len(attachments), 1)
            mapping = one["source_map"]
            self.assertEqual({entry["pdf_page"] for entry in mapping["entries"]}, {1, 2})
            self.assertTrue(all(entry["mapping_warning"] for entry in mapping["entries"]))
            self.assertEqual(one["index"]["questions"][0]["number"], 66)
            self.assertEqual(one["index"]["questions"][0]["source_pages"], [1, 2])
            self.assertEqual(one["index"]["questions"][1]["source_pages"], [2])

    def test_boundary_uncertainty_is_reported_without_guessing(self):
        candidate = self.candidate()
        candidate["pages"][0]["text"] = "说明**66.**行中题干\n\n**68.**后续题\nA.a\nB.b\nC.c\nD.d"
        with tempfile.TemporaryDirectory() as directory:
            result = export_exam_bundle(candidate, directory, "uncertain")
            kinds = {item["kind"] for item in result["unresolved"]["items"]}
            self.assertIn("missing_question_marker", kinds)
            self.assertIn("embedded_question_marker", kinds)
            self.assertIn("行中题干", result["text"])
            self.assertIn("后续题", result["text"])
            saved = json.loads((Path(directory) / "uncertain.unresolved.json").read_text())
            self.assertEqual(saved["status"], "complete_with_unresolved")

    def test_duplicate_question_numbers_use_section_stable_blocks(self):
        candidate = {
            "workflow": "exam-lite-v1",
            "review_topology": "text-a-sharded-b-change-c",
            "protocol_revision": 2,
            "pages": [{"page": 1, "text": "## 第一部分\n\n1. 甲题\nA.甲\nB.乙\n\n2. 乙题\nA.甲\nB.乙\n\n## 第二部分\n\n1. 丙题\nA.甲\nB.乙\n"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = export_exam_bundle(candidate, directory, "duplicate")
            records = result["index"]["questions"]
            self.assertEqual([record["number"] for record in records], [1, 2, 1])
            self.assertEqual(len({record["block_id"] for record in records}), 3)
            self.assertTrue(records[2]["block_id"].startswith("qs-"))


if __name__ == "__main__":
    unittest.main()
