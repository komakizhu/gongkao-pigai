#!/usr/bin/env python3
"""Small behavioral checks; no production PDFs, model downloads or fake reviews."""
from __future__ import annotations

import argparse
import copy
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import ocr_review as ocr


def sample_pdf(path):
    """Generate a real three-page PDF, including a blank page, for extraction tests."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>"]
    texts = ["OCR review sample. Year 2025. Page one.", "", "Final page 3. Keep names and 10.5 units."]
    for i, text in enumerate(texts):
        content_id = 4 + i * 2
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Resources << /Font << /F1 9 0 R >> >> /Contents {content_id} 0 R >>".encode())
        stream = f"BT /F1 13 Tf 25 240 Td ({text}) Tj ET".encode()
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    Path(path).write_bytes(data)


def decision(page, text, old, new):
    pos = text.index(old)
    return {"page": page, "start": pos, "end": pos + len(old), "before": old, "after": new,
            "decision": "replace", "reason": "test image reading",
            "evidence": {"kind": "image", "pdf_page": page, "region": "test region", "reading": new or "confirmed deletion"}}


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.text = "标题\n\n运用梁的方法，2025年。\n\n![](data:image/png;base64,ABCDEF)\n\n日期：XXXX年XX月XX日。"
        self.candidate = {"pages": [{"page": 1, "text": self.text}, {"page": 2, "text": "保持这一页\n"}]}

    def judgment(self, edits):
        return {"status": "complete", "reviewed_pages": [1], "decisions": edits}

    def test_precise_unicode_changes_preserve_images_other_pages_and_unmodified_text(self):
        before = copy.deepcopy(self.candidate)
        edits = [decision(1, self.text, "梁", "柔"), decision(1, self.text, "2025", "2026")]
        result = ocr.apply_decisions(self.candidate, self.judgment(edits))
        self.assertEqual(result["pages"][0]["text"], self.text.replace("梁", "柔").replace("2025", "2026"))
        self.assertEqual(result["pages"][1], self.candidate["pages"][1])
        self.assertEqual(self.candidate, before)

    def test_mismatch_overlaps_and_missing_image_evidence_are_rejected(self):
        edit = decision(1, self.text, "梁", "柔")
        for changes in ([{**edit, "before": "错"}], [edit, edit], [{**edit, "evidence": {"kind": "ocr"}}]):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ocr.apply_decisions(self.candidate, self.judgment(changes))

    def test_image_edits_rejected_even_if_payload_matches(self):
        with self.assertRaises(ValueError):
            ocr.apply_decisions(self.candidate, self.judgment([decision(1, self.text, "ABCDEF", "ABXDEF")]))
        for source, needle in (
            ("![](images/figure(1).png)", ".png"),
            ("![图][fig]\n\n[fig]: images/a.png", "a.png"),
        ):
            start = source.index(needle)
            edit = {"page": 1, "start": start, "end": start + len(needle), "before": needle, "after": "changed.png",
                    "decision": "replace", "reason": "must be rejected", "evidence": {"kind": "image", "pdf_page": 1, "region": "image", "reading": "changed"}}
            with self.subTest(source=source), self.assertRaises(ValueError):
                ocr.apply_decisions({"pages": [{"page": 1, "text": source}]}, self.judgment([edit]))

    def test_code_literal_is_not_treated_as_media(self):
        source = "`![](images/a.png)`"
        edit = decision(1, source, "a.png", "b.png")
        self.assertEqual(ocr.apply_decisions({"pages": [{"page": 1, "text": source}]}, self.judgment([edit]))["pages"][0]["text"], "`![](images/b.png)`")

    def test_candidate_revision_prevents_stale_judgment(self):
        old = {"schema_version": 2, "lane": "wps", "round": 1, "revision": 3,
               "pages": [{"page": 1, "text": "甲乙丙。"}]}
        edit = decision(1, "甲乙丙。", "乙", "戊")
        judgment = self.judgment([edit])
        judgment["candidate_meta"] = {"schema_version": 2, "lane": "wps", "round": 1, "revision": 3}
        self.assertIn("甲戊丙", ocr.apply_decisions(old, judgment)["pages"][0]["text"])
        newer = {**old, "revision": 4, "pages": [{"page": 1, "text": "甲乙丁。"}]}
        with self.assertRaises(ValueError):
            ocr.apply_decisions(newer, judgment)

    def test_clean_layout_export_keeps_notes_and_removes_only_approved_regions(self):
        pages = [{"page": 1, "text": "书名\n正文。\n1 注释\n1"}, {"page": 2, "text": "参考文献"}]
        blocks = {1: [{"type": "header", "text": "书名", "bbox": [0, .01, .5, .05]},
                      {"type": "body", "text": "正文。", "bbox": [0, .2, .9, .5]},
                      {"type": "footnote", "text": "1 注释", "bbox": [0, .8, .9, .9]},
                      {"type": "page_number", "text": "1", "bbox": [.5, .95, .6, .99]}],
                  2: [{"type": "heading", "text": "参考文献"}]}
        layout = ocr.build_layout(pages, source="test", block_records=blocks)
        for region in layout["pages"][0]["regions"]:
            if region["type"] in {"header", "page_number"}:
                region["status"] = "approved_exclude"
        rendered, mapping = ocr.render_clean_markdown(pages, layout)
        self.assertNotIn("pdf-page:", rendered)
        self.assertNotIn("书名", rendered)
        self.assertIn("## 脚注", rendered)
        self.assertLess(rendered.index("脚注"), rendered.index("参考文献"))
        self.assertTrue(any(entry.get("region_id") for entry in mapping["entries"]))

    def test_clean_layout_export_handles_unpositioned_notes(self):
        pages = [{"page": 1, "text": "正文\n图注"}]
        layout = ocr.build_layout(
            pages,
            source="test",
            block_records={1: [
                {"type": "body", "text": "正文", "bbox": [0, .1, .9, .5]},
                {"type": "footnote", "text": "图注", "bbox": [0, .8, .9, .9]},
            ]},
        )
        note = layout["pages"][0]["regions"][1]
        note["start"] = None
        note["end"] = None
        rendered, _ = ocr.render_clean_markdown(pages, layout)
        self.assertIn("图注", rendered)

    def test_mineru_pixel_bbox_is_normalized_without_losing_page_provenance(self):
        pages = [{"page": 1, "text": "正文"}]
        middle = {"pages": [{"page_idx": 0, "width": 1000, "height": 2000,
                              "blocks": [{"type": "text", "bbox": [100, 200, 500, 800], "content": "正文"}]}]}
        layout = ocr.build_mineru_layout(pages, middle)
        self.assertEqual(layout["pages"][0]["regions"][0]["bbox"], [0.1, 0.1, 0.5, 0.4])

    def test_unresolved_is_unchanged_and_punctuation_edits_are_not_normalized_away(self):
        hold = {"page": 1, "decision": "unresolved", "reason": "unreadable"}
        self.assertEqual(ocr.apply_decisions(self.candidate, self.judgment([hold])), self.candidate)
        d = decision(1, self.text, "，", "；")
        self.assertIn("柔", ocr.apply_decisions(self.candidate, self.judgment([decision(1, self.text, "梁", "柔")]))["pages"][0]["text"])
        self.assertEqual(ocr.apply_decisions(self.candidate, self.judgment([d]))["pages"][0]["text"], self.text.replace("，", "；"))

    def test_insertions_and_deletions_use_original_offsets(self):
        edits = [decision(1, self.text, "2025", ""), {"page": 1, "start": 0, "end": 0, "before": "", "after": "前言\n", "decision": "replace", "reason": "image shows preface", "evidence": {"kind": "image", "pdf_page": 1, "region": "top", "reading": "前言"}}]
        self.assertEqual(ocr.apply_decisions(self.candidate, self.judgment(edits))["pages"][0]["text"], "前言\n" + self.text.replace("2025", ""))

    def test_incomplete_or_duplicate_coverage_cannot_be_applied(self):
        for judgment in ({"status": "incomplete", "reviewed_pages": [1], "decisions": []},
                         {"status": "complete", "reviewed_pages": [1, 1], "decisions": []}):
            with self.assertRaises(ValueError):
                ocr.apply_decisions(self.candidate, judgment)


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-review-test-")
        self.root = Path(self.temp.name)
        self.pdf = self.root / "source.pdf"
        sample_pdf(self.pdf)
        self.pages = [{"page": 1, "text": "name\n![](data:image/png;base64,LONGPAYLOAD)"},
                      {"page": 2, "text": ""}, {"page": 3, "text": "last"}]
        ocr.dump(self.root / "manifest.json", {"source": ocr.source_info(self.pdf), "page_count": 3, "status": "ready_for_review"})
        for lane in ("wps", "mineru"):
            ocr.dump(self.root / f"{lane}.json", {"pages": self.pages})

    def tearDown(self):
        self.temp.cleanup()

    def args(self, role="S1", round_no=1):
        return argparse.Namespace(run=str(self.root), lane="wps", round=round_no, first=1, last=2,
                                  role=role, attempt=1, candidate=None, alternative=[])

    def create_packet(self, args):
        with redirect_stdout(io.StringIO()):
            ocr.packet(args)
        return ocr.unit_root(args) / args.role / "attempt1"

    def test_separate_inputs_no_prior_reports_and_no_base64_in_transport(self):
        one = self.create_packet(self.args("S1"))
        ocr.dump(one / "report.json", {"secret_prior_verdict": "do not propagate"})
        two = self.create_packet(self.args("S2"))
        self.assertNotEqual(one, two)
        self.assertEqual(ocr.read_json(one / "candidate.json"), ocr.read_json(two / "candidate.json"))
        for name in ("input.json", "preview.md", "task.md"):
            text = (two / name).read_text()
            self.assertNotIn("secret_prior_verdict", text)
            self.assertNotIn("LONGPAYLOAD", text)
        self.assertIn("LONGPAYLOAD", (two / "candidate.json").read_text())

    def test_round2_requires_candidate_and_strips_judgment_metadata(self):
        args = self.args(round_no=2)
        with self.assertRaises(ValueError):
            self.create_packet(args)
        # A round-2 packet is only legal after a complete round-1 unit.
        first_args = self.args(round_no=1)
        for role in ocr.ROLES:
            folder = self.create_packet(self.args(role, round_no=1))
            ocr.dump(folder / "report.json", {"role": role, "lane": "wps", "round": 1, "status": "complete",
                     "reviewed_pages": [1, 2], "image_checked_pages": [1, 2], "findings": [], "limitations": []})
        with redirect_stdout(io.StringIO()):
            ocr.judge_packet(first_args)
        ocr.dump(ocr.unit_root(first_args) / "J/attempt1/decisions.json", {
            "status": "complete", "lane": "wps", "round": 1,
            "reviewed_pages": [1, 2], "decisions": [], "limitations": [],
            "candidate_meta": {"schema_version": 2, "lane": "wps", "round": 1, "revision": 0},
        })
        jdir = ocr.unit_root(first_args) / "J/attempt1"
        applied_candidate = self.root / "applied-round1.json"
        applied_markdown = self.root / "applied-round1.md"
        ocr.dump(applied_candidate, {"schema_version": 2, "lane": "wps", "round": 1, "revision": 0, "pages": self.pages[:2]})
        applied_markdown.write_text(ocr.markdown(self.pages[:2]), encoding="utf-8")
        ocr.dump(jdir / "application.json", {"status": "applied", "input_meta": {"schema_version": 2, "lane": "wps", "round": 1, "revision": 0},
                 "output_candidate": str(applied_candidate), "output_markdown": str(applied_markdown)})
        source = self.root / "previous-candidate.json"
        ocr.dump(source, {"pages": self.pages, "decisions": "SECRET REASON", "votes": [6]})
        args.candidate = str(source)
        folder = self.create_packet(args)
        self.assertNotIn("SECRET REASON", (folder / "candidate.json").read_text())

    def test_judge_needs_all_six_and_matching_inputs(self):
        args = self.args()
        with self.assertRaises(ValueError):
            ocr.judge_packet(args)
        for role in ocr.ROLES:
            folder = self.create_packet(self.args(role))
            ocr.dump(folder / "report.json", {"role": role, "lane": "wps", "round": 1, "status": "complete",
                     "reviewed_pages": [1, 2], "image_checked_pages": [1, 2], "findings": [], "limitations": []})
        with redirect_stdout(io.StringIO()):
            ocr.judge_packet(args)
        reports = ocr.read_json(ocr.unit_root(args) / "J/attempt1/reports.json")
        self.assertEqual(set(reports), set(ocr.ROLES))
        folder = ocr.unit_root(args) / "S6/attempt1"
        c = ocr.read_json(folder / "candidate.json")
        c["pages"][0]["text"] = "different input"
        ocr.dump(folder / "candidate.json", c)
        args.attempt = 2
        with self.assertRaises(ValueError):
            ocr.judge_packet(args)

    def test_full_page_coverage_detects_missing_last_page(self):
        with self.assertRaises(ValueError):
            ocr.require_coverage(self.pages[:-1], range(1, 4))

    def test_merge_cannot_choose_text_only_candidate_and_lose_assets(self):
        text_only = self.root / "wps-reviewed.json"
        ocr.dump(text_only, {"pages": [{**p, "text": ocr.MEDIA.sub("", p["text"])} for p in self.pages]})
        args = self.args()
        args.lane = "merge"
        args.candidate = str(text_only)
        args.alternative = [str(self.root / "mineru.json")]
        with self.assertRaises(ValueError):
            self.create_packet(args)
        args.candidate, args.alternative = str(self.root / "mineru.json"), [str(text_only)]
        self.assertTrue((self.create_packet(args) / "task.md").exists())

    @unittest.skipUnless(shutil.which("pdftotext") and shutil.which("pdfinfo"), "Poppler unavailable")
    def test_real_pdf_extraction_preserves_blank_and_last_page(self):
        pages = ocr.extract_wps(self.pdf)
        self.assertEqual(len(pages), 3)
        self.assertIn("Page one", pages[0]["text"])
        self.assertFalse(pages[1]["text"].strip())
        self.assertIn("Final page 3", pages[2]["text"])

    def test_verify_detects_lost_content_and_modified_source(self):
        candidate = self.root / "final.json"
        md = self.root / "final.md"
        ocr.dump(candidate, {"pages": self.pages})
        md.write_text(ocr.markdown(self.pages))
        args = argparse.Namespace(run=str(self.root), candidate=str(candidate), markdown=str(md), level="structural")
        with redirect_stdout(io.StringIO()):
            ocr.verify(args)
        md.write_text("missing unchanged lines and images")
        with self.assertRaises(ValueError):
            ocr.verify(args)

        args.level = "complete"
        with self.assertRaises(ValueError):
            ocr.verify(args)
        md.write_text(ocr.markdown(self.pages))
        self.pdf.write_bytes(self.pdf.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            ocr.verify(args)

    def test_resume_uses_valid_checkpoints_without_recognition(self):
        manifest = ocr.read_json(self.root / "manifest.json")
        manifest.update({"chunk_pages": 2, "tier": "standard", "chunks": ["1-2", "3-3"],
                         "input_gaps": [2], "input_resolutions": {"2": {"classification": "blank", "source": "visual_review"}}})
        ocr.dump(self.root / "manifest.json", manifest)
        for first, last in ((1, 2), (3, 3)):
            chunk = self.root / "ocr-chunks" / f"p{first:04d}-{last:04d}" / "pages.json"
            ocr.dump(chunk, {"mode": "ocr", "requested_pages": list(range(first, last + 1)),
                             "pages": [p for p in self.pages if first <= p["page"] <= last]})
        args = argparse.Namespace(pdf=str(self.pdf), run=str(self.root), mineru_python=None,
                                  mineru_home=None, chunk_pages=2, tier="standard", resume=True)
        with patch.object(ocr, "find_mineru_python", return_value=("/synthetic/python", {})), \
             patch.object(ocr, "find_mineru_home", return_value=None), \
             patch.object(ocr, "page_count", return_value=3), \
             patch.object(ocr, "run_command", side_effect=AssertionError("must not re-run OCR")), \
             redirect_stdout(io.StringIO()):
            ocr.prepare(args)
        self.assertEqual(ocr.pages_of(ocr.read_json(self.root / "mineru.json")), self.pages)
        self.assertEqual(ocr.read_json(self.root / "manifest.json")["input_gaps"], [])

    def test_corrupt_checkpoint_is_quarantined_for_local_retry(self):
        checkpoint = self.root / "bad-pages.json"
        checkpoint.write_text("{broken", encoding="utf-8")
        self.assertIsNone(ocr.load_checkpoint(checkpoint, 1, 2))
        self.assertFalse(checkpoint.exists())
        self.assertTrue((self.root / "bad-pages.json.corrupt.1").exists())

    def test_repeating_same_packet_is_idempotent(self):
        args = self.args("S1")
        first = self.create_packet(args)
        second = self.create_packet(args)
        self.assertEqual(first, second)

    def test_s3_image_then_candidate_keeps_the_first_phase_independent(self):
        args = self.args("S3")
        args.s3_phase = "image"
        self.create_packet(args)
        image_dir = ocr.unit_root(args) / "S3" / "attempt1" / "image"
        image_input = ocr.read_json(image_dir / "input.json")
        self.assertNotIn("candidate_meta", image_input)
        self.assertNotIn("name", (image_dir / "preview.md").read_text())
        ocr.dump(image_dir / "transcription.json", {"pages": [{"page": 1, "text": "图像转录"}, {"page": 2, "text": ""}]})
        args.s3_phase = "candidate"
        self.create_packet(args)
        candidate_dir = ocr.unit_root(args) / "S3" / "attempt1" / "candidate"
        candidate_input = ocr.read_json(candidate_dir / "input.json")
        self.assertEqual(candidate_input["transcription"]["pages"][0]["text"], "图像转录")
        self.assertTrue((candidate_dir / "candidate.json").exists())
        self.create_packet(args)

    def test_r3_acceptance_records_a_revert_without_overwriting_output(self):
        args = self.args("S1", round_no=3)
        unit = ocr.unit_root(args)
        candidate = {"schema_version": 2, "lane": "wps", "round": 2, "revision": 1, "pages": self.pages}
        before_path = self.root / "round2.json"
        after_path = self.root / "round3.json"
        after_md = self.root / "round3.md"
        ocr.dump(before_path, candidate)
        ocr.dump(after_path, candidate)
        after_md.write_text(ocr.markdown(self.pages), encoding="utf-8")
        report = {"role": "S1", "lane": "wps", "round": 3, "status": "complete",
                  "reviewed_pages": [1, 2], "image_checked_pages": [1, 2], "findings": [], "limitations": []}
        for role in ocr.ROLES:
            role_dir = unit / role / "attempt1"
            role_dir.mkdir(parents=True, exist_ok=True)
            ocr.dump(role_dir / "report.json", {**report, "role": role})
        jdir = unit / "J" / "attempt1"
        jdir.mkdir(parents=True, exist_ok=True)
        ocr.dump(jdir / "candidate.json", candidate)
        ocr.dump(jdir / "decisions.json", {
            "status": "complete", "lane": "wps", "round": 3,
            "reviewed_pages": [1, 2], "decisions": [], "limitations": [],
            "candidate_meta": {k: candidate[k] for k in ("schema_version", "lane", "round", "revision")},
        })
        ocr.dump(jdir / "application.json", {"status": "applied", "input_meta": {k: candidate[k] for k in ("schema_version", "lane", "round", "revision")},
                 "candidate_input": str(before_path),
                 "output_candidate": str(after_path), "output_markdown": str(after_md)})
        with redirect_stdout(io.StringIO()):
            ocr.acceptance_packet(args)
        acceptance_dir = unit / "J" / "acceptance" / "attempt1"
        acceptance = {
            "status": "complete", "lane": "wps", "round": 3,
            "reviewed_pages": [1, 2], "image_checked_pages": [1, 2],
            "candidate_meta": {k: candidate[k] for k in ("schema_version", "lane", "round", "revision")},
            "accepted": False, "decisions": [{"page": 1, "decision": "revert", "reason": "test", "evidence": {"kind": "image"}}],
            "limitations": [],
        }
        ocr.dump(acceptance_dir / "acceptance.json", acceptance)
        apply_args = argparse.Namespace(run=str(self.root), lane="wps", first=1, last=2,
                                        candidate=str(after_path), acceptance=str(acceptance_dir / "acceptance.json"))
        with redirect_stdout(io.StringIO()):
            ocr.apply_acceptance(apply_args)
        self.assertTrue((self.root / "round3.reverted.json").exists())
        self.assertTrue((acceptance_dir / "result.json").exists())


class SinglePassTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-single-pass-test-")
        self.root = Path(self.temp.name)
        self.pdf = self.root / "source.pdf"
        sample_pdf(self.pdf)
        self.pages = [{"page": 1, "text": "第一段\n"},
                      {"page": 2, "text": "第二段\n"},
                      {"page": 3, "text": "第三段\n"}]
        ocr.dump(self.root / "manifest.json", {
            "schema_version": 2, "source": ocr.source_info(self.pdf), "page_count": 3,
            "status": "ready_for_review", "input_gaps": [], "chunk_pages": 8,
            "workflow": {"id": ocr.SINGLE_WORKFLOW, "state": "ready_for_review", "lanes": ["joint"], "rounds": [1]},
        })
        ocr.dump(self.root / "wps.json", {"schema_version": 2, "lane": "wps", "revision": 0, "pages": self.pages})
        ocr.dump(self.root / "mineru.json", {"schema_version": 2, "lane": "mineru", "revision": 0, "pages": self.pages})

    def tearDown(self):
        self.temp.cleanup()

    def packet_args(self, role, phase=None):
        return argparse.Namespace(run=str(self.root), role=role, first=1, last=3,
                                  attempt=1, s3_phase=phase, dpi=72)

    def create_packets(self):
        for role in ("S1", "S2", "S4", "S5", "S6"):
            with redirect_stdout(io.StringIO()):
                ocr.single_pass_packet(self.packet_args(role))
        with redirect_stdout(io.StringIO()):
            ocr.single_pass_packet(self.packet_args("S3", "image"))
        image_dir = ocr.single_unit_root(self.root, 1, 3) / "S3" / "attempt1" / "image"
        ocr.dump(image_dir / "transcription.json", {"pages": self.pages})
        with redirect_stdout(io.StringIO()):
            ocr.single_pass_packet(self.packet_args("S3", "candidate"))

    def write_reports(self):
        started = "2026-10-16T10:00:00+00:00"
        finished = "2026-10-16T10:00:05+00:00"
        unit = ocr.single_unit_root(self.root, 1, 3)
        for role in ocr.ROLES:
            folder = unit / role / "attempt1" / ("candidate" if role == "S3" else "")
            ocr.dump(folder / "report.json", {
                "workflow": ocr.SINGLE_WORKFLOW, "role": role, "status": "complete",
                "reviewed_pages": [1, 2, 3], "image_checked_pages": [1, 2, 3],
                "started_at": started, "finished_at": finished,
                "findings": [], "limitations": [],
            })

    def test_single_pass_end_to_end_without_rounds(self):
        self.create_packets()
        self.write_reports()
        with redirect_stdout(io.StringIO()):
            ocr.single_pass_judge(argparse.Namespace(run=str(self.root), first=1, last=3, attempt=1))
        unit = ocr.single_unit_root(self.root, 1, 3)
        jdir = unit / "J" / "attempt1"
        ocr.dump(jdir / "decisions.json", {
            "workflow": ocr.SINGLE_WORKFLOW, "status": "complete", "lane": "joint", "round": 1,
            "reviewed_pages": [1, 2, 3], "decisions": [], "region_decisions": [], "limitations": [],
            "candidate_meta": {"schema_version": 2, "lane": "joint", "round": 1, "revision": 0},
        })
        with redirect_stdout(io.StringIO()):
            ocr.single_pass_apply(argparse.Namespace(run=str(self.root), first=1, last=3))
            ocr.single_pass_accept_packet(argparse.Namespace(run=str(self.root), first=1, last=3, attempt=1, dpi=72))
        candidate = self.root / "single-pass-final.json"
        output = self.root / "final.md"
        mapping = self.root / "map.json"
        with redirect_stdout(io.StringIO()):
            ocr.export_clean(argparse.Namespace(run=str(self.root), candidate=str(candidate), output=str(output),
                                                mapping=str(mapping), layout=None, allow_draft=False))
            ocr.verify(argparse.Namespace(run=str(self.root), candidate=str(candidate), markdown=str(output), level="complete"))
        inventory = ocr.workflow_inventory(self.root)
        self.assertTrue(inventory["complete"])
        self.assertTrue((unit / "J" / "acceptance" / "automatic" / "result.json").exists())

    def test_single_pass_requires_wps_text_layer(self):
        manifest = ocr.read_json(self.root / "manifest.json")
        manifest["input_gaps"] = [2]
        ocr.dump(self.root / "manifest.json", manifest)
        with self.assertRaises(ValueError):
            ocr.single_pass_packet(self.packet_args("S1"))

    def test_single_pass_estimate_detects_parallel_reports(self):
        self.create_packets()
        self.write_reports()
        output = io.StringIO()
        with redirect_stdout(output):
            ocr.estimate_run(argparse.Namespace(run=str(self.root)))
        result = json.loads(output.getvalue())
        self.assertTrue(result["six_roles_overlapped"])
        self.assertEqual(result["max_parallel_roles"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
