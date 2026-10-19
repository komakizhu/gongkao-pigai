#!/usr/bin/env python3
"""Track one active review and at most one next-PDF input prefetch.

The queue does not create agent reports and does not count OCR-only or
input-attention runs as completed.  A caller may point it at the
context_pipeline.py entry point; the older ocr_review.py prepare command is
kept for legacy queues only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


WORKFLOW = "context-first-v1"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(path)


def init_queue(args):
    catalog = read(args.catalog)
    items = []
    for item in catalog.get("items", []):
        items.append({"index": item["index"], "kind": catalog.get("kind"),
                      "pdf": item["pdf"], "run": item["run"], "status": "pending"})
    write(args.queue, {"schema_version": 2, "workflow": WORKFLOW,
                       "created_at": now(), "prefetch_limit": 1,
                       "active_index": None, "items": items})
    print(json.dumps({"queue": str(Path(args.queue).absolute()), "items": len(items),
                      "prefetch_limit": 1}, ensure_ascii=False))


def refresh_status(item):
    manifest_path = Path(item["run"]) / "manifest.json"
    completion_path = Path(item["run"]) / "completion.json"
    if completion_path.exists():
        try:
            completion = read(completion_path)
            if completion.get("workflow") == WORKFLOW and completion.get("structural_verification") == "passed":
                return "completed"
        except (OSError, ValueError, json.JSONDecodeError):
            return "error"
    if not manifest_path.exists():
        return "pending"
    try:
        manifest = read(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return "error"
    decision = manifest.get("input_decision") or {}
    if manifest.get("input_gaps") and decision.get("decision") != "no_replacement":
        return "input_attention"
    return str(manifest.get("status", "unknown"))


def status_queue(args):
    queue = read(args.queue)
    counts = {}
    for item in queue.get("items", []):
        status = refresh_status(item)
        item["observed_status"] = status
        counts[status] = counts.get(status, 0) + 1
    write(args.queue, queue)
    print(json.dumps({"queue": str(Path(args.queue).absolute()), "counts": counts,
                      "items": queue.get("items", []), "prefetch_limit": queue.get("prefetch_limit", 1)},
                     ensure_ascii=False))


def _prefetch_slots(queue):
    return [item for item in queue.get("items", [])
            if item.get("status") in {"prefetching", "prefetched", "input_attention"}]


def _command_for(script, item, args):
    script_path = Path(script).resolve(strict=True)
    if script_path.name == "context_pipeline.py":
        return [sys.executable, str(script_path), "init", "--pdf", item["pdf"], "--run", item["run"],
                "--chunk-pages", str(args.chunk_pages), "--tier", args.tier]
    return [sys.executable, str(script_path), "prepare", "--pdf", item["pdf"], "--run", item["run"],
            "--chunk-pages", str(args.chunk_pages), "--tier", args.tier]


def prepare_next(args):
    queue = read(args.queue)
    slots = _prefetch_slots(queue)
    if len(slots) >= queue.get("prefetch_limit", 1):
        write(args.queue, queue)
        print(json.dumps({"prepared": None, "reason": "one-PDF prefetch slot is occupied",
                          "prefetch": slots[0]}, ensure_ascii=False))
        return
    pending = []
    for item in queue.get("items", []):
        observed = refresh_status(item)
        item["observed_status"] = observed
        if item.get("status") == "pending" and observed in {"pending", "error"}:
            pending.append(item)
    if not pending:
        write(args.queue, queue)
        print(json.dumps({"prepared": None, "reason": "no pending item"}, ensure_ascii=False))
        return
    item = pending[0]
    item["status"] = "prefetching"
    item["prefetch_started_at"] = now()
    write(args.queue, queue)
    command = _command_for(args.script, item, args)
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    item["last_prepare"] = {"at": now(), "returncode": result.returncode,
                             "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}
    item["observed_status"] = refresh_status(item)
    if result.returncode:
        item["status"] = "error"
    elif item["observed_status"] == "input_attention":
        item["status"] = "input_attention"
    else:
        item["status"] = "prefetched"
    write(args.queue, queue)
    print(json.dumps({"prepared": item, "returncode": result.returncode,
                      "review_concurrency": "one active PDF; one prefetch slot"}, ensure_ascii=False))
    if result.returncode:
        raise SystemExit(result.returncode)


def release(args):
    queue = read(args.queue)
    matches = [item for item in queue.get("items", []) if str(item["index"]) == str(args.index)]
    if len(matches) != 1:
        raise ValueError("queue index not found or not unique")
    item = matches[0]
    if refresh_status(item) != "completed":
        raise ValueError("only a structurally verified completed run can release its prefetch slot")
    item["status"] = "completed"
    item["released_at"] = now()
    write(args.queue, queue)
    print(json.dumps({"released": item["index"]}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("init")
    p.add_argument("--catalog", required=True)
    p.add_argument("--queue", required=True)
    p = commands.add_parser("status")
    p.add_argument("--queue", required=True)
    p = commands.add_parser("prepare-next")
    p.add_argument("--queue", required=True)
    p.add_argument("--script", required=True)
    p.add_argument("--chunk-pages", type=int, default=8)
    p.add_argument("--tier", default="standard")
    p = commands.add_parser("release")
    p.add_argument("--queue", required=True)
    p.add_argument("--index", required=True)
    args = parser.parse_args()
    if args.command == "init":
        init_queue(args)
    elif args.command == "status":
        status_queue(args)
    elif args.command == "prepare-next":
        prepare_next(args)
    else:
        release(args)


if __name__ == "__main__":
    main()
