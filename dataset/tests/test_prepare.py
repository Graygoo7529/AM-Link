from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataset import prepare


class PrepareTests(unittest.TestCase):
    def test_json_array_reader_handles_chunk_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text('[{"text":"alpha, beta"}, {"n":2}]', encoding="utf-8")
            with patch.object(prepare, "CHUNK_READ_SIZE", 5):
                self.assertEqual(
                    list(prepare.iter_json_array(path)),
                    [{"text": "alpha, beta"}, {"n": 2}],
                )

    def test_locomo_manifest_uses_only_included_evidence_and_never_gold_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locomo.json"
            source = [
                {
                    "sample_id": "conv-test",
                    "conversation": {
                        "speaker_a": "Alice",
                        "session_1_date_time": "10:00 AM on 01 January, 2024",
                        "session_1": [
                            {"dia_id": "D1:1", "speaker": "Alice", "text": "Evidence from first session."}
                        ],
                        "session_2_date_time": "10:00 AM on 02 January, 2024",
                        "session_2": [
                            {"dia_id": "D2:1", "speaker": "Bob", "text": "Evidence from second session."}
                        ],
                    },
                    "qa": [
                        {
                            "question": "What happened first?",
                            "answer": "SECRET-GOLD-ANSWER",
                            "evidence": ["D1:1"],
                            "category": 1,
                        },
                        {
                            "question": "What happened later?",
                            "answer": "SECRET-GOLD-ANSWER",
                            "evidence": ["D2:1"],
                            "category": 1,
                        },
                    ],
                }
            ]
            path.write_text(json.dumps(source), encoding="utf-8")

            manifest = prepare.build_locomo(
                path=path,
                conversation_ids=["conv-test"],
                conversation_limit=None,
                session_limit=1,
                questions_per_category=None,
                categories={1},
                chunk_size=20,
                top_k=5,
            )

        case = manifest["cases"][0]
        self.assertEqual([search["request"]["query"] for search in case["searches"]], ["What happened first?"])
        self.assertEqual(case["searches"][0]["expected"], [{"contains_any": ["Evidence from first session."]}])
        serialized = json.dumps(manifest)
        self.assertNotIn("SECRET-GOLD-ANSWER", serialized)
        self.assertTrue(all("second session" not in message["content"] for add in case["adds"] for message in add["messages"]))

    def test_longmemeval_manifest_uses_has_answer_turn_not_answer_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "longmemeval.json"
            records = [
                {
                    "question_id": "q1",
                    "question_type": "single-session-user",
                    "question": "What is the remembered preference?",
                    "answer": "SECRET-GOLD-ANSWER",
                    "haystack_session_ids": ["s1"],
                    "haystack_dates": ["2024-01-01"],
                    "haystack_sessions": [
                        [
                            {"role": "user", "content": "I prefer tea.", "has_answer": True},
                            {"role": "assistant", "content": "Understood.", "has_answer": False},
                        ]
                    ],
                    "answer_session_ids": ["s1"],
                }
            ]
            path.write_text(json.dumps(records), encoding="utf-8")

            manifest = prepare.build_longmemeval(
                path=path,
                question_ids=None,
                question_limit=1,
                session_limit=1,
                question_type=None,
                chunk_size=20,
                top_k=5,
            )

        case = manifest["cases"][0]
        self.assertEqual(case["searches"][0]["expected"], [{"contains_any": ["I prefer tea."]}])
        self.assertNotIn("SECRET-GOLD-ANSWER", json.dumps(manifest))

    def test_longmemeval_question_limit_counts_cases_with_included_gold_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "longmemeval.json"
            records = [
                {
                    "question_id": "q1",
                    "question_type": "single-session-user",
                    "question": "First question?",
                    "haystack_session_ids": ["s1", "s2"],
                    "haystack_sessions": [
                        [{"role": "user", "content": "Unrelated history.", "has_answer": False}],
                        [{"role": "user", "content": "Gold evidence.", "has_answer": True}],
                    ],
                    "answer_session_ids": ["s2"],
                },
                {
                    "question_id": "q2",
                    "question_type": "single-session-user",
                    "question": "Second question?",
                    "haystack_session_ids": ["s1"],
                    "haystack_sessions": [[{"role": "user", "content": "Useful evidence.", "has_answer": True}]],
                    "answer_session_ids": ["s1"],
                },
            ]
            path.write_text(json.dumps(records), encoding="utf-8")

            manifest = prepare.build_longmemeval(
                path=path,
                question_ids=None,
                question_limit=1,
                session_limit=1,
                question_type=None,
                chunk_size=20,
                top_k=5,
            )

        self.assertEqual([case["id"] for case in manifest["cases"]], ["q2"])


if __name__ == "__main__":
    unittest.main()
