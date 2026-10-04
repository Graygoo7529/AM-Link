from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark.core import run_replay, validate_manifest
from benchmark.targets import TargetResponse


class FakeTarget:
    def __init__(self) -> None:
        self.add_requests = []
        self.search_requests = []

    def add(self, request):
        self.add_requests.append(request)
        return TargetResponse(
            status_code=200,
            body={
                "success": True,
                "request_id": request["request_id"],
                "user_id": request["user_id"],
                "session_id": request["session_id"],
            },
        )

    def search(self, request):
        self.search_requests.append(request)
        return TargetResponse(
            status_code=200,
            body={
                "data": [
                    {"id": "noise", "content": "An unrelated detail."},
                    {"id": "memory-1", "content": "Alice prefers tea."},
                    {"id": "memory-2", "content": "She moved in March."},
                ]
            },
        )


def manifest_fixture():
    return {
        "schema_version": 1,
        "dataset": {"id": "test-public-slice"},
        "cases": [
            {
                "id": "case-1",
                "adds": [
                    {
                        "request_id": "add-1",
                        "messages": [{"role": "user", "content": "I prefer tea."}],
                        "user_id": "sample-1",
                        "session_id": "session-1",
                    }
                ],
                "searches": [
                    {
                        "id": "search-1",
                        "request": {"query": "What does Alice prefer and when did she move?", "user_id": "sample-1", "top_k": 3},
                        "expected": [
                            {"contains_any": ["Alice prefers tea."]},
                            {"contains_any": ["She moved in March."]},
                        ],
                        "category": "multi-hop",
                    }
                ],
            }
        ],
    }


class ReplayTests(unittest.TestCase):
    def test_replay_records_scoped_requests_evidence_ranks_and_full_trace(self) -> None:
        manifest = manifest_fixture()
        validate_manifest(manifest)
        target = FakeTarget()

        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "trace.jsonl"
            report = run_replay(
                manifest=manifest,
                cases=manifest["cases"],
                target=target,
                run_id="run-1",
                system={"name": "fake", "version": "1", "target": "aml-api"},
                trace_path=trace_path,
            )
            events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(target.add_requests[0]["request_id"].startswith("arena:run-1:"))
        self.assertTrue(target.add_requests[0]["user_id"].startswith("arena:run-1:"))
        self.assertEqual(target.search_requests[0]["user_id"], target.add_requests[0]["user_id"])
        self.assertEqual(report["summary"]["retrieval"]["overall"]["evidence_recall@5"], 1.0)
        self.assertEqual(report["summary"]["retrieval"]["overall"]["chain_coverage@1"], 0.0)
        self.assertEqual(report["summary"]["retrieval"]["overall"]["chain_coverage@5"], 1.0)
        self.assertEqual(events[1]["target_ranks"], [2, 3])
        self.assertEqual(events[1]["results"][1]["content"], "Alice prefers tea.")

    def test_official_target_rejects_non_200_add_response(self) -> None:
        from benchmark.core import _add_error

        request = {
            "request_id": "req-1",
            "user_id": "user-1",
            "session_id": "session-1",
        }
        response = TargetResponse(
            status_code=202,
            body={"success": True, **request},
        )
        self.assertEqual(_add_error(response, request, "aml-api"), "http_status_202")


if __name__ == "__main__":
    unittest.main()
