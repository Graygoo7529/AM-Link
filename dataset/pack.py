from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PACK_SCHEMA_VERSION = 1


def validate_pack(value: Any) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != PACK_SCHEMA_VERSION:
        raise ValueError(f"dataset pack schema_version must be {PACK_SCHEMA_VERSION}")
    dataset = value.get("dataset")
    if not isinstance(dataset, dict) or not _text(dataset.get("id")):
        raise ValueError("dataset pack requires dataset.id")
    preparation = value.get("preparation")
    if not isinstance(preparation, dict) or not isinstance(preparation.get("selection"), dict):
        raise ValueError("dataset pack requires preparation.selection")
    if not isinstance(preparation.get("input"), dict) or not _text(preparation["input"].get("sha256")):
        raise ValueError("dataset pack requires preparation.input.sha256")
    records = value.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("dataset pack requires at least one record")

    record_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not _text(record.get("id")):
            raise ValueError("each dataset record requires a non-empty id")
        if record["id"] in record_ids:
            raise ValueError(f"duplicate dataset record id: {record['id']}")
        record_ids.add(record["id"])
        sessions = record.get("sessions")
        tasks = record.get("tasks")
        if not isinstance(sessions, list) or not isinstance(tasks, list):
            raise ValueError(f"record {record['id']} requires sessions and tasks lists")

        session_ids: set[str] = set()
        turn_ids: set[str] = set()
        for session in sessions:
            if not isinstance(session, dict) or not _text(session.get("id")):
                raise ValueError(f"record {record['id']} has a session without an id")
            if session["id"] in session_ids:
                raise ValueError(f"duplicate session id in record {record['id']}")
            session_ids.add(session["id"])
            turns = session.get("turns")
            if not isinstance(turns, list):
                raise ValueError(f"session {session['id']} requires a turns list")
            for turn in turns:
                if not isinstance(turn, dict) or not _text(turn.get("id")):
                    raise ValueError(f"session {session['id']} has a turn without an id")
                if turn["id"] in turn_ids:
                    raise ValueError(f"duplicate turn id in record {record['id']}")
                if not _text(turn.get("content")):
                    raise ValueError(f"turn {turn['id']} requires non-empty content")
                turn_ids.add(turn["id"])

        task_ids: set[str] = set()
        for task in tasks:
            if not isinstance(task, dict) or not _text(task.get("id")):
                raise ValueError(f"record {record['id']} has a task without an id")
            if task["id"] in task_ids:
                raise ValueError(f"duplicate task id in record {record['id']}")
            task_ids.add(task["id"])
            if not isinstance(task.get("input"), dict):
                raise ValueError(f"task {task['id']} requires an input object")
            if not isinstance(task.get("annotations", {}), dict):
                raise ValueError(f"task {task['id']} annotations must be an object")


def load_pack(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_pack(value)
    return value


def write_pack(path: Path, value: dict[str, Any]) -> None:
    validate_pack(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
