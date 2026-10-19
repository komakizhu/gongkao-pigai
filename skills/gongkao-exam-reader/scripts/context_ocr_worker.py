#!/usr/bin/env python3
"""context-first-v1: resident OCR and a separate, single-process formatter.

Run in the verified MinerU Python: context_ocr_worker.py --run ROOT
--stage ocr / --stage format resume either stage independently; all is default.
The manifest is read-only. Successful checkpoints are reused automatically.
ocr-chunks/pNNNN-NNNN/middle.json is an atomic envelope containing the COMPLETE
MiddleJson under middle_json, plain pages, source/config identity and revision.
format.json refers to that revision and holds per-page Markdown. Root status
files are completion markers: consumers must require state == "complete".
No inference occurs in the formatter. Tests can inject a parser and result type.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import copy
import fcntl
from html.parser import HTMLParser
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

import ocr_review as review

WORKFLOW = "context-first-v1"
THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
              "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS",
              "RAYON_NUM_THREADS", "TORCH_NUM_THREADS", "TF_NUM_INTRAOP_THREADS",
              "TF_NUM_INTEROP_THREADS")
CONTAINERS = {"list", "index", "image", "table", "chart", "code"}


class IdentityMismatch(ValueError):
    """A different source/config must never overwrite an existing run."""


def atomic_write(path, value, *, raw=False):
    path = Path(path)
    text = value if raw else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8", errors="replace") == text:
        return  # Keep successful records, including their mtime, unchanged.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read(path):
    return review.read_json(path)


def configuration(root):
    manifest = read(root / "manifest.json")
    if review.workflow_id(manifest) != WORKFLOW:
        raise IdentityMismatch(f"workflow.id must be {WORKFLOW}")
    if manifest.get("mineru_status") == "complete_imported":
        raise ValueError("this run already contains an imported complete OCR export; create a new run to re-run OCR")
    gaps = manifest.get("input_gaps", [])
    decision = manifest.get("input_decision", {})
    if gaps and (not isinstance(decision, dict) or decision.get("decision") != "no_replacement"):
        raise ValueError("text-layer gaps require an explicit no_replacement decision before MinerU")
    for name in ("page_count", "chunk_pages"):
        if type(manifest.get(name)) is not int or manifest[name] < 1:
            raise ValueError(f"manifest {name} must be a positive integer")
    if manifest.get("tier") not in {"flash", "basic", "standard", "advanced"}:
        raise ValueError("invalid manifest tier")
    cfg = {key: manifest[key] for key in ("source", "page_count", "chunk_pages", "tier")}
    cfg.update(workflow=WORKFLOW, parse_mode="ocr", format_mode="full", worker_schema=1)
    verify_source(cfg)
    if review.page_count(cfg["source"]["path"]) != cfg["page_count"]:
        raise IdentityMismatch("source page count differs from manifest")
    return cfg, manifest


def verify_source(cfg):
    if review.source_info(cfg["source"]["path"]) != cfg["source"]:
        raise IdentityMismatch("source metadata changed; use a new run directory")


def ranges(cfg):
    for first in range(1, cfg["page_count"] + 1, cfg["chunk_pages"]):
        yield first, min(first + cfg["chunk_pages"] - 1, cfg["page_count"])


def chunk_dir(root, first, last):
    return Path(root) / "ocr-chunks" / f"p{first:04d}-{last:04d}"


def identity(record, cfg):
    if not isinstance(record, dict):
        raise ValueError("checkpoint must be an object")
    if "config" in record and record["config"] != cfg:
        raise IdentityMismatch("checkpoint source/config differs; use a new run directory")
    if record.get("config") != cfg:
        raise ValueError("checkpoint config is missing")


def preflight(root, cfg):
    """Check every existing identity before any new OCR or status writes."""
    paths = list((root / "ocr-chunks").glob("*/middle.json"))
    paths += list((root / "ocr-chunks").glob("*/format.json"))
    paths += [root / "ocr-status.json", root / "format-status.json"]
    for path in paths:
        try:
            record = read(path)
            identity(record, cfg)
        except IdentityMismatch:
            raise
        except (OSError, ValueError, TypeError):
            continue  # Damaged local records will be regenerated, never skipped.


def asset_manifest(value):
    """Record asset-bearing nodes without duplicating their base64 payloads."""
    counts = {}

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, child in node.items():
                if key.casefold() in {"image_base64", "image_path", "image_url", "img_path", "images"}:
                    kind = key.casefold()
                    counts[kind] = counts.get(kind, 0) + (len(child) if isinstance(child, list) else 1)
                walk(child, f"{path}/{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}/{index}")

    walk(value)
    return {"counts": counts, "has_assets": bool(counts)}


def preserve_assets(root, cfg, first, last, middle):
    """Copy local MinerU image payloads into the run and rewrite safe paths.

    MiddleJson may contain relative paths, absolute paths, data URIs or remote
    URLs.  Only local files are copied; unresolved local image paths are a hard
    error so serialization cannot silently turn a completed export into a
    broken media reference.
    """
    root = Path(root).absolute()
    source_parent = Path(cfg["source"]["path"]).resolve().parent
    candidates_root = [Path.cwd(), source_parent, root]
    copied, seen, missing = [], {}, []
    counter = 0

    def locate(raw):
        value = str(raw).strip()
        if not value or value.startswith(("data:", "http://", "https://", "//")):
            return None
        path = Path(value).expanduser()
        options = [path] if path.is_absolute() else [base / path for base in candidates_root]
        checked = set()
        for option in options:
            try:
                resolved = option.resolve()
            except OSError:
                continue
            if resolved in checked:
                continue
            checked.add(resolved)
            if resolved.is_file():
                return resolved
        missing.append(value)
        return None

    def visit(node):
        nonlocal counter
        if isinstance(node, dict):
            for key, child in list(node.items()):
                if key.casefold() in {"image_path", "img_path"} and isinstance(child, str):
                    resolved = locate(child)
                    if resolved is not None:
                        source_pdf = Path(cfg["source"]["path"]).resolve()
                        if resolved == source_pdf:
                            missing.append(child)
                        else:
                            cache_key = str(resolved)
                            relative = seen.get(cache_key)
                            if relative is None:
                                counter += 1
                                destination = root / "assets" / f"p{first:04d}-{last:04d}" / \
                                    f"{counter:04d}-{resolved.name}"
                                destination.parent.mkdir(parents=True, exist_ok=True)
                                if destination.resolve() != resolved:
                                    temporary = destination.with_name(destination.name + ".partial")
                                    shutil.copy2(resolved, temporary)
                                    os.replace(temporary, destination)
                                relative = destination.relative_to(root).as_posix()
                                seen[cache_key] = relative
                                copied.append(relative)
                            node[key] = relative
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(middle)
    if missing:
        unique = sorted(set(missing))
        raise ValueError("local MinerU image assets are missing: " + ", ".join(unique[:20]))
    return {"files": copied, "count": len(copied)}


class TableText(HTMLParser):
    """Read HTML table cells as text, retaining row/cell boundaries and alt text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")
        elif tag == "img":
            self.parts.append(dict(attrs).get("alt", "") or "")

    def handle_endtag(self, tag):
        if tag in {"td", "th"}:
            self.parts.append("\t")
        elif tag in {"tr", "p", "div"}:
            self.parts.append("\n")


def plain_node(node):
    """Traverse semantic content only: never stringify a block or render Markdown.

    Adjacent inline spans join without added spaces; block children use newlines.
    Equations/code retain literal source text. HTML tables lose markup only.
    """
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(plain_node(item) for item in node)
    if not isinstance(node, dict) or "content" not in node:
        raise ValueError("unsupported content node; refusing silent text loss")
    content = node["content"]
    if node.get("type") in CONTAINERS:
        if not isinstance(content, list):
            raise ValueError("container content must be a list")
        return "\n".join(plain_node(child) for child in content)
    if node.get("type") == "table_body" and isinstance(content, str):
        parser = TableText()
        parser.feed(content)
        parser.close()
        return "\n".join(line.strip("\t ") for line in "".join(parser.parts).splitlines()).strip()
    return plain_node(content)


def result_type():
    from mineru.parser.base import ParseResult
    return ParseResult


def validate_middle(middle, cfg, first, last, result_cls=None):
    result = (result_cls or result_type()).from_dict(middle)
    indices = [page.page_idx for page in result.pages]
    expected = list(range(first - 1, last))
    if indices not in (expected, list(range(last - first + 1))):
        raise ValueError(f"page mapping mismatch for {first}-{last}: {indices}")
    actual = middle.get("extensions", {}).get("mineru")
    if actual is not None and actual != {"tier": cfg["tier"], "parse_mode": "ocr"}:
        raise ValueError("MiddleJson reports a different tier or non-OCR parse mode")
    return result


def plain_pages(middle, first):
    return [{"page": first + offset,
             "text": "\n".join(plain_node(block) for block in page["blocks"])}
            for offset, page in enumerate(middle["pages"])]


def load_ocr(root, cfg, first, last, result_cls=None):
    path = chunk_dir(root, first, last) / "middle.json"
    try:
        saved = read(path)
        identity(saved, cfg)
        if saved.get("state") != "complete" or saved.get("requested_pages") != list(range(first, last + 1)):
            raise ValueError("incomplete or shifted OCR checkpoint")
        if not isinstance(saved.get("revision"), str) or not saved["revision"]:
            raise ValueError("missing OCR revision")
        validate_middle(saved["middle_json"], cfg, first, last, result_cls)
        if saved.get("asset_manifest") is not None and saved.get("asset_manifest") != asset_manifest(saved["middle_json"]):
            raise ValueError("OCR asset manifest does not match MiddleJson")
        for relative in saved.get("asset_files", []):
            path_value = Path(relative)
            if path_value.is_absolute() or not (Path(root) / path_value).is_file():
                raise ValueError("OCR asset file is missing")
        if saved["pages"] != plain_pages(saved["middle_json"], first):
            raise ValueError("plain text does not match the MiddleJson tree")
        review.require_coverage(review.pages_of(saved), range(first, last + 1))
        return saved
    except IdentityMismatch:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _attempt_store(root):
    path = Path(root) / "worker-attempts.json"
    if not path.exists():
        return {}, path
    try:
        value = read(path)
        return (value if isinstance(value, dict) else {}), path
    except (OSError, ValueError, TypeError):
        raise RuntimeError("worker-attempts.json is damaged; preserve it and inspect before retrying")


def retry(root, stage, first, last, operation):
    key = f"{stage}:{first}-{last}"
    for _ in range(3):  # Initial attempt + at most two total retries across resumes.
        attempts, path = _attempt_store(root)
        attempt = int(attempts.get(key, 0)) + 1
        if attempt > 3:
            raise RuntimeError(f"{stage} chunk {first}-{last} already used three attempts")
        attempts[key] = attempt
        atomic_write(path, attempts)
        start = time.monotonic()
        review.record_metric(root, f"{stage}_chunk_started", first=first, last=last, attempt=attempt)
        try:
            value = operation(attempt)
            if isinstance(value, dict) and "attempts" in value:
                value["attempts"] = attempt
            review.record_metric(root, f"{stage}_chunk_finished", first=first, last=last,
                                 attempt=attempt, elapsed_seconds=round(time.monotonic() - start, 3))
            return value
        except IdentityMismatch:
            raise
        except Exception as exc:
            review.record_metric(root, f"{stage}_chunk_failed", first=first, last=last,
                                 attempt=attempt, error=str(exc))
            if attempt == 3:
                raise RuntimeError(f"{stage} chunk {first}-{last} failed after 3 attempts: {exc}") from exc


def recognize_chunk(root, cfg, first, last, parser, result_cls=None):
    def attempt(number):
        verify_source(cfg)
        result = parser.parse(Path(cfg["source"]["path"]), page_range=f"{first}-{last}")
        # ParseResult.to_json()/to_dict() deliberately omit PDF image_base64.
        middle = result.middle_json.model_dump(mode="json", by_alias=True)
        validate_middle(middle, cfg, first, last, result_cls)
        pages = plain_pages(middle, first)
        review.require_coverage(pages, range(first, last + 1))
        assets = preserve_assets(root, cfg, first, last, middle)
        verify_source(cfg)
        attempts, _ = _attempt_store(root)
        saved = {"config": cfg, "state": "complete", "requested_pages": list(range(first, last + 1)),
                 "revision": uuid.uuid4().hex, "attempts": attempts.get(f"ocr:{first}-{last}", number), "pages": pages,
                 "asset_manifest": asset_manifest(middle), "asset_files": assets["files"],
                 "middle_json": middle}
        atomic_write(chunk_dir(root, first, last) / "middle.json", saved)
        return saved
    return retry(root, "ocr", first, last, attempt)


def status(root, stage, cfg, state, chunks, error=None):
    record = {"workflow": WORKFLOW, "config": cfg, "state": state,
              "page_count": cfg["page_count"], "chunks": chunks}
    if error:
        record["error"] = str(error)
    atomic_write(Path(root) / f"{stage}-status.json", record)


def chunk_record(saved):
    return {"state": "complete", "revision": saved["revision"], "attempts": saved["attempts"]}


def format_initializer():
    # spawn, not fork: no inherited inference runtime or model allocation.
    # Module-level imports are stdlib-only, including ocr_review/ocr_layout.
    for key in THREAD_ENV:
        os.environ[key] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.nice(10)


def load_format(root, cfg, first, last, ocr):
    try:
        saved = read(chunk_dir(root, first, last) / "format.json")
        identity(saved, cfg)
        if (saved.get("state") != "complete" or saved.get("revision") != ocr["revision"]
                or saved.get("requested_pages") != list(range(first, last + 1))):
            return None
        review.require_coverage(review.pages_of(saved), range(first, last + 1))
        return saved
    except IdentityMismatch:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        return None


def format_chunk(root, cfg, first, last, result_cls=None):
    root = Path(root)
    verify_source(cfg)
    ocr = load_ocr(root, cfg, first, last, result_cls)
    if ocr is None:
        raise ValueError(f"missing/corrupt OCR chunk {first}-{last}; resume --stage ocr first")
    saved = load_format(root, cfg, first, last, ocr)
    if saved is not None:
        review.record_metric(root, "format_chunk_reused", first=first, last=last)
        return chunk_record(saved)

    def attempt(number):
        result = validate_middle(ocr["middle_json"], cfg, first, last, result_cls)
        pages = []
        for page_number, page in zip(range(first, last + 1), result.pages):
            one = copy.copy(result)
            one.middle_json = result.middle_json.model_copy(update={"pages": [page]})
            # FULL retains headers/footers too; normal rendering retains images/tables.
            pages.append({"page": page_number, "text": one.markdown(add_markers=False)})
        review.require_coverage(review.pages_of({"pages": pages}), range(first, last + 1))
        verify_source(cfg)
        attempts, _ = _attempt_store(root)
        record = {"config": cfg, "state": "complete", "revision": ocr["revision"],
                  "requested_pages": list(range(first, last + 1)),
                  "attempts": attempts.get(f"format:{first}-{last}", number), "pages": pages}
        atomic_write(chunk_dir(root, first, last) / "format.json", record)
        return chunk_record(record)
    return retry(root, "format", first, last, attempt)


def finalize_format(root, cfg, failures=None, result_cls=None):
    """Executed in the same low-priority worker; publish status last."""
    root = Path(root)
    chunks, pages, middle_pages, asset_files = {}, [], [], []
    errors = dict(failures or {})
    try:
        verify_source(cfg)
        for first, last in ranges(cfg):
            key = f"{first}-{last}"
            ocr = load_ocr(root, cfg, first, last, result_cls)
            saved = load_format(root, cfg, first, last, ocr) if ocr else None
            if saved is None:
                chunks[key] = {"state": "failed", "error": errors.get(key, "missing/corrupt checkpoint")}
                errors.setdefault(key, "missing/corrupt checkpoint")
                continue
            chunks[key] = chunk_record(saved)
            pages.extend(saved["pages"])
            asset_files.extend(ocr.get("asset_files", []))
            middle_pages.extend(dict(page, page_idx=first - 1 + offset)
                                for offset, page in enumerate(ocr["middle_json"]["pages"]))
        if errors:
            raise ValueError(str(errors))
        review.require_coverage(pages, range(1, cfg["page_count"] + 1))
        layout = review.build_mineru_layout(pages, {"pages": middle_pages})
        verify_source(cfg)
        atomic_write(root / "mineru.json", {"pages": pages})
        atomic_write(root / "mineru.md", review.markdown(pages, include_page_markers=True), raw=True)
        atomic_write(root / "mineru-layout.json", layout)
        atomic_write(root / "mineru-assets.json", {"workflow": WORKFLOW,
                                                     "files": sorted(set(asset_files))})
        status(root, "format", cfg, "complete", chunks)
        review.record_metric(root, "format_worker_finished", state="complete")
    except Exception as exc:
        status(root, "format", cfg, "failed", chunks, exc)
        review.record_metric(root, "format_worker_finished", state="failed", error=str(exc))
        raise


def default_parser(cfg):
    from mineru.parser import MinerUParser
    return MinerUParser(tier=cfg["tier"], parse_mode="ocr")


def run(root, cfg, stage="all", *, parser_factory=default_parser, result_cls=None, pool_factory=None):
    """The parent owns OCR status; the child owns format status and publication."""
    root = Path(root)
    preflight(root, cfg)
    parser, pool, futures = None, None, []
    parser_uses = 0
    chunks, pages, ocr_errors, format_errors = {}, [], {}, {}
    started = time.monotonic()
    if stage != "ocr":
        factory = pool_factory or ProcessPoolExecutor
        pool = factory(max_workers=1, mp_context=multiprocessing.get_context("spawn"),
                       initializer=format_initializer)
    review.record_metric(root, "context_worker_started", stage=stage, pid=os.getpid())
    try:
        for first, last in ranges(cfg):
            key = f"{first}-{last}"
            saved = load_ocr(root, cfg, first, last, result_cls)
            if stage != "format":
                try:
                    if saved is None:
                        status(root, "ocr", cfg, "running", chunks)
                        if parser is None:
                            init_started = time.monotonic()
                            review.record_metric(root, "ocr_parser_initialization_started",
                                                 parser_use_count=parser_uses)
                            parser = parser_factory(cfg)
                            review.record_metric(
                                root, "ocr_parser_initialization_finished",
                                elapsed_seconds=round(time.monotonic() - init_started, 3),
                                parser_use_count=parser_uses,
                                model_load_observed=False,
                                model_load_boundary="inside_parser_factory",
                            )
                        parser_reused = parser_uses > 0
                        parse_started = time.monotonic()
                        review.record_metric(root, "ocr_parser_chunk_started", first=first, last=last,
                                             parser_call=parser_uses + 1, parser_reused=parser_reused)
                        try:
                            saved = recognize_chunk(root, cfg, first, last, parser, result_cls)
                        except Exception as exc:
                            review.record_metric(
                                root, "ocr_parser_chunk_finished", first=first, last=last,
                                parser_call=parser_uses + 1, parser_reused=parser_reused,
                                state="failed", elapsed_seconds=round(time.monotonic() - parse_started, 3),
                                error=str(exc),
                            )
                            raise
                        review.record_metric(
                            root, "ocr_parser_chunk_finished", first=first, last=last,
                            parser_call=parser_uses + 1, parser_reused=parser_reused,
                            state="complete", elapsed_seconds=round(time.monotonic() - parse_started, 3),
                            attempts=saved.get("attempts"),
                        )
                        parser_uses += 1
                    else:
                        review.record_metric(root, "ocr_chunk_reused", first=first, last=last)
                    chunks[key] = chunk_record(saved)
                    pages.extend(saved["pages"])
                except IdentityMismatch:
                    raise
                except Exception as exc:
                    ocr_errors[key] = str(exc)
                    chunks[key] = {"state": "failed", "error": str(exc)}
            if pool is not None:
                # Paths transfer the immutable full checkpoint without copying base64
                # through a process pipe. submit never waits for Markdown to finish.
                try:
                    futures.append((key, pool.submit(format_chunk, root, cfg, first, last)))
                except Exception as exc:
                    format_errors[key] = str(exc)
        if parser is not None:
            parser.close()
            parser = None
        if stage != "format":
            verify_source(cfg)
            if not ocr_errors:
                review.require_coverage(pages, range(1, cfg["page_count"] + 1))
                atomic_write(root / "mineru-text.json", {"workflow": WORKFLOW, "mode": "ocr",
                             "text_format": "plain", "pages": pages})
            status(root, "ocr", cfg, "failed" if ocr_errors else "complete", chunks,
                   str(ocr_errors) if ocr_errors else None)
            review.record_metric(root, "ocr_worker_finished", state="failed" if ocr_errors else "complete",
                                 elapsed_seconds=round(time.monotonic() - started, 3))
        if pool is not None:
            format_chunks = {}
            for key, future in futures:
                try:
                    format_chunks[key] = future.result()
                except Exception as exc:
                    format_errors[key] = str(exc)
                    format_chunks[key] = {"state": "failed", "error": str(exc)}
            try:
                pool.submit(finalize_format, root, cfg, format_errors).result()
            except Exception as exc:
                # Broken worker fallback, after all submitted chunk jobs settled.
                # Never touch the independent successful OCR status here.
                status(root, "format", cfg, "failed", format_chunks, exc)
                raise
        if ocr_errors:
            raise RuntimeError(str(ocr_errors))
    except BaseException as exc:
        if stage != "format" and not (root / "ocr-status.json").exists():
            status(root, "ocr", cfg, "failed", chunks, exc)
        elif stage != "format":
            previous = read(root / "ocr-status.json")
            if previous.get("state") != "complete":
                status(root, "ocr", cfg, "failed", chunks, exc)
        raise
    finally:
        try:
            if parser is not None:
                parser.close()
        finally:
            if pool is not None:
                pool.shutdown(wait=True)


@contextmanager
def run_lock(root):
    with (root / ".context-worker.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another context worker is using this run") from exc
        yield


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--stage", choices=("all", "ocr", "format"), default="all")
    args = ap.parse_args(argv)
    try:
        root = args.run.resolve(strict=True)
        cfg, manifest = configuration(root)
        # Verify the currently executing interpreter; never silently fall back.
        interpreter, _ = review.find_mineru_python(sys.executable)
        configured = manifest.get("mineru_python")
        if configured and os.path.abspath(configured) != os.path.abspath(interpreter):
            raise ValueError(f"run this script with manifest mineru_python: {configured}")
        home = review.find_mineru_home(interpreter, manifest.get("mineru_home"))
        if home:
            os.environ["MINERU_HOME"] = home
        with run_lock(root):
            run(root, cfg, args.stage)
        return 0
    except Exception as exc:
        print(f"context OCR worker failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
