"""Safety tests for context-first-v1; fixtures never represent production agents."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import context_pipeline as p
import context_render


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="context-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / "source.pdf"
        self.pdf.write_bytes(b"unit fixture")
        self.c = {
            "workflow": p.FLOW, "schema_version": 2, "lane": "native-context", "round": 0,
            "revision": 0, "review_route": "native_plus_mineru", "evidence_mode": "text_comparison",
            "pages": [{"page": 1, "text": "中 国文字。"}, {"page": 2, "text": "公式 2。"}],
            "page_origins": {"1": "native_text_layer", "2": "native_text_layer"},
        }
        p.save(self.root / "manifest.json", {
            "schema_version": 3, "workflow": {"id": p.FLOW, "protocol_version": p.PROTOCOL_VERSION},
            "source": p.core.source_info(self.pdf), "page_count": 2, "chunk_pages": 8,
            "tier": "standard", "input_gaps": [], "input_decision": {"decision": "not_required"},
            "review_route": "native_plus_mineru", "evidence_mode": "text_comparison",
            "started_at": p.now(), "status": "review_ready",
        })
        p.save(self.root / "candidate.json", self.c)
        p.save(self.root / "wps.json", {"pages": self.c["pages"]})
        p.save(self.root / "wps-input-report.json", {"missing_pages": [], "native_layer_complete": True})
        self.mineru = {"workflow": p.FLOW, "mode": "ocr", "pages": [
            {"page": 1, "text": "中国文字。"}, {"page": 2, "text": "公式 2。"}]}
        p.save(self.root / "mineru-text.json", self.mineru)
        for role in (*p.READERS, "S3"):
            p.packet(self.root, role)
        self.finding = {"id": "S4-001", "revision": 0, "page": 1, "start": 1, "end": 2,
                        "before": " ", "suggested": "", "reason": "中文词内空格", "confidence": "high"}

    def _reports(self, finding=None):
        for role in p.READERS:
            findings = [finding] if role == "S4" and finding else []
            p.save(self.root / "review" / role / "report.json", {
                "workflow": p.FLOW, "role": role, "status": "complete",
                "candidate_meta": p.meta(self.c), "reviewed_pages": [1, 2],
                "evidence_mode": "text_context", "limitations": [], "findings": findings,
                "withdrawn_ids": [],
            })
        inbox = p.sync(self.root)
        p.save(self.root / "review/S3/report.json", {
            "workflow": p.FLOW, "role": "S3", "status": "complete",
            "candidate_meta": p.meta(self.c), "reviewed_pages": [1, 2],
            "evidence_mode": "text_context", "limitations": [], "reviewed_roles": list(p.READERS),
            "assessments": [{"finding_id": f["id"], "verdict": "supported", "reason": "上下文支持"}
                            for f in inbox["findings"]],
            "processed_events": [e["event_key"] for e in inbox["events"]],
        })

    def _j(self):
        self._reports(self.finding)
        p.judge_packet(self.root)
        differences = p.read(self.root / "review/J/input.json")["differences"]
        value = {
            "workflow": p.FLOW, "status": "complete", "candidate_meta": p.meta(self.c),
            "reviewed_pages": [1, 2],
            "finding_dispositions": [{"finding_id": "S4-001", "decision": "replace", "reason": "空格"}],
            "difference_dispositions": [{"difference_id": d["id"], "decision": "replace", "reason": "空格"}
                                         for d in differences],
            "decisions": [{"id": "J-001", "page": 1, "start": 1, "end": 2,
                           "before": " ", "after": "", "decision": "replace", "reason": "中文词内空格",
                           "selected_source": "context",
                           "evidence": {"kind": "context", "pdf_page": 1, "basis": "两路文字及上下文"}}],
            "limitations": [],
        }
        p.save(self.root / "review/J/decisions.json", value)
        return value

    def test_missing_layer_waits_and_refusal_creates_single_source_candidate(self):
        m = p.read(self.root / "manifest.json")
        m["input_gaps"] = [2]
        m["review_route"] = None
        m["evidence_mode"] = None
        m["input_decision"] = {"state": "pending", "decision": None}
        p.save(self.root / "manifest.json", m)
        (self.root / "candidate.json").unlink()
        (self.root / "mineru-text.json").unlink()
        shutil.rmtree(self.root / "review")
        with self.assertRaisesRegex(ValueError, "waiting for a user decision"):
            p.build_candidate(self.root)
        args = type("Args", (), {"run": str(self.root), "decision": "no_replacement", "pdf": None,
                                  "output": None, "tier": "standard", "chunk_pages": 8,
                                  "mineru_python": None, "mineru_home": None})()
        p.input_decision(args)
        with self.assertRaisesRegex(ValueError, "complete MinerU OCR"):
            p.build_candidate(self.root)
        p.save(self.root / "mineru-text.json", {"workflow": p.FLOW, "pages": self.mineru["pages"]})
        candidate = p.build_candidate(self.root)
        self.assertEqual(candidate["review_route"], "mineru_only")
        self.assertEqual(set(candidate["page_origins"].values()), {"mineru_only"})
        self.assertEqual(p.manifest(self.root)["evidence_mode"], "single_source")

    def test_init_reports_file_and_page_without_invoking_wps(self):
        root = self.root / "input-check"
        pdf = self.root / "input-check.pdf"
        pdf.write_bytes(b"pdf fixture")
        pages = [{"page": 1, "text": "有文字"}, {"page": 2, "text": ""}]
        args = type("Args", (), {"run": str(root), "pdf": str(pdf), "latest_pdf": None,
                                  "tier": "standard", "chunk_pages": 8, "mineru_python": None,
                                  "mineru_home": None})()
        with patch.object(p.core, "extract_wps", return_value=pages), \
             patch.object(p.core, "extract_wps_bbox", return_value=""), \
             patch.object(p.core, "build_wps_layout", return_value={"pages": []}):
            result = p.init(args, quiet=True)
        self.assertEqual(result["missing_pages"], [2])
        self.assertFalse(result["review_ready"])
        self.assertFalse((root / "candidate.json").exists())
        report = p.read(root / "wps-input-report.json")
        self.assertEqual(report["missing_pages"], [2])
        self.assertFalse(report["wps_invoked"])
        self.assertEqual(p.manifest(root)["status"], "waiting_for_input")

    def test_bbox_failure_keeps_text_review_ready_with_page_precision(self):
        root = self.root / "bbox-fallback"
        pdf = self.root / "bbox-fallback.pdf"
        pdf.write_bytes(b"pdf fixture")
        pages = [{"page": 1, "text": "有文字"}]
        args = type("Args", (), {"run": str(root), "pdf": str(pdf), "latest_pdf": None,
                                  "tier": "standard", "chunk_pages": 8, "mineru_python": None,
                                  "mineru_home": None})()
        with patch.object(p.core, "extract_wps", return_value=pages), \
             patch.object(p.core, "extract_wps_bbox", side_effect=subprocess.CalledProcessError(1, "pdftotext")), \
             patch.object(p.core, "build_layout", return_value={"pages": []}):
            result = p.init(args, quiet=True)
        self.assertTrue(result["review_ready"])
        report = p.read(root / "wps-input-report.json")
        self.assertEqual(report["location_precision"], "page")

    def test_replacement_uses_a_new_run_and_does_not_reuse_candidate(self):
        m = p.read(self.root / "manifest.json")
        m["input_gaps"] = [2]
        m["review_route"] = None
        m["evidence_mode"] = None
        m["input_decision"] = {"state": "pending", "decision": None}
        p.save(self.root / "manifest.json", m)
        (self.root / "candidate.json").unlink()
        shutil.rmtree(self.root / "review")
        replacement_pdf = self.root / "latest.pdf"
        replacement_pdf.write_bytes(b"new fixture")
        output = self.root / "replacement-run"
        args = type("Args", (), {"run": str(self.root), "decision": "supply_latest",
                                  "pdf": str(replacement_pdf), "output": str(output),
                                  "tier": "standard", "chunk_pages": 8, "mineru_python": None,
                                  "mineru_home": None})()
        pages = [{"page": 1, "text": "新版一"}, {"page": 2, "text": "新版二"}]
        with patch.object(p.core, "extract_wps", return_value=pages), \
             patch.object(p.core, "extract_wps_bbox", return_value=""), \
             patch.object(p.core, "build_wps_layout", return_value={"pages": []}):
            result = p.input_decision(args)
        self.assertEqual(result["replacement_run"], str(output))
        self.assertTrue((output / "candidate.json").exists())
        self.assertEqual(p.manifest(output)["input_lineage"]["replaced_run"], str(self.root))
        self.assertEqual(p.manifest(self.root)["status"], "replaced_by_new_run")

    def test_legacy_ocr_import_reuses_only_validated_text_layout_and_assets(self):
        old = self.root / "old-run"
        old.mkdir()
        old_source = p.core.source_info(self.pdf)
        p.save(old / "manifest.json", {
            "source": old_source, "page_count": 2, "chunk_pages": 8, "tier": "standard",
            "workflow": {"id": "single-pass-v1"},
        })
        p.save(old / "mineru.json", {"pages": self.mineru["pages"]})
        p.save(old / "mineru-layout.json", {"pages": []})
        (old / "mineru.md").write_text("旧OCR导出\n", encoding="utf-8")
        args = type("Args", (), {"run": str(self.root), "from_run": str(old)})()
        result = p.reuse_ocr(args)
        self.assertFalse(result["reports_reused"])
        self.assertEqual(p.read(self.root / "mineru-text.json")["pages"], self.mineru["pages"])
        self.assertEqual(p.manifest(self.root)["ocr_reuse"]["source_workflow"], "single-pass-v1")

    def test_streamed_finding_requires_revision_and_tracks_withdrawal(self):
        p.save(self.root / "review/S4/progress.json", {"findings": [self.finding], "withdrawn_ids": []})
        first = p.sync(self.root)
        self.assertEqual(len(first["events"]), 1)
        changed = {**self.finding, "revision": 1, "suggested": "未知"}
        p.save(self.root / "review/S4/progress.json", {"findings": [changed], "withdrawn_ids": []})
        second = p.sync(self.root)
        self.assertEqual(len(second["events"]), 2)
        p.save(self.root / "review/S4/report.json", {
            "workflow": p.FLOW, "role": "S4", "status": "complete",
            "candidate_meta": p.meta(self.c), "reviewed_pages": [1, 2],
            "evidence_mode": "text_context", "limitations": [], "findings": [],
            "withdrawn_ids": [{"id": "S4-001", "revision": 2, "reason": "重新核对后撤回"}],
        })
        withdrawn = p.sync(self.root)
        self.assertEqual(withdrawn["findings"], [])
        self.assertEqual(withdrawn["events"][-1]["kind"], "withdraw")

    def test_progress_batches_preserve_prior_findings_until_explicit_withdrawal(self):
        p.save(self.root / "review/S4/progress.json", {"findings": [self.finding], "withdrawn_ids": []})
        p.sync(self.root)
        second = {"id": "S1-001", "revision": 0, "page": 2, "start": 0, "end": 2,
                  "before": "公式", "suggested": "公式", "reason": "上下文检查", "confidence": "medium"}
        p.save(self.root / "review/S1/progress.json", {"findings": [second], "withdrawn_ids": []})
        batched = p.sync(self.root)
        self.assertEqual({item["id"] for item in batched["findings"]}, {"S4-001", "S1-001"})
        p.save(self.root / "review/S4/progress.json", {
            "findings": [], "withdrawn_ids": [{"id": "S4-001", "revision": 1, "reason": "撤回"}],
        })
        withdrawn = p.sync(self.root)
        self.assertEqual({item["id"] for item in withdrawn["findings"]}, {"S1-001"})

    def test_packets_are_text_only_and_j_requires_all_differences(self):
        packets = {role: p.read(self.root / "review" / role / "input.json")
                   for role in (*p.READERS, "S3")}
        raw = json.dumps(packets, ensure_ascii=False)
        self.assertNotIn("source.pdf", raw)
        self.assertNotIn("image", raw.lower())
        self._reports(self.finding)
        p.judge_packet(self.root)
        differences = p.read(self.root / "review/J/input.json")["differences"]
        self.assertTrue(differences)
        j = self._j()
        j["difference_dispositions"] = []
        p.save(self.root / "review/J/decisions.json", j)
        with self.assertRaisesRegex(ValueError, "every text difference"):
            p.judgment(self.root)

    def test_j_apply_and_local_acceptance_preserve_other_changes(self):
        self._j()
        p.apply(self.root)
        judged = p.read(self.root / "judged.json")
        self.assertEqual(judged["pages"][0]["text"], "中国文字。")
        p.save(self.root / "review/acceptance/acceptance.json", {
            "workflow": p.FLOW, "status": "complete", "candidate_meta": p.meta(judged),
            "reviewed_pages": [1], "evidence_mode": "text_context",
            "decisions": [{"id": "J-001", "decision": "unresolved", "reason": "保守回退"}],
            "limitations": [],
        })
        accepted, _, _ = p.accepted_candidate(self.root)
        self.assertEqual(accepted["pages"], self.c["pages"])
        self.assertEqual(p.read(self.root / "judged.json"), judged)

    def test_host_events_are_reported_without_capacity_inference(self):
        times = {
            "S1": ("2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00"),
            "S2": ("2026-01-01T00:00:01+00:00", "2026-01-01T00:01:01+00:00"),
            "S4": ("2026-01-01T00:00:02+00:00", "2026-01-01T00:01:02+00:00"),
            "S5": ("2026-01-01T00:00:03+00:00", "2026-01-01T00:01:03+00:00"),
            "S6": ("2026-01-01T00:00:04+00:00", "2026-01-01T00:01:04+00:00"),
        }
        for role, (start, finish) in times.items():
            p.record_agent_event(self.root, role, role + "-host", "start", started_at=start)
            p.record_agent_event(self.root, role, role + "-host", "finish", finished_at=finish)
        result = p.timing(self.root)
        self.assertTrue(result["five_reader_host_intervals_overlap"])
        self.assertIn("no capacity inference", result["timing_evidence"])

    def test_agent_retry_events_are_bounded_and_success_is_not_restarted(self):
        p.record_agent_event(self.root, "S1", "s1-1", "start", started_at="2026-01-01T00:00:00+00:00")
        p.record_agent_event(self.root, "S1", "s1-1", "fail",
                             finished_at="2026-01-01T00:00:01+00:00", error="temporary")
        p.record_agent_event(self.root, "S1", "s1-2", "start", attempt=2,
                             started_at="2026-01-01T00:00:02+00:00")
        p.record_agent_event(self.root, "S1", "s1-2", "finish", attempt=2,
                             finished_at="2026-01-01T00:00:03+00:00")
        with self.assertRaisesRegex(ValueError, "cannot be rerun"):
            p.record_agent_event(self.root, "S1", "s1-3", "start", attempt=3)
        with self.assertRaisesRegex(ValueError, "limited"):
            p.record_agent_event(self.root, "S2", "s2-4", "start", attempt=4)

    def test_whitespace_separator_is_not_erased_by_renderer(self):
        rendered, provenance = context_render.compose_pages(
            [{"page": 1, "text": "中 国文字。"}],
            [{"page": 1, "text": "中国文字。"}],
        )
        self.assertFalse(provenance["ok"])
        self.assertEqual(rendered[0]["text"], "中 国文字。")

    def test_matching_text_table_keeps_mineru_structure_without_duplication(self):
        table = "| A | B |\n|---|---|\n| C | D |"
        rendered, provenance = context_render.compose_pages(
            [{"page": 1, "text": "A B\nC D"}], [{"page": 1, "text": table}])
        self.assertTrue(provenance["ok"])
        self.assertEqual(rendered[0]["text"], table)
        self.assertTrue(provenance["pages"][0]["table_visible_match"])

    def test_degraded_composition_is_never_a_completed_export(self):
        self._j()
        p.apply(self.root)
        p.save(self.root / "review/acceptance/acceptance.json", {
            "workflow": p.FLOW, "status": "complete", "candidate_meta": p.meta(p.read(self.root / "judged.json")),
            "reviewed_pages": [1], "evidence_mode": "text_context",
            "decisions": [{"id": "J-001", "decision": "accept", "reason": "test"}], "limitations": [],
        })
        p.save(self.root / "mineru.json", {"pages": [
            {"page": 1, "text": "中国文字。\n![x](asset.png)"}, {"page": 2, "text": "公式 2。"}]})
        with self.assertRaisesRegex(ValueError, "composition is degraded"):
            p.finish(self.root)
        self.assertTrue((self.root / "composition-pending.json").exists())
        self.assertFalse((self.root / "completion.json").exists())

    def test_unresolved_j_decision_blocks_completed_export(self):
        j = self._j()
        j["difference_dispositions"][0]["decision"] = "unresolved"
        p.save(self.root / "review/J/decisions.json", j)
        p.apply(self.root)
        p.save(self.root / "review/acceptance/acceptance.json", {
            "workflow": p.FLOW, "status": "complete", "candidate_meta": p.meta(p.read(self.root / "judged.json")),
            "reviewed_pages": [1], "evidence_mode": "text_context",
            "decisions": [{"id": "J-001", "decision": "accept", "reason": "test"}], "limitations": [],
        })
        p.save(self.root / "mineru.json", {"pages": p.read(self.root / "judged.json")["pages"]})
        with self.assertRaisesRegex(ValueError, "unresolved decisions"):
            p.finish(self.root)
        self.assertTrue((self.root / "decision-pending.json").exists())
        self.assertFalse((self.root / "completion.json").exists())

    def test_missing_copied_asset_blocks_completed_export(self):
        self._j()
        p.apply(self.root)
        judged = p.read(self.root / "judged.json")
        p.save(self.root / "review/acceptance/acceptance.json", {
            "workflow": p.FLOW, "status": "complete", "candidate_meta": p.meta(judged),
            "reviewed_pages": [1], "evidence_mode": "text_context",
            "decisions": [{"id": "J-001", "decision": "accept", "reason": "test"}],
            "limitations": [],
        })
        p.save(self.root / "mineru.json", {"pages": judged["pages"]})
        p.save(self.root / "mineru-assets.json", {"workflow": p.FLOW, "files": ["assets/missing.png"]})
        with self.assertRaisesRegex(ValueError, "missing MinerU asset"):
            p.finish(self.root)
        self.assertFalse((self.root / "completion.json").exists())

    def test_clean_text_composition_produces_verified_mapping_and_completion(self):
        self._j()
        p.apply(self.root)
        judged = p.read(self.root / "judged.json")
        p.save(self.root / "review/acceptance/acceptance.json", {
            "workflow": p.FLOW, "status": "complete", "candidate_meta": p.meta(judged),
            "reviewed_pages": [1], "evidence_mode": "text_context",
            "decisions": [{"id": "J-001", "decision": "accept", "reason": "文字一致"}],
            "limitations": [],
        })
        p.save(self.root / "mineru.json", {"pages": judged["pages"]})
        timing = p.finish(self.root)
        self.assertIsNone(timing["five_reader_host_intervals_overlap"])
        self.assertEqual(p.verify(self.root)["structural_verification"], "passed")
        self.assertTrue((self.root / "completion.json").exists())
        self.assertTrue(p.read(self.root / "source-map.json")["spans"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
