from dataclasses import replace

import pytest

from amlink.config import Config
from amlink.engine import Engine
from amlink.errors import MemoryError
from amlink.observation import Observer
from amlink.schemas import AddRequest, SearchRequest
from amlink.store import Store


class FakeProviders:
    embedding_fingerprint = "fake-embedding-v1"

    def __init__(self):
        self.calls = []
        self.reflection = None

    def embed(self, texts, deadline):
        self.calls.append(("embed", list(texts)))
        return [[1.0, 0.0] for _ in texts]

    def tool(self, purpose, prompt, payload, tools, deadline):
        if purpose == 'reflection_plan':
            return 'reflection_plan', {'groups': [{'title':'Fixture group', 'question':' '.join(r['text'] for r in payload['messages'])[:1200],
                'background_positions': []}], 'primary_groups': {f'p{i}': 0 for i in range(len(payload['messages']))}}
        self.calls.append((purpose, payload))
        if purpose == "reflection":
            if self.reflection:
                stage = payload['context']['reflection_control'].get('pending_mutation', {}).get('stage')
                if stage == 'relations': return 'reflection_relations', {'links': []}
                return "reflection_items", self.reflection(payload)
            return "reflection_stop", {"reason": "No additional semantic change is needed in this fixture."}
        if purpose == 'reflection_review':
            return 'review', {'resolution': 'commit', 'reason': 'Fixture handles this group.', 'reviews': [{'position': u['position'], 'action': 'keep', 'text': None, 'detail': 'fixture',
                'source_positions': [i for i in u['source_positions'] if {s['position']: s for s in payload['sources']}[i]['source_ref'] in u['proposal']['source_refs']]} for u in payload['units']]}
        if purpose == "bfs":
            return "bfs_stop", {"action": "stop"}
        raise AssertionError(f"unexpected tool {purpose}")

    def close(self):
        pass


@pytest.fixture
def make_engine(tmp_path):
    stores = []

    def make(**overrides):
        config = replace(Config(mode="graph", embedding_enabled=False, reflection_threshold=2, reflection_min_adds=1,
                                search_model=False), **overrides)
        store = Store(tmp_path / f"memory-{len(stores)}.sqlite3")
        stores.append(store)
        providers = FakeProviders()
        return Engine(config, store, providers, Observer()), providers

    yield make
    for store in stores:
        store.close()


def add(engine, request_id, text, *, session="s", user="u"):
    return engine.add(AddRequest(request_id=request_id, user_id=user, session_id=session,
                                 messages=[{"role": "user", "content": text}]))


def search(engine, query, *, user="u", top_k=5):
    return engine.search(SearchRequest(query=query, user_id=user, top_k=top_k))["data"]


def test_each_add_creates_searchable_episode_and_is_idempotent(make_engine):
    engine, providers = make_engine(mode="raw")
    response = add(engine, "a1", "The Orchid project uses blue notebooks.")
    assert response["success"] is True
    assert search(engine, "Orchid")
    assert len(engine.store.nodes("u")) == 1
    assert providers.calls == []
    assert add(engine, "a1", "The Orchid project uses blue notebooks.") == response
    assert len(engine.store.nodes("u")) == 1


def test_working_accumulates_until_reflection_and_episode_remains_visible(make_engine):
    engine, providers = make_engine(reflection_threshold=3)
    add(engine, "a1", "First note about the lighthouse")
    add(engine, "a2", "Second note about the lighthouse")
    assert engine.store.state("u")["settled_through"] == 0
    assert search(engine, "lighthouse")
    assert not [call for call in providers.calls if call[0] == "reflection"]
    add(engine, "a3", "Third note about the lighthouse")
    assert engine.store.state("u")["settled_through"] == 3
    assert not engine.store.raw("u", pending=True)


def test_reflection_mutation_is_source_grounded_and_search_can_inspect(make_engine):
    engine, providers = make_engine(reflection_threshold=1)

    def mutation(payload):
        source = payload["working"][0]["ref"]
        return {"items": [{"ref": "new:project", "kind": "fact",
                           "text": "The Orchid project uses blue notebooks.",
                           "source_refs": [source]}]}

    providers.reflection = mutation
    add(engine, "a1", "The Orchid project uses blue notebooks.")
    nodes = engine.store.nodes("u")
    assert {node["kind"] for node in nodes} == {"episode", "fact"}
    assert not engine.store.raw("u", pending=True)
    rows = search(engine, "blue notebooks")
    assert any("blue notebooks" in row["content"] for row in rows)


def test_user_adds_are_serialized_instead_of_rejected(make_engine):
    engine, _ = make_engine(mode="raw")
    lock = engine._lock("u")
    lock.acquire()
    try:
        # The implementation waits for the per-user coordinator; it no longer
        # returns a synthetic user_busy error for an ordinary concurrent Add.
        # Release from a helper thread so this test remains bounded.
        import threading
        result = []
        thread = threading.Thread(target=lambda: result.append(add(engine, "queued", "queued note")))
        thread.start()
        assert thread.is_alive()
    finally:
        lock.release()
    thread.join(timeout=2)
    assert result and result[0]["request_id"] == "queued"
