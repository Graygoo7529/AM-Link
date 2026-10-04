from __future__ import annotations

import json
import io
import urllib.error
import unittest
from unittest.mock import patch

from benchmark.targets import AmlApiTarget, Mem0LibraryTarget, Mem0OssTarget


class FakeResponse:
    def __init__(self, body):
        self.status = 200
        self.body = json.dumps(body).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TargetTests(unittest.TestCase):
    def test_http_error_keeps_structured_error_body_for_trace(self) -> None:
        target = AmlApiTarget(
            base_url="https://memory.example",
            timeout=5,
            auth_scheme="none",
            api_key=None,
        )
        error = urllib.error.HTTPError(
            "https://memory.example/v1/memory/search",
            429,
            "Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"rate_limited"}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            response = target.search({"query": "remember", "user_id": "u1", "top_k": 5})
        self.assertEqual(response.error_code, "HTTP_429")
        self.assertEqual(response.raw_body, {"error": "rate_limited"})

    def test_aml_target_uses_official_paths_and_auth_header(self) -> None:
        response = FakeResponse({"success": True})
        target = AmlApiTarget(
            base_url="https://memory.example",
            timeout=5,
            auth_scheme="bearer",
            api_key="test-secret",
        )
        payload = {"request_id": "r1", "messages": [], "user_id": "u1", "session_id": "s1"}

        with patch("urllib.request.urlopen", return_value=response) as open_url:
            target.add(payload)
            target.search({"query": "remember", "user_id": "u1", "top_k": 5})

        add_request = open_url.call_args_list[0].args[0]
        search_request = open_url.call_args_list[1].args[0]
        self.assertEqual(add_request.full_url, "https://memory.example/v1/memory/add")
        self.assertEqual(search_request.full_url, "https://memory.example/v1/memory/search")
        self.assertEqual(add_request.get_header("Authorization"), "Bearer test-secret")

    def test_mem0_adapter_maps_add_scope_and_preserves_search_diagnostics(self) -> None:
        responses = [
            FakeResponse({"results": [{"id": "mem-1", "event": "ADD"}]}),
            FakeResponse(
                {
                    "results": [
                        {
                            "id": "mem-1",
                            "memory": "Alice prefers tea.",
                            "score": 0.93,
                            "score_details": {"semantic": 0.93},
                            "run_id": "session-1",
                        }
                    ]
                }
            ),
        ]
        target = Mem0OssTarget(
            base_url="http://127.0.0.1:8000",
            timeout=5,
            auth_scheme="none",
            api_key=None,
        )
        request = {
            "request_id": "req-1",
            "user_id": "user-1",
            "session_id": "session-1",
            "messages": [
                {"role": "user", "content": "I prefer tea.", "timestamp": 1000}
            ],
        }

        with patch("urllib.request.urlopen", side_effect=responses) as open_url:
            add_response = target.add(request)
            search_response = target.search({"query": "What does Alice prefer?", "user_id": "user-1", "top_k": 5})

        add_request = open_url.call_args_list[0].args[0]
        search_request = open_url.call_args_list[1].args[0]
        add_payload = json.loads(add_request.data)
        search_payload = json.loads(search_request.data)
        self.assertEqual(add_request.full_url, "http://127.0.0.1:8000/memories")
        self.assertEqual(search_request.full_url, "http://127.0.0.1:8000/search")
        self.assertEqual(add_payload["run_id"], "session-1")
        self.assertNotIn("request_id", add_payload)
        self.assertNotIn("timestamp", add_payload["messages"][0])
        self.assertTrue(search_payload["explain"])
        self.assertEqual(add_response.body["request_id"], "req-1")
        candidate = search_response.body["data"][0]
        self.assertEqual(candidate["target_metadata"]["score_details"], {"semantic": 0.93})
        self.assertEqual(candidate["content"], "Alice prefers tea.")

    def test_mem0_add_does_not_treat_empty_results_as_success(self) -> None:
        target = Mem0OssTarget(
            base_url="http://127.0.0.1:8000",
            timeout=5,
            auth_scheme="none",
            api_key=None,
        )
        response = FakeResponse({"results": []})
        request = {
            "request_id": "req-1",
            "user_id": "user-1",
            "session_id": "session-1",
            "messages": [{"role": "user", "content": "Remember this."}],
        }
        with patch("urllib.request.urlopen", return_value=response):
            result = target.add(request)
        self.assertEqual(result.error_type, "invalid_mem0_add_response")

    def test_mem0_library_maps_official_add_search_and_scopes(self) -> None:
        class FakeMemory:
            def __init__(self):
                self.add_call = None
                self.search_call = None

            def add(self, messages, **kwargs):
                self.add_call = (messages, kwargs)
                return {"results": [{"id": "mem-1", "event": "ADD"}]}

            def search(self, query, **kwargs):
                self.search_call = (query, kwargs)
                return {
                    "results": [
                        {
                            "id": "mem-1",
                            "memory": "Alice prefers tea.",
                            "score": 0.91,
                            "score_details": {"semantic": 0.91},
                        }
                    ]
                }

        memory = FakeMemory()
        target = Mem0LibraryTarget(memory)
        request = {
            "request_id": "req-1",
            "user_id": "user-1",
            "session_id": "session-1",
            "messages": [
                {"role": "user", "content": "I prefer tea.", "timestamp": 1000}
            ],
        }

        add_response = target.add(request)
        search_response = target.search(
            {"query": "What does Alice prefer?", "user_id": "user-1", "top_k": 5}
        )

        messages, add_options = memory.add_call
        self.assertEqual(messages, [{"role": "user", "content": "I prefer tea."}])
        self.assertEqual(add_options, {"user_id": "user-1", "run_id": "session-1"})
        query, search_options = memory.search_call
        self.assertEqual(query, "What does Alice prefer?")
        self.assertEqual(search_options["top_k"], 5)
        self.assertEqual(search_options["filters"], {"user_id": "user-1"})
        self.assertTrue(search_options["explain"])
        self.assertEqual(add_response.body["request_id"], "req-1")
        self.assertEqual(search_response.body["data"][0]["target_metadata"]["score_details"], {"semantic": 0.91})


if __name__ == "__main__":
    unittest.main()
