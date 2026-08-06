from __future__ import annotations

from aml_memory.locomo import convert_locomo


def test_convert_locomo_preserves_chunks_timestamps_and_evidence() -> None:
    turns = [
        {
            "speaker": "Alice" if index % 2 == 0 else "Bob",
            "dia_id": f"D1:{index + 1}",
            "text": f"turn {index + 1}",
        }
        for index in range(21)
    ]
    turns[0]["blip_caption"] = "a red bicycle"
    sample = {
        "sample_id": "test-0",
        "conversation": {
            "speaker_a": "Alice",
            "speaker_b": "Bob",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": turns,
        },
        "qa": [
            {
                "question": "What did Alice show?",
                "answer": "A red bicycle",
                "evidence": ["D1:1"],
                "category": 1,
            },
            {
                "question": "What follows turn 1?",
                "answer": "turn 2",
                "evidence": ["D1:1", "D1:2"],
                "category": 3,
            },
            {
                "question": "Unanswerable",
                "answer": "none",
                "evidence": [],
                "category": 3,
            },
        ],
    }

    manifest = convert_locomo([sample], qa_per_category=1)

    case = manifest.cases[0]
    assert [len(request.messages) for request in case.adds] == [20, 1]
    assert case.adds[0].messages[0].role == "user"
    assert case.adds[0].messages[1].role == "assistant"
    assert case.adds[0].messages[0].timestamp == 1683554160000
    assert case.adds[0].messages[0].content.endswith("[Image: a red bicycle]")
    assert [search.category for search in case.searches] == [
        "single_hop",
        "multi_hop",
    ]
    assert case.searches[1].expected[1].contains_any == ["turn 2"]
    assert all(search.request.top_k == 100 for search in case.searches)


def test_convert_locomo_can_filter_categories_and_samples() -> None:
    def sample(sample_id: str) -> dict:
        return {
            "sample_id": sample_id,
            "conversation": {
                "speaker_a": "A",
                "speaker_b": "B",
                "session_1_date_time": "9:00 am on 1 January, 2024",
                "session_1": [
                    {"speaker": "A", "dia_id": "D1:1", "text": "evidence"}
                ],
            },
            "qa": [
                {
                    "question": "When?",
                    "answer": "today",
                    "evidence": ["D1:1"],
                    "category": 2,
                },
                {
                    "question": "Why?",
                    "answer": "reason",
                    "evidence": ["D1:1"],
                    "category": 4,
                },
            ],
        }

    manifest = convert_locomo(
        [sample("one"), sample("two")],
        sample_limit=1,
        categories={2},
    )

    assert len(manifest.cases) == 1
    assert len(manifest.cases[0].searches) == 1
    assert manifest.cases[0].searches[0].category == "temporal"


def test_convert_locomo_session_limit_excludes_partial_evidence() -> None:
    sample = {
        "sample_id": "sessions",
        "conversation": {
            "speaker_a": "A",
            "speaker_b": "B",
            "session_1_date_time": "9:00 am on 1 January, 2024",
            "session_1": [
                {"speaker": "A", "dia_id": "D1:1", "text": "first"}
            ],
            "session_2_date_time": "9:00 am on 2 January, 2024",
            "session_2": [
                {"speaker": "B", "dia_id": "D2:1", "text": "second"}
            ],
        },
        "qa": [
            {
                "question": "First?",
                "answer": "first",
                "evidence": ["D1:1"],
                "category": 1,
            },
            {
                "question": "Both?",
                "answer": "first and second",
                "evidence": ["D1:1", "D2:1"],
                "category": 3,
            },
        ],
    }

    manifest = convert_locomo([sample], session_limit=1)

    case = manifest.cases[0]
    assert len(case.adds) == 1
    assert [search.request.query for search in case.searches] == ["First?"]


def test_convert_locomo_normalizes_dirty_evidence_annotations() -> None:
    sample = {
        "sample_id": "dirty",
        "conversation": {
            "speaker_a": "A",
            "speaker_b": "B",
            "session_1_date_time": "9:00 am on 1 January, 2024",
            "session_1": [
                {"speaker": "A", "dia_id": "D1:1", "text": "first"},
                {"speaker": "B", "dia_id": "D1:2", "text": "second"},
            ],
        },
        "qa": [
            {
                "question": "Both?",
                "answer": "first and second",
                "evidence": ["D1:01 D1:2", "D"],
                "category": 1,
            },
            {
                "question": "Only invalid?",
                "answer": "none",
                "evidence": ["D", "D9:9"],
                "category": 4,
            },
        ],
    }

    manifest = convert_locomo([sample])

    searches = manifest.cases[0].searches
    assert len(searches) == 1
    assert [target.contains_any for target in searches[0].expected] == [
        ["first"],
        ["second"],
    ]
