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
from amlink.projection import visible_fragments


class Scripted:
    embedding_fingerprint = "repair-tests"

    def __init__(self):
        self.calls = []
        self.fail_embedding = False
        self.review = lambda payload: {"reviews": [{"position": u["position"], "action": "keep", "text": None, "detail": "fixture source support",
            "source_positions": [i for i in u["source_positions"] if payload["sources"][i]["source_ref"] in u["proposal"]["source_refs"]]} for u in payload["units"]]}
        self.decide = lambda purpose, payload: ("reflection_stop", {}) if purpose == "reflection" else ("bfs_action", {"action": "stop"})

    def embed(self, texts, deadline):
        self.calls.append(("embedding", texts))
        if self.fail_embedding:
            self.fail_embedding = False
            raise MemoryError("provider_timeout", 504)
        return [[1.0, 0.0] for _ in texts]

    def tool(self, purpose, prompt, payload, tools, deadline):
        self.calls.append((purpose, payload))
        if purpose == "reflection_review":
            return "review", self.review(payload)
        assert len(dumps(tool_body(self.engine.config, purpose, prompt, payload, tools))) <= self.engine.config.model_input_chars
        if purpose == "select":
            positions = [row["position"] for row in payload["candidates"]]
            assert tools[0]["parameters"]["properties"]["positions"]["items"]["enum"] == positions
        name, args = self.decide(purpose, payload)
        if purpose == "bfs" and name == "bfs_action":
            name = "bfs_" + args["action"]
        if name in {"bfs_inspect", "reflection_inspect"} and "target" not in args:
            args = dict(args)
            key = "frontier_position" if name == "bfs_inspect" else "reference_position"
            target = {key: args.pop(key, None), "page_position": args.pop("page_position", None)}
            args["target"] = target
        return name, args


@pytest.fixture
def make():
    stores = []

    def create(**kwargs):
        config = replace(Config(embedding_enabled=False, search_model=False, reflection_min_adds=1), **kwargs)
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
            stage = payload['context']['reflection_control'].get('pending_mutation', {}).get('stage')
            if stage == 'relations': return 'reflection_relations', {'links': []}
            if stage == 'commit': return 'reflection_commit', {}
            return "reflection_items", {"items": [{"ref": "new:journey", "kind": "episode",
                "text": "A separate account of the journey", "source_refs": [payload["working"][0]["ref"]]}]}
        return "bfs_action", {"action": "stop"}

    provider.decide = decide
    engine.add(request("journey", ["I crossed the river to meet my sister."]))
    nodes = engine.store.nodes("u")
    vectors = list(engine.store.vector_rows("u", provider.embedding_fingerprint))
    assert len(nodes) == len(vectors) == 2
    # The current batch's minimum episode is no longer an OLD orientation match.
    assert len(engine.store.state("u")["context"]["items"]) == 1


def test_select_pages_visit_all_candidates_and_global_order_is_preserved(make):
    engine, provider = make(select_candidate_limit=2)
    candidates = [{"ref": f"memory:fact-{i}", "kind": "fact", "text": f"Topic fact {i}", "source_refs": []}
                  for i in range(5)]

    def decide(purpose, payload):
        assert "context" not in payload
        assert payload["question"] == "topic"
        return "select", {"positions": list(reversed([row["position"] for row in payload["candidates"]]))}

    provider.decide = decide
    selected = engine._select_refs("u", "topic", candidates, {"text": "x" * 200000}, time.monotonic() + 30, reason="query")
    calls = [payload for name, payload in provider.calls if name == "select"]
    assert [len(payload["candidates"]) for payload in calls] == [2, 2, 1, 5]
    assert [row["position"] for row in calls[2]["candidates"]] == [0]
    assert [row["position"] for row in calls[3]["candidates"]] == [0, 1, 2, 3, 4]
    assert {row["ref"] for payload in calls[:3] for row in payload["candidates"]} == {row["ref"] for row in candidates}
    assert [row["ref"] for row in selected] == ["memory:fact-4", "memory:fact-2", "memory:fact-3", "memory:fact-0", "memory:fact-1"]


def test_select_empty_is_valid_and_unknown_tool_is_error(make):
    engine, provider = make()
    row = {"ref": "memory:fact-a", "kind": "fact", "text": "A", "source_refs": []}
    provider.decide = lambda *args: ("select", {"positions": []})
    assert engine._select_refs("u", "B", [row], {}, time.monotonic() + 10, reason="query") == []
    provider.decide = lambda *args: ("select", {"refs": ["memory:fact-typo"]})
    with pytest.raises(MemoryError, match="selection_invalid_position"):
        engine._select_refs("u", "B", [row], {}, time.monotonic() + 10, reason="query")
    provider.decide = lambda *args: ("other_tool", {"refs": []})
    with pytest.raises(MemoryError, match="model_unknown_tool"):
        engine._select_refs("u", "B", [row], {}, time.monotonic() + 10, reason="query")


def test_select_rejects_mixed_valid_and_invalid_positions(make):
    engine, provider = make()
    rows = [{"ref": f"memory:fact-{i}", "kind": "fact", "text": f"Fact {i}", "source_refs": []}
            for i in range(3)]
    provider.decide = lambda purpose, payload: ("select", {"positions": [1, 20]})
    with pytest.raises(MemoryError, match="selection_invalid_position"):
        engine._select_refs("u", "facts", rows, {}, time.monotonic() + 10, reason="query")


def test_invalid_relation_is_filtered_without_dropping_grounded_items(make):
    engine, _ = make(mode="raw")
    engine.add(request("source", ["Maya discussed a design meeting."]))
    source = engine.store.raw("u")[0]["ref"]
    context = {"sources": engine.store.raw("u"), "items": {}, "memories": [], "new_refs": [source]}
    mutation = prepare_mutation({
        "items": [
            {"ref": "new:meeting", "kind": "event", "text": "Maya discussed a design meeting.", "source_refs": [source]},
            {"ref": "new:topic", "kind": "fact", "text": "The topic was design.", "source_refs": [source]},
        ],
        "links": [{"from_ref": "new:meeting", "to_ref": "new:topic", "relation": "about", "source_refs": [source]}],
        "forget": [],
    }, user="u", request_id="followup", number=1, context=context, store=engine.store)
    assert len(mutation["items"]) == 2
    assert mutation["links"] == []
    assert mutation["filtered_links"][0]["reason"] == "relation_type_mismatch"


def test_self_and_unknown_links_are_filtered_without_dropping_items(make):
    engine, _ = make(mode="raw")
    engine.add(request("source", ["Maya discussed a design meeting."]))
    source = engine.store.raw("u")[0]["ref"]
    context = {"sources": engine.store.raw("u"), "items": {}, "memories": [], "new_refs": [source]}
    mutation = prepare_mutation({
        "items": [{"ref": "new:meeting", "kind": "event",
                   "text": "Maya discussed a design meeting.", "source_refs": [source]}],
        "links": [
            {"from_ref": "new:meeting", "to_ref": "new:meeting", "relation": "same_event_as", "source_refs": [source]},
            {"from_ref": "new:meeting", "to_ref": "memory:event-not-loaded", "relation": "same_event_as", "source_refs": [source]},
        ],
        "forget": [],
    }, user="u", request_id="followup", number=1, context=context, store=engine.store)
    assert len(mutation["items"]) == 1
    assert mutation["links"] == []
    assert [link["reason"] for link in mutation["filtered_links"]] == ["self_link", "unknown_memory"]


def test_misplaced_root_time_fields_are_observable_and_discarded(make):
    engine, _ = make(mode="raw")
    engine.add(request("source", ["Maya discussed a design meeting."]))
    source = engine.store.raw("u")[0]["ref"]
    context = {"sources": engine.store.raw("u"), "items": {}, "memories": [], "new_refs": [source]}
    mutation = prepare_mutation({
        "items": [{"ref": "new:meeting", "kind": "event",
                   "text": "Maya discussed a design meeting.", "source_refs": [source]}],
        "links": [], "forget": [], "time_start": "2026-01-01",
    }, user="u", request_id="followup", number=1, context=context, store=engine.store)
    assert len(mutation["items"]) == 1
    assert mutation["filtered_fields"] == [{"field": "time_start", "reason": "mutation_field_without_item"}]


def test_select_merge_fits_with_full_survivor_set_and_heavy_lineage(make):
    engine, provider = make()
    candidates = [{"ref": f"memory:event-{'semantic-name-' * 5}{i}", "kind": "event",
        "text": (f"Person {i} completed a distinct project in 2023. " * 160),
        "source_refs": [f"raw:{j:032d}" for j in range(32)],
        "lineage": [{"branch": f"Which project did person {i} complete? " * 20,
                     "channel": "embedding", "rank": j, "cosine": .8} for j in range(4)]}
        for i in range(64)]
    provider.decide = lambda purpose, payload: ("select", {
        "positions": [row["position"] for row in payload["candidates"]]})
    selected = engine._select_refs("u", "Which projects were completed?", candidates, {},
                                  time.monotonic() + 30, reason="query")
    assert [row["ref"] for row in selected] == [row["ref"] for row in candidates]
    calls = [payload for purpose, payload in provider.calls if purpose == "select"]
    assert {row['ref'] for row in calls[-1]['candidates']} == {row['ref'] for row in candidates}
    assert all(row["narrative"] and row["ref"] for row in calls[-1]["candidates"])


def test_select_compacts_a_single_oversized_candidate(make):
    engine, provider = make(model_input_chars=12000, select_candidate_limit=24)
    candidate = {"ref": "memory:episode-long", "kind": "episode",
        "text": "A long source message with a date and a subject. " * 1200,
        "source_refs": [f"raw:{i:032d}" for i in range(64)],
        "lineage": [{"branch": "which date and subject?" * 20,
                     "channel": "embedding", "rank": i, "cosine": .8} for i in range(8)]}
    provider.decide = lambda purpose, payload: ("select", {"positions": [0]})
    selected = engine._select_refs("u", "which date?", [candidate], {},
                                   time.monotonic() + 30, reason="query")
    assert [row["ref"] for row in selected] == [candidate["ref"]]
    calls = [payload for purpose, payload in provider.calls if purpose == "select"]
    assert len(calls) == 1
    assert calls[0]["candidates"][0]["ref"] == candidate["ref"]


def test_reflection_schema_explains_event_time_and_episode_semantics(make):
    engine, _ = make()
    schema = engine._mutation_tool_schema({"sources": [{"ref": "raw:source", "role": "user"}]})
    item = schema["$defs"]["ItemChange"]["properties"]
    assert "Never copy the source message timestamp" in item["time_start"]["description"]
    assert "Exact time phrase" in item["time_expression"]["description"]
    assert "minimum episode is immutable" in item["kind"]["description"]


def test_about_episode_link_is_filtered_without_dropping_grounded_nodes(make):
    engine, _ = make(mode="raw")
    engine.add(request("source", ["I am Maya and I attended a design meeting."]))
    raw_ref = engine.store.raw("u")[0]["ref"]
    episode_ref = engine.store.request("u", "source")["episode_ref"]
    context = {"sources": engine.store.raw("u"), "items": {}, "memories": [], "new_refs": [raw_ref]}
    mutation = prepare_mutation({
        "items": [
            {"ref": "new:meeting", "kind": "event", "text": "Maya attended a design meeting.", "source_refs": [raw_ref]},
            {"ref": "new:maya", "kind": "person", "text": "Maya.", "source_refs": [raw_ref]},
        ],
        "links": [
            {"from_ref": "new:meeting", "to_ref": "new:maya", "relation": "about", "source_refs": [raw_ref]},
            {"from_ref": "new:meeting", "to_ref": episode_ref, "relation": "about", "source_refs": [raw_ref]},
        ],
        "forget": [],
    }, user="u", request_id="followup", number=1, context=context, store=engine.store)
    assert len(mutation["items"]) == 2
    assert [row["relation"] for row in mutation["links"]] == ["about"]
    assert mutation["filtered_links"][0]["reason"] == "about_requires_semantic_nodes"


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
        position = next((row["position"] for row in payload["context"]["choices"] if row["ref"] == ref), None)
        return "bfs_action", {"action": action, "frontier_position": position}

    provider.decide = decide
    result = engine.search(SearchRequest(user_id="u", query="Caroline", top_k=5))
    assert any(v['origin_ref'] == items[0]['ref'] and v['text'] == items[0]['text'] for v in visible_fragments(seen[1]))
    assert items[1]["ref"] in seen[2]["references"]
    assert any("Sweden" in edge.get("narrative", "") for edge in seen[3]["edges"])
    assert any(items[1]["ref"] in row["content"] for row in result["data"])
    assert any("--about-->" in row["content"] for row in result["data"])


def test_reflection_can_inspect_backlink_and_validate_newly_loaded_old_node(make):
    engine, provider = make(mode="raw", reflection_steps=8)
    items = graph(engine)
    engine.config = replace(engine.config, mode="graph", reflection_threshold=1)
    engine._search_refs = lambda *args, **kwargs: [engine.store.get("u", items[0]["ref"])]
    actions = iter([("reflection_backlinks", {"ref": items[0]["ref"]}),
                    ("reflection_inspect", {"ref": items[1]["ref"]}),
                    ("reflection_inspect", {"ref": items[0]["ref"]}), ("reflection_validate", {}),
                    ("reflection_relations", {"links": []}), ("reflection_commit", {})])
    contexts = []

    def decide(purpose, payload):
        contexts.append(payload["context"])
        if payload['step'] == 0:
            return 'reflection_items', {'items': [{**items[0], 'text': 'Caroline remembers that move.',
                'source_refs': [payload['working'][0]['ref']]}]}
        name, arguments = next(actions)
        ref = arguments.pop("ref", None)
        if ref:
            arguments["reference_position"] = next(row["position"] for row in payload["context"]["choices"] if row["ref"] == ref)
        return name, arguments

    provider.decide = decide
    assert engine.add(request("new", ["Caroline remembers that move."]))["success"]
    assert any(v['origin_ref'] == items[1]['ref'] and v['text'] == items[1]['text'] for v in visible_fragments(contexts[-1]))
    persisted = engine.store.state("u")["context"]
    assert items[1]["ref"] in persisted["items"]
    assert items[1]["ref"] in persisted["items"]


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
