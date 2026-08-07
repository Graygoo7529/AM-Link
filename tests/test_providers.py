from __future__ import annotations

import json
import time

import httpx
import pytest

from aml_memory.providers import (
    OpenAICompatibleJsonModel,
    ProviderDeadlineExceeded,
    ZhipuEmbeddingProvider,
)


def test_openai_compatible_provider_uses_fixed_chat_completions_contract() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"facts":[]}'}}]},
        )

    provider = OpenAICompatibleJsonModel(
        api_key="test-key",
        base_url="https://proxy.example/v1",
        model="gpt-4o-mini",
        timeout_seconds=1,
        max_output_tokens=500,
        max_retries=0,
        max_concurrency=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = provider.generate_json(
            system_prompt="Return JSON.", payload={"task": "maintenance"}
        )
    finally:
        provider.close()

    assert result == {"facts": []}
    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    body = captured["body"]
    assert body["model"] == "gpt-4o-mini"
    assert body["max_tokens"] == 500
    assert body["response_format"] == {"type": "json_object"}


def test_zhipu_provider_batches_and_normalizes_embedding_3_vectors() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [3.0, 4.0, *([0.0] * 254)]}
                    for index, _ in enumerate(body["input"])
                ]
            },
        )

    provider = ZhipuEmbeddingProvider(
        api_key="test-key",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="embedding-3",
        dimensions=256,
        batch_size=2,
        timeout_seconds=1,
        max_retries=0,
        max_concurrency=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        vectors = provider.embed(["one", "two", "three"])
    finally:
        provider.close()

    assert [len(batch["input"]) for batch in captured] == [2, 1]
    assert all(batch["model"] == "embedding-3" for batch in captured)
    assert all(batch["dimensions"] == 256 for batch in captured)
    assert len(vectors) == 3
    assert vectors[0][:2] == [0.6, 0.8]


def test_model_provider_retries_protocol_transport_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("synthetic disconnect", request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"facts":[]}'}}]},
        )

    provider = OpenAICompatibleJsonModel(
        api_key="test-key",
        base_url="https://proxy.example/v1",
        model="gpt-4o-mini",
        timeout_seconds=1,
        max_output_tokens=500,
        max_retries=1,
        max_concurrency=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = provider.generate_json(
            system_prompt="Return JSON.", payload={"task": "maintenance"}
        )
    finally:
        provider.close()

    assert result == {"facts": []}
    assert attempts == 2


def test_provider_deadline_expires_before_request_or_capacity_wait() -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    provider = OpenAICompatibleJsonModel(
        api_key="test-key",
        base_url="https://proxy.example/v1",
        model="gpt-4o-mini",
        timeout_seconds=30,
        max_output_tokens=500,
        max_retries=2,
        max_concurrency=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        with provider.deadline_scope(time.monotonic() - 1):
            with pytest.raises(ProviderDeadlineExceeded):
                provider.generate_json(
                    system_prompt="Return JSON.", payload={"task": "maintenance"}
                )
    finally:
        provider.close()

    assert requests == 0
