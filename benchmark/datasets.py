from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from dataset.pack import validate_pack


MAX_ADD_MESSAGES = 20
MAX_ADD_WORDS = 2000


def _history_requests(record: dict[str, Any], user_id: str, chunk_size: int):
    adds = []
    turn_map: dict[str, list[dict[str, Any]]] = {}
    participants = record.get("participants", [])
    for session in record["sessions"]:
        session_id = str(session["id"])
        pending = []
        words_in_batch = 0
        chunk_index = 0

        def flush():
            nonlocal pending, words_in_batch, chunk_index
            if pending:
                adds.append({"request_id": f"{user_id}:session:{session_id}:chunk:{chunk_index}",
                    "messages": pending, "user_id": user_id, "session_id": f"{user_id}:{session_id}"})
                pending = []
                words_in_batch = 0
                chunk_index += 1

        for turn in session["turns"]:
            role = turn.get("role")
            if role is None and turn.get("speaker") in participants:
                role = "user" if turn["speaker"] == participants[0] else "assistant"
            if role not in {"user", "assistant"}:
                raise ValueError(f"turn {turn['id']} requires a role or a declared speaker")
            content = turn["content"]
            # API role is a transport mapping, not a real person's identity.
            # Preserve an explicit source speaker without changing source offsets
            # or injecting any task annotation into the method's input.
            prefix = f"Speaker: {turn['speaker']}\n" if turn.get("speaker") else ""
            prefix_words = len(prefix.split())
            fragment_words = MAX_ADD_WORDS - prefix_words
            if fragment_words < 1:
                raise ValueError("speaker metadata exceeds message word budget")
            words = list(re.finditer(r"\S+", content))
            fragments = []
            for word_start in range(0, len(words), fragment_words):
                word_end = min(word_start + fragment_words, len(words))
                start = words[word_start].start()
                end = words[word_end - 1].end()
                word_count = word_end - word_start + prefix_words
                if len(pending) >= chunk_size or words_in_batch + word_count > MAX_ADD_WORDS:
                    flush()
                message = {"role": role, "content": prefix + content[start:end]}
                if turn.get("timestamp") is not None:
                    message["timestamp"] = turn["timestamp"]
                pending.append(message)
                words_in_batch += word_count
                fragments.append({"content": content[start:end], "session_id": session_id,
                    "char_start": start, "char_end": end,
                    "add_request_id": f"{user_id}:session:{session_id}:chunk:{chunk_index}"})
            turn_map[turn["id"]] = fragments
        flush()
    return adds, turn_map


def build_retrieval_manifest(
    pack: dict[str, Any],
    *,
    chunk_size: int,
    top_k: int,
) -> dict[str, Any]:
    """Adapt neutral conversation/task records to the arena Add/Search plan."""
    validate_pack(pack)
    if not 1 <= chunk_size <= MAX_ADD_MESSAGES:
        raise ValueError(f"chunk-size must be between 1 and {MAX_ADD_MESSAGES}")
    if not 1 <= top_k <= 100:
        raise ValueError("top-k must be between 1 and 100")

    cases = []
    excluded = []
    source_maps = {}
    for record in pack["records"]:
        if record.get("history_status") in {"unavailable_in_release", "external_history_required"}:
            excluded.append({"record_id": record["id"], "reason": record["history_status"]})
            continue
        searches = []
        user_id = f"{pack['dataset']['id']}:{record['id']}"
        adds, turn_map = _history_requests(record, user_id, chunk_size)

        for task in record["tasks"]:
            query = task.get("input", {}).get("text")
            if not isinstance(query, str) or not query.strip():
                excluded.append({"record_id": record["id"], "task_id": task["id"], "reason": "no_separated_text_task"})
                continue
            annotations = task.get("annotations", {})
            evidence_ids = annotations.get("evidence_turn_ids")
            disabled = task.get("attributes", {}).get("retrieval_grading_disabled")
            expected = []
            if isinstance(evidence_ids, list) and not disabled:
                for turn_id in dict.fromkeys(evidence_ids):
                    mapped = turn_map.get(turn_id)
                    if mapped is None:
                        raise ValueError(
                            f"task {task['id']} references turn {turn_id} outside prepared history"
                        )
                    for fragment in mapped:
                        expected.append(
                            {
                                "contains_any": [fragment["content"]],
                                "source": {
                                    "dataset_id": pack["dataset"]["id"],
                                    "dataset_record_id": record["id"],
                                    "turn_id": turn_id,
                                    "session_id": fragment["session_id"],
                                    "char_start": fragment["char_start"], "char_end": fragment["char_end"],
                                    "add_request_id": fragment["add_request_id"],
                                },
                            }
                        )
            # An unanswerable QA can still have relevant history. Only an explicit
            # retrieval annotation may require an empty Search response.
            expect_empty = annotations.get("retrieval_expect_empty") is True and not disabled
            grading = "evidence" if expected else "empty" if expect_empty else "ungraded"
            attributes = task.get("attributes", {})
            searches.append(
                {
                    "id": f"{record['id']}:{task['id']}",
                    "request": {"query": query, "user_id": user_id, "top_k": top_k},
                    "expected": expected,
                    "expect_empty": grading == "empty",
                    "grading": grading,
                    "category": attributes.get("category", attributes.get("question_type", attributes.get("context_category", "general"))),
                    "dataset_task": {"record_id": record["id"], "task_id": task["id"]},
                }
            )
        if searches:
            cases.append({"id": record["id"], "adds": adds, "searches": searches})
            source_maps[record["id"]] = turn_map
    if not cases:
        raise ValueError("dataset pack contains no searchable tasks")

    dataset = dict(pack["dataset"])
    dataset["source_sha256"] = pack["preparation"]["input"]["sha256"]
    return {
        "schema_version": 1,
        "dataset": dataset,
        "adapter": {
            "id": "evidence-retrieval-v2",
            "options": {"chunk_size": chunk_size, "top_k": top_k, "max_add_words": MAX_ADD_WORDS},
            "word_counter": "whitespace-delimited Unicode words; local approximation",
            "speaker_role_mapping": "first declared participant -> user; other participant -> assistant",
            "speaker_identity": "explicit source speaker is prefixed to each message fragment; API role is not identity",
            "evidence_unit": "source turn fragment bounded by max_add_words",
        },
        "selection": pack["preparation"]["selection"],
        "dataset_pack_sha256": hashlib.sha256(
            json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "cases": cases,
        "excluded": excluded,
        "source_map": source_maps,
    }
