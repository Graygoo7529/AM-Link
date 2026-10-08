"""Run the archived phase-1 service in an isolated benchmark database."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from benchmark.targets import TargetResponse


class Phase1Target:
    def __init__(self, *, db_path: Path, use_environment: bool = False) -> None:
        try:
            from aml_memory.models import AddRequest, SearchRequest
            from aml_memory.errors import IdempotencyConflictError
            from aml_memory.projection import MarkdownProjector
            from aml_memory.repository import SQLiteMemoryRepository
            from aml_memory.service import MemoryService
            from aml_memory.settings import Settings
        except ImportError as error:
            raise ValueError(
                "phase1 target requires the archived phase-1 package installed"
            ) from error

        settings = Settings.from_env() if use_environment else Settings()
        if settings.enrichment_mode != "sync":
            raise ValueError("phase1 arena currently requires AML_ENRICHMENT_MODE=sync")
        settings = replace(
            settings,
            db_path=db_path.resolve(),
            markdown_view_dir=None,
            enrichment_mode="sync",
        )
        settings.validate()
        repository = SQLiteMemoryRepository(
            settings.db_path,
            working_memory_event_limit=settings.working_memory_event_limit,
            working_memory_char_limit=settings.working_memory_char_limit,
        )
        repository.initialize()
        model_provider = None
        embedding_provider = None
        if settings.llm_enabled:
            from aml_memory.providers import OpenAICompatibleJsonModel

            model_provider = OpenAICompatibleJsonModel(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.llm_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_output_tokens=settings.llm_max_output_tokens,
                max_retries=settings.llm_max_retries,
                max_concurrency=settings.llm_max_concurrency,
            )
        if settings.embedding_enabled:
            from aml_memory.providers import ZhipuEmbeddingProvider

            embedding_provider = ZhipuEmbeddingProvider(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                batch_size=settings.embedding_batch_size,
                timeout_seconds=settings.embedding_timeout_seconds,
                max_retries=settings.embedding_max_retries,
                max_concurrency=settings.embedding_max_concurrency,
            )
        self._add_request = AddRequest
        self._search_request = SearchRequest
        self._idempotency_conflict_error = IdempotencyConflictError
        self.service = MemoryService(
            repository,
            MarkdownProjector(None),
            max_top_k=settings.max_top_k,
            enrichment_mode="sync",
            maintenance_event_threshold=settings.maintenance_event_threshold,
            maintenance_char_threshold=settings.maintenance_char_threshold,
            enrichment_max_attempts=settings.enrichment_max_attempts,
            add_deadline_seconds=settings.add_deadline_seconds,
            search_deadline_seconds=settings.search_deadline_seconds,
            model_provider=model_provider if settings.llm_enabled else None,
            embedding_provider=embedding_provider if settings.embedding_enabled else None,
        )
        self.model_capture_complete = not (settings.llm_enabled or settings.embedding_enabled)
        self.model_configuration = {
            "llm": {
                "enabled": settings.llm_enabled,
                "name": settings.llm_model if settings.llm_enabled else None,
            },
            "embedding": {
                "enabled": settings.embedding_enabled,
                "name": settings.embedding_model if settings.embedding_enabled else None,
                "dimensions": settings.embedding_dimensions if settings.embedding_enabled else None,
            },
        }
        self.adapter_notes = [
            "phase-1 implementation is archived 0.3.0; API boundary is observed but internal steps are not instrumented",
            "each benchmark run uses an isolated SQLite database stored in its ignored run directory",
        ]
        if use_environment:
            self.adapter_notes.append(
                "model settings and credentials are read from the current process environment"
            )
            self.adapter_notes.append(
                "model names, embedding dimensions, and enablement are recorded without credentials"
            )

    def add(self, request: dict) -> TargetResponse:
        try:
            result = self.service.add(self._add_request.model_validate(request))
        except self._idempotency_conflict_error:
            return TargetResponse(409, error_code="idempotency_conflict")
        return TargetResponse(200, body=result.model_dump(mode="json"))

    def search(self, request: dict) -> TargetResponse:
        result = self.service.search(self._search_request.model_validate(request))
        return TargetResponse(200, body=result.model_dump(mode="json"))

    def close(self) -> None:
        self.service.close()


def factory(*, recorder, artifacts, db_path: Path, use_environment: bool = False):
    del recorder, artifacts
    return Phase1Target(db_path=db_path, use_environment=use_environment)
