"""Behavioral regressions for the failures in the 2026-10-11 audit."""
from dataclasses import replace
import time

import pytest

from amlink.config import Config
from amlink.engine import Engine
from amlink.errors import MemoryError
from amlink.observation import Observer
from amlink.providers import tool_body
from amlink.reflection import prepare_mutation
from amlink.schemas import AddRequest, SearchRequest
from amlink.store import Store
from amlink.text import dumps


class Scripted:
    embedding_fingerprint = "repair-tests"

    def __init__(self):
        self.calls = []
        self.fail_embedding = False
        self.decide = lambda purpose, payload: ("reflection_stop", {}) if purpose == "reflection" else ("bfs_action", {"action": "stop"})

    def embed(self, texts, deadline):
        self.calls.append(("embedding", texts))
        if self.fail_embedding:
            self.fail_embedding = False
            raise MemoryError("provider_timeout", 504)
        return [[1.0, 0.0] for _ in texts]

    def tool(self, purpose, prompt, payload, tools, deadline):
        self.calls.append((purpose, payload))
        assert len(dumps(tool_body(self.engine.config, purpose, prompt, payload, tools))) <= self.engine.config.model_input_chars
        if purpose == "select":
            assert tools[0]["parameters"]["properties"]["refs"]["items"]["enum"] == [row["ref"] for row in payload["candidates"]]
        return self.decide(purpose, payload)


@pytest.fixture
def make():
    stores = []

    def create(**kwargs):
        config = replace(Config(embedding_enabled=False, search_model=False), **kwargs)
        store = Store(":memory:")
        stores.append(store)
        provider = Scripted()
        engine = Engine(config, store, provider, Observer())
        provider.engine = engine
        return engine, provider

    yield create
    for store in stores:
        store.close()


def request(rid, texts, timestamp=None):
    return AddRequest(user_id="u", session_id="session", request_id=rid,
        messages=[{"role": "user", "content": text, "timestamp": timestamp} for text in texts])


def test_failed_episode_not_completed_by_later_reflection(make):
    engine, provider = make(embedding_enabled=True, embedding_dimensions=2, reflection_threshold=1)
    first = request("failed", ["Orchid launch is on Raven Island"])
    provider.fail_embedding = True
    with pytest.raises(MemoryError, match="provider_timeout"):
        engine.add(first)
    engine.add(request("next", ["Maple notebooks are orange"]))
    assert engine.store.request("u", "failed")["status"] == "accepted"
    before = len(provider.calls)
    assert engine.add(first)["success"]
    assert len(provider.calls) > before
    assert engine.store.request("u", "failed")["episode_ref"]
    before = len(provider.calls)
    assert engine.add(first)["success"]
    assert len(provider.calls) == before


def test_batch_failure_retains_exact_watermark_and_replay_only_consumes_tail(make):
    engine, provider = make(reflection_threshold=1, batch_messages=2, max_batches=10)
    seen = []

    def decide(purpose, payload):
        seen.append([row["ordinal"] for row in payload["working"]])
        if len(seen) == 2:
            raise MemoryError("provider_timeout", 504)
        return "reflection_stop", {}

    provider.decide = decide
    req = request("batch", [f"Information item {i}" for i in range(5)])
    with pytest.raises(MemoryError, match="provider_timeout"):
        engine.add(req)
    assert engine.store.state("u")["settled_through"] == 2
    assert engine.store.request("u", "batch")["status"] == "accepted"
    assert engine.add(req)["success"]
    assert seen == [[1, 2], [3, 4], [3, 4], [5]]
    assert len(engine.store.raw("u")) == 5
    assert engine.store.state("u")["settled_through"] == 5
    assert engine.store.state("u")["context"]["items"]


def test_long_backlog_uses_full_bounded_batches_not_per_message_truncation(make):
    engine, provider = make(reflection_threshold=1, batch_messages=8, batch_chars=6000,
                            max_request_chars=64000, max_batches=64)
    texts = [(f"Evidence {i}: " + "Quoted narrative with date and subject. " * 18) for i in range(80)]
    engine.add(request("long", texts))
    calls = [payload for purpose, payload in provider.calls if purpose == "reflection"]
    assert len(calls) > 1
    seen = [row["text"] for payload in calls for row in payload["working"]]
    assert seen == texts
    assert all(len(payload["working"]) <= 8 for payload in calls)
    assert not engine.store.raw("u", pending=True)


def test_lock_wait_counts_toward_deadline(make):
    engine, _ = make(mode="raw", request_seconds=0.04, model_timeout=0.01)
    lock = engine._lock("u")
    lock.acquire()
    try:
        with pytest.raises(MemoryError, match="request_deadline"):
            engine.add(request("queued", ["Not yet accepted"]))
    finally:
        lock.release()
    assert not engine.store.raw("u")


def test_minimum_episode_cannot_be_replaced_with_summary(make):
    engine, _ = make(mode="raw")
    engine.add(request("original", ["I went to the group yesterday; not last week."], 1683554160000))
    item = engine.store.nodes("u")[0]
    context = {"sources": engine.store.raw("u"), "items": {item["ref"]: item}, "new_refs": []}
    with pytest.raises(MemoryError, match="minimum_episode_immutable"):
        prepare_mutation({"items": [{"ref": item["ref"], "kind": "episode", "text": "They attended a group.",
                                    "source_refs": item["source_refs"]}]},
                         user="u", request_id="later", number=1, context=context, store=engine.store)
    assert engine.store.get("u", item["ref"])["text"] == item["text"]


def test_derived_episode_also_gets_vector_and_workspace_survives(make):
    engine, provider = make(embedding_enabled=True, embedding_dimensions=2, reflection_threshold=1)

    def decide(purpose, payload):
        if purpose == "reflection":
            return "reflection_mutation", {"items": [{"ref": "new:journey", "kind": "episode",
                "text": "A separate account of the journey", "source_refs": [payload["working"][0]["ref"]]}]}
        return "bfs_action", {"action": "stop"}

    provider.decide = decide
    engine.add(request("journey", ["I crossed the river to meet my sister."]))
    nodes = engine.store.nodes("u")
    vectors = list(engine.store.vector_rows("u", provider.embedding_fingerprint))
    assert len(nodes) == len(vectors) == 2
    assert len(engine.store.state("u")["context"]["items"]) == 2


def test_select_pages_visit_all_candidates_and_global_order_is_preserved(make):
    engine, provider = make(select_candidate_limit=2)
    candidates = [{"ref": f"memory:fact-{i}", "kind": "fact", "text": f"Topic fact {i}", "source_refs": []}
                  for i in range(5)]

    def decide(purpose, payload):
        assert "context" not in payload
        assert payload["question"] == "topic"
        return "select", {"refs": [row["ref"] for row in reversed(payload["candidates"])]}

    provider.decide = decide
    selected = engine._select_refs("u", "topic", candidates, {"text": "x" * 200000}, time.monotonic() + 30, reason="query")
    calls = [payload for name, payload in provider.calls if name == "select"]
    assert [len(payload["candidates"]) for payload in calls] == [2, 2, 1, 5]
    assert {row["ref"] for payload in calls[:3] for row in payload["candidates"]} == {row["ref"] for row in candidates}
    assert [row["ref"] for row in selected] == ["memory:fact-4", "memory:fact-2", "memory:fact-3", "memory:fact-0", "memory:fact-1"]


def test_select_empty_is_valid_and_unknown_tool_is_error(make):
    engine, provider = make()
    row = {"ref": "memory:fact-a", "kind": "fact", "text": "A", "source_refs": []}
    provider.decide = lambda *args: ("select", {"refs": []})
    assert engine._select_refs("u", "B", [row], {}, time.monotonic() + 10, reason="query") == []
    provider.decide = lambda *args: ("select", {"refs": ["memory:fact-typo"]})
    with pytest.raises(MemoryError, match="selection_unknown_ref"):
        engine._select_refs("u", "B", [row], {}, time.monotonic() + 10, reason="query")
    provider.decide = lambda *args: ("other_tool", {"refs": []})
    with pytest.raises(MemoryError, match="model_unknown_tool"):
        engine._select_refs("u", "B", [row], {}, time.monotonic() + 10, reason="query")


def graph(engine):
    engine.add(request("source", ["Caroline was born in Sweden and moved from her home country four years ago."], 1683554160000))
    source = engine.store.raw("u")[0]["ref"]
    items = [{"ref": "memory:person-caroline", "kind": "person", "text": "Caroline, from Sweden.", "source_refs": [source]},
             {"ref": "memory:fact-move", "kind": "fact", "text": "Caroline moved from her home country four years ago.", "source_refs": [source]},
             {"ref": "memory:entity-sweden", "kind": "entity", "text": "Sweden is Caroline's home country.", "source_refs": [source]}]
    links = [{"from_ref": "memory:fact-move", "to_ref": item["ref"], "relation": "about", "source_refs": [source]}
             for item in (items[0], items[2])]
    engine.store.commit_mutation("u", {"items": items, "links": links, "forget": []}, watermark=1, fingerprint="test", vectors={})
    return items


def test_search_inspect_then_backlink_same_ref_and_follow_new_ref(make):
    engine, provider = make(mode="raw", search_model=True, search_steps=5)
    items = graph(engine)
    engine.config = replace(engine.config, mode="graph", max_nodes=1)
    engine._search_refs = lambda *args, **kwargs: [dict(engine.store.get("u", items[0]["ref"]), score=9)]
    decisions = iter([("inspect", items[0]["ref"]), ("backlinks", items[0]["ref"]),
                      ("inspect", items[1]["ref"]), ("stop", None)])
    seen = []

    def decide(purpose, payload):
        seen.append(payload["context"])
        action, ref = next(decisions)
        return "bfs_action", {"action": action, **({"ref": ref} if ref else {})}

    provider.decide = decide
    result = engine.search(SearchRequest(user_id="u", query="Caroline", top_k=5))
    assert seen[1]["items"][items[0]["ref"]]["text"] == items[0]["text"]
    assert items[1]["ref"] in seen[2]["references"]
    assert any("Sweden" in edge.get("narrative", "") for edge in seen[3]["edges"])
    assert any(row["id"] == items[1]["ref"] for row in result["data"])
    assert any("--about-->" in row["content"] for row in result["data"])


def test_reflection_can_inspect_backlink_and_validate_newly_loaded_old_node(make):
    engine, provider = make(mode="raw", reflection_steps=6)
    items = graph(engine)
    engine.config = replace(engine.config, mode="graph", reflection_threshold=1)
    engine._search_refs = lambda *args, **kwargs: [engine.store.get("u", items[0]["ref"])]
    actions = iter([("reflection_inspect", {"ref": items[0]["ref"]}),
                    ("reflection_backlinks", {"ref": items[0]["ref"]}),
                    ("reflection_inspect", {"ref": items[1]["ref"]}), ("reflection_stop", {})])
    contexts = []

    def decide(purpose, payload):
        contexts.append(payload["context"])
        return next(actions)

    provider.decide = decide
    assert engine.add(request("new", ["Caroline remembers that move."]))["success"]
    assert items[1]["ref"] in contexts[-1]["items"]
    persisted = engine.store.state("u")["context"]
    assert items[1]["ref"] in persisted["items"]
    assert any(item["ref"] == items[1]["ref"] for item in persisted["memories"])


def test_pack_preserves_input_order_propagates_date_and_deduplicates_source(make):
    engine, _ = make(mode="raw")
    engine.add(request("a", ["I went to the support group yesterday."], 1683554160000))
    engine.add(request("b", ["I painted a sunrise last year."], 1683554160000))
    a = engine.store.get("u", engine.store.request("u", "a")["episode_ref"])
    b = engine.store.get("u", engine.store.request("u", "b")["episode_ref"])
    rows = engine._assemble("u", "support group", [dict(a, score=0.1), dict(b, score=100)], 5, "support group")
    assert [row["id"] for row in rows] == [a["ref"], b["ref"]]
    assert rows[0]["content"].count("I went to the support group yesterday.") == 1
    assert "2023-05-08T13:56:00Z" in rows[0]["content"]
    assert "yesterday" in rows[0]["content"]
    assert rows[0]["score"] > rows[1]["score"]


def test_query_lexical_rank_not_counted_twice(make):
    engine, _ = make(mode="raw")
    engine.add(request("a", ["Orchid expedition launch date"])); engine.add(request("b", ["Orchid notes"]))
    rows = engine._search_refs("u", "Orchid", {}, time.monotonic() + 10)
    assert rows[0]["score"] == pytest.approx(1/61)
