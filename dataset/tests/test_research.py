import json
import tempfile
import unittest
from pathlib import Path

from dataset.prepare import _parse_timestamp
from dataset.research_cases import visible_events
from dataset.survey import context_tasks, distribution
from benchmark.lexical_study import rank


class ResearchTests(unittest.TestCase):
    def test_source_calendar_dates_survive_normalization(self):
        start = _parse_timestamp("2023/01/08 (Sun) 12:49")
        end = _parse_timestamp("2023/01/15 (Sun) 00:27")
        self.assertEqual(start, _parse_timestamp("2023-01-08T12:49:00Z"))
        self.assertTrue(6 * 86400000 < end-start < 7 * 86400000)

    def test_pv3_excludes_future_other_people_and_nested_labels(self):
        base = {"persona_id": "a", "event_id": "1", "timestamp": "9", "user_message": "Do not remember this",
                "preferences": "SECRET-GOLD", "extras_json": "SECRET-EXTRA", "interaction_type": "SECRET-INFERRED",
                "conversation_json": json.dumps([{"role":"user","content":"A plan", "embeds_pref_idx":[123456]}])}
        rows = [base, {**base,"timestamp":"10"}, {**base,"timestamp":"11"}, {**base,"persona_id":"b"}]
        visible = visible_events(rows, "a", 10)
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["user_message"], "Do not remember this")
        self.assertNotIn("SECRET", json.dumps(visible))
        self.assertNotIn("embeds_pref_idx", json.dumps(visible))
        self.assertEqual(json.loads(visible[0]["conversation_json"]), [{"role":"user","content":"A plan"}])

    def test_census_does_not_call_unseparated_messages_ready(self):
        rows = [{"messages":[{"role":"user","content":"No separator"}],"rubrics":["x"],"metadata":{"task_id":"1"}},
                {"messages":[{"role":"user","content":"History<|TASK|>Question"}],"rubrics":["y"],"metadata":{"task_id":"2"}}]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"data.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in rows),encoding="utf-8")
            self.assertEqual(context_tasks(path)["boundaries"],{"保持原输入，边界未认证":1,"可按当前规则拆分":1})

    def test_bm25_ranks_query_terms_and_rejects_zero_overlap(self):
        result=rank([("a","A cat named Luna"),("b","gardening flowers"),("c","Luna cat cat")],"cat Luna")
        self.assertEqual(result[0][0],"c")
        self.assertEqual({x[0] for x in result},{"a","c"})
        self.assertEqual(rank([("a","no overlap")],"zebra"),[])

    def test_distribution_reports_its_population(self):
        self.assertEqual(distribution([4,1,3,2]),{"n":4,"min":1,"median":2.5,"p90":3,"max":4,"sum":10})


if __name__=="__main__":unittest.main()
