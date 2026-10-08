"""Versioned, local span records for AM-Link instrumentation (no model calls)."""
from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

VERSION = "amlink.observation.v1"
OPERATIONS = {"add", "extract", "store", "index", "search", "retrieve", "rerank", "context", "answer", "eval", "model"}
STATUSES = {"ok", "error", "skipped"}
RELATIONS = {"derived_from", "retrieved_from", "selected_from", "supports", "contradicts", "supersedes"}
BASE_KEYS = {"schema_version", "run_id", "dataset_pack_sha256", "trace_id", "span_id", "parent_span_id",
    "record_id", "task_id", "request_id", "operation", "name", "started_at", "ended_at", "duration_ms",
    "status", "attempt", "replay", "inputs", "outputs", "links", "candidates", "model", "error"}


def _string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_event(event: dict) -> None:
    """Fail closed on malformed instrumentation; unknown is represented by null."""
    if not isinstance(event, dict) or set(event) != BASE_KEYS or event.get("schema_version") != VERSION:
        raise ValueError("invalid observation event fields/version")
    for field in ("run_id", "trace_id", "span_id", "record_id", "request_id", "name"):
        if not _string(event[field]):
            raise ValueError(f"observation requires {field}")
    if not _sha(event["dataset_pack_sha256"]):
        raise ValueError("observation requires canonical pack SHA-256")
    for field in ("parent_span_id", "task_id"):
        if event[field] is not None and not _string(event[field]):
            raise ValueError(f"invalid {field}")
    if event["operation"] not in OPERATIONS or event["status"] not in STATUSES:
        raise ValueError("unknown operation/status")
    if type(event["attempt"]) is not int or event["attempt"] < 1 or event["replay"] not in {"none", "cached", "resumed"}:
        raise ValueError("invalid attempt/replay")
    if event["operation"] == "model" and (event["status"] == "skipped" or event["replay"] == "cached"):
        raise ValueError("model span must represent an actual invocation")
    if type(event["duration_ms"]) not in (int, float) or not math.isfinite(event["duration_ms"]) or event["duration_ms"] < 0:
        raise ValueError("invalid duration")
    if any(not _string(event[key]) for key in ("started_at", "ended_at")):
        raise ValueError("timestamps must be strings")
    dates = [datetime.fromisoformat(event[key]) for key in ("started_at", "ended_at")]
    if any(d.utcoffset() is None for d in dates) or dates[1] < dates[0]:
        raise ValueError("timestamps require timezone and chronological order")
    refs = set()
    if any(not isinstance(event[key], list) for key in ("inputs", "outputs", "links", "candidates")):
        raise ValueError("references, links and candidates must be lists")
    for ref in event["inputs"] + event["outputs"]:
        if not isinstance(ref, dict) or set(ref) != {"id", "kind", "artifact", "sha256", "locator"} or not all(_string(ref[k]) for k in ref):
            raise ValueError("invalid artifact reference")
        if ref["kind"] not in {"source", "memory", "query", "result", "context", "answer", "evaluation"} or not _sha(ref["sha256"]):
            raise ValueError("invalid reference kind/hash")
        artifact = PurePosixPath(ref["artifact"])
        if artifact.is_absolute() or ".." in artifact.parts or ":" in ref["artifact"] or "\\" in ref["artifact"]:
            raise ValueError("artifact must be a relative POSIX path")
        if ref["id"] in refs:
            raise ValueError("reference IDs must be unique within a span")
        refs.add(ref["id"])
    for link in event["links"]:
        if not isinstance(link, dict) or set(link) != {"from_id", "to_id", "relation"} or not all(_string(v) for v in link.values()) or link["relation"] not in RELATIONS or any(link[k] not in refs for k in ("from_id", "to_id")):
            raise ValueError("link requires declared input/output references")
    ranks = set()
    for candidate in event["candidates"]:
        if not isinstance(candidate, dict) or set(candidate) != {"ref_id", "rank", "score", "selected"} or not _string(candidate["ref_id"]) or candidate["ref_id"] not in refs:
            raise ValueError("candidate must reference declared artifact")
        rank, score = candidate["rank"], candidate["score"]
        if type(rank) is not int or rank < 1 or rank in ranks or type(candidate["selected"]) is not bool:
            raise ValueError("invalid candidate rank/selection")
        if score is not None and (type(score) not in (int, float) or not math.isfinite(score)):
            raise ValueError("invalid candidate score")
        ranks.add(rank)
    model = event["model"]
    if model is not None:
        if not isinstance(model, dict) or event["operation"] != "model" or set(model) != {"provider", "name", "input_tokens", "output_tokens", "cached_tokens", "cost_usd", "usage_source"}:
            raise ValueError("usage belongs to one actual model span")
        if not all(_string(model[k]) for k in ("provider", "name", "usage_source")):
            raise ValueError("model identity and usage source required")
        for field in ("input_tokens", "output_tokens", "cached_tokens"):
            if model[field] is not None and (type(model[field]) is not int or model[field] < 0):
                raise ValueError("tokens must be nonnegative integers or null")
        cost = model["cost_usd"]
        if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
            raise ValueError("cost must be nonnegative or null")
    if event["status"] == "error":
        error = event["error"]
        if not isinstance(error, dict) or set(error) != {"code", "retryable"} or not _string(error["code"]) or type(error["retryable"]) is not bool:
            raise ValueError("failed span requires explicit error code/retryability")
    elif event["error"] is not None:
        raise ValueError("successful/skipped span cannot have error")


class ObservationRecorder:
    """One recorder per run; callers supply stable record/task/request identities."""

    def __init__(self, path: Path, *, run_id: str, dataset_pack_sha256: str, append: bool = False):
        if not _string(run_id) or not _sha(dataset_pack_sha256):
            raise ValueError("recorder requires run ID and pack digest")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.run_id, self.pack_hash = path, run_id, dataset_pack_sha256
        if append:
            if not path.is_file():
                raise FileNotFoundError("append requires an existing observation stream")
            seen = set()
            with path.open("r", encoding="utf-8") as existing:
                for line in existing:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    validate_event(event)
                    if event["run_id"] != run_id or event["dataset_pack_sha256"] != dataset_pack_sha256:
                        raise ValueError("cannot append to a different run/pack")
                    if event["span_id"] in seen:
                        raise ValueError("existing observation stream has duplicate span IDs")
                    seen.add(event["span_id"])
            self._file = path.open("a", encoding="utf-8", newline="\n")
        else:
            self._file = path.open("x", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()

    @contextmanager
    def span(self, operation: str, *, name: str, record_id: str, request_id: str,
        task_id: str | None = None, trace_id: str | None = None, parent: dict | None = None,
        attempt: int = 1, replay: str = "none"):
        if parent and (parent["run_id"] != self.run_id or parent["dataset_pack_sha256"] != self.pack_hash or parent["record_id"] != record_id or parent["task_id"] != task_id or parent["request_id"] != request_id):
            raise ValueError("child must share parent run/pack/record/task/request")
        if parent and trace_id and trace_id != parent["trace_id"]:
            raise ValueError("child trace differs from parent")
        started = time.perf_counter()
        now = lambda: datetime.now(timezone.utc).isoformat()
        event = {"schema_version": VERSION, "run_id": self.run_id, "dataset_pack_sha256": self.pack_hash,
            "trace_id": parent["trace_id"] if parent else trace_id or uuid.uuid4().hex,
            "span_id": uuid.uuid4().hex, "parent_span_id": parent["span_id"] if parent else None,
            "record_id": record_id, "task_id": task_id, "request_id": request_id, "operation": operation,
            "name": name, "started_at": now(), "ended_at": now(), "duration_ms": 0,
            "status": "ok", "attempt": attempt, "replay": replay,
            "inputs": [], "outputs": [], "links": [], "candidates": [], "model": None, "error": None}
        validate_event(event)
        try:
            yield event
        except BaseException as error:
            event["status"] = "error"
            # Do not leak exception messages, which may contain credentials or inputs.
            if event["error"] is None:
                event["error"] = {"code": type(error).__name__, "retryable": False}
            raise
        finally:
            event["ended_at"] = now()
            event["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            validate_event(event)
            with self._lock:
                self._file.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
