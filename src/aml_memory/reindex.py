from __future__ import annotations

import argparse

from .projection import MarkdownProjector
from .providers import ZhipuEmbeddingProvider
from .repository import SQLiteMemoryRepository
from .service import MemoryService
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild AML memory embeddings")
    parser.add_argument("--user-id", help="Rebuild only one opaque user_id")
    arguments = parser.parse_args()

    settings = Settings.from_env()
    if not settings.embedding_enabled:
        raise SystemExit("set AML_EMBEDDING_ENABLED=true before rebuilding")
    repository = SQLiteMemoryRepository(
        settings.db_path,
        working_memory_event_limit=settings.working_memory_event_limit,
        working_memory_char_limit=settings.working_memory_char_limit,
    )
    repository.initialize()
    provider = ZhipuEmbeddingProvider(
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
        MarkdownProjector(None),
        max_top_k=settings.max_top_k,
        embedding_provider=provider,
    )
    try:
        users, nodes = service.rebuild_embeddings(arguments.user_id)
    finally:
        service.close()
    print(f"rebuilt_users={users} rebuilt_nodes={nodes}")


if __name__ == "__main__":
    main()
