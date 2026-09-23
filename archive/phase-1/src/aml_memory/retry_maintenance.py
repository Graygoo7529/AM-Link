from __future__ import annotations

import argparse

from .projection import MarkdownProjector
from .providers import OpenAICompatibleJsonModel, ZhipuEmbeddingProvider
from .repository import SQLiteMemoryRepository
from .service import MemoryService
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry one failed Add maintenance run")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.llm_enabled:
        raise SystemExit("set AML_LLM_ENABLED=true before retrying maintenance")
    repository = SQLiteMemoryRepository(
        settings.db_path,
        working_memory_event_limit=settings.working_memory_event_limit,
        working_memory_char_limit=settings.working_memory_char_limit,
    )
    repository.initialize()
    provider = OpenAICompatibleJsonModel(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        max_retries=settings.llm_max_retries,
        max_concurrency=settings.llm_max_concurrency,
    )
    embedding_provider = None
    if settings.embedding_enabled:
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
    service = MemoryService(
        repository,
        MarkdownProjector(settings.markdown_view_dir),
        max_top_k=settings.max_top_k,
        model_provider=provider,
        embedding_provider=embedding_provider,
    )
    try:
        retried = service.retry_failed_maintenance(
            user_id=args.user_id,
            request_id=args.request_id,
        )
        status = repository.maintenance_status(args.user_id, args.request_id)
    finally:
        service.close()
    print(f"claimed={retried} status={status}")


if __name__ == "__main__":
    main()
