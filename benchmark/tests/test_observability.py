import json
import tempfile
import unittest
from pathlib import Path

from benchmark.observability import ObservationRecorder, validate_event


class ObservabilityTests(unittest.TestCase):
    def test_nested_call_preserves_unknown_usage_and_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with ObservationRecorder(path, run_id="r", dataset_pack_sha256="a"*64) as recorder:
                with recorder.span("search", name="search", record_id="u", task_id="q", request_id="req") as parent:
                    with recorder.span("model", name="embedding", record_id="u", task_id="q", request_id="req", parent=parent) as child:
                        child["model"] = dict(provider="test", name="synthetic", input_tokens=None,
                            output_tokens=None, cached_tokens=None, cost_usd=None, usage_source="unavailable")
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(events[0]["parent_span_id"], events[1]["span_id"])
            self.assertIsNone(events[0]["model"]["cost_usd"])
            self.assertGreaterEqual(events[1]["duration_ms"], events[0]["duration_ms"])
            with self.assertRaises(FileExistsError):
                ObservationRecorder(path, run_id="r", dataset_pack_sha256="a"*64)

    def test_exception_recorded_without_exception_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with ObservationRecorder(path, run_id="r", dataset_pack_sha256="a"*64) as recorder:
                with self.assertRaisesRegex(RuntimeError, "sensitive"):
                    with recorder.span("add", name="add", record_id="u", request_id="req"):
                        raise RuntimeError("sensitive input must not be logged")
            raw = path.read_text()
            self.assertNotIn("sensitive", raw)
            self.assertEqual(json.loads(raw)["error"], {"code": "RuntimeError", "retryable": False})

    def test_identity_and_reference_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with ObservationRecorder(Path(tmp)/"events.jsonl", run_id="r", dataset_pack_sha256="a"*64) as recorder:
                with recorder.span("search", name="search", record_id="u", task_id="q", request_id="req") as parent:
                    with self.assertRaisesRegex(ValueError, "share parent"):
                        with recorder.span("retrieve", name="bad", record_id="other", task_id="q", request_id="req", parent=parent):
                            pass
                    bad = dict(parent, inputs=None)
                    with self.assertRaises(ValueError):
                        validate_event(bad)
                    bad = dict(parent, inputs=[dict(id="x", kind="source", artifact="../private", sha256="b"*64, locator="/0")])
                    with self.assertRaises(ValueError):
                        validate_event(bad)
                    with self.assertRaises(ValueError):
                        validate_event(dict(parent, links=[dict(from_id="absent", to_id="absent", relation="derived_from")]))
                    with self.assertRaisesRegex(ValueError, "actual invocation"):
                        validate_event(dict(parent, operation="model", status="skipped"))

    def test_cached_replay_emits_only_actual_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"events.jsonl"
            with ObservationRecorder(path, run_id="r", dataset_pack_sha256="a"*64) as recorder:
                with recorder.span("add", name="add", record_id="u", request_id="req", replay="cached"):
                    pass
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["replay"], "cached")

    def test_append_preserves_stream_and_rejects_other_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            with ObservationRecorder(path, run_id="r", dataset_pack_sha256="a"*64) as recorder:
                with recorder.span("search", name="search", record_id="u", task_id="q", request_id="req"):
                    pass
            with ObservationRecorder(path, run_id="r", dataset_pack_sha256="a"*64, append=True) as recorder:
                with recorder.span("answer", name="answer", record_id="u", task_id="q", request_id="req"):
                    pass
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([event["operation"] for event in events], ["search", "answer"])
            with self.assertRaisesRegex(ValueError, "different run/pack"):
                ObservationRecorder(path, run_id="other", dataset_pack_sha256="b"*64, append=True)
