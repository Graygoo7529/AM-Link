from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataset import prepare
from dataset.pack import validate_pack
from dataset.split import split_pack


class PrepareTests(unittest.TestCase):
    def test_context_tasks_use_explicit_boundary_and_keep_rubrics_separate(self) -> None:
        row = {"messages": [{"role": "user", "content": "Raw context\n<|TASK|>\nThe task?"}],
            "rubrics": ["SECRET-RUBRIC"], "metadata": {"context_id": "c1"}}
        record = prepare._context_task_record(row, "t1")
        self.assertEqual(record["sessions"][0]["turns"][0]["content"], "Raw context")
        self.assertEqual(record["tasks"][0]["input"]["text"], "The task?")
        self.assertNotIn("SECRET-RUBRIC", json.dumps(record["sessions"]))
        self.assertEqual(record["group_id"], "c1")

    def test_ambiguous_context_is_preserved_without_guessing_a_question_boundary(self) -> None:
        row = {"messages": [{"role": "system", "content": "Instructions"},
            {"role": "user", "content": "Context and question without declared boundary"}], "rubrics": []}
        record = prepare._context_task_record(row, "t1")
        self.assertEqual(record["sessions"], [])
        self.assertEqual(record["tasks"][0]["input"]["messages"], row["messages"])
        self.assertNotIn("text", record["tasks"][0]["input"])

    def test_beam_only_uses_chat_as_history(self) -> None:
        row = {"conversation_id": "c1", "user_profile": {"secret": "GOLD"},
            "chat": [[{"role": "user", "content": "Actual dialogue"}]],
            "probing_questions": "{'abstention': [{'question': 'Why?', 'ideal_response': 'GOLD'}]}"}
        record = prepare._beam_record(row, 0)
        self.assertNotIn("GOLD", json.dumps(record["sessions"]))
        self.assertEqual(record["tasks"][0]["annotations"]["ideal_response"], "GOLD")

    def test_split_preserves_source_groups_and_is_repeatable(self) -> None:
        pack = {"schema_version": 1, "dataset": {"id": "fixture"},
            "preparation": {"input": {"sha256": "x"}, "selection": {}},
            "records": [{"id": str(i), "group_id": str(i // 2), "sessions": [], "tasks": []} for i in range(8)]}
        result = split_pack(pack, holdout_fraction=0.5, seed=7)
        self.assertEqual(result, split_pack(pack, holdout_fraction=0.5, seed=7))
        left = {r["group_id"] for r in result["dev"]["records"]}
        right = {r["group_id"] for r in result["holdout"]["records"]}
        self.assertFalse(left & right)
        self.assertEqual(len(pack["records"]), 8)

    def test_slice_streams_selected_json_rows_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "raw.json"
            output = Path(directory) / "slice.json"
            source.write_text('[{"id":1},{"id":2},{"id":3}]', encoding="utf-8")
            result = prepare.slice_rows(source, output, offset=1, limit=1)
            self.assertEqual(json.loads(output.read_text()), [{"id": 2}])
            self.assertEqual(result["rows"], 1)
            with self.assertRaises(ValueError):
                prepare.slice_rows(source, source, offset=0, limit=1)

    def test_json_array_reader_handles_chunk_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text('[{"text":"alpha, beta"}, {"n":2}]', encoding="utf-8")
            with patch.object(prepare, "CHUNK_READ_SIZE", 5):
                self.assertEqual(
                    list(prepare.iter_json_array(path)),
                    [{"text": "alpha, beta"}, {"n": 2}],
                )

    def test_locomo_pack_preserves_source_annotations_without_benchmark_requests(self) -> None:
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

            pack = prepare.build_locomo(
                path=path,
                conversation_ids=["conv-test"],
                conversation_limit=None,
                session_limit=1,
                questions_per_category=None,
                categories={1},
            )

        validate_pack(pack)
        record = pack["records"][0]
        self.assertEqual([task["input"]["text"] for task in record["tasks"]], ["What happened first?"])
        self.assertEqual(
            record["tasks"][0]["annotations"],
            {"answer": "SECRET-GOLD-ANSWER", "evidence_turn_ids": ["D1:1"]},
        )
        self.assertNotIn("adds", record)
        self.assertNotIn("searches", record)
        serialized_history = json.dumps(record["sessions"])
        self.assertNotIn("SECRET-GOLD-ANSWER", serialized_history)
        self.assertNotIn("second session", serialized_history)
        self.assertEqual(pack["preparation"]["excluded_tasks"][0]["missing_turn_ids"], ["D2:1"])

    def test_longmemeval_pack_preserves_answer_and_turn_annotations_separately(self) -> None:
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

            pack = prepare.build_longmemeval(
                path=path,
                question_ids=None,
                question_limit=1,
                session_limit=1,
                question_type=None,
            )

        record = pack["records"][0]
        self.assertEqual(
            record["tasks"][0]["annotations"],
            {
                "answer": "SECRET-GOLD-ANSWER",
                "evidence_turn_ids": ["s1:0"],
                "answer_session_ids": ["s1"],
                "is_answerable": True,
            },
        )
        self.assertNotIn("SECRET-GOLD-ANSWER", json.dumps(record["sessions"]))

    def test_longmemeval_question_limit_counts_records_with_included_evidence(self) -> None:
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

            pack = prepare.build_longmemeval(
                path=path,
                question_ids=None,
                question_limit=1,
                session_limit=1,
                question_type=None,
            )

        self.assertEqual([record["id"] for record in pack["records"]], ["q2"])

    def test_longmemeval_abstention_with_source_sessions_is_not_answerable(self) -> None:
        raw = {"question_id": "q_abs", "question": "Unsupported detail?", "answer": "unknown",
            "haystack_session_ids": ["s1"], "answer_session_ids": ["s1"],
            "haystack_sessions": [[{"role": "user", "content": "Related history.", "has_answer": True}]]}
        record = prepare._longmemeval_record(raw, session_limit=None)
        annotations = record["tasks"][0]["annotations"]
        self.assertFalse(annotations["is_answerable"])
        self.assertEqual(annotations["answer_session_ids"], ["s1"])
        self.assertNotIn("retrieval_expect_empty", annotations)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"source.json"
            path.write_text(json.dumps([raw]), encoding="utf-8")
            stats = prepare.inspect_dataset("longmemeval-s", path)
            self.assertEqual(stats["answerable_questions"], 0)

    def test_longmemeval_duplicate_session_ids_get_stable_pack_ids(self) -> None:
        raw = {"question_id": "q1", "question": "Which day?", "answer_session_ids": [],
            "haystack_session_ids": ["same", "same"], "haystack_dates": ["2024-01-01", "2024-01-02"],
            "haystack_sessions": [[{"role": "user", "content": "First.", "has_answer": False}],
                [{"role": "user", "content": "Second.", "has_answer": False}]]}
        record = prepare._longmemeval_record(raw, session_limit=None)
        self.assertEqual([s["id"] for s in record["sessions"]], ["same", "same#2"])
        self.assertEqual([s["source_id"] for s in record["sessions"]], ["same", "same"])

    def test_personamem_v2_joins_history_and_keeps_labels_out_of_turns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "benchmark.csv"
            source.write_text("persona_id,chat_history_32k_link,chat_history_128k_link,user_query,correct_answer,preference\n"
                "1,data/chat_history_32k/p.json,data/chat_history_128k/q.json,What?,yes,tea\n", encoding="utf-8")
            history = root / "data/chat_history_32k/p.json"
            history.parent.mkdir(parents=True)
            history.write_text(json.dumps({"chat_history": [
                {"role": "system", "content": "persona prompt"},
                {"role": "user", "content": "I like tea."},
                {"role": "assistant", "content": "Noted."}]}), encoding="utf-8")
            receipt = {"sha256": prepare.sha256_file(source), "source_revision": "test"}
            source.with_suffix(source.suffix + ".receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
            pack = prepare.build_personamem_v2(path=source, history_root=root, persona_ids=["1"], task_limit=1)
            self.assertEqual(pack["preparation"]["history_inputs"][0]["sha256"], prepare.sha256_file(history))
            history.with_suffix(history.suffix + ".receipt.json").write_text(json.dumps({"sha256": "wrong"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs from receipt"):
                prepare.build_personamem_v2(path=source, history_root=root, persona_ids=["1"], task_limit=1)
        self.assertEqual(len(pack["records"][0]["sessions"][0]["turns"]), 2)
        self.assertEqual(pack["records"][0]["tasks"][0]["input"]["text"], "What?")
        self.assertEqual(pack["records"][0]["tasks"][0]["annotations"]["preference"], "tea")
        self.assertNotIn("persona prompt", json.dumps(pack["records"][0]["sessions"]))


if __name__ == "__main__":
    unittest.main()
