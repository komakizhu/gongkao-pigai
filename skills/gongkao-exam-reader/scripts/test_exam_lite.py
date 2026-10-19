#!/usr/bin/env python3
"""Behavioral tests for the exam-lite-v1 public workflow seams."""
from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import ocr_review as ocr
from test_ocr_review import sample_pdf


class ExamLiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-exam-lite-test-")
        self.root = Path(self.temp.name)
        self.pdf = self.root / "source.pdf"
        sample_pdf(self.pdf)
        self.pages = [
            {"page": 1, "text": "第一题：下列说法中错误的是？\nA. 保留选项\nB. 原图文字\n![](images/question-1.png)\n"},
            {"page": 2, "text": "第二题：表格题\n| 选项 | 数值 |\n| --- | ---: |\n| A | 10 |\n"},
            {"page": 3, "text": "第三题：结尾。\n"},
        ]
        manifest = {
            "schema_version": ocr.LAYOUT_SCHEMA_VERSION,
            "source": ocr.source_info(self.pdf),
            "page_count": 3,
            "chunk_pages": 8,
            "tier": "standard",
            "status": "ready_for_review",
            "input_gaps": [],
            "workflow": {
                "id": ocr.EXAM_LITE_WORKFLOW,
                "state": "ready_for_review",
                "lanes": ["joint"],
                "rounds": [1],
                "roles": ["A", "B"],
            },
        }
        ocr.dump(self.root / "manifest.json", manifest)
        for lane, pages in (("wps", self.pages), ("mineru", self.pages)):
            ocr.dump(self.root / f"{lane}.json", {
                "schema_version": ocr.LAYOUT_SCHEMA_VERSION,
                "lane": lane,
                "round": 1,
                "revision": 0,
                "pages": pages,
            })
            ocr.dump(self.root / f"{lane}-layout.json", ocr.build_layout(pages, source=lane))

    def tearDown(self):
        self.temp.cleanup()

    def packet_args(self, role, attempt=1):
        return argparse.Namespace(run=str(self.root), role=role, attempt=attempt, dpi=150)

    def create_packets(self):
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_packet(self.packet_args("A"))
            ocr.exam_lite_packet(self.packet_args("B"))

    def packet_dir(self, role, attempt=1):
        return self.root / "packets" / ocr.EXAM_LITE_WORKFLOW / role / f"attempt{attempt}"

    def report(self, role, *, context_id=None, started="2026-10-16T10:00:00+00:00",
               finished="2026-10-16T10:00:05+00:00", findings=None, status="complete"):
        directory = self.packet_dir(role)
        input_path = directory / "input.json"
        context_id = context_id or f"fresh-{role.lower()}"
        return {
            "workflow": ocr.EXAM_LITE_WORKFLOW,
            "role": role,
            "status": status,
            "reviewed_pages": [1, 2, 3],
            "image_checked_pages": [1, 2, 3],
            "started_at": started,
            "finished_at": finished,
            "agent_context_id": context_id,
            "independent_context": True,
            "input_digest": ocr.exam_lite_digest(input_path),
            "findings": findings or [],
            "region_decisions": [],
            "limitations": [],
        }

    def write_reports(self, a=None, b=None):
        for role, report in (("A", a or self.report("A")), ("B", b or self.report("B"))):
            ocr.dump(self.packet_dir(role) / "report.json", report)

    def merge_args(self, attempt=1):
        return argparse.Namespace(run=str(self.root), attempt=attempt)

    def test_input_report_distinguishes_blank_image_only_and_missing(self):
        manifest = ocr.read_json(self.root / "manifest.json")
        manifest["input_gaps"] = [1, 2, 3]
        ocr.dump(self.root / "manifest.json", manifest)
        ocr.dump(self.root / "wps-input-report.json", {
            "pages": [
                {"page": 1, "text_layer": "empty_or_missing", "characters": 0, "needs_visual_check": True},
                {"page": 2, "text_layer": "empty_or_missing", "characters": 0, "needs_visual_check": True},
                {"page": 3, "text_layer": "empty_or_missing", "characters": 0, "needs_visual_check": True},
            ],
            "complete": False,
        })
        args = argparse.Namespace(run=str(self.root), page=["1=blank", "2=image_only", "3=text_layer_missing"])
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_resolve_input(args)
        manifest = ocr.read_json(self.root / "manifest.json")
        self.assertEqual(manifest["input_gaps"], [3])
        report = ocr.read_json(self.root / "wps-input-report.json")
        self.assertEqual([row["resolution"]["classification"] for row in report["pages"]],
                         ["blank", "image_only", "text_layer_missing"])

    def test_exam_packets_are_full_document_and_do_not_create_old_rounds(self):
        self.create_packets()
        for role in ("A", "B"):
            packet = ocr.read_json(self.packet_dir(role) / "input.json")
            self.assertEqual(packet["workflow"], ocr.EXAM_LITE_WORKFLOW)
            self.assertEqual(packet["target_pages"], [1, 2, 3])
            self.assertNotIn("reports", packet)
        self.assertIn("表格、图表", (self.packet_dir("B") / "task.md").read_text(encoding="utf-8"))
        self.assertFalse((self.root / "packets" / "single-pass").exists())
        self.assertFalse((self.root / "packets" / "wps").exists())
        self.assertEqual(ocr.exam_lite_roles(), ("A", "B"))

    def test_exam_lite_refuses_unresolved_text_layer_gap(self):
        manifest = ocr.read_json(self.root / "manifest.json")
        manifest["input_gaps"] = [2]
        ocr.dump(self.root / "manifest.json", manifest)
        with self.assertRaises(ValueError):
            ocr.exam_lite_packet(self.packet_args("A"))

    def test_auto_checkpoint_mode_is_distinct_from_forced_ocr(self):
        checkpoint = self.root / "auto-pages.json"
        ocr.dump(checkpoint, {"mode": "auto", "requested_pages": [1, 2, 3], "pages": self.pages})
        self.assertEqual(ocr.load_checkpoint(checkpoint, 1, 3, mode="auto"), self.pages)
        ocr.dump(checkpoint, {"mode": "auto", "requested_pages": [1, 2, 3], "pages": self.pages})
        self.assertIsNone(ocr.load_checkpoint(checkpoint, 1, 3, mode="ocr"))
        self.assertTrue((self.root / "auto-pages.json.corrupt.1").exists())

    def test_exam_prepare_records_auto_mode_and_resident_command(self):
        prep_root = self.root / "prepared"
        seen = {}

        def fake_run(command, **kwargs):
            seen["command"] = command
            self.assertIn("--mode", command)
            self.assertEqual(command[command.index("--mode") + 1], "auto")
            chunk = prep_root / "ocr-chunks" / "p0001-0003"
            ocr.dump(chunk / "pages.json", {"mode": "auto", "requested_pages": [1, 2, 3], "pages": self.pages})

        args = argparse.Namespace(pdf=str(self.pdf), run=str(prep_root), mineru_python=None,
                                  mineru_home=None, chunk_pages=3, tier="standard", resume=False,
                                  workflow=ocr.EXAM_LITE_WORKFLOW, mineru_mode="auto")
        with patch.object(ocr, "find_mineru_python", return_value=("/synthetic/python", {"supported": True})), \
             patch.object(ocr, "find_mineru_home", return_value=None), \
             patch.object(ocr, "page_count", return_value=3), \
             patch.object(ocr, "extract_wps", return_value=self.pages), \
             patch.object(ocr, "extract_wps_bbox", return_value="<html></html>"), \
             patch.object(ocr, "run_command", side_effect=fake_run), \
             redirect_stdout(io.StringIO()):
            ocr.prepare(args)
        manifest = ocr.read_json(prep_root / "manifest.json")
        self.assertEqual(manifest["workflow"]["id"], ocr.EXAM_LITE_WORKFLOW)
        self.assertEqual(manifest["mineru_mode"], "auto")
        self.assertEqual(manifest["status"], "ready_for_review")
        self.assertTrue(seen["command"])
        input_report = ocr.read_json(prep_root / "wps-input-report.json")
        self.assertEqual(input_report["source_pdf"], str(self.pdf.resolve()))
        self.assertEqual(input_report["missing_text_layer_pages"], [])

    def test_two_reports_are_required_independent_and_overlapping(self):
        self.create_packets()
        ocr.dump(self.packet_dir("A") / "report.json", self.report("A"))
        with self.assertRaises(ValueError):
            ocr.exam_lite_merge(self.merge_args())
        same_context = self.report("B", context_id="fresh-a")
        ocr.dump(self.packet_dir("B") / "report.json", same_context)
        with self.assertRaises(ValueError):
            ocr.exam_lite_merge(self.merge_args())
        good_b = self.report("B", context_id="fresh-b", started="2026-10-16T10:00:01+00:00",
                             finished="2026-10-16T10:00:04+00:00")
        ocr.dump(self.packet_dir("B") / "report.json", good_b)
        output = io.StringIO()
        with redirect_stdout(output):
            ocr.exam_lite_merge(self.merge_args())
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["parallel"]["overlapped"])
        self.assertEqual(result["parallel"]["unique_contexts"], 2)

    def test_old_report_cannot_fill_exam_lite_report_slot(self):
        self.create_packets()
        ocr.dump(self.packet_dir("A") / "report.json", self.report("A"))
        old = self.root / "packets" / "single-pass" / "p0001-0003" / "S1" / "attempt1"
        ocr.dump(old / "report.json", {"workflow": ocr.SINGLE_WORKFLOW, "status": "complete"})
        with self.assertRaises(ValueError):
            ocr.exam_lite_merge(self.merge_args())

    def test_conflicting_patch_is_blocked_and_not_applied(self):
        self.create_packets()
        text = self.pages[0]["text"]
        start = text.index("错误")
        base = {"page": 1, "start": start, "end": start + 2, "before": "错误",
                "verdict": "replace", "reason": "原图确认", "evidence": {
                    "kind": "image", "pdf_page": 1, "region": "题干", "reading": "错误"}}
        a = self.report("A", findings=[{**base, "suggested": "正确"}])
        b = self.report("B", findings=[{**base, "suggested": "错项"}], context_id="fresh-b")
        self.write_reports(a, b)
        output = io.StringIO()
        with redirect_stdout(output):
            ocr.exam_lite_merge(self.merge_args())
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "needs_local_upgrade")
        self.assertTrue(result["conflicts"])
        with self.assertRaises(ValueError):
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
        local_path = self.root / "local-upgrade.json"
        ocr.dump(local_path, {
            "workflow": ocr.EXAM_LITE_WORKFLOW, "status": "complete", "reviewed_pages": [1],
            "candidate_meta": {"schema_version": 2, "lane": "exam-lite", "round": 1, "revision": 0},
            "decisions": [{**base, "suggested": "正确", "after": "正确", "decision": "replace"}],
            "region_decisions": [], "limitations": ["只复核冲突页"],
        })
        stale_path = self.root / "stale-local-upgrade.json"
        stale = ocr.read_json(local_path)
        stale["candidate_meta"]["revision"] = 99
        ocr.dump(stale_path, stale)
        with self.assertRaises(ValueError):
            ocr.exam_lite_local_upgrade(argparse.Namespace(run=str(self.root), decisions=str(stale_path), attempt=2))
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_local_upgrade(argparse.Namespace(run=str(self.root), decisions=str(local_path), attempt=2))
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
        self.assertIn("正确", ocr.read_json(self.root / "exam-lite-final.json")["pages"][0]["text"])

    def test_media_table_mapping_and_no_change_acceptance_complete(self):
        self.create_packets()
        self.write_reports()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=150))
        automatic = ocr.read_json(self.root / "packets" / ocr.EXAM_LITE_WORKFLOW / "acceptance" / "automatic" / "result.json")
        self.assertEqual(automatic["structural_checks"], {
            "page_coverage": "passed", "source_metadata": "passed",
            "media_protection": "passed", "unchanged_candidate": "passed",
        })
        candidate = self.root / "exam-lite-final.json"
        output = self.root / "final.md"
        mapping = self.root / "source-map.json"
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_export(argparse.Namespace(run=str(self.root), candidate=str(candidate),
                                                    output=str(output), mapping=str(mapping), layout=None,
                                                    allow_draft=False))
            ocr.exam_lite_verify(argparse.Namespace(run=str(self.root), candidate=str(candidate),
                                                    markdown=str(output), level="complete"))
        estimate_output = io.StringIO()
        with redirect_stdout(estimate_output):
            ocr.exam_lite_estimate(argparse.Namespace(run=str(self.root)))
        estimate = json.loads(estimate_output.getvalue())
        self.assertIn("stage_durations_seconds", estimate)
        self.assertIsNotNone(estimate["stage_durations_seconds"]["merge"])
        self.assertIsNotNone(estimate["stage_durations_seconds"]["acceptance"])
        rendered = output.read_text(encoding="utf-8")
        self.assertIn("images/question-1.png", rendered)
        self.assertIn("| 选项 | 数值 |", rendered)
        self.assertTrue(ocr.read_json(mapping)["entries"])
        self.assertTrue(ocr.workflow_inventory(self.root)["complete"])

    def test_v1_formal_export_rejects_candidate_changed_after_acceptance(self):
        self.create_packets()
        self.write_reports()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=72))
        automatic = ocr.read_json(self.root / "packets" / ocr.EXAM_LITE_WORKFLOW / "acceptance" / "automatic" / "result.json")
        changed = ocr.read_json(automatic["output_candidate"])
        changed["pages"][0]["text"] = changed["pages"][0]["text"].replace("错误", "改写")
        changed_path = self.root / "v1-changed-after-acceptance.json"
        ocr.dump(changed_path, changed)
        with self.assertRaises(ValueError):
            ocr.exam_lite_export(argparse.Namespace(
                run=str(self.root), candidate=str(changed_path), output=str(self.root / "v1-changed.md"),
                mapping=str(self.root / "v1-changed-map.json"), layout=None, allow_draft=False,
            ))

    def test_v1_formal_exports_keep_old_protocol_and_support_obsidian(self):
        self.create_packets()
        self.write_reports()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=72))

        formatted = self.root / "v1.formatted.json"
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_format(argparse.Namespace(
                run=str(self.root), candidate=str(self.root / "exam-lite-final.json"),
                formatted_candidate=str(formatted), output=str(self.root / "v1-format.md"),
                mapping=str(self.root / "v1-format-map.json"), layout=None,
            ))
        formatted_data = ocr.read_json(formatted)
        self.assertNotIn("review_topology", formatted_data)
        self.assertNotIn("protocol_revision", formatted_data)

        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_export(argparse.Namespace(
                run=str(self.root), candidate=str(formatted), output=str(self.root / "v1-formatted.md"),
                mapping=str(self.root / "v1-formatted-map.json"), layout=None, allow_draft=False,
            ))
            ocr.exam_lite_obsidian_export(argparse.Namespace(
                run=str(self.root), exam_id="v1-accepted", output_dir=str(self.root / "v1-obsidian"),
                candidate=None, boundaries=None, layout=None, allow_draft=False,
            ))
        obsidian_manifest = ocr.read_json(self.root / "v1-obsidian" / "export-manifest.json")
        self.assertEqual(obsidian_manifest["draft"], False)
        self.assertIsNone(obsidian_manifest["protocol_revision"])

    def test_v2_incomplete_obsidian_draft_uses_merged_candidate(self):
        self.write_v2_reports()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_v2_merge(self.merge_args())
            ocr.exam_lite_obsidian_export(argparse.Namespace(
                run=str(self.root), exam_id="v2-draft", output_dir=str(self.root / "v2-draft-obsidian"),
                candidate=None, boundaries=None, layout=None, allow_draft=True,
            ))
        manifest = ocr.read_json(self.root / "v2-draft-obsidian" / "export-manifest.json")
        self.assertTrue(manifest["draft"])

    def test_formal_export_allow_draft_is_marked_in_machine_readable_outputs(self):
        self.write_v2_reports()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_v2_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=72))
            ocr.exam_lite_export(argparse.Namespace(
                run=str(self.root), candidate=None, output=str(self.root / "accepted-before-draft.md"),
                mapping=str(self.root / "accepted-before-draft-map.json"), layout=None, allow_draft=False,
            ))
        changed = ocr.read_json(self.root / "exam-lite-v2-merged.json")
        changed["pages"][0]["text"] = changed["pages"][0]["text"].replace("错误", "草稿改写")
        changed_path = self.root / "draft-candidate.json"
        ocr.dump(changed_path, changed)
        output = io.StringIO()
        with redirect_stdout(output):
            ocr.exam_lite_export(argparse.Namespace(
                run=str(self.root), candidate=str(changed_path), output=str(self.root / "draft.md"),
                mapping=str(self.root / "draft-map.json"), layout=None, allow_draft=True,
            ))
        result = json.loads(output.getvalue())
        self.assertTrue(result["draft"])
        self.assertFalse(result["formal_export"])
        self.assertIn("草稿", (self.root / "draft.md").read_text(encoding="utf-8"))
        mapping = ocr.read_json(self.root / "draft-map.json")
        self.assertTrue(mapping["draft"])

    def test_stale_acceptance_result_cannot_be_used_for_current_application(self):
        self.create_packets()
        self.write_reports()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=72))
        original_pdf = self.pdf.read_bytes()
        original_stat = self.pdf.stat()
        self.pdf.write_bytes(original_pdf + b"changed-after-acceptance")
        with self.assertRaisesRegex(ValueError, "source PDF changed"):
            ocr.exam_lite_export(argparse.Namespace(
                run=str(self.root), candidate=None, output=str(self.root / "changed-source.md"),
                mapping=str(self.root / "changed-source-map.json"), layout=None, allow_draft=False,
            ))
        self.pdf.write_bytes(original_pdf)
        os.utime(self.pdf, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        result_path = self.root / "packets" / ocr.EXAM_LITE_WORKFLOW / "acceptance" / "automatic" / "result.json"
        result = ocr.read_json(result_path)
        result["output_candidate"] = str(self.root / "mineru.json")
        ocr.dump(result_path, result)
        with self.assertRaisesRegex(ValueError, "different application|current application"):
            ocr.exam_lite_export(argparse.Namespace(
                run=str(self.root), candidate=None, output=str(self.root / "stale.md"),
                mapping=str(self.root / "stale-map.json"), layout=None, allow_draft=False,
            ))

    def test_changed_page_acceptance_can_revert_and_malformed_report_fails(self):
        self.create_packets()
        text = self.pages[0]["text"]
        start = text.index("错误")
        finding = {"page": 1, "start": start, "end": start + 2, "before": "错误",
                   "suggested": "正确", "verdict": "replace", "reason": "原图确认", "evidence": {
                       "kind": "image", "pdf_page": 1, "region": "题干", "reading": "正确"}}
        self.write_reports(self.report("A", findings=[finding]), self.report("B", context_id="fresh-b"))
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=150))
        acceptance_dir = self.root / "packets" / ocr.EXAM_LITE_WORKFLOW / "acceptance" / "attempt1"
        bad = {"workflow": ocr.EXAM_LITE_WORKFLOW, "status": "complete"}
        ocr.dump(acceptance_dir / "acceptance.json", bad)
        with self.assertRaises(ValueError):
            ocr.exam_lite_apply_acceptance(argparse.Namespace(run=str(self.root), acceptance=None))
        good = {
            "workflow": ocr.EXAM_LITE_WORKFLOW, "status": "complete", "accepted": False,
            "reviewed_pages": [1], "image_checked_pages": [1],
            "agent_context_id": "fresh-acceptance", "independent_context": True,
            "input_digest": ocr.exam_lite_digest(acceptance_dir / "input.json"),
            "candidate_meta": {"schema_version": 2, "lane": "exam-lite", "round": 1, "revision": 1},
            "decisions": [{"page": 1, "decision": "revert", "reason": "原图不支持", "evidence": {
                "kind": "image", "pdf_page": 1, "region": "题干", "reading": "错误"}}],
            "limitations": [],
        }
        empty = {**good, "accepted": True, "decisions": []}
        ocr.dump(acceptance_dir / "acceptance.json", empty)
        with self.assertRaisesRegex(ValueError, "every changed page"):
            ocr.exam_lite_apply_acceptance(argparse.Namespace(run=str(self.root), acceptance=None))
        ocr.dump(acceptance_dir / "acceptance.json", good)
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_apply_acceptance(argparse.Namespace(run=str(self.root), acceptance=None))
        self.assertTrue((self.root / "exam-lite-final.reverted.json").exists())

    def enable_v2(self):
        manifest = ocr.read_json(self.root / "manifest.json")
        manifest["review_topology"] = ocr.EXAM_LITE_TOPOLOGY
        manifest["protocol_revision"] = ocr.EXAM_LITE_PROTOCOL_REVISION
        manifest["workflow"].update({"review_topology": ocr.EXAM_LITE_TOPOLOGY,
                                      "protocol_revision": ocr.EXAM_LITE_PROTOCOL_REVISION})
        ocr.dump(self.root / "manifest.json", manifest)

    def v2_packet_dir(self, role, shard_id=None):
        return ocr._exam_v2_packet_dir(self.root, role, 1, shard_id)

    def v2_report(self, role, shard_id=None, findings=None, started="2026-10-16T10:00:00+00:00",
                  finished="2026-10-16T10:00:05+00:00", context_id=None):
        directory = self.v2_packet_dir(role, shard_id)
        payload = ocr.read_json(directory / "input.json")
        report = {
            "workflow": ocr.EXAM_LITE_WORKFLOW,
            "review_topology": ocr.EXAM_LITE_TOPOLOGY,
            "protocol_revision": ocr.EXAM_LITE_PROTOCOL_REVISION,
            "role": role,
            "status": "complete",
            "candidate_meta": payload["candidate_meta"],
            "started_at": started,
            "finished_at": finished,
            "agent_context_id": context_id or f"v2-{role}-{shard_id or 'full'}",
            "independent_context": True,
            "input_digest": ocr.exam_lite_digest(directory / "input.json"),
            "findings": findings or [],
            "limitations": [],
        }
        if role == "A":
            report["reviewed_pages"] = payload["primary_pages"]
        else:
            report.update({"shard_id": shard_id, "primary_pages": payload["primary_pages"],
                           "context_pages": payload["context_pages"],
                           "reviewed_pages": payload["primary_pages"],
                           "image_checked_pages": payload["primary_pages"]})
        return report

    def create_v2_packets(self):
        self.enable_v2()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_dispatch(argparse.Namespace(run=str(self.root), dpi=72))

    def write_v2_reports(self, findings_a=None, findings_b=None, conflict=False):
        self.create_v2_packets()
        a = self.v2_report("A", findings=findings_a,
                           started="2026-10-16T10:00:00+00:00", finished="2026-10-16T10:00:08+00:00")
        ocr.dump(self.v2_packet_dir("A") / "report.json", a)
        shards = ocr.exam_lite_shards(3)
        for index, shard in enumerate(shards):
            findings = findings_b if index == 0 else []
            if conflict and index == 0:
                findings = findings_b
            report = self.v2_report("B", shard["shard_id"], findings=findings,
                                    started="2026-10-16T10:00:01+00:00",
                                    finished="2026-10-16T10:00:06+00:00",
                                    context_id=f"v2-B-{shard['shard_id']}")
            ocr.dump(self.v2_packet_dir("B", shard["shard_id"]) / "report.json", report)

    def test_v2_dispatch_creates_text_a_and_nonoverlapping_two_page_b_shards(self):
        self.create_v2_packets()
        a_payload = ocr.read_json(self.v2_packet_dir("A") / "input.json")
        self.assertEqual(a_payload["review_topology"], ocr.EXAM_LITE_TOPOLOGY)
        self.assertEqual(a_payload["protocol_revision"], 2)
        self.assertFalse(a_payload["image_access"])
        self.assertNotIn("shared_images", a_payload)
        self.assertNotIn("source_pdf", a_payload)
        shards = ocr.exam_lite_shards(3)
        self.assertEqual([shard["primary_pages"] for shard in shards], [[1, 2], [3]])
        self.assertEqual(sum((shard["primary_pages"] for shard in shards), []), [1, 2, 3])
        for shard in shards:
            payload = ocr.read_json(self.v2_packet_dir("B", shard["shard_id"]) / "input.json")
            self.assertEqual(payload["shard_id"], shard["shard_id"])
            self.assertTrue(payload["shared_images"])
            self.assertEqual(payload["primary_pages"], shard["primary_pages"])

    def test_v2_parallel_summary_accepts_pairwise_shard_overlap(self):
        reports = {
            "B-01": {"started_at": "2026-10-16T10:00:00+00:00", "finished_at": "2026-10-16T10:00:04+00:00", "agent_context_id": "b1"},
            "B-02": {"started_at": "2026-10-16T10:00:03+00:00", "finished_at": "2026-10-16T10:00:07+00:00", "agent_context_id": "b2"},
            "B-03": {"started_at": "2026-10-16T10:00:06+00:00", "finished_at": "2026-10-16T10:00:10+00:00", "agent_context_id": "b3"},
        }
        summary = ocr._exam_parallel_summary(reports)
        self.assertTrue(summary["overlapped"])
        self.assertEqual(summary["max_parallel_agents"], 2)

    def test_v2_a_uses_text_evidence_and_b_requires_image_evidence(self):
        self.create_v2_packets()
        text = self.pages[0]["text"]
        start = text.index("错误")
        a_finding = {"page": 1, "start": start, "end": start + 2, "before": "错误",
                     "after": "正确", "verdict": "replace", "reason": "文字层上下文确认",
                     "evidence": {"kind": "text_layer", "source": "wps+mineru+adjacent", "reading": "正确"}}
        a = self.v2_report("A", findings=[a_finding])
        self.assertNotIn("image_checked_pages", a)
        ocr.dump(self.v2_packet_dir("A") / "report.json", a)
        bad_b = self.v2_report("B", "B-01", findings=[{
            "page": 1, "start": 0, "end": 1, "before": "第", "after": "第",
            "verdict": "replace", "category": "option", "reason": "bad", "evidence": {"kind": "text_layer"}
        }])
        with self.assertRaises(ValueError):
            ocr._exam_v2_validate_report(bad_b, self.v2_packet_dir("B", "B-01") / "input.json",
                                          ocr.read_json(self.v2_packet_dir("B", "B-01") / "input.json"),
                                          ocr.read_json(self.v2_packet_dir("B", "B-01") / "candidate.json"))

    def test_v2_merge_apply_and_c_accepts_a_and_b_changes(self):
        text = self.pages[0]["text"]
        a_start = text.index("错误")
        b_start = text.index("保留选项")
        a_finding = {"page": 1, "start": a_start, "end": a_start + 2, "before": "错误",
                     "after": "正确", "verdict": "replace", "reason": "文字层上下文确认",
                     "evidence": {"kind": "text_layer", "source": "wps", "reading": "正确"}}
        b_finding = {"page": 1, "start": b_start, "end": b_start + 4, "before": "保留选项",
                     "after": "保留选项A", "verdict": "replace", "category": "option", "reason": "原图标签确认",
                     "evidence": {"kind": "image", "pdf_page": 1, "region": "option-A", "reading": "保留选项A"}}
        self.write_v2_reports([a_finding], [b_finding])
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=72))
        acceptance_dir = ocr._exam_v2_packets_root(self.root) / "acceptance" / "attempt1"
        packet = ocr.read_json(acceptance_dir / "input.json")
        decisions = []
        for change in packet["changes"]:
            decisions.append({"change_id": change["change_id"], "decision": "accept",
                              "evidence": {"kind": "image", "pdf_page": change["page"],
                                            "region": "changed-region", "reading": change["after"]}})
        report = {"workflow": ocr.EXAM_LITE_WORKFLOW, "review_topology": ocr.EXAM_LITE_TOPOLOGY,
                  "protocol_revision": 2, "role": "C", "status": "complete",
                  "reviewed_pages": packet["target_pages"], "candidate_meta": packet["candidate_meta"],
                  "agent_context_id": "v2-C", "independent_context": True,
                  "input_digest": ocr.exam_lite_digest(acceptance_dir / "input.json"),
                  "started_at": "2026-10-16T10:01:00+00:00", "finished_at": "2026-10-16T10:01:04+00:00",
                  "decisions": decisions, "limitations": []}
        ocr.dump(acceptance_dir / "acceptance.json", report)
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_apply_acceptance(argparse.Namespace(run=str(self.root), acceptance=None))
        final = ocr.read_json(self.root / "exam-lite-final.json")
        self.assertIn("正确", final["pages"][0]["text"])
        self.assertIn("保留选项A", final["pages"][0]["text"])
        result = ocr.read_json(acceptance_dir / "result.json")
        self.assertEqual((result["accepted"], result["reverted"], result["unresolved"]), (2, 0, 0))
        self.assertTrue(ocr.workflow_inventory(self.root)["complete"])

    def test_v2_conflict_is_anonymous_to_c_and_unresolved_returns_original(self):
        text = self.pages[0]["text"]
        start = text.index("错误")
        a_finding = {"page": 1, "start": start, "end": start + 2, "before": "错误",
                     "after": "正确", "verdict": "replace", "reason": "A", "evidence": {
                         "kind": "text_layer", "source": "wps", "reading": "正确"}}
        b_finding = {"page": 1, "start": start, "end": start + 2, "before": "错误",
                     "after": "错项", "verdict": "replace", "category": "option", "reason": "B", "evidence": {
                         "kind": "image", "pdf_page": 1, "region": "option", "reading": "错项"}}
        self.write_v2_reports([a_finding], [b_finding], conflict=True)
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=72))
        acceptance_dir = ocr._exam_v2_packets_root(self.root) / "acceptance" / "attempt1"
        packet = ocr.read_json(acceptance_dir / "input.json")
        decisions = [{"change_id": change["change_id"], "decision": "unresolved" if change["after"] == "正确" else "revert",
                      "evidence": {"kind": "image", "pdf_page": change["page"], "region": "conflict", "reading": "无法唯一确认"}}
                     for change in packet["changes"]]
        self.assertEqual(len(packet["conflict_groups"]), 1)
        self.assertNotIn("reason", packet["changes"][0])
        report = {"workflow": ocr.EXAM_LITE_WORKFLOW, "review_topology": ocr.EXAM_LITE_TOPOLOGY,
                  "protocol_revision": 2, "role": "C", "status": "complete",
                  "reviewed_pages": packet["target_pages"], "candidate_meta": packet["candidate_meta"],
                  "agent_context_id": "v2-C-conflict", "independent_context": True,
                  "input_digest": ocr.exam_lite_digest(acceptance_dir / "input.json"),
                  "started_at": "2026-10-16T10:01:00+00:00", "finished_at": "2026-10-16T10:01:04+00:00",
                  "decisions": decisions, "limitations": ["conflict unresolved"]}
        ocr.dump(acceptance_dir / "acceptance.json", report)
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_apply_acceptance(argparse.Namespace(run=str(self.root), acceptance=None))
        result = ocr.read_json(acceptance_dir / "result.json")
        self.assertEqual(result["status"], "accepted_with_unresolved")
        self.assertIn("错误", ocr.read_json(self.root / "exam-lite-final.json")["pages"][0]["text"])

    def test_v2_without_changes_skips_c_and_format_is_idempotent(self):
        self.write_v2_reports()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=72))
        acceptance = ocr._exam_v2_packets_root(self.root) / "acceptance"
        self.assertTrue((acceptance / "automatic" / "result.json").exists())
        self.assertFalse((acceptance / "attempt1").exists())
        source = "**66.** 张某？ A. 10/13 B. 13/10 C. 20/13 D. 13/5\n①第一项②第二项\nA.①② B.①③ C.②④ D.③④\n****"
        formatted = ocr.format_exam_text(source)
        self.assertEqual(ocr.format_exam_text(formatted), formatted)
        self.assertIn("A. 10/13\nB. 13/10", formatted)
        self.assertIn("①第一项\n②第二项", formatted)
        self.assertIn("A.①②\nB.①③", formatted)

    def test_v2_formal_exports_reject_a_candidate_changed_after_acceptance(self):
        self.write_v2_reports()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=72))
        automatic = ocr.read_json(ocr._exam_v2_packets_root(self.root) / "acceptance" / "automatic" / "result.json")
        accepted_path = Path(automatic["output_candidate"])
        changed = ocr.read_json(accepted_path)
        changed["pages"][0]["text"] = changed["pages"][0]["text"].replace("错误", "改写")
        changed_path = self.root / "changed-after-acceptance.json"
        ocr.dump(changed_path, changed)

        with self.assertRaises(ValueError):
            ocr.exam_lite_export(argparse.Namespace(
                run=str(self.root), candidate=str(changed_path), output=str(self.root / "changed.md"),
                mapping=str(self.root / "changed-map.json"), layout=None, allow_draft=False,
            ))

        with self.assertRaises(ValueError):
            ocr.exam_lite_obsidian_export(argparse.Namespace(
                run=str(self.root), exam_id="changed", output_dir=str(self.root / "changed-obsidian"),
                candidate=str(changed_path), boundaries=None, layout=None, allow_draft=False,
            ))

    def test_v2_formal_exports_accept_reviewed_and_deterministically_formatted_candidates(self):
        self.write_v2_reports()
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_merge(self.merge_args())
            ocr.exam_lite_apply(argparse.Namespace(run=str(self.root)))
            ocr.exam_lite_accept_packet(argparse.Namespace(run=str(self.root), attempt=1, dpi=72))

        raw_output = self.root / "raw.md"
        raw_map = self.root / "raw-map.json"
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_export(argparse.Namespace(
                run=str(self.root), candidate=None, output=str(raw_output), mapping=str(raw_map),
                layout=None, allow_draft=False,
            ))
        formatted = self.root / "exam-lite-final.formatted.json"
        self.assertTrue(formatted.exists())
        self.assertNotIn("草稿", raw_output.read_text(encoding="utf-8"))

        formatted_output = self.root / "formatted.md"
        formatted_map = self.root / "formatted-map.json"
        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_export(argparse.Namespace(
                run=str(self.root), candidate=str(formatted), output=str(formatted_output),
                mapping=str(formatted_map), layout=None, allow_draft=False,
            ))
        self.assertEqual(formatted_output.read_text(encoding="utf-8"), raw_output.read_text(encoding="utf-8"))

        with redirect_stdout(io.StringIO()):
            ocr.exam_lite_obsidian_export(argparse.Namespace(
                run=str(self.root), exam_id="accepted", output_dir=str(self.root / "accepted-obsidian"),
                candidate=None, boundaries=None, layout=None, allow_draft=False,
            ))
        self.assertTrue((self.root / "accepted-obsidian" / "export-manifest.json").exists())

    def test_exam_formatter_protects_titles_and_updates_layout_mapping(self):
        source = "**国考行测标题**\n\n**66.** 张某8:00开车从A地出发****\nA. 10/13 B. 13/10 C. 20/13 D. 13/5\n①第一项②第二项\nA.①② B.①③ C.②④ D.③④"
        candidate = {
            "schema_version": ocr.LAYOUT_SCHEMA_VERSION,
            "lane": "exam-lite",
            "round": 1,
            "revision": 0,
            "pages": [{"page": 1, "text": source}],
            "layout": ocr.build_layout([{"page": 1, "text": source}], source="mineru"),
        }
        formatted, edits = ocr.format_exam_candidate(candidate)
        value = formatted["pages"][0]["text"]
        self.assertIn("**国考行测标题**", value)
        self.assertNotIn("****", value)
        self.assertIn("66. 张某8:00开车从A地出发", value)
        self.assertIn("A. 10/13\nB. 13/10\nC. 20/13\nD. 13/5", value)
        self.assertIn("①第一项\n②第二项", value)
        self.assertIn("A.①②\nB.①③\nC.②④\nD.③④", value)
        self.assertEqual(ocr.format_exam_text("**A.A**\n**D.①④⑤，②③⑥**"),
                         "A.A\nD.①④⑤，②③⑥\n")
        self.assertEqual(ocr.format_exam_text(value), value)
        self.assertTrue(edits)
        region = formatted["layout"]["pages"][0]["regions"][0]
        self.assertEqual(region["start"], 0)
        self.assertEqual(region["end"], len(value))
        rendered, mapping = ocr.render_clean_markdown(formatted["pages"], formatted["layout"])
        self.assertEqual(rendered.strip(), value.strip())
        self.assertTrue(any(entry.get("region_id") for entry in mapping["entries"]))
        self.assertTrue(all(entry.get("pdf_page") == 1 for entry in mapping["entries"]))

    def test_v2_rejects_stale_candidate_and_bad_unicode_span(self):
        self.create_v2_packets()
        a = self.v2_report("A")
        a["candidate_meta"]["revision"] = 99
        ocr.dump(self.v2_packet_dir("A") / "report.json", a)
        with self.assertRaises(ValueError):
            ocr._exam_v2_load_reports(self.root, ocr.read_json(self.root / "manifest.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
