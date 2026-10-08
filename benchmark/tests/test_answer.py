import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.answer import main
from benchmark.observability import ObservationRecorder, VERSION


class AnswerTests(unittest.TestCase):
    def test_answer_only_receives_query_and_returned_search_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            run_id, pack_hash = "answer-test", "a" * 64
            with ObservationRecorder(run / "observability.jsonl", run_id=run_id,
                    dataset_pack_sha256=pack_hash) as recorder:
                with recorder.span("search", name="Search API", record_id="record", task_id="task",
                        request_id="search-1"):
                    pass
            (run / "report.json").write_text(json.dumps({"run": {"run_id": run_id}}), encoding="utf-8")
            (run / "observability.meta.json").write_text(json.dumps({
                "schema_version": VERSION, "run_id": run_id, "dataset_pack_sha256": pack_hash,
                "model_capture_complete": True, "producer": "test"}), encoding="utf-8")
            trace = {"event": "search", "run_id": run_id, "search_id": "search-1", "ok": True,
                "dataset_task": {"record_id": "record", "task_id": "task"},
                "request": {"query": "Who owns the blue bike?", "user_id": "u", "top_k": 2},
                "results": [{"id": "m1", "content": "Lina owns the blue bike."}],
                "expected": [{"contains_any": ["GOLD_MUST_NOT_BE_SENT"]}]}
            (run / "trace.jsonl").write_text(json.dumps(trace) + "\n", encoding="utf-8")
            env_file = Path(tmp) / "provider.env"
            env_file.write_text("OPENAI_API_KEY=test-key\nOPENAI_BASE_URL=https://provider.invalid/v1\n", encoding="utf-8")
            response = {"model": "gpt-5.6-luna", "usage": {"prompt_tokens": 34,
                "completion_tokens": 9, "prompt_tokens_details": {"cached_tokens": 0}},
                "choices": [{"message": {"content": "Lina owns it."}}]}
            with patch("benchmark.answer._complete", return_value=response) as complete, \
                    patch("benchmark.answer.register") as register, \
                    patch("benchmark.answer.publish") as publish, \
                    patch("builtins.print"):
                main(["--run", str(run), "--env-file", str(env_file), "--answer-id", "answer-one"])
            complete.assert_called_once()
            self.assertEqual(complete.call_args.kwargs["api_key"], "test-key")
            self.assertEqual(complete.call_args.kwargs["model"], "gpt-5.6-luna")
            self.assertEqual(complete.call_args.kwargs["timeout"], 45)
            sent = complete.call_args.kwargs["messages"][1]["content"]
            sent = json.loads(sent)
            self.assertEqual(sent, {"question": "Who owns the blue bike?", "retrieved_memories": [
                {"rank": 1, "content": "Lina owns the blue bike."}]})
            self.assertNotIn("GOLD_MUST_NOT_BE_SENT", json.dumps(sent))
            register.assert_called_once()
            publish.assert_called_once()
            answer_dir = run / "answers" / "answer-one"
            row = json.loads((answer_dir / "answer.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(row["answer"], "Lina owns it.")
            events = [json.loads(line) for line in (run / "observability.jsonl").read_text().splitlines()]
            self.assertEqual([event["operation"] for event in events], ["search", "model", "answer"])
            self.assertEqual(events[1]["parent_span_id"], events[2]["span_id"])
            self.assertEqual(events[1]["model"]["name"], "gpt-5.6-luna")
            self.assertEqual(json.loads((answer_dir / "answer-run.json").read_text())["request_retries"], 0)


if __name__ == "__main__":
    unittest.main()
