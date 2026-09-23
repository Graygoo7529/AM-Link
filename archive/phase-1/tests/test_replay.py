from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aml_memory.api import create_app
from aml_memory.replay import ReplayRunner, load_manifest
from aml_memory.settings import Settings


def test_replay_smoke_manifest_reports_quality_and_latency(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        markdown_view_dir=None,
    )
    application = create_app(settings)
    manifest = load_manifest(Path("examples/replay-smoke.json"))

    with TestClient(application) as client:
        service = application.state.memory_service
        report = ReplayRunner(
            client,
            repository=service.repository,
            metrics_supplier=service.metrics_snapshot,
        ).run(manifest)

    assert report["cases"] == 2
    assert report["adds"]["total"] == 2
    assert report["adds"]["success_rate"] == 1.0
    assert report["searches"]["total"] == 2
    assert report["searches"]["success_rate"] == 1.0
    assert report["quality"]["evidence_recall_at_1"] >= 0.5
    assert report["quality"]["evidence_recall_at_10"] == 1.0
    assert report["quality"]["temporal_recall_at_10"] == 1.0
    assert report["quality"]["multi_hop_chain_coverage_at_10"] == 1.0
    assert report["quality"]["duplicate_rate"] == 0.0
    assert report["provider_calls"] == {
        "embedding_context_calls": 0,
        "embedding_index_calls": 0,
        "embedding_index_texts": 0,
        "embedding_search_calls": 0,
        "llm_maintenance_calls": 0,
        "llm_search_calls": 0,
    }
    assert report["errors"] == []

