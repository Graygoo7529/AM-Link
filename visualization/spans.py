"""Join explicit internal observations to the API trace, preserving unknowns."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from benchmark.observability import VERSION, validate_event
from visualization.sources import excerpt, file_digest


def read_memory_snapshot(directory: Path, ref: dict) -> dict:
    """Explicit Mem0 study snapshot projection; never expose arbitrary response fields."""
    path = (directory / ref["artifact"]).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError("memory snapshot must exist inside run directory")
    if path.stat().st_size > 1_000_000 or file_digest(path) != ref["sha256"]:
        raise ValueError("memory snapshot size/hash mismatch")
    data = json.loads(path.read_text(encoding="utf-8"))
    memories = data["memories"]["results"]
    changes = data["response"]["results"]
    return {"artifact": ref["artifact"], "sha256": ref["sha256"],
        "count": len(memories), "memories": [{"id": m["id"], "content": excerpt(m["memory"], 2000)} for m in memories[:20]],
        "changes": [{k: c[k] for k in ("id", "event") if k in c} for c in changes[:20]]}


def attach_spans(run: dict, path: Path, request_scope: dict) -> None:
    source = path / "observability.jsonl"
    run["observability"] = {"status": "missing", "span_count": None, "orphan_ids": [],
        "model_calls": None, "cost_usd": None, "capture_declared_complete": False}
    for query in run["queries"]:
        query["spans"] = []
    if not source.exists():
        return
    events = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id, refs = {}, {}
    for event in events:
        validate_event(event)
        if event["run_id"] != run["run_id"] or event["dataset_pack_sha256"] != run["dataset_pack_sha256"]:
            raise ValueError("internal observation run/pack mismatch")
        if event["span_id"] in by_id:
            raise ValueError("duplicate internal span ID")
        scope = request_scope.get(event["request_id"])
        if scope is None or scope[:2] != (event["record_id"], event["task_id"]):
            raise ValueError("internal observation request/record/task mismatch")
        if event["parent_span_id"] is None and event["operation"] not in scope[2]:
            raise ValueError("internal root operation mismatches API request")
        by_id[event["span_id"]] = event
        for ref in event["inputs"] + event["outputs"]:
            if ref["id"] in refs and refs[ref["id"]] != ref:
                raise ValueError("same artifact ID has inconsistent references")
            refs[ref["id"]] = ref
    orphans, roots = [], set()
    for event in events:
        parent_id = event["parent_span_id"]
        if parent_id is None:
            roots.add((event["request_id"], event["operation"]))
            continue
        if parent_id not in by_id:
            orphans.append(event["span_id"])
            continue
        parent = by_id[parent_id]
        if any(event[k] != parent[k] for k in ("trace_id", "record_id", "task_id", "request_id")):
            raise ValueError("internal parent identity mismatch")
        if datetime.fromisoformat(event["started_at"]) < datetime.fromisoformat(parent["started_at"]) or datetime.fromisoformat(event["ended_at"]) > datetime.fromisoformat(parent["ended_at"]):
            raise ValueError("internal child outside parent time bounds")
        ancestors = {event["span_id"]}
        while parent_id in by_id:
            if parent_id in ancestors:
                raise ValueError("cycle in internal span graph")
            if event["operation"] == "model" and by_id[parent_id]["replay"] == "cached":
                raise ValueError("cached replay cannot contain model invocations")
            ancestors.add(parent_id)
            parent_id = by_id[parent_id]["parent_span_id"]
    # Presence of a well-formed file never proves that all calls were captured.
    # A separate explicit collection declaration is required before reporting zero.
    complete = False
    meta_path = path / "observability.meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if set(meta) != {"schema_version", "run_id", "dataset_pack_sha256", "model_capture_complete", "producer"} or meta["schema_version"] != VERSION or meta["run_id"] != run["run_id"] or meta["dataset_pack_sha256"] != run["dataset_pack_sha256"] or type(meta["model_capture_complete"]) is not bool or not isinstance(meta["producer"], str) or not meta["producer"].strip():
            raise ValueError("invalid internal collection declaration")
        complete = meta["model_capture_complete"]
        if complete and (orphans or any((request, "add" if scope[1] is None else "search") not in roots for request, scope in request_scope.items())):
            raise ValueError("complete collection declaration lacks API root spans")
        run["artifacts"][meta_path.name] = file_digest(meta_path)
    models = [e for e in events if e["operation"] == "model"]
    costs = [e["model"]["cost_usd"] if e["model"] else None for e in models]
    run["observability"] = {"status": "incomplete" if orphans else "linked", "span_count": len(events),
        "orphan_ids": orphans, "observed_model_calls": len(models),
        "model_calls": len(models) if complete else None,
        "cost_usd": sum(costs) if complete and all(c is not None for c in costs) else None,
        "capture_declared_complete": complete}
    run["artifacts"][source.name] = file_digest(source)
    ordered = sorted(events, key=lambda e: (datetime.fromisoformat(e["started_at"]), e["span_id"]))
    for query in run["queries"]:
        requests = {query["search_id"]} | {a["id"] for a in query["adds"]}
        query["spans"] = [e for e in ordered if e["request_id"] in requests]
        if run["system"].get("target") == "mem0-research":
            for add in query["adds"]:
                outputs = [ref for e in query["spans"] if e["operation"] == "add" and e["request_id"] == add["id"]
                    for ref in e["outputs"] if ref["kind"] == "memory"]
                if len(outputs) == 1:
                    add["memory_snapshot"] = read_memory_snapshot(path, outputs[0])
