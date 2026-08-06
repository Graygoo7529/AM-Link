from __future__ import annotations

import argparse

from .repository import SQLiteMemoryRepository
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge AML memory before a UTC cutoff")
    parser.add_argument(
        "--before",
        required=True,
        help="UTC ISO-8601 cutoff, for example 2026-09-07T00:00:00Z",
    )
    args = parser.parse_args()
    settings = Settings.from_env()
    repository = SQLiteMemoryRepository(
        settings.db_path,
        working_memory_event_limit=settings.working_memory_event_limit,
        working_memory_char_limit=settings.working_memory_char_limit,
    )
    repository.initialize()
    print(repository.purge_before(args.before))


if __name__ == "__main__":
    main()
