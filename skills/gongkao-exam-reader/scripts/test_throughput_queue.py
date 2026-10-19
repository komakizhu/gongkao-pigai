"""Unit tests for the one-active-review/one-prefetch queue policy."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import throughput_queue as queue


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="context-queue-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue_path = self.root / "queue.json"

    def _write_queue(self, items):
        queue.write(self.queue_path, {
            "schema_version": 2,
            "workflow": queue.WORKFLOW,
            "prefetch_limit": 1,
            "active_index": None,
            "items": items,
        })

    def test_second_prefetch_is_refused_while_slot_is_occupied(self):
        self._write_queue([
            {"index": 1, "pdf": "one.pdf", "run": "one", "status": "prefetched"},
            {"index": 2, "pdf": "two.pdf", "run": "two", "status": "pending"},
        ])
        args = type("Args", (), {"queue": str(self.queue_path), "script": "context_pipeline.py",
                                  "chunk_pages": 8, "tier": "standard"})()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            queue.prepare_next(args)
        result = json.loads(output.getvalue())
        self.assertIsNone(result["prepared"])
        self.assertIn("occupied", result["reason"])
        self.assertEqual(queue.read(self.queue_path)["items"][1]["status"], "pending")

    def test_only_verified_context_completion_is_releasable(self):
        run = self.root / "run"
        run.mkdir()
        queue.write(run / "manifest.json", {"workflow": {"id": queue.WORKFLOW}})
        self._write_queue([{"index": 1, "pdf": "one.pdf", "run": str(run), "status": "prefetched"}])
        args = type("Args", (), {"queue": str(self.queue_path), "index": "1"})()
        with self.assertRaisesRegex(ValueError, "structurally verified"):
            queue.release(args)

        queue.write(run / "completion.json", {
            "workflow": queue.WORKFLOW,
            "structural_verification": "passed",
        })
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            queue.release(args)
        self.assertEqual(queue.read(self.queue_path)["items"][0]["status"], "completed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
