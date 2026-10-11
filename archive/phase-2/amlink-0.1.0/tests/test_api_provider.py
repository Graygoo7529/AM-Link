import json
import time
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from amlink.api import create_app
from amlink.config import Config
from amlink.errors import MemoryError
from amlink.observation import Observer
from amlink.providers import Providers


def test_api_exact_contract_auth_and_validation(tmp_path):
    cfg = Config(mode="raw", db_path=str(tmp_path / "api.sqlite3"), auth_scheme="bearer", api_key="test-only")
    with TestClient(create_app(config=cfg)) as client:
        assert client.get("/health").status_code == 200
        request = {"request_id": "r", "user_id": "u", "session_id": "s", "messages": [{"role": "user", "content": "blue comet"}]}
        assert client.post("/v1/memory/add", json=request).status_code == 401
        headers = {"Authorization": "Bearer test-only"}
        response = client.post("/v1/memory/add", json=request, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"success": True, "request_id": "r", "user_id": "u", "session_id": "s"}
        result = client.post("/v1/memory/search", headers=headers, json={"query": "comet", "user_id": "u", "top_k": 1})
        assert result.status_code == 200 and len(result.json()["data"]) == 1
        assert set(result.json()["data"][0]) == {"id", "content", "score", "created_at"}
        for bad in (True, 101, "5", 0):
            assert client.post("/v1/memory/search", headers=headers, json={"query": "comet", "user_id": "u", "top_k": bad}).status_code == 422
        assert client.post("/v1/memory/add", headers=headers, json={**request, "surprise": True}).status_code == 422


@pytest.mark.parametrize("status", [429, 500, 401])
def test_provider_one_attempt_no_retry(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "do not expose body"})
    provider = Providers(Config(llm_api_key="test"), Observer(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(MemoryError) as error:
            provider.json("test", "JSON", {}, time.monotonic()+10)
        assert len(calls) == 1
        assert "do not expose" not in str(error.value)
    finally:
        provider.close()


def test_embedding_index_reorder_and_dimension_validation():
    def handler(request):
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0., 2.]}, {"index": 0, "embedding": [3., 0.]}]})
    provider = Providers(Config(embedding_dimensions=2, embedding_api_key="test"), Observer(), transport=httpx.MockTransport(handler))
    try:
        assert provider.embed(["a", "b"], time.monotonic()+10) == [[1., 0.], [0., 1.]]
        provider.config = replace(provider.config, embedding_dimensions=3)
        with pytest.raises(MemoryError, match="embedding_output_invalid"):
            provider.embed(["a", "b"], time.monotonic()+10)
    finally:
        provider.close()


def test_provider_budget_stops_before_network():
    count = []
    provider = Providers(Config(llm_api_key="test", max_provider_calls=1), Observer(),
        transport=httpx.MockTransport(lambda request: count.append(1) or httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})))
    try:
        provider.json("test", "JSON", {}, time.monotonic()+10)
        with pytest.raises(MemoryError, match="provider_run_budget"):
            provider.json("test", "JSON", {}, time.monotonic()+10)
        assert len(count) == 1
    finally:
        provider.close()
