from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
DERIVED_DIR = ROOT / "data" / "derived"
CATALOG_PATH = ROOT / "catalog.json"
BUILDER_VERSION = 1
CHUNK_READ_SIZE = 1024 * 1024
SESSION_PATTERN = re.compile(r"^session_(\d+)$")
DIALOG_ID_PATTERN = re.compile(r"D:?(\d+):(\d+)", re.IGNORECASE)
CATEGORY_MAP = {
    1: "single_hop",
    2: "temporal",
    3: "multi_hop",
    4: "open_domain",
    5: "adversarial",
}


def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def source_path(dataset_id: str) -> Path:
    datasets = load_catalog()["datasets"]
    if dataset_id not in datasets:
        raise ValueError(f"unknown dataset: {dataset_id}")
    return RAW_DIR / datasets[dataset_id]["raw_relative_path"]


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
    chunk_size: int,
    top_k: int,
) -> dict[str, Any]:
    if conversation_limit is not None and conversation_limit < 1:
        raise ValueError("conversation-limit must be positive")
    if session_limit is not None and session_limit < 1:
        raise ValueError("session-limit must be positive")
    if questions_per_category is not None and questions_per_category < 1:
        raise ValueError("questions-per-category must be positive")
    _validate_build_limits(chunk_size, top_k)
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

    cases = []
    for sample in raw_conversations:
        case = _locomo_case(
            sample,
            session_limit=session_limit,
            questions_per_category=questions_per_category,
            categories=selected_categories,
            chunk_size=chunk_size,
            top_k=top_k,
        )
        if case:
            cases.append(case)
    if not cases:
        raise ValueError("selected conversations produced no questions with included evidence")
    dataset = load_catalog()["datasets"]["locomo"]
    return _manifest(
        dataset_id="locomo-original-public",
        dataset=dataset,
        path=path,
        selection={
            "conversation_ids": [case["id"] for case in cases],
            "conversation_limit": conversation_limit,
            "session_limit": session_limit,
            "questions_per_category": questions_per_category,
            "categories": sorted(selected_categories),
            "chunk_size": chunk_size,
            "top_k": top_k,
        },
        cases=cases,
    )


def _locomo_case(
    sample: dict[str, Any],
    *,
    session_limit: int | None,
    questions_per_category: int | None,
    categories: set[int],
    chunk_size: int,
    top_k: int,
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

    user_id = f"locomo:{sample_id}"
    evidence_text: dict[str, str] = {}
    adds: list[dict[str, Any]] = []
    for session_number, session_key in sessions:
        raw_turns = conversation.get(session_key)
        if not isinstance(raw_turns, list):
            raise ValueError(f"session {session_key} must be an array")
        timestamp = _parse_locomo_date(conversation.get(f"{session_key}_date_time"))
        messages = []
        for turn in raw_turns:
            if not isinstance(turn, dict):
                raise ValueError(f"conversation {sample_id} contains an invalid turn")
            dialog_id = _normal_dialog_id(turn.get("dia_id"))
            if dialog_id is None:
                raise ValueError(f"conversation {sample_id} contains an invalid dialog id")
            content = _turn_content(turn)
            evidence_text[dialog_id] = content
            messages.append(
                {
                    "role": "user" if turn.get("speaker") == speaker_a else "assistant",
                    "timestamp": timestamp,
                    "content": content,
                }
            )
        session_id = f"locomo:{sample_id}:session:{session_number}"
        for chunk_index, offset in enumerate(range(0, len(messages), chunk_size)):
            adds.append(
                {
                    "request_id": f"locomo:{sample_id}:session:{session_number}:chunk:{chunk_index}",
                    "messages": messages[offset : offset + chunk_size],
                    "user_id": user_id,
                    "session_id": session_id,
                }
            )

    searches = []
    category_counts: Counter[int] = Counter()
    for qa_index, qa in enumerate(sample.get("qa", [])):
        if not isinstance(qa, dict):
            continue
        try:
            category = int(qa.get("category"))
        except (TypeError, ValueError):
            continue
        evidence_ids = _evidence_ids(qa.get("evidence", []))
        if category not in categories or not evidence_ids:
            continue
        valid_ids = [identifier for identifier in evidence_ids if identifier in evidence_text]
        if not valid_ids or len(set(valid_ids)) != len(set(evidence_ids)):
            continue
        if questions_per_category is not None and category_counts[category] >= questions_per_category:
            continue
        question = qa.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        category_counts[category] += 1
        searches.append(
            {
                "id": f"locomo:{sample_id}:qa:{qa_index}",
                "request": {"query": question, "user_id": user_id, "top_k": top_k},
                "expected": [
                    {"contains_any": [evidence_text[identifier]]}
                    for identifier in dict.fromkeys(valid_ids)
                ],
                "category": CATEGORY_MAP[category],
            }
        )
    if not searches:
        return None
    return {"id": sample_id, "adds": adds, "searches": searches}


def build_longmemeval(
    *,
    path: Path,
    question_ids: list[str] | None,
    question_limit: int | None,
    session_limit: int | None,
    question_type: str | None,
    chunk_size: int,
    top_k: int,
) -> dict[str, Any]:
    if question_limit is not None and question_limit < 1:
        raise ValueError("question-limit must be positive")
    if session_limit is not None and session_limit < 1:
        raise ValueError("session-limit must be positive")
    _validate_build_limits(chunk_size, top_k)
    requested = set(question_ids or [])
    if len(requested) != len(question_ids or []):
        raise ValueError("question-ids must be unique")
    if requested and question_limit is not None and len(requested) > question_limit:
        raise ValueError("question-limit cannot be smaller than the number of requested question IDs")
    cases = []
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
        case = _longmemeval_case(
            record,
            session_limit=session_limit,
            chunk_size=chunk_size,
            top_k=top_k,
        )
        if case:
            cases.append(case)
        requested_found = requested and requested <= found_ids
        if requested_found or (not requested and question_limit is not None and len(cases) >= question_limit):
            break
    if requested:
        missing = requested - found_ids
        if missing:
            raise ValueError(f"question IDs not found in selected type/limit: {', '.join(sorted(missing))}")
    if not cases:
        raise ValueError("selected questions produced no complete included evidence")
    dataset = load_catalog()["datasets"]["longmemeval-s"]
    return _manifest(
        dataset_id="longmemeval-s-original-public",
        dataset=dataset,
        path=path,
        selection={
            "question_ids": [case["id"] for case in cases],
            "question_limit": question_limit,
            "question_type": question_type,
            "session_limit": session_limit,
            "chunk_size": chunk_size,
            "top_k": top_k,
            "abstention_policy": "excluded; retrieval-only harness cannot judge answer abstention",
        },
        cases=cases,
    )


def _longmemeval_case(
    record: dict[str, Any],
    *,
    session_limit: int | None,
    chunk_size: int,
    top_k: int,
) -> dict[str, Any] | None:
    question_id = record["question_id"]
    session_ids = record.get("haystack_session_ids")
    sessions = record.get("haystack_sessions")
    dates = record.get("haystack_dates", [])
    answer_session_ids = record.get("answer_session_ids", [])
    if not isinstance(session_ids, list) or not isinstance(sessions, list) or len(session_ids) != len(sessions):
        raise ValueError(f"question {question_id} has mismatched history sessions")
    if not isinstance(answer_session_ids, list) or not answer_session_ids:
        return None
    selected_sessions = list(zip(session_ids, sessions, strict=True))
    if session_limit is not None:
        selected_sessions = selected_sessions[:session_limit]
    included_ids = {identifier for identifier, _ in selected_sessions}
    if not set(answer_session_ids) <= included_ids:
        return None
    adds = []
    targets = []
    seen_targets: set[str] = set()
    user_id = f"longmemeval:{question_id}"
    for session_index, (session_id, turns) in enumerate(selected_sessions):
        if not isinstance(turns, list):
            raise ValueError(f"question {question_id} contains an invalid session")
        session_timestamp = _parse_timestamp(dates[session_index] if session_index < len(dates) else None)
        messages = []
        for turn in turns:
            if not isinstance(turn, dict):
                raise ValueError(f"question {question_id} contains an invalid turn")
            role = turn.get("role")
            content = turn.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
                raise ValueError(f"question {question_id} contains an invalid role/content")
            message_timestamp = _parse_timestamp(turn.get("timestamp")) or session_timestamp
            messages.append({"role": role, "timestamp": message_timestamp, "content": content})
            if session_id in answer_session_ids and turn.get("has_answer"):
                signature = " ".join(content.casefold().split())
                if signature and signature not in seen_targets:
                    seen_targets.add(signature)
                    targets.append({"contains_any": [content]})
        session_id_text = str(session_id)
        for chunk_index, offset in enumerate(range(0, len(messages), chunk_size)):
            adds.append(
                {
                    "request_id": f"longmemeval:{question_id}:session:{session_id_text}:chunk:{chunk_index}",
                    "messages": messages[offset : offset + chunk_size],
                    "user_id": user_id,
                    "session_id": f"longmemeval:{question_id}:session:{session_id_text}",
                }
            )
    if not targets:
        return None
    question = record.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"question {question_id} has no question text")
    return {
        "id": question_id,
        "adds": adds,
        "searches": [
            {
                "id": question_id,
                "request": {"query": question, "user_id": user_id, "top_k": top_k},
                "expected": targets,
                "category": record.get("question_type", "general"),
            }
        ],
    }


def _manifest(
    *,
    dataset_id: str,
    dataset: dict[str, Any],
    path: Path,
    selection: dict[str, Any],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset": {
            "id": dataset_id,
            "title": dataset["title"],
            "official_suite_name": dataset["official_suite_name"],
            "upstream": dataset["upstream"],
            "license": dataset["license"],
            "attribution": dataset["attribution"],
            "source_revision": dataset.get("revision"),
            "source_sha256": sha256_file(path),
            "source_file": path.name,
            "selection": selection,
            "builder_version": BUILDER_VERSION,
        },
        "cases": cases,
    }


def _validate_build_limits(chunk_size: int, top_k: int) -> None:
    if not 1 <= chunk_size <= 20:
        raise ValueError("chunk-size must be between 1 and 20")
    if not 1 <= top_k <= 100:
        raise ValueError("top-k must be between 1 and 100")


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


def inspect_dataset(dataset_id: str) -> dict[str, Any]:
    path = source_path(dataset_id)
    if not path.is_file():
        raise FileNotFoundError(f"dataset is unavailable: {path}")
    if dataset_id == "locomo":
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
    record_count = sum(1 for _ in iter_json_array(path))
    return {
        "id": dataset_id,
        "path": str(path),
        "sha256": sha256_file(path),
        "questions": record_count,
    }


def _comma_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise ValueError("list argument must contain at least one value")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect public datasets and build Add/Search manifests")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--dataset", choices=("locomo", "longmemeval-s"), required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--dataset", choices=("locomo", "longmemeval-s"), required=True)
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
    build_parser.add_argument("--chunk-size", type=int, default=20)
    build_parser.add_argument("--top-k", type=int, default=10)
    arguments = parser.parse_args()
    try:
        if arguments.command == "inspect":
            result = inspect_dataset(arguments.dataset)
        else:
            input_path = arguments.input or source_path(arguments.dataset)
            if arguments.dataset == "locomo":
                result = build_locomo(
                    path=input_path,
                    conversation_ids=_comma_list(arguments.conversation_ids),
                    conversation_limit=arguments.conversation_limit,
                    session_limit=arguments.session_limit,
                    questions_per_category=arguments.questions_per_category,
                    categories=set(arguments.category) if arguments.category else None,
                    chunk_size=arguments.chunk_size,
                    top_k=arguments.top_k,
                )
            else:
                result = build_longmemeval(
                    path=input_path,
                    question_ids=_comma_list(arguments.question_ids),
                    question_limit=arguments.question_limit,
                    session_limit=arguments.session_limit,
                    question_type=arguments.question_type,
                    chunk_size=arguments.chunk_size,
                    top_k=arguments.top_k,
                )
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = {
                "output": str(arguments.output),
                "dataset": result["dataset"],
                "cases": len(result["cases"]),
                "adds": sum(len(case["adds"]) for case in result["cases"]),
                "searches": sum(len(case["searches"]) for case in result["cases"]),
            }
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"dataset operation failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
