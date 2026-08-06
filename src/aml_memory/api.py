from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .auth import MemorySystemAuthenticator
from .errors import AuthenticationError, IdempotencyConflictError
from .models import AddRequest, AddResponse, SearchRequest, SearchResponse
from .projection import MarkdownProjector
from .providers import (
    EmbeddingProvider,
    JsonModelProvider,
    OpenAICompatibleJsonModel,
    ZhipuEmbeddingProvider,
)
from .repository import SQLiteMemoryRepository
from .service import MemoryService
from .settings import Settings


def create_app(
    settings: Settings | None = None,
    *,
    model_provider: JsonModelProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> FastAPI:
    effective_settings = settings or Settings.from_env()
    effective_settings.validate()
    repository = SQLiteMemoryRepository(
        effective_settings.db_path,
        working_memory_event_limit=effective_settings.working_memory_event_limit,
        working_memory_char_limit=effective_settings.working_memory_char_limit,
    )
    effective_model_provider = model_provider
    if effective_settings.llm_enabled and effective_model_provider is None:
        effective_model_provider = OpenAICompatibleJsonModel(
            api_key=effective_settings.openai_api_key,
            base_url=effective_settings.openai_base_url,
            model=effective_settings.llm_model,
            timeout_seconds=effective_settings.llm_timeout_seconds,
            max_output_tokens=effective_settings.llm_max_output_tokens,
            max_retries=effective_settings.llm_max_retries,
            max_concurrency=effective_settings.llm_max_concurrency,
        )
    effective_embedding_provider = embedding_provider
    if effective_settings.embedding_enabled and effective_embedding_provider is None:
        effective_embedding_provider = ZhipuEmbeddingProvider(
            api_key=effective_settings.embedding_api_key,
            base_url=effective_settings.embedding_base_url,
            model=effective_settings.embedding_model,
            dimensions=effective_settings.embedding_dimensions,
            batch_size=effective_settings.embedding_batch_size,
            timeout_seconds=effective_settings.embedding_timeout_seconds,
            max_retries=effective_settings.embedding_max_retries,
            max_concurrency=effective_settings.embedding_max_concurrency,
        )
    service = MemoryService(
        repository,
        MarkdownProjector(effective_settings.markdown_view_dir),
        max_top_k=effective_settings.max_top_k,
        enrichment_mode=effective_settings.enrichment_mode,
        maintenance_event_threshold=(
            effective_settings.maintenance_event_threshold
        ),
        maintenance_char_threshold=effective_settings.maintenance_char_threshold,
        add_deadline_seconds=effective_settings.add_deadline_seconds,
        search_deadline_seconds=effective_settings.search_deadline_seconds,
        model_provider=(
            effective_model_provider if effective_settings.llm_enabled else None
        ),
        embedding_provider=(
            effective_embedding_provider
            if effective_settings.embedding_enabled
            else None
        ),
    )
    authenticator = MemorySystemAuthenticator(effective_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        await run_in_threadpool(repository.initialize)
        application.state.settings = effective_settings
        application.state.memory_service = service
        service.start_worker()
        try:
            yield
        finally:
            service.stop_worker()
            await run_in_threadpool(service.close)

    application = FastAPI(
        title="AML Memory Add/Search",
        version="0.2.0",
        lifespan=lifespan,
    )

    def authorize(request: Request) -> None:
        authenticator.verify(request)

    @application.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        _request: Request, error: AuthenticationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": {"reason": str(error)}},
            headers={"WWW-Authenticate": effective_settings.auth_scheme},
        )

    @application.exception_handler(IdempotencyConflictError)
    async def idempotency_error_handler(
        _request: Request, error: IdempotencyConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": {"reason": str(error)}},
        )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post(
        "/v1/memory/add",
        response_model=AddResponse,
        dependencies=[Depends(authorize)],
    )
    async def add(request: AddRequest) -> AddResponse:
        return await run_in_threadpool(service.add, request)

    @application.post(
        "/v1/memory/search",
        response_model=SearchResponse,
        dependencies=[Depends(authorize)],
    )
    async def search(request: SearchRequest) -> SearchResponse:
        return await run_in_threadpool(service.search, request)

    return application


app = create_app()
