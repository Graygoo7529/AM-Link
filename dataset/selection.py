"""Explicit, source-preserving experiment slices; never synthesize history from gold."""
from __future__ import annotations

import copy
import hashlib
import json

from dataset.pack import validate_pack


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def select_pack(pack, *, record_ids=None, task_ids=None, scope="full", turn_ids=None,
                radius=1, before=None, allow_partial=False, case_id=None, dataset_key=None):
    """full = all history in selected base records; anchors/window are diagnostic cuts.

    A cutoff is exclusive, in milliseconds, and rejects undated turns rather than
    guessing. IDs and source order survive. Missing gold is either rejected or
    explicitly disables retrieval grading for that task, without deleting labels.
    """
    validate_pack(pack)
    if scope not in {"full", "anchors", "window"} or type(radius) is not int or radius < 0:
        raise ValueError("invalid scope/radius")
    if before is not None and (type(before) is not int or before < 0):
        raise ValueError("before must be a nonnegative millisecond timestamp")
    selected_ids = set(record_ids or [r["id"] for r in pack["records"]])
    if selected_ids - {r["id"] for r in pack["records"]}:
        raise ValueError("unknown record ID")
    records = copy.deepcopy([r for r in pack["records"] if r["id"] in selected_ids])
    if (task_ids or scope != "full") and len(records) != 1:
        raise ValueError("task/turn selection requires exactly one record")
    anchors = set(turn_ids or [])
    if scope != "full" and not anchors:
        raise ValueError("anchors/window requires explicit source turn IDs")
    if anchors and scope == "full":
        raise ValueError("turn IDs apply only to anchors/window")
    missing = {}
    original_counts = {"records": len(records), "tasks": sum(len(r["tasks"]) for r in records),
        "turns": sum(len(s["turns"]) for r in records for s in r["sessions"])}
    for record in records:
        if task_ids:
            if set(task_ids) - {t["id"] for t in record["tasks"]}:
                raise ValueError("unknown task ID")
            record["tasks"] = [t for t in record["tasks"] if t["id"] in task_ids]
        all_ids = {t["id"] for s in record["sessions"] for t in s["turns"]}
        if anchors - all_ids:
            raise ValueError("unknown source turn ID")
        sessions = []
        for session in record["sessions"]:
            turns = session["turns"]
            keep = set(range(len(turns))) if scope == "full" else set()
            for i, turn in enumerate(turns):
                if turn["id"] in anchors:
                    distance = radius if scope == "window" else 0
                    keep.update(range(max(0, i-distance), min(len(turns), i+distance+1)))
            selected = []
            for i, turn in enumerate(turns):
                if i not in keep:
                    continue
                if before is not None:
                    timestamp = turn.get("timestamp", session.get("timestamp"))
                    if type(timestamp) is not int:
                        raise ValueError("cutoff cannot be applied to an undated turn")
                    if timestamp >= before:
                        continue
                selected.append(turn)
            if selected:
                sessions.append({**session, "turns": selected})
        record["sessions"] = sessions
        kept_ids = {t["id"] for s in sessions for t in s["turns"]}
        for task in record["tasks"]:
            absent = sorted(set(task.get("annotations", {}).get("evidence_turn_ids", [])) - kept_ids)
            if absent:
                if not allow_partial:
                    raise ValueError(f"slice excludes annotated evidence for {record['id']}:{task['id']}; use allow_partial explicitly")
                missing[f"{record['id']}:{task['id']}"] = absent
                task.setdefault("attributes", {})["retrieval_grading_disabled"] = "slice excludes annotated evidence"
        if case_id:
            record.setdefault("attributes", {}).update(case_id=case_id, dataset_key=dataset_key)
    result = copy.deepcopy(pack)
    result["records"] = records
    result["preparation"]["selection"] = {"base_pack_sha256": canonical_hash(pack),
        "base_selection": copy.deepcopy(pack["preparation"]["selection"]),
        "record_ids": [r["id"] for r in records], "task_ids": task_ids,
        "scope": scope, "anchor_turn_ids": sorted(anchors), "window_radius": radius if scope == "window" else None,
        "before_ms_exclusive": before, "allow_partial": allow_partial, "missing_evidence": missing,
        "case_id": case_id, "selection_assisted": scope != "full",
        "base_counts": original_counts, "selected_counts": {"records": len(records),
            "tasks": sum(len(r["tasks"]) for r in records),
            "turns": sum(len(s["turns"]) for r in records for s in r["sessions"])},
        "interpretation": "full means all history in selected base records, not the entire upstream dataset; anchors/window are curated diagnostic selections"}
    validate_pack(result)
    return result
