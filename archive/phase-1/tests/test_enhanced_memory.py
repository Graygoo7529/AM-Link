from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aml_memory.api import create_app
from aml_memory.maintenance import FactProposal, MemoryMaintainer
from aml_memory.models import SearchResult
from aml_memory.providers import ProviderError
from aml_memory.repository import (
    GraphPath,
    NodeRecord,
    RankingFeatures,
    SQLiteMemoryRepository,
    stable_memory_id,
    stable_structured_id,
)
from aml_memory.service import _fuse_rankings, _rank_graph_paths
from aml_memory.settings import Settings


class FakeModelProvider:
    model = "gpt-4o-mini"

    def __init__(self) -> None:
        self.tasks: list[str] = []
        self.payloads: list[dict[str, Any]] = []
        self.closed = False

    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        assert system_prompt
        self.payloads.append(payload)
        task = str(payload["task"])
        self.tasks.append(task)
        if task == "maintenance":
            return {
                "facts": [
                    {
                        "title": "Preferred vehicle",
                        "content": "The user's preferred vehicle is an automobile.",
                        "source_ordinals": [0],
                        "entities": ["Automobile"],
                        "concepts": ["Transportation preference"],
                        "event_time": None,
                        "confidence": 0.93,
                        "supersedes_memory_ids": [],
                    }
                ],
                "tombstone_memory_ids": [],
            }
        assert task == "search_plan"
        candidates = payload.get("candidates", [])
        preferred_ids = [candidates[0]["id"]] if candidates else []
        return {
            "retrieval_queries": ["automobile preference"],
            "keywords": ["automobile"],
            "entity_names": ["Automobile"],
            "time_hints": [],
            "preferred_memory_ids": preferred_ids,
            "intent": "general",
        }

    def close(self) -> None:
        self.closed = True


class FakeEmbeddingProvider:
    model = "embedding-3"
    dimensions = 256

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.closed = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            vector[0 if any(word in text.lower() for word in ("car", "automobile")) else 1] = 1.0
            vectors.append(vector)
        return vectors

    def close(self) -> None:
        self.closed = True


class FailingModelProvider(FakeModelProvider):
    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.tasks.append(str(payload["task"]))
        raise ProviderError("synthetic model outage")


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        raise ProviderError("synthetic embedding outage")


class RecoveringModelProvider(FakeModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.fail_once = True

    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if self.fail_once and payload["task"] == "maintenance":
            self.fail_once = False
            self.tasks.append("maintenance")
            raise ProviderError("synthetic first-attempt outage")
        return super().generate_json(system_prompt=system_prompt, payload=payload)


class ToggleModelProvider(FakeModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.available = False

    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if payload["task"] == "maintenance" and not self.available:
            self.tasks.append("maintenance")
            raise ProviderError("synthetic provider outage")
        return super().generate_json(system_prompt=system_prompt, payload=payload)


class CrossUserMutationProvider(FakeModelProvider):
    def __init__(self, foreign_memory_id: str) -> None:
        super().__init__()
        self.foreign_memory_id = foreign_memory_id

    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if payload["task"] == "search_plan":
            return super().generate_json(system_prompt=system_prompt, payload=payload)
        self.tasks.append("maintenance")
        return {
            "facts": [
                {
                    "title": "Invalid update",
                    "content": "This update must be rejected.",
                    "source_ordinals": [0],
                    "entities": [],
                    "concepts": [],
                    "event_time": None,
                    "confidence": 0.5,
                    "supersedes_memory_ids": [self.foreign_memory_id],
                }
            ],
            "tombstone_memory_ids": [],
        }


class VersionedModelProvider(FakeModelProvider):
    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        task = str(payload["task"])
        self.tasks.append(task)
        if task == "search_plan":
            historical = "previously" in str(payload["query"]).lower()
            return {
                "retrieval_queries": ["Paris"] if historical else [],
                "keywords": [],
                "entity_names": [],
                "time_hints": ["previously"] if historical else [],
                "intent": "historical" if historical else "current",
            }
        message = str(payload["new_events"][0]["content"])
        if "Berlin" in message:
            content = "The user lives in Berlin."
            valid_from = "2026-01-01"
            supersedes = [
                stable_structured_id(
                    "run:user-1", "fact", "The user lives in Paris."
                )
            ]
        else:
            content = "The user lives in Paris."
            valid_from = "2025-01-01"
            supersedes = []
        return {
            "facts": [
                {
                    "title": "Current residence",
                    "content": content,
                    "source_ordinals": [0],
                    "entities": [],
                    "concepts": ["Residence"],
                    "event_time": valid_from,
                    "valid_from": valid_from,
                    "valid_to": None,
                    "confidence": 0.95,
                    "supersedes_memory_ids": supersedes,
                }
            ],
            "tombstone_memory_ids": [],
        }


class TombstoneModelProvider(FakeModelProvider):
    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if payload["task"] == "maintenance" and "forget" in str(
            payload["new_events"][0]["content"]
        ).lower():
            self.tasks.append("maintenance")
            return {
                "facts": [],
                "tombstone_memory_ids": [
                    stable_structured_id(
                        "run:user-1",
                        "fact",
                        "The user's preferred vehicle is an automobile.",
                    )
                ],
            }
        return super().generate_json(system_prompt=system_prompt, payload=payload)


class CanonicalFactProvider(FakeModelProvider):
    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if payload["task"] == "search_plan":
            return super().generate_json(system_prompt=system_prompt, payload=payload)
        self.tasks.append("maintenance")
        content = str(payload["new_events"][0]["content"])
        return {
            "facts": [
                {
                    "title": "Vehicle preference",
                    "content": content,
                    "canonical_key": "preference:vehicle=compact_automobile",
                    "source_ordinals": [0],
                    "entities": [],
                    "concepts": [],
                    "event_time": None,
                    "confidence": 0.9,
                    "supersedes_memory_ids": [],
                }
            ],
            "tombstone_memory_ids": [],
        }


class OutOfScopeMutationProvider(FakeModelProvider):
    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        return {
            "facts": [],
            "tombstone_memory_ids": ["fact_not_retrieved"],
        }


class InvalidThenValidMaintenanceProvider(FakeModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.maintenance_attempts = 0

    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if payload["task"] == "maintenance":
            self.maintenance_attempts += 1
            if self.maintenance_attempts == 1:
                self.payloads.append(payload)
                self.tasks.append("maintenance")
                return {
                    "facts": [],
                    "tombstone_memory_ids": [],
                    "unexpected": True,
                }
            assert payload["schema_retry"] == {
                "attempt": 2,
                "validation_errors": [
                    {"path": "unexpected", "type": "extra_forbidden"}
                ],
            }
        return super().generate_json(system_prompt=system_prompt, payload=payload)


class NullListMaintenanceProvider(FakeModelProvider):
    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if payload["task"] != "maintenance":
            return super().generate_json(system_prompt=system_prompt, payload=payload)
        self.payloads.append(payload)
        self.tasks.append("maintenance")
        return {
            "facts": [
                {
                    "title": "Preferred vehicle",
                    "content": "The user's preferred vehicle is an automobile.",
                    "source_ordinals": [0],
                    "entities": None,
                    "concepts": None,
                    "confidence": None,
                    "supersedes_memory_ids": None,
                }
            ],
            "tombstone_memory_ids": None,
        }


class LinkInspectModelProvider(FakeModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.maintenance_calls = 0
        self.preferred_link_id: str | None = None

    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        task = str(payload["task"])
        self.tasks.append(task)
        if task == "search_plan":
            linked = next(
                candidate
                for candidate in payload["candidates"]
                if candidate["retrieval_source"] == "link_inspect"
            )
            self.preferred_link_id = str(linked["id"])
            return {
                "retrieval_queries": [],
                "keywords": [],
                "entity_names": [],
                "time_hints": [],
                "preferred_memory_ids": [self.preferred_link_id],
                "intent": "multi_hop",
            }
        self.maintenance_calls += 1
        if self.maintenance_calls == 1:
            title = "Alice employment"
            content = "Alice works at Lab A."
            concepts = ["Employment"]
        else:
            title = "Alice mentoring"
            content = "Alice mentors Bob."
            concepts = ["Mentoring"]
        return {
            "facts": [
                {
                    "title": title,
                    "content": content,
                    "canonical_key": f"alice:{self.maintenance_calls}",
                    "source_ordinals": [0],
                    "entities": ["Alice"],
                    "concepts": concepts,
                    "event_time": None,
                    "confidence": 0.95,
                    "supersedes_memory_ids": [],
                }
            ],
            "tombstone_memory_ids": [],
        }


class FailsExpandedQueryEmbedding(FakeEmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        if len(self.calls) >= 3:
            self.calls.append(texts)
            raise ProviderError("synthetic expanded query outage")
        return super().embed(texts)


def test_high_ranked_fact_brings_existing_direct_evidence_forward() -> None:
    fact = SearchResult(id="fact", content="Caroline prefers counseling.")
    source = SearchResult(id="source", content="I want to pursue counseling.")
    distractor = SearchResult(id="distractor", content="Counseling workshop.")
    features = {
        "fact": RankingFeatures(
            kind="fact",
            confidence=0.9,
            activity=0.0,
            status="active",
            event_time=None,
            valid_from=None,
            valid_to=None,
            evidence_group_id="fact-group",
            source_event_ids=("source",),
            resolved_time_start=None,
            resolved_time_end=None,
        ),
        "source": RankingFeatures(
            kind="daily",
            confidence=1.0,
            activity=0.0,
            status="active",
            event_time=None,
            valid_from=None,
            valid_to=None,
            evidence_group_id="source-group",
            source_event_ids=("source",),
            resolved_time_start=None,
            resolved_time_end=None,
        ),
        "distractor": RankingFeatures(
            kind="daily",
            confidence=1.0,
            activity=0.0,
            status="active",
            event_time=None,
            valid_from=None,
            valid_to=None,
            evidence_group_id="distractor-group",
            source_event_ids=("distractor",),
            resolved_time_start=None,
            resolved_time_end=None,
        ),
    }

    ranked = _fuse_rankings(
        [fact, distractor, source],
        [],
        [],
        [source],
        [],
        [fact],
        features,
        intent="multi_hop",
        limit=3,
    )

    ranked_ids = [item.id for item in ranked]
    assert set(ranked_ids[:2]) == {"fact", "source"}
    assert ranked_ids.index("source") < ranked_ids.index("distractor")


def enhanced_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=tmp_path / "markdown",
        llm_enabled=True,
        openai_api_key="fake-model-key",
        embedding_enabled=True,
        embedding_api_key="fake-embedding-key",
        embedding_dimensions=256,
    )


def add_payload(
    *,
    user_id: str = "run:user-1",
    request_id: str = "run:add-1",
    content: str = "I prefer driving an automobile.",
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "messages": [{"role": "user", "content": content}],
        "user_id": user_id,
        "session_id": "run:session-1",
    }


def test_enhanced_add_search_is_structured_vectorized_and_idempotent(
    tmp_path: Path,
) -> None:
    settings = enhanced_settings(tmp_path)
    model = FakeModelProvider()
    embeddings = FakeEmbeddingProvider()
    payload = add_payload()
    application = create_app(
        settings,
        model_provider=model,
        embedding_provider=embeddings,
    )

    with TestClient(application) as client:
        first = client.post("/v1/memory/add", json=payload)
        replay = client.post("/v1/memory/add", json=payload)
        assert model.tasks == ["maintenance"]
        assert len(embeddings.calls) == 2
        found = client.post(
            "/v1/memory/search",
            json={
                "query": "Which car does the user prefer?",
                "options": None,
                "user_id": payload["user_id"],
                "top_k": 10,
            },
        )

    assert first.status_code == replay.status_code == found.status_code == 200
    assert model.tasks == ["maintenance", "search_plan"]
    assert model.payloads[-1]["candidates"]
    candidate_ids = {candidate["id"] for candidate in model.payloads[-1]["candidates"]}
    assert found.json()["data"][0]["id"] in candidate_ids
    assert len(found.json()["data"]) == 2
    assert sum(
        item["id"].startswith(("fact_", "ent_", "con_"))
        for item in found.json()["data"]
    ) == 1
    assert len(embeddings.calls) == 4
    assert "automobile preference" in embeddings.calls[-1][0]
    assert any("automobile" in item["content"].lower() for item in found.json()["data"])
    assert model.closed and embeddings.closed

    metrics = application.state.memory_service.metrics_snapshot()
    assert metrics == {
        "llm_maintenance_calls": 1,
        "llm_search_calls": 1,
        "embedding_context_calls": 1,
        "embedding_search_calls": 2,
        "embedding_index_calls": 1,
        "embedding_index_texts": 4,
    }

    with sqlite3.connect(settings.db_path) as connection:
        kinds = dict(
            connection.execute(
                "SELECT kind, COUNT(*) FROM memory_nodes GROUP BY kind"
            ).fetchall()
        )
        assert kinds == {"concept": 1, "daily": 1, "entity": 1, "fact": 1}
        assert connection.execute("SELECT COUNT(*) FROM memory_links").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 4
        assert connection.execute(
            "SELECT status FROM maintenance_runs"
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT status, attempts FROM enrichment_jobs"
        ).fetchone() == ("completed", 1)

    graph = SQLiteMemoryRepository(settings.db_path).expand_links(
        user_id="run:user-1",
        seed_ids=[stable_memory_id("run:user-1", "run:add-1", 0)],
        limit=20,
        query_text="automobile",
    )
    assert any(item.id.startswith("fact_") and item.score == 1.0 for item in graph)
    assert any(item.id.startswith("con_") and item.score == 0.5 for item in graph)

    graph_paths = SQLiteMemoryRepository(settings.db_path).expand_link_paths(
        user_id="run:user-1",
        seed_ids=[stable_memory_id("run:user-1", "run:add-1", 0)],
        limit=20,
        query_text="automobile",
    )
    concept_path = next(
        path for path in graph_paths if path.result.id.startswith("con_")
    )
    assert concept_path.hop == 2
    assert concept_path.path_ids[0] == stable_memory_id(
        "run:user-1", "run:add-1", 0
    )
    assert concept_path.relations == ("supports", "related_to")
    assert concept_path.source_event_ids == (
        stable_memory_id("run:user-1", "run:add-1", 0),
    )

    user_root = next((settings.markdown_view_dir).iterdir())
    assert len(list((user_root / "fact").glob("*.md"))) == 1
    assert len(list((user_root / "entity").glob("*.md"))) == 1
    assert len(list((user_root / "concept").glob("*.md"))) == 1


def test_maintenance_mutations_are_limited_to_retrieved_memory_ids() -> None:
    provider = OutOfScopeMutationProvider()
    maintainer = MemoryMaintainer(provider)
    context = (
        NodeRecord(
            memory_id="fact_retrieved",
            user_id="run:user-1",
            kind="fact",
            title="Known fact",
            content="Known fact with evidence.",
            event_time=None,
            valid_from=None,
            valid_to=None,
            created_at="2026-08-01T00:00:00Z",
            updated_at="2026-08-01T00:00:00Z",
            confidence=0.9,
            activity=1.0,
            status="active",
            version=2,
            source_event_ids='["mem_source"]',
            canonical_key="known:key",
            evidence_group_id="group_known",
            time_expression=None,
            resolved_time_start=None,
            resolved_time_end=None,
            time_precision=None,
        ),
    )

    with pytest.raises(ValueError, match="retrieved memory IDs"):
        maintainer.plan(
            events=(),
            context=context,
            links=(),
            working_memory="# Working Memory\n",
        )

    payload = provider.payloads[0]
    assert payload["mutable_memory_ids"] == ["fact_retrieved"]
    assert payload["existing_memories"][0]["canonical_key"] == "known:key"
    assert payload["existing_memories"][0]["source_event_ids"] == ["mem_source"]


def test_maintenance_retries_one_schema_failure_without_relaxing_validation(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
    )
    provider = InvalidThenValidMaintenanceProvider()
    with TestClient(create_app(settings, model_provider=provider)) as client:
        added = client.post("/v1/memory/add", json=add_payload())

    assert added.status_code == 200
    assert provider.maintenance_attempts == 2
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT status FROM maintenance_runs"
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE kind = 'fact'"
        ).fetchone()[0] == 1


def test_maintenance_normalizes_null_optional_lists_without_schema_retry(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
    )
    provider = NullListMaintenanceProvider()
    with TestClient(create_app(settings, model_provider=provider)) as client:
        added = client.post("/v1/memory/add", json=add_payload())

    assert added.status_code == 200
    assert provider.tasks == ["maintenance"]
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT status FROM maintenance_runs"
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT confidence FROM memory_nodes WHERE kind = 'fact'"
        ).fetchone()[0] == 0.8


def test_fact_accepts_only_empty_misplaced_plan_tombstone_field() -> None:
    base = {
        "title": "Known fact",
        "content": "Known fact content.",
        "source_ordinals": [0],
    }
    accepted = FactProposal.model_validate(
        {**base, "tombstone_memory_ids": []}
    )
    assert accepted.title == "Known fact"

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        FactProposal.model_validate(
            {**base, "tombstone_memory_ids": ["fact_should_not_be_ignored"]}
        )


def test_search_planner_sees_link_inspect_candidates_and_can_seed_them(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
    )
    provider = LinkInspectModelProvider()
    with TestClient(create_app(settings, model_provider=provider)) as client:
        assert client.post(
            "/v1/memory/add",
            json=add_payload(content="Alice works at Lab A."),
        ).status_code == 200
        assert client.post(
            "/v1/memory/add",
            json=add_payload(
                request_id="run:add-2", content="Alice mentors Bob."
            ),
        ).status_code == 200
        found = client.post(
            "/v1/memory/search",
            json={
                "query": "What is connected to Lab A?",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 20,
            },
        )

    assert found.status_code == 200
    planner_payload = provider.payloads[-1]
    assert any(
        candidate["retrieval_source"] == "link_inspect"
        for candidate in planner_payload["candidates"]
    )
    assert provider.preferred_link_id is not None
    assert any("Alice mentors Bob" in item["content"] for item in found.json()["data"])


def test_expanded_embedding_failure_degrades_to_initial_semantic_results(
    tmp_path: Path,
) -> None:
    settings = enhanced_settings(tmp_path)
    embeddings = FailsExpandedQueryEmbedding()
    with TestClient(
        create_app(
            settings,
            model_provider=FakeModelProvider(),
            embedding_provider=embeddings,
        )
    ) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        found = client.post(
            "/v1/memory/search",
            json={
                "query": "Which car does the user prefer?",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 10,
            },
        )

    assert found.status_code == 200
    assert found.json()["data"]
    assert len(embeddings.calls) == 4


def test_search_graph_depth_is_intent_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app(
        Settings(
            db_path=tmp_path / "memory.db",
            markdown_view_dir=None,
            llm_enabled=True,
            openai_api_key="fake-model-key",
        ),
        model_provider=FakeModelProvider(),
    )
    with TestClient(application) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        repository = application.state.memory_service.repository
        original = repository.expand_link_paths
        observed_hops: list[int] = []

        def tracking_expand_link_paths(**kwargs: Any) -> list[GraphPath]:
            observed_hops.append(int(kwargs["max_hops"]))
            return original(**kwargs)

        monkeypatch.setattr(repository, "expand_link_paths", tracking_expand_link_paths)
        assert client.post(
            "/v1/memory/search",
            json={
                "query": "Why is automobile related?",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 10,
            },
        ).status_code == 200
        assert observed_hops[-2:] == [1, 3]
        assert client.post(
            "/v1/memory/search",
            json={
                "query": "automobile",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 10,
            },
        ).status_code == 200
        assert observed_hops[-2:] == [1, 2]


def test_maintenance_threshold_batches_pending_adds(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=tmp_path / "markdown",
        llm_enabled=True,
        openai_api_key="fake-model-key",
        maintenance_event_threshold=2,
        maintenance_char_threshold=10_000,
    )
    model = FakeModelProvider()
    first_payload = add_payload(content="I prefer compact cars.")
    second_payload = add_payload(
        request_id="run:add-2",
        content="I also enjoy taking trains.",
    )

    application = create_app(settings, model_provider=model)
    with TestClient(application) as client:
        first = client.post("/v1/memory/add", json=first_payload)
        assert first.status_code == 200
        assert model.tasks == []
        assert application.state.memory_service.repository.maintenance_backlog(
            "run:user-1"
        ) == (1, len("I prefer compact cars."))

        second = client.post("/v1/memory/add", json=second_payload)
        replay = client.post("/v1/memory/add", json=second_payload)

    assert second.status_code == replay.status_code == 200
    assert model.tasks == ["maintenance"]
    assert [
        event["ordinal"] for event in model.payloads[0]["new_events"]
    ] == [0, 1]
    assert [
        event["content"] for event in model.payloads[0]["new_events"]
    ] == ["I prefer compact cars.", "I also enjoy taking trains."]
    assert application.state.memory_service.repository.maintenance_backlog(
        "run:user-1"
    ) == (0, 0)

    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT maintenance_watermark FROM working_memory"
        ).fetchone()[0] == "run:add-2"
        assert connection.execute(
            "SELECT COUNT(*) FROM maintenance_runs"
        ).fetchone()[0] == 1


def test_graph_path_ranking_keeps_intermediate_and_endpoint() -> None:
    middle = SearchResult(id="middle", content="shared entity", score=0.5)
    endpoint = SearchResult(id="endpoint", content="target evidence", score=0.25)
    paths = [
        GraphPath(
            result=middle,
            hop=1,
            path_ids=("seed", "middle"),
            relations=("about",),
            source_event_ids=("source-1",),
            query_relevance=0.0,
            relation_relevance=0.0,
        ),
        GraphPath(
            result=endpoint,
            hop=2,
            path_ids=("seed", "middle", "endpoint"),
            relations=("about", "supports"),
            source_event_ids=("source-1", "source-2"),
            query_relevance=1.0,
            relation_relevance=0.0,
        ),
    ]

    ranked = _rank_graph_paths(paths)

    assert [item.id for item in ranked] == ["middle", "endpoint"]
    assert ranked[0].score > middle.score
    assert ranked[1].score > endpoint.score


def test_provider_failures_degrade_to_raw_lexical_memory(tmp_path: Path) -> None:
    settings = enhanced_settings(tmp_path)
    model = FailingModelProvider()
    embeddings = FailingEmbeddingProvider()

    with TestClient(
        create_app(settings, model_provider=model, embedding_provider=embeddings)
    ) as client:
        added = client.post(
            "/v1/memory/add",
            json=add_payload(content="I will visit Shanghai next Monday."),
        )
        found = client.post(
            "/v1/memory/search",
            json={
                "query": "Shanghai",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 10,
            },
        )

    assert added.status_code == found.status_code == 200
    assert "Shanghai" in found.json()["data"][0]["content"]
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT status, error_type FROM maintenance_runs"
        ).fetchone() == ("failed", "ProviderError")
        assert connection.execute(
            "SELECT status FROM enrichment_jobs"
        ).fetchone()[0] == "failed"
        assert connection.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 1


def test_embedding_index_can_be_rebuilt_atomically(tmp_path: Path) -> None:
    settings = enhanced_settings(tmp_path)
    application = create_app(
        settings,
        model_provider=FakeModelProvider(),
        embedding_provider=FakeEmbeddingProvider(),
    )
    with TestClient(application) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        with sqlite3.connect(settings.db_path) as connection:
            connection.execute("DELETE FROM memory_embeddings")
        users, nodes = application.state.memory_service.rebuild_embeddings(
            "run:user-1"
        )

    assert (users, nodes) == (1, 4)
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_embeddings"
        ).fetchone()[0] == 4


def test_second_add_maintenance_receives_related_nodes_and_links(tmp_path: Path) -> None:
    settings = enhanced_settings(tmp_path)
    model = FakeModelProvider()

    with TestClient(
        create_app(
            settings,
            model_provider=model,
            embedding_provider=FakeEmbeddingProvider(),
        )
    ) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        assert client.post(
            "/v1/memory/add",
            json=add_payload(
                request_id="run:add-2",
                content="This is another note about transportation.",
            ),
        ).status_code == 200

    maintenance_payloads = [
        payload for payload in model.payloads if payload["task"] == "maintenance"
    ]
    assert len(maintenance_payloads) == 2
    assert maintenance_payloads[1]["existing_memories"]
    assert maintenance_payloads[1]["existing_links"]


def test_canonical_fact_key_reuses_evidence_group(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
    )
    provider = CanonicalFactProvider()
    with TestClient(create_app(settings, model_provider=provider)) as client:
        assert client.post(
            "/v1/memory/add",
            json=add_payload(content="I prefer a compact car."),
        ).status_code == 200
        assert client.post(
            "/v1/memory/add",
            json=add_payload(
                request_id="run:add-2", content="A small automobile is my choice."
            ),
        ).status_code == 200
        found = client.post(
            "/v1/memory/search",
            json={
                "query": "vehicle preference",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 20,
            },
        )

    assert found.status_code == 200
    with sqlite3.connect(settings.db_path) as connection:
        facts = connection.execute(
            "SELECT memory_id, canonical_key, evidence_group_id, activity "
            "FROM memory_nodes WHERE kind = 'fact'"
        ).fetchall()
    assert len(facts) == 1
    assert facts[0][1:] == (
        "preference:vehicle=compact_automobile",
        facts[0][2],
        2,
    )
    fact_id = facts[0][0]
    assert [item["id"] for item in found.json()["data"]].count(fact_id) == 1


def test_existing_memory_nodes_schema_gets_metadata_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE memory_nodes (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                event_time TEXT,
                valid_from TEXT,
                valid_to TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confidence REAL,
                activity REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                version INTEGER NOT NULL DEFAULT 1,
                source_event_ids TEXT NOT NULL
            )
            """
        )
        connection.commit()

    SQLiteMemoryRepository(db_path).initialize()
    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(memory_nodes)")
        }
    assert {
        "canonical_key",
        "evidence_group_id",
        "time_expression",
        "resolved_time_start",
        "resolved_time_end",
        "time_precision",
    } <= columns


def test_fact_persists_resolved_temporal_hint_from_source_event(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
    )
    payload = add_payload(content="I will visit Shanghai next Monday.")
    payload["messages"] = [
        {
            "role": "user",
            "timestamp": 1_704_067_200_000,
            "content": "I will visit Shanghai next Monday.",
        }
    ]
    with TestClient(create_app(settings, model_provider=FakeModelProvider())) as client:
        assert client.post("/v1/memory/add", json=payload).status_code == 200

    with sqlite3.connect(settings.db_path) as connection:
        temporal = connection.execute(
            "SELECT time_expression, resolved_time_start, resolved_time_end "
            "FROM memory_nodes WHERE kind = 'fact'"
        ).fetchone()
    assert temporal == ("next Monday", "2024-01-08", "2024-01-09")


def test_add_deadline_preserves_raw_and_records_retryable_failure(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
        add_deadline_seconds=1e-9,
    )
    provider = FakeModelProvider()
    with TestClient(create_app(settings, model_provider=provider)) as client:
        response = client.post("/v1/memory/add", json=add_payload())

    assert response.status_code == 200
    assert provider.tasks == []
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 1
        assert connection.execute(
            "SELECT status, error_type FROM maintenance_runs"
        ).fetchone() == ("failed", "DeadlineExceeded")
        assert connection.execute(
            "SELECT status, attempts FROM enrichment_jobs"
        ).fetchone() == ("failed", 1)


def test_search_deadline_skips_optional_providers_but_keeps_lexical(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
        embedding_enabled=True,
        embedding_api_key="fake-embedding-key",
        embedding_dimensions=256,
        search_deadline_seconds=1e-9,
    )
    model = FakeModelProvider()
    embeddings = FakeEmbeddingProvider()
    with TestClient(
        create_app(settings, model_provider=model, embedding_provider=embeddings)
    ) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        model_calls = len(model.tasks)
        embedding_calls = len(embeddings.calls)
        found = client.post(
            "/v1/memory/search",
            json={
                "query": "automobile",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 10,
            },
        )

    assert found.status_code == 200
    assert found.json()["data"]
    assert len(model.tasks) == model_calls
    assert len(embeddings.calls) == embedding_calls


def test_async_enrichment_is_persistent_and_manually_drainable(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        enrichment_mode="async",
        llm_enabled=True,
        openai_api_key="fake-model-key",
    )
    provider = FakeModelProvider()
    application = create_app(settings, model_provider=provider)
    with TestClient(application) as client:
        service = application.state.memory_service
        service.stop_worker()
        added = client.post("/v1/memory/add", json=add_payload())
        assert added.status_code == 200
        assert provider.tasks == []
        assert service.repository.enrichment_status(
            "run:user-1", "run:add-1"
        ) == "pending"
        with sqlite3.connect(settings.db_path) as connection:
            connection.execute(
                "UPDATE enrichment_jobs SET status = 'running', "
                "started_at = '2020-01-01T00:00:00.000Z'"
            )
        service.repository.initialize()
        assert service.repository.enrichment_status(
            "run:user-1", "run:add-1"
        ) == "pending"
        assert service.process_pending_enrichment(limit=1) == 1

    assert provider.tasks == ["maintenance"]
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT status, attempts FROM enrichment_jobs"
        ).fetchone() == ("completed", 1)
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE kind = 'fact'"
        ).fetchone()[0] == 1


def test_failed_maintenance_can_be_explicitly_retried_without_duplicate_raw_events(
    tmp_path: Path,
) -> None:
    settings = enhanced_settings(tmp_path)
    model = RecoveringModelProvider()
    application = create_app(
        settings,
        model_provider=model,
        embedding_provider=FakeEmbeddingProvider(),
    )
    payload = add_payload()

    with TestClient(application) as client:
        assert client.post("/v1/memory/add", json=payload).status_code == 200
        assert application.state.memory_service.retry_failed_maintenance(
            user_id="run:user-1",
            request_id="run:add-1",
        )

    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE kind = 'fact'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT status FROM maintenance_runs"
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT status, attempts FROM enrichment_jobs"
        ).fetchone() == ("completed", 2)


def test_stale_failed_maintenance_does_not_move_watermark_backwards(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
    )
    model = RecoveringModelProvider()
    application = create_app(settings, model_provider=model)

    with TestClient(application) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        assert client.post(
            "/v1/memory/add",
            json=add_payload(
                request_id="run:add-2", content="I also enjoy taking trains."
            ),
        ).status_code == 200
        assert not application.state.memory_service.retry_failed_maintenance(
            user_id="run:user-1",
            request_id="run:add-1",
        )

    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT maintenance_watermark FROM working_memory"
        ).fetchone()[0] == "run:add-2"
        assert connection.execute(
            "SELECT status FROM maintenance_runs "
            "WHERE trigger_request_id = 'run:add-1'"
        ).fetchone()[0] == "failed"


def test_retry_batches_later_pending_events_and_advances_watermark(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
    )
    model = ToggleModelProvider()
    application = create_app(settings, model_provider=model)

    with TestClient(application) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        assert client.post(
            "/v1/memory/add",
            json=add_payload(
                request_id="run:add-2", content="I also enjoy taking trains."
            ),
        ).status_code == 200
        model.available = True
        assert application.state.memory_service.retry_failed_maintenance(
            user_id="run:user-1",
            request_id="run:add-1",
        )
        assert not application.state.memory_service.retry_failed_maintenance(
            user_id="run:user-1",
            request_id="run:add-2",
        )

    successful_payload = model.payloads[-1]
    assert [
        event["ordinal"] for event in successful_payload["new_events"]
    ] == [0, 1]
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT maintenance_watermark FROM working_memory"
        ).fetchone()[0] == "run:add-2"
    assert application.state.memory_service.repository.maintenance_backlog(
        "run:user-1"
    ) == (0, 0)


def test_purge_before_removes_raw_and_derived_records(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
    )
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200

    with sqlite3.connect(settings.db_path) as connection:
        connection.executescript(
            """
            UPDATE add_requests SET created_at = '2020-01-01T00:00:00.000Z',
                completed_at = '2020-01-01T00:00:00.000Z';
            UPDATE raw_events SET ingested_at = '2020-01-01T00:00:00.000Z';
            UPDATE memory_nodes SET created_at = '2020-01-01T00:00:00.000Z',
                updated_at = '2020-01-01T00:00:00.000Z';
            UPDATE working_memory SET updated_at = '2020-01-01T00:00:00.000Z';
            """
        )

    counts = SQLiteMemoryRepository(settings.db_path).purge_before(
        "2021-01-01T00:00:00.000Z"
    )
    assert counts["raw_events"] == 1
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_nodes").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM add_requests").fetchone()[0] == 0


def test_nonofficial_model_requires_explicit_debug_switch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="AML_ALLOW_NONOFFICIAL_LLM_MODEL"):
        create_app(
            Settings(
                db_path=tmp_path / "blocked.db",
                markdown_view_dir=None,
                llm_enabled=True,
                llm_model="gpt-5.4-mini",
                openai_api_key="fake-key",
            )
        )
    allowed = Settings(
        db_path=tmp_path / "allowed.db",
        markdown_view_dir=None,
        llm_enabled=True,
        llm_model="gpt-5.4-mini",
        allow_nonofficial_llm_model=True,
        openai_api_key="fake-key",
    )
    allowed.validate()


def test_cross_user_supersede_is_rejected_atomically(tmp_path: Path) -> None:
    settings = enhanced_settings(tmp_path)
    foreign_id = stable_structured_id(
        "run:user-a", "fact", "The user's preferred vehicle is an automobile."
    )
    with TestClient(
        create_app(
            settings,
            model_provider=FakeModelProvider(),
            embedding_provider=FakeEmbeddingProvider(),
        )
    ) as client:
        assert client.post(
            "/v1/memory/add",
            json=add_payload(user_id="run:user-a"),
        ).status_code == 200

    provider = CrossUserMutationProvider(foreign_id)

    with TestClient(
        create_app(
            settings,
            model_provider=provider,
            embedding_provider=FakeEmbeddingProvider(),
        )
    ) as client:
        response = client.post(
            "/v1/memory/add",
            json=add_payload(user_id="run:user-b", content="A separate user's note."),
        )

    assert response.status_code == 200
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE kind = 'fact'"
        ).fetchone()[0] == 1
        assert connection.execute(
            """
            SELECT status FROM maintenance_runs
            WHERE user_id = 'run:user-b'
            """
        ).fetchone()[0] == "failed"


def test_superseded_fact_is_hidden_from_current_and_available_to_history(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=tmp_path / "markdown",
        llm_enabled=True,
        openai_api_key="fake-model-key",
    )
    provider = VersionedModelProvider()
    paris_id = stable_structured_id(
        "run:user-1", "fact", "The user lives in Paris."
    )

    with TestClient(create_app(settings, model_provider=provider)) as client:
        assert client.post(
            "/v1/memory/add",
            json=add_payload(content="I live in Paris."),
        ).status_code == 200
        assert client.post(
            "/v1/memory/add",
            json=add_payload(
                request_id="run:add-2", content="I moved to Berlin."
            ),
        ).status_code == 200
        current = client.post(
            "/v1/memory/search",
            json={
                "query": "Where does the user live now, Paris?",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 20,
            },
        )
        historical = client.post(
            "/v1/memory/search",
            json={
                "query": "Where did the user live previously?",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 20,
            },
        )

    current_ids = {item["id"] for item in current.json()["data"]}
    historical_ids = {item["id"] for item in historical.json()["data"]}
    assert paris_id not in current_ids
    assert paris_id in historical_ids
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT status, valid_from, valid_to FROM memory_nodes WHERE memory_id = ?",
            (paris_id,),
        ).fetchone() == ("superseded", "2025-01-01", "2026-01-01")


def test_tombstoned_fact_is_removed_from_all_retrieval_indexes(tmp_path: Path) -> None:
    settings = enhanced_settings(tmp_path)
    fact_id = stable_structured_id(
        "run:user-1", "fact", "The user's preferred vehicle is an automobile."
    )
    provider = TombstoneModelProvider()

    with TestClient(
        create_app(
            settings,
            model_provider=provider,
            embedding_provider=FakeEmbeddingProvider(),
        )
    ) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        assert client.post(
            "/v1/memory/add",
            json=add_payload(
                request_id="run:add-2",
                content="Please forget my vehicle preference.",
            ),
        ).status_code == 200
        found = client.post(
            "/v1/memory/search",
            json={
                "query": "automobile",
                "options": None,
                "user_id": "run:user-1",
                "top_k": 20,
            },
        )

    assert fact_id not in {item["id"] for item in found.json()["data"]}
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT status FROM memory_nodes WHERE memory_id = ?", (fact_id,)
        ).fetchone()[0] == "tombstoned"
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_fts WHERE memory_id = ?", (fact_id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_embeddings WHERE memory_id = ?", (fact_id,)
        ).fetchone()[0] == 0


def test_failed_sync_enrichment_recovers_through_bounded_worker_path(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
        enrichment_max_attempts=3,
    )
    provider = RecoveringModelProvider()
    application = create_app(settings, model_provider=provider)

    with TestClient(application) as client:
        service = application.state.memory_service
        service.stop_worker()
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        with sqlite3.connect(settings.db_path) as connection:
            connection.execute(
                "UPDATE enrichment_jobs SET available_at = "
                "'2020-01-01T00:00:00.000Z'"
            )
        assert service.process_pending_enrichment(
            limit=1, include_pending=False
        ) == 1

    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT status, attempts FROM enrichment_jobs"
        ).fetchone() == ("completed", 2)
        assert connection.execute(
            "SELECT status FROM maintenance_runs"
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE kind = 'fact'"
        ).fetchone()[0] == 1


def test_persistent_enrichment_failure_stops_at_configured_attempt_limit(
    tmp_path: Path,
) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
        llm_enabled=True,
        openai_api_key="fake-model-key",
        enrichment_max_attempts=3,
    )
    application = create_app(settings, model_provider=FailingModelProvider())

    with TestClient(application) as client:
        service = application.state.memory_service
        service.stop_worker()
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        for _attempt in range(2):
            with sqlite3.connect(settings.db_path) as connection:
                connection.execute(
                    "UPDATE enrichment_jobs SET available_at = "
                    "'2020-01-01T00:00:00.000Z'"
                )
            service.process_pending_enrichment(limit=1, include_pending=False)
        with sqlite3.connect(settings.db_path) as connection:
            connection.execute(
                "UPDATE enrichment_jobs SET available_at = "
                "'2020-01-01T00:00:00.000Z'"
            )
        assert service.process_pending_enrichment(
            limit=1, include_pending=False
        ) == 0

    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT status, attempts FROM enrichment_jobs"
        ).fetchone() == ("failed", 3)


def test_enrichment_worker_survives_a_transient_iteration_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app(
        Settings(db_path=tmp_path / "memory.db", markdown_view_dir=None)
    )
    with TestClient(application):
        service = application.state.memory_service
        service.stop_worker()
        service._worker_stop.clear()
        attempts = 0

        def process_once_then_stop(*, limit: int, include_pending: bool) -> int:
            nonlocal attempts
            assert limit == 4
            assert not include_pending
            attempts += 1
            if attempts == 1:
                raise sqlite3.OperationalError("temporary storage failure")
            service._worker_stop.set()
            return 0

        monkeypatch.setattr(
            service, "process_pending_enrichment", process_once_then_stop
        )
        monkeypatch.setattr(service._worker_stop, "wait", lambda _seconds: False)
        service._worker_loop()

        assert attempts == 2
