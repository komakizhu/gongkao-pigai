"""Unit tests for checkpoint identity and durable retry behavior."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json

import context_ocr_worker as worker


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="context-ocr-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_asset_manifest_counts_without_copying_payloads(self):
        value = {"pages": [{"blocks": [{"image_base64": "very-large", "image_path": "p.png"}]}],
                 "images": [{"image_url": "x"}, {"image_url": "y"}]}
        summary = worker.asset_manifest(value)
        self.assertTrue(summary["has_assets"])
        self.assertEqual(summary["counts"]["image_base64"], 1)
        self.assertEqual(summary["counts"]["image_url"], 2)
        self.assertNotIn("very-large", str(summary))

    def test_local_image_paths_are_copied_and_rewritten(self):
        source = self.root / "source.pdf"
        source.write_bytes(b"pdf")
        original = self.root / "parser-assets" / "table.png"
        original.parent.mkdir()
        original.write_bytes(b"png")
        middle = {"pages": [], "blocks": [{"image_path": str(original)}]}
        cfg = {"source": {"path": str(source)}}
        result = worker.preserve_assets(self.root, cfg, 1, 2, middle)
        self.assertEqual(result["count"], 1)
        rewritten = Path(middle["blocks"][0]["image_path"])
        self.assertFalse(rewritten.is_absolute())
        self.assertEqual((self.root / rewritten).read_bytes(), b"png")

    def test_retry_budget_survives_a_new_worker_invocation(self):
        calls = []

        def first_operation(attempt):
            calls.append(attempt)
            if attempt == 1:
                raise RuntimeError("temporary")
            return {"attempts": attempt, "state": "complete"}

        value = worker.retry(self.root, "ocr", 1, 2, first_operation)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(value["state"], "complete")
        self.assertEqual(worker.read(self.root / "worker-attempts.json")["ocr:1-2"], 2)

        value = worker.retry(self.root, "ocr", 1, 2, lambda attempt: {"attempts": attempt, "ok": True})
        self.assertEqual(value["ok"], True)
        self.assertEqual(worker.read(self.root / "worker-attempts.json")["ocr:1-2"], 3)
        with self.assertRaisesRegex(RuntimeError, "already used three attempts"):
            worker.retry(self.root, "ocr", 1, 2, lambda attempt: {"ok": True})

    def test_missing_text_layer_blocks_ocr_until_explicit_refusal(self):
        manifest = {
            "workflow": {"id": worker.WORKFLOW, "protocol_version": 2},
            "source": {"path": str(self.root / "source.pdf"), "size": 1, "mtime_ns": 1},
            "page_count": 1, "chunk_pages": 1, "tier": "standard", "input_gaps": [1],
            "input_decision": {"decision": None},
        }
        worker.atomic_write(self.root / "manifest.json", manifest)
        with patch.object(worker.review, "source_info", return_value=manifest["source"]), \
             patch.object(worker.review, "page_count", return_value=1):
            with self.assertRaisesRegex(ValueError, "explicit no_replacement"):
                worker.configuration(self.root)
        manifest["input_decision"] = {"decision": "no_replacement"}
        worker.atomic_write(self.root / "manifest.json", manifest)
        with patch.object(worker.review, "source_info", return_value=manifest["source"]), \
             patch.object(worker.review, "page_count", return_value=1):
            cfg, _ = worker.configuration(self.root)
        self.assertEqual(cfg["parse_mode"], "ocr")

    def test_parser_initialization_and_reuse_events_are_distinct(self):
        cfg = {"workflow": worker.WORKFLOW, "source": {}, "page_count": 2,
               "chunk_pages": 1, "tier": "standard", "parse_mode": "ocr", "format_mode": "full",
               "worker_schema": 1}
        saved = [
            {"revision": "one", "attempts": 1, "pages": [{"page": 1, "text": "一"}]},
            {"revision": "two", "attempts": 1, "pages": [{"page": 2, "text": "二"}]},
        ]

        class FakeParser:
            def close(self):
                pass

        with patch.object(worker, "preflight"), \
             patch.object(worker, "verify_source"), \
             patch.object(worker, "load_ocr", return_value=None), \
             patch.object(worker, "recognize_chunk", side_effect=saved):
            worker.run(self.root, cfg, stage="ocr", parser_factory=lambda _cfg: FakeParser())

        events = [json.loads(line) for line in (self.root / "timing.jsonl").read_text().splitlines()]
        init = [e for e in events if e["event"] == "ocr_parser_initialization_finished"]
        chunks = [e for e in events if e["event"] == "ocr_parser_chunk_finished"]
        self.assertEqual(len(init), 1)
        self.assertFalse(init[0]["model_load_observed"])
        self.assertEqual([e["parser_call"] for e in chunks], [1, 2])
        self.assertEqual([e["parser_reused"] for e in chunks], [False, True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
