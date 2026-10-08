from __future__ import annotations

import unittest

from benchmark.core import validate_manifest, _group_metrics
from benchmark.datasets import build_retrieval_manifest


def pack_fixture() -> dict:
    return {
        "schema_version": 1,
        "dataset": {"id": "fixture", "title": "Fixture"},
        "preparation": {"selection": {"record_ids": ["record-1"]}, "input": {"sha256": "abc"}},
        "records": [
            {
                "id": "record-1",
                "sessions": [
                    {
                        "id": "session-1",
                        "turns": [
                            {"id": "turn-1", "role": "user", "content": "I prefer tea."},
                            {"id": "turn-2", "role": "assistant", "content": "I will remember that."},
                        ],
                    }
                ],
                "tasks": [
                    {
                        "id": "question-1",
                        "kind": "question_answering",
                        "input": {"text": "What drink do I prefer?"},
                        "annotations": {
                            "answer": "tea (gold only)",
                            "evidence_turn_ids": ["turn-1"],
                        },
                        "attributes": {"category": "preference"},
                    }
                ],
            }
        ],
    }


class DatasetAdapterTests(unittest.TestCase):
    def test_mrr_includes_missed_questions_in_the_denominator(self) -> None:
        queries = [
            {"target_count": 1, "target_ranks": [2], "first_relevant_rank": 2},
            {"target_count": 1, "target_ranks": [None], "first_relevant_rank": None},
        ]
        self.assertEqual(_group_metrics(queries)["mrr"], 0.25)
    def test_adapter_builds_requests_and_keeps_answers_out_of_target_plan(self) -> None:
        manifest = build_retrieval_manifest(pack_fixture(), chunk_size=1, top_k=5)
        validate_manifest(manifest)

        case = manifest["cases"][0]
        self.assertEqual(len(case["adds"]), 2)
        self.assertEqual(case["adds"][0]["messages"][0]["content"], "I prefer tea.")
        search = case["searches"][0]
        self.assertEqual(search["request"]["query"], "What drink do I prefer?")
        self.assertEqual(search["grading"], "evidence")
        self.assertEqual(search["expected"][0]["source"]["add_request_id"], case["adds"][0]["request_id"])
        self.assertNotIn("tea (gold only)", str(manifest))

    def test_unanswerable_and_unannotated_tasks_are_distinguished(self) -> None:
        pack = pack_fixture()
        pack["records"][0]["tasks"] = [
            {
                "id": "empty",
                "input": {"text": "Unanswerable?"},
                "annotations": {"retrieval_expect_empty": True},
            },
            {"id": "ungraded", "input": {"text": "Task without evidence labels?"}, "annotations": {}},
        ]
        manifest = build_retrieval_manifest(pack, chunk_size=2, top_k=5)
        validate_manifest(manifest)
        self.assertEqual(
            [search["grading"] for search in manifest["cases"][0]["searches"]],
            ["empty", "ungraded"],
        )

    def test_unanswerable_qa_does_not_imply_empty_retrieval(self) -> None:
        pack = pack_fixture()
        pack["records"][0]["tasks"][0]["annotations"] = {"is_answerable": False}
        manifest = build_retrieval_manifest(pack, chunk_size=2, top_k=5)
        self.assertEqual(manifest["cases"][0]["searches"][0]["grading"], "ungraded")

    def test_context_free_task_can_be_inspected_without_fabricating_history(self) -> None:
        pack = pack_fixture()
        pack["records"][0]["sessions"] = []
        pack["records"][0]["tasks"][0]["annotations"] = {}
        manifest = build_retrieval_manifest(pack, chunk_size=2, top_k=5)
        validate_manifest(manifest)
        self.assertEqual(manifest["cases"][0]["adds"], [])

    def test_missing_required_history_is_rejected_before_target_use(self) -> None:
        pack = pack_fixture()
        pack["records"][0]["history_status"] = "external_history_required"
        with self.assertRaisesRegex(ValueError, "no searchable tasks"):
            build_retrieval_manifest(pack, chunk_size=2, top_k=5)

    def test_long_turn_fragments_remain_traceable_to_source_offsets(self) -> None:
        pack = pack_fixture()
        content = " ".join(f"word{i}" for i in range(2100))
        pack["records"][0]["sessions"][0]["turns"][0]["content"] = content
        manifest = build_retrieval_manifest(pack, chunk_size=20, top_k=5)
        case = manifest["cases"][0]
        self.assertEqual(len(case["adds"]), 2)
        self.assertTrue(all(sum(len(m["content"].split()) for m in a["messages"]) <= 2000 for a in case["adds"]))
        fragments = manifest["source_map"]["record-1"]["turn-1"]
        self.assertEqual(len(fragments), 2)
        for fragment in fragments:
            self.assertEqual(content[fragment["char_start"]:fragment["char_end"]], fragment["content"])


if __name__ == "__main__":
    unittest.main()


def test_speaker_identity_survives_role_mapping_and_chunk_budget():
    pack = pack_fixture()
    record = pack['records'][0]
    record['participants'] = ['Joanna', 'Nate']
    turn = record['sessions'][0]['turns'][0]
    turn.pop('role')
    turn['speaker'] = 'Joanna'
    turn['content'] = ' '.join(f'word{i}' for i in range(2100))
    manifest = build_retrieval_manifest(pack, chunk_size=20, top_k=5)
    case = manifest['cases'][0]
    assert case['adds'][0]['messages'][0]['role'] == 'user'
    assert case['adds'][0]['messages'][0]['content'].startswith('Speaker: Joanna\n')
    assert all(sum(len(m['content'].split()) for m in a['messages']) <= 2000 for a in case['adds'])
    for fragment in manifest['source_map']['record-1']['turn-1']:
        assert fragment['content'] == turn['content'][fragment['char_start']:fragment['char_end']]
    assert 'gold only' not in str(case['adds'])
