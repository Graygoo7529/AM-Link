from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AddRequest, MemoryMessage, SearchRequest
from .replay import EvidenceTarget, ReplayCase, ReplayManifest, ReplaySearch


_SESSION_PATTERN = re.compile(r"^session_(\d+)$")
_DIALOG_ID_PATTERN = re.compile(r"D:?(\d+):(\d+)", re.IGNORECASE)
_CATEGORY_MAP = {
    1: "single_hop",
    2: "temporal",
    3: "multi_hop",
    4: "open_domain",
    5: "adversarial",
}


def load_locomo(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("LoCoMo input must be a JSON array")
    return payload


def convert_locomo(
    samples: list[dict[str, Any]],
    *,
    sample_limit: int | None = None,
    session_limit: int | None = None,
    qa_per_category: int | None = None,
    categories: set[int] | None = None,
    chunk_size: int = 20,
    top_k: int = 100,
) -> ReplayManifest:
    if sample_limit is not None and sample_limit < 1:
        raise ValueError("sample_limit must be positive")
    if session_limit is not None and session_limit < 1:
        raise ValueError("session_limit must be positive")
    if qa_per_category is not None and qa_per_category < 1:
        raise ValueError("qa_per_category must be positive")
    if not 1 <= chunk_size <= 20:
        raise ValueError("chunk_size must be between 1 and 20")
    selected_categories = categories or set(_CATEGORY_MAP)
    unknown = selected_categories - set(_CATEGORY_MAP)
    if unknown:
        raise ValueError(f"unsupported LoCoMo categories: {sorted(unknown)}")

    cases = [
        _convert_sample(
            sample,
            session_limit=session_limit,
            qa_per_category=qa_per_category,
            categories=selected_categories,
            chunk_size=chunk_size,
            top_k=top_k,
        )
        for sample in samples[:sample_limit]
    ]
    if not cases:
        raise ValueError("no LoCoMo samples selected")
    return ReplayManifest(version=1, cases=cases)


def _convert_sample(
    sample: dict[str, Any],
    *,
    session_limit: int | None,
    qa_per_category: int | None,
    categories: set[int],
    chunk_size: int,
    top_k: int,
) -> ReplayCase:
    sample_id = str(sample["sample_id"])
    conversation = sample["conversation"]
    speaker_a = str(conversation["speaker_a"])
    user_id = f"locomo:{sample_id}"
    evidence_text: dict[str, str] = {}
    adds: list[AddRequest] = []

    sessions = sorted(
        (
            (int(match.group(1)), key)
            for key in conversation
            if (match := _SESSION_PATTERN.match(key))
        ),
        key=lambda item: item[0],
    )
    if session_limit is not None:
        sessions = sessions[:session_limit]
    for session_number, session_key in sessions:
        timestamp = _parse_session_timestamp(
            str(conversation[f"{session_key}_date_time"])
        )
        messages: list[MemoryMessage] = []
        for turn in conversation[session_key]:
            content = _turn_content(turn)
            dialog_id = _normalize_dialog_id(str(turn["dia_id"]))
            if dialog_id is None:
                raise ValueError(
                    f"sample {sample_id} contains invalid dialog id {turn['dia_id']!r}"
                )
            evidence_text[dialog_id] = content
            messages.append(
                MemoryMessage(
                    role="user" if str(turn["speaker"]) == speaker_a else "assistant",
                    timestamp=timestamp,
                    content=content,
                )
            )
        for chunk_index, offset in enumerate(range(0, len(messages), chunk_size)):
            adds.append(
                AddRequest(
                    request_id=(
                        f"locomo:{sample_id}:session:{session_number}:chunk:{chunk_index}"
                    ),
                    messages=messages[offset : offset + chunk_size],
                    user_id=user_id,
                    session_id=f"locomo:{sample_id}:session:{session_number}",
                )
            )

    searches: list[ReplaySearch] = []
    category_counts = {category: 0 for category in categories}
    for qa_index, qa in enumerate(sample["qa"]):
        category = int(qa["category"])
        evidence_ids = _evidence_ids(qa.get("evidence", []))
        valid_evidence_ids = [
            ident for ident in evidence_ids if ident in evidence_text
        ]
        if session_limit is not None and len(valid_evidence_ids) != len(evidence_ids):
            continue
        if category not in categories or not valid_evidence_ids:
            continue
        if (
            qa_per_category is not None
            and category_counts[category] >= qa_per_category
        ):
            continue
        category_counts[category] += 1
        searches.append(
            ReplaySearch(
                id=f"locomo:{sample_id}:qa:{qa_index}",
                request=SearchRequest(
                    query=str(qa["question"]),
                    user_id=user_id,
                    top_k=top_k,
                ),
                expected=[
                    EvidenceTarget(contains_any=[evidence_text[ident]])
                    for ident in dict.fromkeys(valid_evidence_ids)
                ],
                category=_CATEGORY_MAP[category],
            )
        )
    if not searches:
        raise ValueError(f"sample {sample_id} has no selected QA with evidence")
    return ReplayCase(id=f"locomo:{sample_id}", adds=adds, searches=searches)


def _turn_content(turn: dict[str, Any]) -> str:
    content = str(turn["text"])
    caption = str(turn.get("blip_caption") or "").strip()
    if caption and caption.casefold() not in content.casefold():
        return f"{content}\n[Image: {caption}]"
    return content


def _evidence_ids(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        for match in _DIALOG_ID_PATTERN.finditer(str(value)):
            result.append(f"D{int(match.group(1))}:{int(match.group(2))}")
    return result


def _normalize_dialog_id(value: str) -> str | None:
    match = _DIALOG_ID_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    return f"D{int(match.group(1))}:{int(match.group(2))}"


def _parse_session_timestamp(value: str) -> int:
    parsed = datetime.strptime(value, "%I:%M %p on %d %B, %Y")
    return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert the official LoCoMo JSON into an Add/Search replay manifest"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sample-limit", type=int)
    parser.add_argument("--session-limit", type=int)
    parser.add_argument("--qa-per-category", type=int)
    parser.add_argument(
        "--categories",
        default="1,2,3,4,5",
        help="comma-separated LoCoMo category numbers",
    )
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=100)
    arguments = parser.parse_args()

    categories = {
        int(value.strip())
        for value in arguments.categories.split(",")
        if value.strip()
    }
    manifest = convert_locomo(
        load_locomo(arguments.input),
        sample_limit=arguments.sample_limit,
        session_limit=arguments.session_limit,
        qa_per_category=arguments.qa_per_category,
        categories=categories,
        chunk_size=arguments.chunk_size,
        top_k=arguments.top_k,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(arguments.output),
                "cases": len(manifest.cases),
                "adds": sum(len(case.adds) for case in manifest.cases),
                "searches": sum(len(case.searches) for case in manifest.cases),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
