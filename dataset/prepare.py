from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import itertools
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from dataset.pack import PACK_SCHEMA_VERSION, write_pack


ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
CATALOG_PATH = ROOT / "catalog.json"
BUILDER_VERSION = 5
CHUNK_READ_SIZE = 1024 * 1024
SESSION_PATTERN = re.compile(r"^session_(\d+)$")
DIALOG_ID_PATTERN = re.compile(r"D:?(\d+):(\d+)", re.IGNORECASE)
CATEGORY_MAP = {
    1: "multi_hop",
    2: "temporal",
    3: "open_domain",
    4: "single_hop",
    5: "adversarial",
}


def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def source_path(dataset_id: str) -> Path:
    entry = source_entry(dataset_id)
    if entry.get("raw_relative_path"):
        return RAW_DIR / entry["raw_relative_path"]
    assets = entry.get("assets", [])
    if not assets:
        raise ValueError(f"dataset {dataset_id} has no local source asset")
    return RAW_DIR / assets[0]["path"]


def source_entry(dataset_id: str) -> dict[str, Any]:
    catalog = load_catalog()
    for section in ("datasets", "sources"):
        entry = catalog.get(section, {}).get(dataset_id)
        if entry is not None:
            return entry
    raise ValueError(f"unknown dataset: {dataset_id}")


def iter_json_array(path: Path) -> Iterator[Any]:
    """Stream array items with stdlib JSON decoding so large histories stay selectable."""
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ValueError(f"invalid JSONL on line {line_number}") from error
        return

    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as source:
        buffer = ""
        position = 0
        eof = False

        def fill() -> None:
            nonlocal buffer, position, eof
            buffer = buffer[position:]
            position = 0
            chunk = source.read(CHUNK_READ_SIZE)
            if chunk:
                buffer += chunk
            else:
                eof = True

        def next_non_whitespace() -> str:
            nonlocal position
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer):
                    return buffer[position]
                if eof:
                    return ""
                fill()

        if next_non_whitespace() != "[":
            raise ValueError("dataset must be a top-level JSON array")
        position += 1
        first = True
        while True:
            marker = next_non_whitespace()
            if marker == "]":
                position += 1
                if next_non_whitespace():
                    raise ValueError("unexpected content after JSON array")
                return
            if not first:
                if marker != ",":
                    raise ValueError("expected a comma between JSON records")
                position += 1
                if next_non_whitespace() in {"", "]", ","}:
                    raise ValueError("missing JSON record after comma")
            first = False
            while True:
                try:
                    record, position = decoder.raw_decode(buffer, position)
                    break
                except json.JSONDecodeError as error:
                    if eof:
                        raise ValueError("truncated or invalid JSON array") from error
                    fill()
            yield record


def build_locomo(
    *,
    path: Path,
    conversation_ids: list[str] | None,
    conversation_limit: int | None,
    session_limit: int | None,
    questions_per_category: int | None,
    categories: set[int] | None,
    dataset_id: str = "locomo",
) -> dict[str, Any]:
    if conversation_limit is not None and conversation_limit < 1:
        raise ValueError("conversation-limit must be positive")
    if session_limit is not None and session_limit < 1:
        raise ValueError("session-limit must be positive")
    if questions_per_category is not None and questions_per_category < 1:
        raise ValueError("questions-per-category must be positive")
    selected_categories = categories or set(CATEGORY_MAP)
    if not selected_categories or not selected_categories <= CATEGORY_MAP.keys():
        raise ValueError("category must be one of 1, 2, 3, 4, 5")
    requested_ids = set(conversation_ids or [])
    if len(requested_ids) != len(conversation_ids or []):
        raise ValueError("conversation-ids must be unique")

    raw_conversations = list(iter_json_array(path))
    if not all(isinstance(sample, dict) for sample in raw_conversations):
        raise ValueError("LoCoMo records must be JSON objects")
    if requested_ids:
        raw_conversations = [
            sample for sample in raw_conversations if sample.get("sample_id") in requested_ids
        ]
        found_ids = {sample.get("sample_id") for sample in raw_conversations}
        missing_ids = requested_ids - found_ids
        if missing_ids:
            raise ValueError(f"unknown conversation IDs: {', '.join(sorted(missing_ids))}")
    if conversation_limit is not None:
        raw_conversations = raw_conversations[:conversation_limit]
    if not raw_conversations:
        raise ValueError("no LoCoMo conversations selected")

    records = []
    for sample in raw_conversations:
        record = _locomo_record(
            sample,
            session_limit=session_limit,
            questions_per_category=questions_per_category,
            categories=selected_categories,
        )
        if record:
            records.append(record)
    if not records:
        raise ValueError("selected conversations produced no usable records")
    dataset = source_entry(dataset_id)
    return _dataset_pack(
        dataset_id=dataset_id,
        dataset=dataset,
        path=path,
        selection={
            "record_ids": [record["id"] for record in records],
            "conversation_limit": conversation_limit,
            "session_limit": session_limit,
            "questions_per_category": questions_per_category,
            "categories": sorted(selected_categories),
        },
        records=records,
    )


def _locomo_record(
    sample: dict[str, Any],
    *,
    session_limit: int | None,
    questions_per_category: int | None,
    categories: set[int],
) -> dict[str, Any] | None:
    sample_id = sample.get("sample_id")
    conversation = sample.get("conversation")
    if not isinstance(sample_id, str) or not isinstance(conversation, dict):
        raise ValueError("LoCoMo sample requires sample_id and conversation")
    speaker_a = str(conversation.get("speaker_a", ""))
    sessions = sorted(
        (
            (int(match.group(1)), key)
            for key in conversation
            if (match := SESSION_PATTERN.fullmatch(key))
        ),
        key=lambda item: item[0],
    )
    if session_limit is not None:
        sessions = sessions[:session_limit]
    if not sessions:
        return None

    included_turn_ids: set[str] = set()
    history = []
    for session_number, session_key in sessions:
        raw_turns = conversation.get(session_key)
        if not isinstance(raw_turns, list):
            raise ValueError(f"session {session_key} must be an array")
        timestamp = _parse_locomo_date(conversation.get(f"{session_key}_date_time"))
        turns = []
        for turn_index, turn in enumerate(raw_turns):
            if not isinstance(turn, dict):
                raise ValueError(f"conversation {sample_id} contains an invalid turn")
            dialog_id = _normal_dialog_id(turn.get("dia_id"))
            if dialog_id is None:
                raise ValueError(f"conversation {sample_id} contains an invalid dialog id")
            content = _turn_content(turn)
            included_turn_ids.add(dialog_id)
            turns.append(
                {
                    "id": dialog_id,
                    "speaker": turn.get("speaker"),
                    "timestamp": timestamp,
                    "content": content,
                }
            )
        history.append(
            {
                "id": str(session_number),
                "source_id": session_key,
                "timestamp": timestamp,
                "turns": turns,
            }
        )

    tasks = []
    excluded_tasks = []
    category_counts: Counter[int] = Counter()
    for qa_index, qa in enumerate(sample.get("qa", [])):
        if not isinstance(qa, dict):
            continue
        try:
            category = int(qa.get("category"))
        except (TypeError, ValueError):
            continue
        evidence_ids = _evidence_ids(qa.get("evidence", []))
        if category not in categories:
            continue
        if evidence_ids and not set(evidence_ids) <= included_turn_ids:
            excluded_tasks.append({
                "task_id": f"qa-{qa_index}", "reason": "evidence_outside_selected_history",
                "missing_turn_ids": sorted(set(evidence_ids) - included_turn_ids),
            })
            continue
        if questions_per_category is not None and category_counts[category] >= questions_per_category:
            continue
        question = qa.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        category_counts[category] += 1
        answer = qa.get("answer")
        tasks.append(
            {
                "id": f"qa-{qa_index}",
                "kind": "question_answering",
                "input": {"text": question},
                "annotations": {
                    "answer": answer,
                    "evidence_turn_ids": list(dict.fromkeys(evidence_ids)),
                },
                "attributes": {
                    "category_id": category,
                    "category": CATEGORY_MAP[category],
                },
            }
        )
    if not tasks:
        return None
    return {"id": sample_id, "participants": [speaker_a, conversation.get("speaker_b")],
        "sessions": history, "tasks": tasks, "excluded_tasks": excluded_tasks}


def build_longmemeval(
    *,
    path: Path,
    question_ids: list[str] | None,
    question_limit: int | None,
    session_limit: int | None,
    question_type: str | None,
    dataset_id: str = "longmemeval-s",
) -> dict[str, Any]:
    if question_limit is not None and question_limit < 1:
        raise ValueError("question-limit must be positive")
    if session_limit is not None and session_limit < 1:
        raise ValueError("session-limit must be positive")
    requested = set(question_ids or [])
    if len(requested) != len(question_ids or []):
        raise ValueError("question-ids must be unique")
    if requested and question_limit is not None and len(requested) > question_limit:
        raise ValueError("question-limit cannot be smaller than the number of requested question IDs")
    records = []
    found_ids: set[str] = set()
    for record in iter_json_array(path):
        if not isinstance(record, dict):
            raise ValueError("LongMemEval records must be JSON objects")
        question_id = record.get("question_id")
        if not isinstance(question_id, str):
            raise ValueError("LongMemEval record requires question_id")
        if requested and question_id not in requested:
            continue
        if question_type and record.get("question_type") != question_type:
            continue
        found_ids.add(question_id)
        record_pack = _longmemeval_record(
            record,
            session_limit=session_limit,
        )
        if record_pack:
            records.append(record_pack)
        requested_found = requested and requested <= found_ids
        if requested_found or (not requested and question_limit is not None and len(records) >= question_limit):
            break
    if requested:
        missing = requested - found_ids
        if missing:
            raise ValueError(f"question IDs not found in selected type/limit: {', '.join(sorted(missing))}")
    if not records:
        raise ValueError("selected questions produced no usable records")
    dataset = source_entry(dataset_id)
    return _dataset_pack(
        dataset_id=dataset_id,
        dataset=dataset,
        path=path,
        selection={
            "record_ids": [record["id"] for record in records],
            "question_limit": question_limit,
            "question_type": question_type,
            "session_limit": session_limit,
        },
        records=records,
    )


def _longmemeval_record(
    record: dict[str, Any],
    *,
    session_limit: int | None,
) -> dict[str, Any] | None:
    question_id = record["question_id"]
    session_ids = record.get("haystack_session_ids")
    sessions = record.get("haystack_sessions")
    dates = record.get("haystack_dates", [])
    answer_session_ids = record.get("answer_session_ids", [])
    if not isinstance(session_ids, list) or not isinstance(sessions, list) or len(session_ids) != len(sessions):
        raise ValueError(f"question {question_id} has mismatched history sessions")
    if not isinstance(answer_session_ids, list):
        raise ValueError(f"question {question_id} has invalid answer_session_ids")
    selected_sessions = list(zip(session_ids, sessions, strict=True))
    if session_limit is not None:
        selected_sessions = selected_sessions[:session_limit]
    included_ids = {identifier for identifier, _ in selected_sessions}
    if answer_session_ids and not set(answer_session_ids) <= included_ids:
        return None
    history = []
    evidence_turn_ids = []
    seen_targets: set[str] = set()
    used_session_ids: set[str] = set()
    for session_index, (session_id, turns) in enumerate(selected_sessions):
        if not isinstance(turns, list):
            raise ValueError(f"question {question_id} contains an invalid session")
        session_timestamp = _parse_timestamp(dates[session_index] if session_index < len(dates) else None)
        source_session_id = str(session_id)
        normalized_session_id = source_session_id
        suffix = 1
        while normalized_session_id in used_session_ids:
            suffix += 1
            normalized_session_id = f"{source_session_id}#{suffix}"
        used_session_ids.add(normalized_session_id)
        normalized_turns = []
        for turn_index, turn in enumerate(turns):
            if not isinstance(turn, dict):
                raise ValueError(f"question {question_id} contains an invalid turn")
            role = turn.get("role")
            content = turn.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
                raise ValueError(f"question {question_id} contains an invalid role/content")
            message_timestamp = _parse_timestamp(turn.get("timestamp")) or session_timestamp
            turn_id = f"{normalized_session_id}:{turn_index}"
            normalized_turns.append(
                {
                    "id": turn_id,
                    "speaker": role,
                    "role": role,
                    "timestamp": message_timestamp,
                    "content": content,
                }
            )
            if session_id in answer_session_ids and turn.get("has_answer"):
                signature = " ".join(content.casefold().split())
                if signature and signature not in seen_targets:
                    seen_targets.add(signature)
                    evidence_turn_ids.append(turn_id)
        history.append(
            {
                "id": normalized_session_id,
                "source_id": source_session_id,
                "timestamp": session_timestamp,
                "source_date": dates[session_index] if session_index < len(dates) else None,
                "timestamp_basis": "source calendar date; timezone absent treated as UTC for normalization",
                "turns": normalized_turns,
            }
        )
    question = record.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"question {question_id} has no question text")
    answer = record.get("answer")
    return {
        "id": question_id,
        "sessions": history,
        "tasks": [
            {
                "id": "question",
                "kind": "question_answering",
                "input": {"text": question},
                "annotations": {
                    "answer": answer,
                    "evidence_turn_ids": evidence_turn_ids,
                    "answer_session_ids": [str(value) for value in answer_session_ids],
                    # The author evaluator identifies abstention by _abs in the ID;
                    # these records still carry answer_session_ids from their source.
                    "is_answerable": "_abs" not in question_id and bool(answer_session_ids),
                },
                "attributes": {"question_type": record.get("question_type", "unknown")},
            }
        ],
    }


def build_context_tasks(
    *,
    dataset_id: str,
    path: Path,
    task_ids: list[str] | None,
    task_limit: int | None,
) -> dict[str, Any]:
    if task_limit is not None and task_limit < 1:
        raise ValueError("task-limit must be positive")
    requested = set(task_ids or [])
    if len(requested) != len(task_ids or []):
        raise ValueError("task-ids must be unique")
    if requested and task_limit is not None and len(requested) > task_limit:
        raise ValueError("task-limit cannot be smaller than the number of requested task IDs")
    entry = source_entry(dataset_id)
    if entry.get("pack_adapter") != "context-task-v1":
        raise ValueError(f"dataset {dataset_id} has no context-task pack adapter")
    records = []
    found_ids: set[str] = set()
    for index, row in enumerate(iter_json_array(path)):
        if not isinstance(row, dict):
            raise ValueError(f"{dataset_id} rows must be JSON objects")
        metadata = row.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        task_id = metadata.get("task_id", str(index))
        if not isinstance(task_id, str) or not task_id:
            task_id = str(index)
        if requested and task_id not in requested:
            continue
        found_ids.add(task_id)
        record = _context_task_record(row, task_id)
        if record is not None:
            records.append(record)
        if requested and requested <= found_ids:
            break
        if not requested and task_limit is not None and len(records) >= task_limit:
            break
    if requested:
        missing = requested - found_ids
        if missing:
            raise ValueError(f"task IDs not found: {', '.join(sorted(missing))}")
    if not records:
        raise ValueError("selected rows produced no usable task records")
    return _dataset_pack(
        dataset_id=dataset_id,
        dataset=entry,
        path=path,
        selection={"record_ids": [record["id"] for record in records], "task_limit": task_limit},
        records=records,
    )


def _context_task_record(row: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    instructions = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
    messages = [m for m in messages if not isinstance(m, dict) or m.get("role") != "system"]
    if not messages:
        raise ValueError(f"task {task_id} has no user messages")
    history_messages: list[dict[str, str]]
    question: str
    if len(messages) == 1 and isinstance(messages[0], dict):
        content = messages[0].get("content")
        if not isinstance(content, str) or "<|TASK|>" not in content:
            # Preserve the source structure when it does not declare the boundary.
            return {
                "id": task_id, "group_id": str(row.get("metadata", {}).get("context_id", task_id)), "sessions": [], "tasks": [{
                    "id": "task", "kind": "context_task",
                    "input": {"messages": row["messages"]},
                    "annotations": {"rubrics": row.get("rubrics", [])},
                    "attributes": {**row.get("metadata", {}), "context_task_boundary": "unseparated"},
                }],
            }
        history_text, question = content.split("<|TASK|>", 1)
        history_text = history_text.strip()
        question = question.strip()
        history_messages = [{"role": "user", "content": history_text}] if history_text else []
    else:
        normalized = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
                return None
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                return None
            normalized.append({"role": message["role"], "content": content})
        if normalized[-1]["role"] != "user":
            return None
        question = normalized[-1]["content"].strip()
        history_messages = normalized[:-1]
    if not question:
        return None

    metadata = row.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    rubrics = row.get("rubrics", [])
    return {
        "id": task_id,
        "group_id": str(metadata.get("context_id", task_id)),
        "sessions": [
            {
                "id": "context",
                "source_id": "messages",
                "turns": [
                    {"id": f"{task_id}:turn:{index}", **message}
                    for index, message in enumerate(history_messages)
                ],
            }
        ] if history_messages else [],
        "tasks": [
            {
                "id": str(metadata.get("task_id", "task")),
                "kind": "context_task",
                "input": {"text": question, "instructions": instructions},
                "annotations": {"rubrics": rubrics if isinstance(rubrics, list) else []},
                "attributes": metadata,
            }
        ],
    }


def build_tasks(*, dataset_id: str, path: Path, task_limit: int | None, task_ids: list[str] | None = None) -> dict[str, Any]:
    """Read source-specific task data without inventing unavailable history."""
    if task_limit is not None and task_limit < 1:
        raise ValueError("task-limit must be positive")
    requested = set(task_ids or [])
    if len(requested) != len(task_ids or []):
        raise ValueError("task-ids must be unique")
    if requested and task_limit is not None and len(requested) > task_limit:
        raise ValueError("task-limit cannot be smaller than requested task IDs")
    found = set()
    records = []
    selected = 0
    for index, row in enumerate(iter_rows(path)):
        if dataset_id == "scriptmem":
            record = {
                "id": row["qa_id"], "group_id": row["conversation_id"],
                "history_status": "unavailable_in_release", "sessions": [],
                "tasks": [{
                    "id": row["qa_id"], "kind": "multiple_choice",
                    "input": {"text": row["question"], "options": row["option"]},
                    "annotations": {"answer": row["answer"], "answer_letters": row["answer_letters"]},
                    "attributes": {"category": row["qa_type"], "source": row["source"]},
                }],
            }
        elif dataset_id == "personamem-v2":
            record = {
                "id": f"persona-{row['persona_id']}:row-{index}", "group_id": f"persona-{row['persona_id']}",
                "history_status": "external_history_required", "sessions": [],
                "history_references": {k: v for k, v in row.items() if k.endswith("_link")},
                "tasks": [{
                    "id": f"row-{index}", "kind": "personalization",
                    "input": {"text": row["user_query"]},
                    "annotations": {k: v for k, v in row.items() if k not in {"user_query", "persona_id"} and not k.endswith("_link")},
                    "attributes": {"category": row.get("pref_type"), "persona_id": row["persona_id"]},
                }],
            }
        elif dataset_id == "beam":
            record = _beam_record(row, index)
        else:
            raise ValueError(f"no task adapter for {dataset_id}")
        if requested:
            record["tasks"] = [t for t in record["tasks"] if t["id"] in requested]
            found.update(t["id"] for t in record["tasks"])
        if task_limit is not None:
            record["tasks"] = record["tasks"][: task_limit - selected]
        if record["tasks"]:
            records.append(record)
        selected += len(record["tasks"])
        if requested and requested <= found:
            break
        if task_limit is not None and selected >= task_limit:
            break
    if requested - found:
        raise ValueError(f"task IDs not found: {', '.join(sorted(requested - found))}")
    if not records:
        raise ValueError("no tasks selected")
    return _dataset_pack(
        dataset_id=dataset_id, dataset=source_entry(dataset_id), path=path,
        selection={"record_ids": [r["id"] for r in records], "task_limit": task_limit, "task_ids": sorted(requested)}, records=records,
    )


def build_personamem_v2(
    *, path: Path, history_root: Path, persona_ids: list[str] | None,
    task_limit: int | None,
) -> dict[str, Any]:
    """Join PersonaMem-v2 benchmark rows with the separately published history files."""
    history_root = history_root.resolve()
    requested = set(persona_ids or [])
    if task_limit is not None and task_limit < 1:
        raise ValueError("task-limit must be positive")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(iter_rows(path)):
        persona_id = str(row.get("persona_id", ""))
        if not persona_id or (requested and persona_id not in requested):
            continue
        grouped.setdefault(persona_id, []).append({"index": index, "row": row})
        if task_limit is not None and sum(len(values) for values in grouped.values()) >= task_limit:
            break
    if requested - set(grouped):
        raise ValueError(f"persona IDs not found: {', '.join(sorted(requested - set(grouped)))}")
    if not grouped:
        raise ValueError("no PersonaMem-v2 rows selected")
    records = []
    used_tasks = 0
    history_sources = []
    for persona_id, selected in grouped.items():
        row = selected[0]["row"]
        link = row.get("chat_history_32k_link")
        if not isinstance(link, str) or not link:
            raise ValueError(f"persona {persona_id} has no 32K history link")
        history_path = (history_root / link).resolve()
        if not history_path.is_relative_to(history_root.resolve()) or not history_path.exists():
            raise ValueError(f"missing history for persona {persona_id}: {link}")
        if any(item["row"].get("chat_history_32k_link") != link for item in selected):
            raise ValueError(f"persona {persona_id} refers to multiple 32K histories")
        history_hash = sha256_file(history_path)
        receipt_path = history_path.with_suffix(history_path.suffix + ".receipt.json")
        history_receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
        if history_receipt and history_receipt.get("sha256") != history_hash:
            raise ValueError(f"history for persona {persona_id} differs from receipt")
        history_sources.append({"file": link, "sha256": history_hash, "acquisition": history_receipt})
        source = json.loads(history_path.read_text(encoding="utf-8"))
        source_persona = source.get("metadata", {}).get("persona_id") if isinstance(source, dict) else None
        if source_persona is not None and str(source_persona) != persona_id:
            raise ValueError(f"history belongs to a different persona: {persona_id}")
        messages = source.get("chat_history") if isinstance(source, dict) else None
        if not isinstance(messages, list):
            raise ValueError(f"history for persona {persona_id} has no chat_history list")
        turns = []
        for message_index, message in enumerate(messages):
            if not isinstance(message, dict):
                raise ValueError(f"history for persona {persona_id} has invalid message {message_index}")
            if message.get("role") == "system":
                continue
            if message.get("role") not in {"user", "assistant"} or not isinstance(message.get("content"), str) or not message["content"].strip():
                raise ValueError(f"history for persona {persona_id} has invalid message {message_index}")
            turns.append({"id": str(message_index), "role": message["role"], "content": message["content"],
                "attributes": {"source_index": message_index}})
        tasks = []
        for item in selected:
            if task_limit is not None and used_tasks >= task_limit:
                break
            row = item["row"]
            query = row["user_query"]
            # CSV stores some questions as Python-literal message dictionaries.
            # Decode the container, never execute it or send role/encoding noise as query.
            if isinstance(query, str) and query.lstrip().startswith("{"):
                decoded = ast.literal_eval(query)
                if not isinstance(decoded, dict) or decoded.get("role") != "user" or not isinstance(decoded.get("content"), str):
                    raise ValueError("PersonaMem user_query must contain a user message")
                query = decoded["content"]
            tasks.append({"id": f"row-{item['index']}", "kind": "personalization",
                "input": {"text": query, "source_text": row["user_query"]},
                "annotations": {k: v for k, v in row.items() if k not in {"user_query", "persona_id", "chat_history_32k_link", "chat_history_128k_link"}},
                "attributes": {"persona_id": persona_id, "history_link": link,
                    "history_window": "32k", "history_path": str(history_path.relative_to(history_root))}})
            used_tasks += 1
        records.append({"id": f"persona-{persona_id}", "group_id": f"persona-{persona_id}",
            "sessions": [{"id": "history-32k", "source_id": link, "turns": turns}], "tasks": tasks,
            "history_references": {"chat_history_32k_link": link}})
    result = _dataset_pack(dataset_id="personamem-v2", dataset=source_entry("personamem-v2"), path=path,
        selection={"record_ids": [record["id"] for record in records], "persona_ids": sorted(requested),
            "task_limit": task_limit, "history_window": "32k", "system_messages": "excluded_generation_background"}, records=records)
    result["preparation"]["history_inputs"] = history_sources
    return result


def _beam_record(row: dict[str, Any], index: int) -> dict[str, Any]:
    sessions = []
    for session_index, messages in enumerate(row["chat"]):
        turns = []
        for turn_index, message in enumerate(messages):
            if message.get("role") not in {"user", "assistant"}:
                raise ValueError("BEAM chat contains an unsupported role")
            turns.append({
                "id": f"{session_index}:{turn_index}", "role": message["role"],
                "content": message["content"],
                "attributes": {k: v for k, v in message.items() if k not in {"role", "content"}},
            })
        sessions.append({"id": str(session_index), "turns": turns})
    probes = row["probing_questions"]
    if isinstance(probes, str):
        probes = ast.literal_eval(probes)
    if not isinstance(probes, dict):
        raise ValueError("BEAM probing_questions must be a category mapping")
    tasks = []
    for category, questions in probes.items():
        for question_index, question in enumerate(questions):
            tasks.append({
                "id": f"{category}:{question_index}", "kind": "question_answering",
                "input": {"text": question["question"]},
                "annotations": {k: v for k, v in question.items() if k != "question"},
                "attributes": {"category": category},
            })
    return {"id": str(row.get("conversation_id", index)), "sessions": sessions, "tasks": tasks}


def iter_rows(path: Path) -> Iterator[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            yield from csv.DictReader(source)
    else:
        yield from iter_json_array(path)


def _dataset_pack(
    *,
    dataset_id: str,
    dataset: dict[str, Any],
    path: Path,
    selection: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    receipt_path = path.with_suffix(path.suffix + ".receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
    actual_hash = sha256_file(path)
    if receipt and receipt.get("sha256") != actual_hash:
        raise ValueError("source file no longer matches its acquisition receipt")
    return {
        "schema_version": PACK_SCHEMA_VERSION,
        "dataset": {
            "id": dataset_id,
            "title": dataset["title"],
            "upstream": dataset["upstream"],
            "license": dataset["license"],
            "attribution": dataset["attribution"],
            "source_revision": receipt.get("source_revision") if receipt else None,
            "format": dataset.get("format"),
        },
        "preparation": {
            "tool": "dataset.prepare",
            "version": BUILDER_VERSION,
            "input": {"file": path.name, "sha256": actual_hash, "acquisition": receipt},
            "selection": selection,
            "excluded_tasks": [{"record_id": r["id"], **item} for r in records for item in r.get("excluded_tasks", [])],
        },
        "records": records,
    }


def _turn_content(turn: dict[str, Any]) -> str:
    content = str(turn.get("text", ""))
    caption = str(turn.get("blip_caption") or "").strip()
    if caption and caption.casefold() not in content.casefold():
        return f"{content}\n[Image: {caption}]"
    return content


def _evidence_ids(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        for match in DIALOG_ID_PATTERN.finditer(str(value)):
            result.append(f"D{int(match.group(1))}:{int(match.group(2))}")
    return result


def _normal_dialog_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = DIALOG_ID_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    return f"D{int(match.group(1))}:{int(match.group(2))}"


def _parse_locomo_date(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%I:%M %p on %d %B, %Y")
    except ValueError as error:
        raise ValueError(f"invalid LoCoMo session date: {value}") from error
    return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _parse_timestamp(value: Any) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0:
        return int(value)
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y/%m/%d (%a) %H:%M")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_READ_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_dataset(dataset_id: str, path: Path | None = None) -> dict[str, Any]:
    entry = source_entry(dataset_id)
    paths = [path] if path else [
        RAW_DIR / asset["path"] for asset in entry.get("assets", [])
        if (RAW_DIR / asset["path"]).is_file()
    ]
    if not paths:
        paths = [path or source_path(dataset_id)]
    inspections = [_inspect_file(dataset_id, asset_path) for asset_path in paths]
    if len(inspections) == 1:
        return inspections[0]
    return {"id": dataset_id, "assets": inspections}


def _inspect_file(dataset_id: str, path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"dataset is unavailable: {path}")
    if source_entry(dataset_id).get("pack_adapter") == "locomo-v1" and path.suffix.lower() != ".jsonl":
        samples = list(iter_json_array(path))
        sessions = 0
        turns = 0
        questions = 0
        categories: Counter[str] = Counter()
        for sample in samples:
            conversation = sample["conversation"]
            session_keys = [key for key in conversation if SESSION_PATTERN.fullmatch(key)]
            sessions += len(session_keys)
            turns += sum(len(conversation[key]) for key in session_keys)
            for question in sample.get("qa", []):
                questions += 1
                categories[str(question.get("category", "unknown"))] += 1
        return {
            "id": dataset_id,
            "path": str(path),
            "sha256": sha256_file(path),
            "conversations": len(samples),
            "sessions": sessions,
            "turns": turns,
            "questions": questions,
            "questions_by_category": dict(sorted(categories.items())),
        }
    entry = source_entry(dataset_id)
    if entry.get("pack_adapter") == "context-task-v1":
        return _inspect_context_tasks(dataset_id, path)
    if path.suffix.lower() == ".csv":
        return _inspect_csv(dataset_id, path)
    if dataset_id in {"scriptmem", "beam", "personamem-v2"} and path.suffix.lower() == ".jsonl":
        return _inspect_task_rows(dataset_id, path)
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as source:
            first = next((char for block in iter(lambda: source.read(4096), "") for char in block if not char.isspace()), "")
        if first != "[":
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError(f"{dataset_id} JSON source must contain an object or array")
            return {
                "id": dataset_id,
                "path": str(path),
                "sha256": sha256_file(path),
                "format": "json-object",
                "top_level_keys": sorted(value),
                "top_level_types": {key: type(item).__name__ for key, item in value.items()},
            }
    record_count = 0
    sessions = 0
    turns = 0
    answerable = 0
    question_types: Counter[str] = Counter()
    for record in iter_json_array(path):
        if not isinstance(record, dict):
            raise ValueError(f"{dataset_id} records must be JSON objects")
        record_count += 1
        question_types[str(record.get("question_type", "unknown"))] += 1
        answer_session_ids = record.get("answer_session_ids")
        if isinstance(answer_session_ids, list) and answer_session_ids and "_abs" not in str(record.get("question_id", "")):
            answerable += 1
        sessions_for_record = record.get("haystack_sessions", [])
        if isinstance(sessions_for_record, list):
            sessions += len(sessions_for_record)
            turns += sum(len(session) for session in sessions_for_record if isinstance(session, list))
    if source_entry(dataset_id).get("pack_adapter") == "longmemeval-v1":
        return {
            "id": dataset_id,
            "path": str(path),
            "sha256": sha256_file(path),
            "questions": record_count,
            "sessions": sessions,
            "turns": turns,
            "answerable_questions": answerable,
            "questions_by_type": dict(sorted(question_types.items())),
        }
    keys: Counter[str] = Counter()
    for row in iter_json_array(path):
        if isinstance(row, dict):
            keys.update(row.keys())
    return {
        "id": dataset_id,
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": record_count,
        "top_level_key_frequency": dict(sorted(keys.items())),
    }


def _inspect_context_tasks(dataset_id: str, path: Path) -> dict[str, Any]:
    row_count = 0
    categories: Counter[str] = Counter()
    subcategories: Counter[str] = Counter()
    message_shapes: Counter[str] = Counter()
    delimiter_rows = 0
    rubric_counts: Counter[int] = Counter()
    for row in iter_json_array(path):
        if not isinstance(row, dict):
            raise ValueError(f"{dataset_id} rows must be JSON objects")
        row_count += 1
        metadata = row.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        categories[str(metadata.get("context_category", "unknown"))] += 1
        subcategories[str(metadata.get("context_subcategory", metadata.get("sub_category", "unknown")))] += 1
        messages = row.get("messages", [])
        if isinstance(messages, list):
            message_shapes[str(len(messages))] += 1
            if len(messages) == 1 and isinstance(messages[0], dict):
                delimiter_rows += int("<|TASK|>" in str(messages[0].get("content", "")))
        rubrics = row.get("rubrics", [])
        rubric_counts[len(rubrics) if isinstance(rubrics, list) else 0] += 1
    return {
        "id": dataset_id,
        "path": str(path),
        "sha256": sha256_file(path),
        "tasks": row_count,
        "tasks_by_category": dict(sorted(categories.items())),
        "tasks_by_subcategory": dict(sorted(subcategories.items())),
        "message_count_distribution": dict(sorted(message_shapes.items())),
        "single_message_delimiter_tasks": delimiter_rows,
        "rubric_count_distribution": dict(sorted(rubric_counts.items())),
    }


def _inspect_task_rows(dataset_id: str, path: Path) -> dict[str, Any]:
    count = 0
    keys: Counter[str] = Counter()
    groups: Counter[str] = Counter()
    types: Counter[str] = Counter()
    history_turns = 0
    for row in iter_rows(path):
        count += 1
        keys.update(row.keys())
        if dataset_id == "scriptmem":
            groups[str(row["source"])] += 1
            types[str(row["qa_type"])] += 1
        elif dataset_id == "personamem-v2":
            groups[str(row["persona_id"])] += 1
            types[str(row["pref_type"])] += 1
        elif dataset_id == "beam":
            record = _beam_record(row, count - 1)
            history_turns += sum(len(s["turns"]) for s in record["sessions"])
            types.update(t["attributes"]["category"] for t in record["tasks"])
    return {"id": dataset_id, "path": str(path), "sha256": sha256_file(path), "rows": count,
        "top_level_key_frequency": dict(sorted(keys.items())), "groups": dict(sorted(groups.items())),
        "task_types": dict(sorted(types.items())), "history_turns": history_turns}


def _inspect_csv(dataset_id: str, path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise ValueError(f"CSV is missing a header row: {path}")
        rows = sum(1 for _ in reader)
    return {
        "id": dataset_id,
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": rows,
        "columns": reader.fieldnames,
    }


def slice_rows(path: Path, output: Path, *, offset: int, limit: int) -> dict[str, Any]:
    if offset < 0 or limit < 1:
        raise ValueError("offset must be non-negative and limit must be positive")
    if path.resolve() == output.resolve() or output.exists():
        raise ValueError("slice output must be a new path distinct from its source")
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    selected = 0
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as source, output.open("w", encoding="utf-8", newline="\n") as target:
            for index, line in enumerate(line for line in source if line.strip()):
                if index < offset:
                    continue
                if selected >= limit:
                    break
                if line.strip():
                    json.loads(line)
                    target.write(line.rstrip("\r\n") + "\n")
                    selected += 1
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise ValueError("CSV is missing a header row")
            with output.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=reader.fieldnames)
                writer.writeheader()
                for index, row in enumerate(reader):
                    if index < offset:
                        continue
                    if selected >= limit:
                        break
                    writer.writerow(row)
                    selected += 1
    elif suffix == ".json":
        selected_rows = list(itertools.islice(iter_json_array(path), offset, offset + limit))
        output.write_text(json.dumps(selected_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        selected = len(selected_rows)
    else:
        raise ValueError("slice supports JSON arrays, JSONL, and CSV")
    if selected == 0:
        output.unlink(missing_ok=True)
        raise ValueError("slice selection contains no rows")
    receipt = {"input": str(path), "input_sha256": sha256_file(path), "output": str(output),
        "offset": offset, "rows": selected, "sha256": sha256_file(output), "source_kind": "local-row-slice"}
    output.with_suffix(output.suffix + ".receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def _comma_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise ValueError("list argument must contain at least one value")
    return values


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspect, slice, and prepare public dataset sources")
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = load_catalog()
    dataset_ids = tuple(catalog.get("datasets", {})) + tuple(catalog.get("sources", {}))
    build_ids = tuple(
        dataset_id
        for dataset_id, entry in catalog["datasets"].items()
        if entry.get("pack_adapter")
    )
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--dataset", choices=dataset_ids, required=True)
    inspect_parser.add_argument("--input", type=Path, default=None)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--dataset", choices=build_ids, required=True)
    build_parser.add_argument("--input", type=Path, default=None)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--conversation-ids", default=None)
    build_parser.add_argument("--conversation-limit", type=int, default=None)
    build_parser.add_argument("--question-ids", default=None)
    build_parser.add_argument("--question-limit", type=int, default=None)
    build_parser.add_argument("--question-type", default=None)
    build_parser.add_argument("--session-limit", type=int, default=None)
    build_parser.add_argument("--questions-per-category", type=int, default=None)
    build_parser.add_argument("--category", type=int, action="append", default=None)
    build_parser.add_argument("--task-ids", default=None)
    build_parser.add_argument("--task-limit", type=int, default=None)
    build_parser.add_argument("--persona-ids", default=None, help="comma-separated PersonaMem-v2 personas")
    build_parser.add_argument("--history-root", type=Path, default=None, help="PersonaMem-v2 data root")
    build_parser.add_argument("--qa-input", type=Path, default=None, help="paired PerLTQA questions file")
    build_parser.add_argument("--character-names", default=None, help="comma-separated PerLTQA subjects")
    build_parser.add_argument("--character-limit", type=int, default=None)
    slice_parser = commands.add_parser("slice", help="write a deterministic row-range slice")
    slice_parser.add_argument("--dataset", choices=dataset_ids, required=True)
    slice_parser.add_argument("--input", type=Path, default=None)
    slice_parser.add_argument("--output", type=Path, required=True)
    slice_parser.add_argument("--offset", type=int, default=0)
    slice_parser.add_argument("--limit", type=int, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "build":
            if arguments.history_root is not None and arguments.dataset != "personamem-v2":
                raise ValueError("--history-root is only supported for PersonaMem-v2")
            if arguments.persona_ids and arguments.history_root is None:
                raise ValueError("--persona-ids requires --history-root")
            if arguments.history_root is not None and arguments.task_ids:
                raise ValueError("joined PersonaMem-v2 history supports --persona-ids and --task-limit, not --task-ids")
        if arguments.command == "inspect":
            result = inspect_dataset(arguments.dataset, arguments.input)
        elif arguments.command == "slice":
            result = slice_rows(
                arguments.input or source_path(arguments.dataset),
                arguments.output,
                offset=arguments.offset,
                limit=arguments.limit,
            )
        else:
            input_path = arguments.input or source_path(arguments.dataset)
            if input_path.resolve() == arguments.output.resolve() or (
                arguments.qa_input and arguments.qa_input.resolve() == arguments.output.resolve()
            ):
                raise ValueError("pack output must differ from the source path")
            adapter = source_entry(arguments.dataset).get("pack_adapter")
            if adapter == "locomo-v1":
                result = build_locomo(
                    dataset_id=arguments.dataset,
                    path=input_path,
                    conversation_ids=_comma_list(arguments.conversation_ids),
                    conversation_limit=arguments.conversation_limit,
                    session_limit=arguments.session_limit,
                    questions_per_category=arguments.questions_per_category,
                    categories=set(arguments.category) if arguments.category else None,
                )
            elif adapter == "longmemeval-v1":
                result = build_longmemeval(
                    dataset_id=arguments.dataset,
                    path=input_path,
                    question_ids=_comma_list(arguments.question_ids),
                    question_limit=arguments.question_limit,
                    session_limit=arguments.session_limit,
                    question_type=arguments.question_type,
                )
            elif adapter == "perltqa-v1":
                from dataset.perltqa import build_perltqa

                qa_path = arguments.qa_input or input_path.with_name("perltqa.json")
                if qa_path.resolve() == arguments.output.resolve():
                    raise ValueError("pack output must differ from the QA source path")
                result = build_perltqa(
                    path=input_path, qa_path=qa_path,
                    character_names=_comma_list(arguments.character_names),
                    character_limit=arguments.character_limit, task_limit=arguments.task_limit,
                )
            elif adapter == "context-task-v1":
                result = build_context_tasks(
                    dataset_id=arguments.dataset,
                    path=input_path,
                    task_ids=_comma_list(arguments.task_ids),
                    task_limit=arguments.task_limit,
                )
            elif adapter == "personamem-v2-v1" and arguments.history_root is not None:
                result = build_personamem_v2(
                    path=input_path,
                    history_root=(arguments.history_root or input_path.parent).resolve(),
                    persona_ids=_comma_list(arguments.persona_ids),
                    task_limit=arguments.task_limit,
                )
            else:
                result = build_tasks(
                    dataset_id=arguments.dataset, path=input_path, task_limit=arguments.task_limit,
                    task_ids=_comma_list(arguments.task_ids),
                )
            write_pack(arguments.output, result)
            result = {
                "output": str(arguments.output),
                "dataset": result["dataset"],
                "records": len(result["records"]),
                "sessions": sum(len(record["sessions"]) for record in result["records"]),
                "turns": sum(
                    len(session["turns"])
                    for record in result["records"]
                    for session in record["sessions"]
                ),
                "tasks": sum(len(record["tasks"]) for record in result["records"]),
            }
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, csv.Error) as error:
        print(f"dataset operation failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
