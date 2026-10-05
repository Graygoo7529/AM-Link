"""Prepare the paired Chinese PerLTQA release without mixing QA into memory."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from dataset.prepare import _dataset_pack, sha256_file, source_entry


def _read_verified(path: Path) -> tuple[Any, dict[str, Any]]:
    digest = sha256_file(path)
    receipt_path = path.with_suffix(path.suffix + ".receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
    if receipt and receipt.get("sha256") != digest:
        raise ValueError(f"source file no longer matches receipt: {path.name}")
    return json.loads(path.read_text(encoding="utf-8")), {
        "file": path.name, "sha256": digest, "acquisition": receipt,
    }


def build_perltqa(
    *, path: Path, qa_path: Path, character_names: list[str] | None = None,
    character_limit: int | None = None, task_limit: int | None = None,
) -> dict[str, Any]:
    """Use complete character memories, with source-document retrieval labels.

    These are author-supplied memory documents, not chronological Add sessions.
    Profile/relationship/event/dialogue objects retain their original fields.
    QA reference IDs are checked; unverified anchor offsets stay annotations.
    """
    for label, limit in (("character-limit", character_limit), ("task-limit", task_limit)):
        if limit is not None and limit < 1:
            raise ValueError(f"{label} must be positive")
    memory_rows, memory_input = _read_verified(path)
    qa_rows, qa_input = _read_verified(qa_path)
    by_name = {}
    for row_index, row in enumerate(memory_rows):
        name = row["profile"]["Protagonist"]
        if name in by_name:
            raise ValueError(f"duplicate character: {name}")
        by_name[name] = (row_index, row)
    qa_by_name = {}
    for row in qa_rows:
        for name, sections in row.items():
            if name in qa_by_name:
                raise ValueError(f"duplicate QA character: {name}")
            qa_by_name[name] = sections
    names = character_names or list(qa_by_name)
    if len(names) != len(set(names)):
        raise ValueError("character names must be unique")
    if set(names) - (by_name.keys() & qa_by_name.keys()):
        raise ValueError("selected character missing memory or QA")
    if character_limit is not None:
        if character_names and len(names) > character_limit:
            raise ValueError("character-limit cannot omit requested names")
        names = names[:character_limit]
    records = []
    selected_tasks = 0
    for name in names:
        row_index, row = by_name[name]
        sessions = []
        available = set()
        for category in ("profile", "profile_description", "social_relationship", "events", "dialogues"):
            values = row.get(category, {})
            if category == "profile_description":
                values = {"description": values} if values else {}
            turns = []
            for source_id, value in values.items():
                turn_id = f"{category}:{source_id}"
                # Identity and section labels are part of the source projection.
                # The envelope is user-role input to the local text environment,
                # not an assertion that the subject spoke this whole document.
                content = json.dumps({"subject": name, "section": category,
                    "source_id": source_id, "value": value}, ensure_ascii=False)
                turns.append({"id": turn_id, "role": "user", "content": content,
                    "attributes": {"source_unit": "memory_document", "category": category,
                        "source_pointer": f"/{row_index}/{category}" if category == "profile_description"
                        else f"/{row_index}/{category}/{str(source_id).replace('~', '~0').replace('/', '~1')}"}})
                available.add(turn_id)
            if turns:
                sessions.append({"id": category, "turns": turns})
        tasks = []
        excluded = []
        for category, groups in qa_by_name[name].items():
            groups = {"fields": groups} if isinstance(groups, list) else groups
            for group_id, questions in groups.items():
                for index, question in enumerate(questions):
                    task_id = f"{category}:{group_id}:{index}"
                    raw_ref = question["Reference Memory"]
                    refs = [raw_ref] if category == "profile" else ast.literal_eval(raw_ref)
                    if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
                        raise ValueError(f"invalid reference list: {task_id}")
                    evidence = list(dict.fromkeys(f"{category}:{ref}" for ref in refs))
                    missing = sorted(set(evidence) - available)
                    if not evidence or missing:
                        excluded.append({"task_id": task_id, "reason": "invalid_source_reference",
                            "missing_turn_ids": missing})
                        continue
                    if task_limit is not None and selected_tasks >= task_limit:
                        continue
                    tasks.append({"id": task_id, "kind": "question_answering",
                        "input": {"text": question["Question"]},
                        "annotations": {"answer": question["Answer"], "evidence_turn_ids": evidence,
                            "reference_memory": raw_ref, "memory_anchors": question.get("Memory Anchors", []),
                            "evidence_granularity": "source_memory_document", "anchor_offsets_verified": False},
                        "attributes": {"category": category}})
                    selected_tasks += 1
        records.append({"id": f"character-{row_index}", "group_id": f"perltqa:character-{row_index}",
            "attributes": {"subject": name, "history_kind": "author_memory_documents",
                "order": "source sections; not chronological interactions"},
            "sessions": sessions, "tasks": tasks, "excluded_tasks": excluded})
        if task_limit is not None and selected_tasks >= task_limit:
            break
    if not selected_tasks:
        raise ValueError("selected characters contain no usable tasks")
    pack = _dataset_pack(dataset_id="perltqa-zh", dataset=source_entry("perltqa-zh"), path=path,
        selection={"character_names": [r["attributes"]["subject"] for r in records],
            "character_limit": character_limit, "task_limit": task_limit}, records=records)
    pack["preparation"]["inputs"] = {"memory": memory_input, "qa": qa_input}
    pack["preparation"]["notes"] = [
        "Full author memory for selected characters; QA annotations are never Add input.",
        "Sections are source documents, not chronological sessions; timestamps remain in source content.",
        "Reference IDs verified; answer correctness and anchor character offsets are not certified.",
    ]
    return pack
