from dataclasses import replace

import pytest

from amlink.config import Config
from amlink.engine import Engine
from amlink.observation import Observer
from amlink.store import Store


class FakeProviders:
    embedding_fingerprint = "test-vectors-v1"

    def __init__(self):
        self.calls = []
        self.handler = lambda purpose, data: {}
        self.embed_handler = lambda texts: [[1., 0.] for _ in texts]

    def json(self, purpose, prompt, payload, deadline):
        self.calls.append((purpose, payload))
        return self.handler(purpose, payload)

    def embed(self, texts, deadline):
        self.calls.append(("embed", texts))
        return self.embed_handler(texts)

    def close(self):
        pass


@pytest.fixture
def make_engine(tmp_path):
    stores = []
    def make(**options):
        config = replace(Config(mode="graph", reflection_threshold=1, search_model=False,
                                embedding_dimensions=2), **options)
        store = Store(tmp_path / f"memory-{len(stores)}.sqlite3")
        stores.append(store)
        providers = FakeProviders()
        return Engine(config, store, providers, Observer()), providers
    yield make
    for store in stores:
        store.close()

