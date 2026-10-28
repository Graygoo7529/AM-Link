"""Migration checks at provider, configuration and atomic indexing boundaries."""
from dataclasses import replace
import json
import time

import httpx
import pytest

from amlink.config import Config
from amlink.engine import Engine
from amlink.errors import MemoryError
from amlink.observation import Observer
from amlink.providers import Providers
from amlink.schemas import AddRequest
from amlink.store import Store


def provider(handler):
    return Providers(Config(embedding_api_key="fixture"), Observer(),
                     transport=httpx.MockTransport(handler))


def response(request, dimensions=1024):
    body = json.loads(request.content)
    return httpx.Response(200, json={"data": [
        {"index": i, "embedding": [2.0 if j == i else 0.0 for j in range(dimensions)]}
        for i in reversed(range(len(body["input"])))],
        "model": "text-embedding-v4"})


def test_v4_request_matches_default_service_and_preserves_index_order():
    requests = []
    def handle(request):
        requests.append(request)
        return response(request)
    api = provider(handle)
    try:
        vectors = api.embed([f"Note {i}" for i in range(10)], time.monotonic() + 10)
        assert str(requests[0].url) == "https://api.zhizengzeng.com/v1/embeddings"
        assert json.loads(requests[0].content) == dict(model="text-embedding-v4",
            input=[f"Note {i}" for i in range(10)], dimensions=1024)
        assert len(vectors) == 10 and all(len(v) == 1024 and v[i] == 1 for i, v in enumerate(vectors))
        with pytest.raises(ValueError, match="batch size"):
            api.embed(["note"] * 11, time.monotonic() + 10)
        assert len(requests) == 1
    finally:
        api.close()


@pytest.mark.parametrize("setting,value,match", [
    ("AML2_EMBEDDING_MODEL", "embedding-3", "academic track"),
    ("AML2_EMBEDDING_BATCH", "11", "at most 10"),
])
def test_stale_environment_is_rejected(monkeypatch, setting, value, match):
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError, match=match):
        Config.from_env()


def test_wrong_embedding_dimensions_fail_without_retry():
    requests = []
    def handle(request):
        requests.append(request)
        return response(request, dimensions=512)
    api = provider(handle)
    try:
        with pytest.raises(MemoryError, match="embedding_output_invalid"):
            api.embed(["A note"], time.monotonic() + 10)
        assert len(requests) == 1
    finally:
        api.close()


@pytest.mark.parametrize("fail_second", [False, True])
def test_reflection_batches_twelve_nodes_and_commits_only_complete_vectors(tmp_path, fail_second):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        if fail_second and len(requests) == 3:
            return httpx.Response(503)
        return response(request)
    api = provider(handle)
    store = Store(tmp_path / "v4.sqlite3")
    engine = Engine(replace(api.config, mode="raw"), store, api, Observer())
    try:
        engine.add(AddRequest(user_id="u", session_id="s", request_id="a",
            messages=[dict(role="user", content="The project has twelve documented facts.")]))
        source = store.raw("u")[0]["ref"]
        prepared = dict(items=[dict(ref=f"memory:fact-{i}", kind="fact",
            text=f"Documented fact {i}.", source_refs=[source]) for i in range(12)],
            links=[], forget=[], filtered_links=[])
        if fail_second:
            with pytest.raises(MemoryError, match="provider_http_failure"):
                engine._commit_reflection("u", prepared, 1, time.monotonic() + 10)
        else:
            engine._commit_reflection("u", prepared, 1, time.monotonic() + 10)
        assert [len(r["input"]) for r in requests] == [1, 10, 2]
        expected = 1 if fail_second else 13
        assert len(store.nodes("u")) == expected
        assert len(list(store.vector_rows("u", api.embedding_fingerprint))) == expected
        assert store.state("u")["settled_through"] == (0 if fail_second else 1)
    finally:
        api.close()
        store.close()


def test_old_model_fingerprint_cannot_be_reused(tmp_path):
    from amlink.text import digest
    store = Store(tmp_path / "old.sqlite3")
    api = provider(lambda request: pytest.fail("must not call provider"))
    try:
        old = digest(["https://open.bigmodel.cn/api/paas/v4", "embedding-3", 512, "narrative-v1"])
        store.metadata("embedding_fingerprint", old)
        with pytest.raises(MemoryError, match="index_configuration_mismatch"):
            Engine(api.config, store, api, Observer())
        assert store.one("SELECT value FROM meta WHERE key='embedding_fingerprint'")["value"] == old
    finally:
        api.close()
        store.close()
