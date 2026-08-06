from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import IdempotencyConflictError
from .models import AddRequest, AddResponse, SearchRequest, SearchResult
from .temporal import TemporalHint, extract_temporal_hint, ranges_overlap

if TYPE_CHECKING:
    from .maintenance import MaintenancePlan


_ENGLISH_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "with",
    }
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timestamp_to_iso(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def stable_memory_id(user_id: str, request_id: str, ordinal: int) -> str:
    source = f"{user_id}\0{request_id}\0{ordinal}".encode("utf-8")
    return "mem_" + hashlib.blake2b(source, digest_size=16).hexdigest()


def request_payload_hash(request: AddRequest) -> str:
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evidence_content(
    *, role: str, content: str, source_time: str | None, session_id: str
) -> str:
    time_label = source_time or "time unknown"
    return f"[{time_label}][{role}][session: {session_id}] {content}"


@dataclass(frozen=True, slots=True)
class EventRecord:
    memory_id: str
    user_id: str
    session_id: str
    request_id: str
    ordinal: int
    role: str
    content: str
    source_timestamp_ms: int | None
    source_time: str | None
    ingested_at: str


@dataclass(frozen=True, slots=True)
class AddOutcome:
    response: AddResponse
    events: tuple[EventRecord, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class NodeRecord:
    memory_id: str
    user_id: str
    kind: str
    title: str
    content: str
    event_time: str | None
    valid_from: str | None
    valid_to: str | None
    created_at: str
    updated_at: str
    confidence: float | None
    activity: float
    status: str
    version: int
    source_event_ids: str
    canonical_key: str | None
    evidence_group_id: str | None
    time_expression: str | None
    resolved_time_start: str | None
    resolved_time_end: str | None
    time_precision: str | None


@dataclass(frozen=True, slots=True)
class EmbeddingChunk:
    memory_id: str
    chunk_no: int
    content: str


@dataclass(frozen=True, slots=True)
class LinkRecord:
    from_memory_id: str
    to_memory_id: str
    relation: str


@dataclass(frozen=True, slots=True)
class GraphPath:
    result: SearchResult
    hop: int
    path_ids: tuple[str, ...]
    relations: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    query_relevance: float
    relation_relevance: float


@dataclass(frozen=True, slots=True)
class RankingFeatures:
    kind: str
    confidence: float | None
    activity: float
    status: str
    event_time: str | None
    valid_from: str | None
    valid_to: str | None
    evidence_group_id: str | None
    source_event_ids: tuple[str, ...]
    resolved_time_start: str | None
    resolved_time_end: str | None


class SQLiteMemoryRepository:
    def __init__(
        self,
        db_path: Path,
        *,
        working_memory_event_limit: int = 40,
        working_memory_char_limit: int = 16_000,
    ) -> None:
        self.db_path = db_path
        self.working_memory_event_limit = working_memory_event_limit
        self.working_memory_char_limit = working_memory_char_limit

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS add_requests (
                    user_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, request_id)
                );

                CREATE TABLE IF NOT EXISTS raw_events (
                    sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_timestamp_ms INTEGER,
                    source_time TEXT,
                    ingested_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    UNIQUE (user_id, request_id, ordinal),
                    FOREIGN KEY (user_id, request_id)
                        REFERENCES add_requests (user_id, request_id)
                );

                CREATE INDEX IF NOT EXISTS idx_raw_events_user_sequence
                    ON raw_events (user_id, sequence_no);
                CREATE INDEX IF NOT EXISTS idx_raw_events_user_source_time
                    ON raw_events (user_id, source_time);

                CREATE TABLE IF NOT EXISTS working_memory (
                    user_id TEXT PRIMARY KEY,
                    markdown TEXT NOT NULL,
                    total_event_count INTEGER NOT NULL,
                    maintenance_watermark TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_nodes (
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
                    source_event_ids TEXT NOT NULL,
                    canonical_key TEXT,
                    evidence_group_id TEXT,
                    time_expression TEXT,
                    resolved_time_start TEXT,
                    resolved_time_end TEXT,
                    time_precision TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_memory_nodes_user_status
                    ON memory_nodes (user_id, status, kind);

                CREATE TABLE IF NOT EXISTS memory_links (
                    user_id TEXT NOT NULL,
                    from_memory_id TEXT NOT NULL,
                    to_memory_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, from_memory_id, to_memory_id, relation),
                    FOREIGN KEY (from_memory_id) REFERENCES memory_nodes (memory_id),
                    FOREIGN KEY (to_memory_id) REFERENCES memory_nodes (memory_id)
                );

                CREATE TABLE IF NOT EXISTS maintenance_runs (
                    maintenance_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    trigger_request_id TEXT NOT NULL,
                    model TEXT,
                    prompt_version TEXT,
                    status TEXT NOT NULL,
                    error_type TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_maintenance_request
                    ON maintenance_runs (user_id, trigger_request_id);

                CREATE TABLE IF NOT EXISTS enrichment_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    available_at TEXT NOT NULL,
                    UNIQUE (user_id, request_id, kind)
                );

                CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status
                    ON enrichment_jobs (status, available_at, created_at);

                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    chunk_no INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (
                        memory_id, model, dimensions, chunk_no
                    ),
                    FOREIGN KEY (memory_id) REFERENCES memory_nodes (memory_id)
                );

                CREATE INDEX IF NOT EXISTS idx_embeddings_user_model
                    ON memory_embeddings (user_id, model, dimensions);

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    memory_id UNINDEXED,
                    user_id UNINDEXED,
                    kind UNINDEXED,
                    content,
                    tokenize = 'unicode61 remove_diacritics 2'
                );
                """
            )
            _ensure_column(connection, "memory_nodes", "valid_from", "TEXT")
            _ensure_column(connection, "memory_nodes", "valid_to", "TEXT")
            _ensure_column(connection, "memory_nodes", "canonical_key", "TEXT")
            _ensure_column(connection, "memory_nodes", "evidence_group_id", "TEXT")
            _ensure_column(connection, "memory_nodes", "time_expression", "TEXT")
            _ensure_column(connection, "memory_nodes", "resolved_time_start", "TEXT")
            _ensure_column(connection, "memory_nodes", "resolved_time_end", "TEXT")
            _ensure_column(connection, "memory_nodes", "time_precision", "TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_nodes_user_group "
                "ON memory_nodes (user_id, evidence_group_id, status)"
            )
            stale_before = (
                datetime.now(UTC) - timedelta(minutes=5)
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            connection.execute(
                """
                UPDATE enrichment_jobs
                SET status = 'pending', error_type = 'WorkerRestart',
                    available_at = ?
                WHERE status = 'running' AND (
                    started_at IS NULL OR started_at < ?
                )
                """,
                (utc_now(), stale_before),
            )

    def add(self, request: AddRequest) -> AddOutcome:
        payload_hash = request_payload_hash(request)
        now = utc_now()
        response = AddResponse(
            success=True,
            request_id=request.request_id,
            user_id=request.user_id,
            session_id=request.session_id,
        )
        response_json = response.model_dump_json()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT payload_hash, response_json
                FROM add_requests
                WHERE user_id = ? AND request_id = ?
                """,
                (request.user_id, request.request_id),
            ).fetchone()
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise IdempotencyConflictError(
                        "request_id was already used with a different Add payload"
                    )
                replay_response = AddResponse.model_validate_json(existing["response_json"])
                events = self._events_for_request(
                    connection, request.user_id, request.request_id
                )
                connection.commit()
                return AddOutcome(replay_response, tuple(events), True)

            connection.execute(
                """
                INSERT INTO add_requests (
                    user_id, request_id, session_id, payload_hash,
                    response_json, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.user_id,
                    request.request_id,
                    request.session_id,
                    payload_hash,
                    response_json,
                    now,
                    now,
                ),
            )

            events: list[EventRecord] = []
            for ordinal, message in enumerate(request.messages):
                memory_id = stable_memory_id(
                    request.user_id, request.request_id, ordinal
                )
                source_time = timestamp_to_iso(message.timestamp)
                event = EventRecord(
                    memory_id=memory_id,
                    user_id=request.user_id,
                    session_id=request.session_id,
                    request_id=request.request_id,
                    ordinal=ordinal,
                    role=message.role,
                    content=message.content,
                    source_timestamp_ms=message.timestamp,
                    source_time=source_time,
                    ingested_at=now,
                )
                events.append(event)
                connection.execute(
                    """
                    INSERT INTO raw_events (
                        memory_id, user_id, session_id, request_id, ordinal,
                        role, content, source_timestamp_ms, source_time, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.memory_id,
                        event.user_id,
                        event.session_id,
                        event.request_id,
                        event.ordinal,
                        event.role,
                        event.content,
                        event.source_timestamp_ms,
                        event.source_time,
                        event.ingested_at,
                    ),
                )
                rendered = evidence_content(
                    role=event.role,
                    content=event.content,
                    source_time=event.source_time,
                    session_id=event.session_id,
                )
                temporal_hint = extract_temporal_hint(
                    event.content, anchor_time=event.source_time
                )
                connection.execute(
                    """
                    INSERT INTO memory_nodes (
                        memory_id, user_id, kind, title, content, event_time,
                        created_at, updated_at, confidence, activity, status,
                        version, source_event_ids, canonical_key, evidence_group_id,
                        time_expression, resolved_time_start, resolved_time_end,
                        time_precision
                    ) VALUES (?, ?, 'daily', ?, ?, ?, ?, ?, 1.0, 0, 'active', 1, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.memory_id,
                        event.user_id,
                        f"Daily event {event.memory_id}",
                        rendered,
                        event.source_time,
                        now,
                        now,
                        json.dumps([event.memory_id]),
                        f"event:{event.memory_id}",
                        f"group_{event.memory_id}",
                        temporal_hint.expression if temporal_hint else None,
                        temporal_hint.start if temporal_hint else None,
                        temporal_hint.end if temporal_hint else None,
                        temporal_hint.precision if temporal_hint else None,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO memory_fts (memory_id, user_id, kind, content)
                    VALUES (?, ?, 'daily', ?)
                    """,
                    (event.memory_id, event.user_id, rendered),
                )

            self._refresh_working_memory(connection, request.user_id, now)
            connection.commit()
            return AddOutcome(response, tuple(events), False)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _events_for_request(
        self, connection: sqlite3.Connection, user_id: str, request_id: str
    ) -> list[EventRecord]:
        rows = connection.execute(
            """
            SELECT memory_id, user_id, session_id, request_id, ordinal, role,
                   content, source_timestamp_ms, source_time, ingested_at
            FROM raw_events
            WHERE user_id = ? AND request_id = ?
            ORDER BY ordinal
            """,
            (user_id, request_id),
        ).fetchall()
        return [EventRecord(**dict(row)) for row in rows]

    def events_for_request(
        self, user_id: str, request_id: str
    ) -> tuple[EventRecord, ...]:
        with self._connect() as connection:
            return tuple(self._events_for_request(connection, user_id, request_id))

    def claim_failed_maintenance(
        self,
        *,
        user_id: str,
        request_id: str,
        model: str,
        prompt_version: str,
    ) -> bool:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE maintenance_runs
                SET status = 'running', model = ?, prompt_version = ?,
                    error_type = NULL, started_at = ?, completed_at = NULL
                WHERE user_id = ? AND trigger_request_id = ? AND status = 'failed'
                """,
                (model, prompt_version, now, user_id, request_id),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    UPDATE enrichment_jobs
                    SET status = 'running', attempts = attempts + 1,
                        error_type = NULL, started_at = ?, completed_at = NULL
                    WHERE user_id = ? AND request_id = ? AND kind = 'add'
                    """,
                    (now, user_id, request_id),
                )
        return cursor.rowcount == 1

    def _refresh_working_memory(
        self, connection: sqlite3.Connection, user_id: str, now: str
    ) -> None:
        rows = connection.execute(
            """
            SELECT memory_id, role, content, source_time, session_id
            FROM raw_events
            WHERE user_id = ? AND status = 'active'
            ORDER BY sequence_no DESC
            LIMIT ?
            """,
            (user_id, self.working_memory_event_limit),
        ).fetchall()
        blocks: list[str] = []
        current_size = 0
        for row in rows:
            time_label = row["source_time"] or "time unknown"
            block = (
                f"- [{time_label}][{row['role']}] {row['content']}\n"
                f"  - memory:daily@{row['memory_id']}"
            )
            if blocks and current_size + len(block) > self.working_memory_char_limit:
                break
            blocks.append(block)
            current_size += len(block)
        blocks.reverse()
        markdown = "# Working Memory\n\n" + "\n\n".join(blocks) + "\n"
        total_event_count = connection.execute(
            "SELECT COUNT(*) FROM raw_events WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO working_memory (
                user_id, markdown, total_event_count, maintenance_watermark, updated_at
            ) VALUES (?, ?, ?, NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                markdown = excluded.markdown,
                total_event_count = excluded.total_event_count,
                updated_at = excluded.updated_at
            """,
            (user_id, markdown, total_event_count, now),
        )

    def get_working_memory(self, user_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT markdown FROM working_memory WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["markdown"] if row else "# Working Memory\n"

    def maintenance_backlog(self, user_id: str) -> tuple[int, int]:
        with self._connect() as connection:
            start_sequence = self._maintenance_start_sequence(connection, user_id)
            row = connection.execute(
                """
                SELECT COUNT(*) AS event_count,
                       COALESCE(SUM(LENGTH(content)), 0) AS char_count
                FROM raw_events
                WHERE user_id = ? AND status = 'active' AND sequence_no > ?
                """,
                (user_id, start_sequence),
            ).fetchone()
        return int(row["event_count"]), int(row["char_count"])

    def pending_maintenance_events(self, user_id: str) -> tuple[EventRecord, ...]:
        with self._connect() as connection:
            start_sequence = self._maintenance_start_sequence(connection, user_id)
            rows = connection.execute(
                """
                SELECT memory_id, user_id, session_id, request_id, ordinal, role,
                       content, source_timestamp_ms, source_time, ingested_at
                FROM raw_events
                WHERE user_id = ? AND status = 'active' AND sequence_no > ?
                ORDER BY sequence_no
                """,
                (user_id, start_sequence),
            ).fetchall()
        events: list[EventRecord] = []
        for source_ordinal, row in enumerate(rows):
            values = dict(row)
            values["ordinal"] = source_ordinal
            events.append(EventRecord(**values))
        return tuple(events)

    @staticmethod
    def _maintenance_start_sequence(
        connection: sqlite3.Connection, user_id: str
    ) -> int:
        working = connection.execute(
            "SELECT maintenance_watermark FROM working_memory WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        watermark = working["maintenance_watermark"] if working else None
        if not watermark:
            return 0
        row = connection.execute(
            """
            SELECT COALESCE(MAX(sequence_no), 0) AS sequence_no
            FROM raw_events
            WHERE user_id = ? AND request_id = ?
            """,
            (user_id, watermark),
        ).fetchone()
        return int(row["sequence_no"])

    def get_context_nodes(self, user_id: str, *, limit: int = 40) -> tuple[NodeRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT memory_id, user_id, kind, title, content, event_time,
                       valid_from, valid_to,
                       created_at, updated_at, confidence, activity, status,
                       version, source_event_ids, canonical_key, evidence_group_id,
                       time_expression, resolved_time_start, resolved_time_end,
                       time_precision
                FROM memory_nodes
                WHERE user_id = ? AND status = 'active' AND kind != 'daily'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return tuple(_row_to_node(row) for row in rows)

    def get_maintenance_context(
        self,
        *,
        user_id: str,
        retrieval_text: str,
        preferred_ids: tuple[str, ...] = (),
        limit: int = 40,
    ) -> tuple[tuple[NodeRecord, ...], tuple[LinkRecord, ...]]:
        ordered_ids: list[str] = []
        seen: set[str] = set()
        tokens = _query_tokens(retrieval_text)
        with self._connect() as connection:
            if preferred_ids:
                unique_preferred = list(dict.fromkeys(preferred_ids))[:limit]
                placeholders = ",".join("?" for _ in unique_preferred)
                rows = connection.execute(
                    f"""
                    SELECT memory_id FROM memory_nodes
                    WHERE user_id = ? AND status = 'active' AND kind != 'daily'
                      AND memory_id IN ({placeholders})
                    """,
                    [user_id, *unique_preferred],
                ).fetchall()
                owned = {row["memory_id"] for row in rows}
                for memory_id in unique_preferred:
                    if memory_id in owned:
                        ordered_ids.append(memory_id)
                        seen.add(memory_id)

            if tokens and len(ordered_ids) < limit:
                fts_query = " OR ".join(_quote_fts_token(token) for token in tokens)
                rows = connection.execute(
                    """
                    SELECT n.memory_id
                    FROM memory_fts
                    JOIN memory_nodes AS n ON n.memory_id = memory_fts.memory_id
                    WHERE memory_fts MATCH ?
                      AND memory_fts.user_id = ? AND n.user_id = ?
                      AND n.status = 'active' AND n.kind != 'daily'
                    ORDER BY bm25(memory_fts), n.updated_at DESC
                    LIMIT ?
                    """,
                    (fts_query, user_id, user_id, limit * 2),
                ).fetchall()
                for row in rows:
                    if row["memory_id"] not in seen:
                        seen.add(row["memory_id"])
                        ordered_ids.append(row["memory_id"])
                        if len(ordered_ids) >= limit:
                            break

            if len(ordered_ids) < limit:
                rows = connection.execute(
                    """
                    SELECT memory_id FROM memory_nodes
                    WHERE user_id = ? AND status = 'active' AND kind != 'daily'
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
                for row in rows:
                    if row["memory_id"] not in seen:
                        seen.add(row["memory_id"])
                        ordered_ids.append(row["memory_id"])
                        if len(ordered_ids) >= limit:
                            break

            link_rows: list[sqlite3.Row] = []
            if ordered_ids:
                seed_ids = ordered_ids[:20]
                placeholders = ",".join("?" for _ in seed_ids)
                link_rows = connection.execute(
                    f"""
                    SELECT from_memory_id, to_memory_id, relation
                    FROM memory_links
                    WHERE user_id = ? AND (
                        from_memory_id IN ({placeholders})
                        OR to_memory_id IN ({placeholders})
                    )
                    ORDER BY created_at DESC
                    LIMIT 200
                    """,
                    [user_id, *seed_ids, *seed_ids],
                ).fetchall()
                neighbor_ids: list[str] = []
                for row in link_rows:
                    for memory_id in (row["from_memory_id"], row["to_memory_id"]):
                        if memory_id not in seen:
                            neighbor_ids.append(memory_id)
                if neighbor_ids and len(ordered_ids) < limit:
                    unique_neighbors = list(dict.fromkeys(neighbor_ids))
                    placeholders = ",".join("?" for _ in unique_neighbors)
                    rows = connection.execute(
                        f"""
                        SELECT memory_id FROM memory_nodes
                        WHERE user_id = ? AND status = 'active' AND kind != 'daily'
                          AND memory_id IN ({placeholders})
                        ORDER BY updated_at DESC
                        """,
                        [user_id, *unique_neighbors],
                    ).fetchall()
                    owned_neighbors = {row["memory_id"] for row in rows}
                    for memory_id in unique_neighbors:
                        if memory_id in owned_neighbors and memory_id not in seen:
                            seen.add(memory_id)
                            ordered_ids.append(memory_id)
                            if len(ordered_ids) >= limit:
                                break

            if not ordered_ids:
                return (), ()
            placeholders = ",".join("?" for _ in ordered_ids)
            rows = connection.execute(
                f"""
                SELECT memory_id, user_id, kind, title, content, event_time,
                       valid_from, valid_to, created_at, updated_at, confidence,
                       activity, status, version, source_event_ids,
                       canonical_key, evidence_group_id,
                       time_expression, resolved_time_start, resolved_time_end,
                       time_precision
                FROM memory_nodes
                WHERE user_id = ? AND memory_id IN ({placeholders})
                """,
                [user_id, *ordered_ids],
            ).fetchall()
        by_id = {row["memory_id"]: _row_to_node(row) for row in rows}
        nodes = tuple(by_id[memory_id] for memory_id in ordered_ids if memory_id in by_id)
        links = tuple(LinkRecord(**dict(row)) for row in link_rows)
        return nodes, links

    def get_ranking_features(
        self, user_id: str, memory_ids: list[str]
    ) -> dict[str, RankingFeatures]:
        unique_ids = list(dict.fromkeys(memory_ids))
        if not unique_ids:
            return {}
        placeholders = ",".join("?" for _ in unique_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT memory_id, kind, confidence, activity, status,
                       event_time, valid_from, valid_to, evidence_group_id,
                       source_event_ids,
                       resolved_time_start, resolved_time_end
                FROM memory_nodes
                WHERE user_id = ? AND memory_id IN ({placeholders})
                """,
                [user_id, *unique_ids],
            ).fetchall()
        return {
            row["memory_id"]: RankingFeatures(
                kind=row["kind"],
                confidence=row["confidence"],
                activity=row["activity"],
                status=row["status"],
                event_time=row["event_time"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                evidence_group_id=row["evidence_group_id"],
                source_event_ids=_decode_source_event_ids(row["source_event_ids"]),
                resolved_time_start=row["resolved_time_start"],
                resolved_time_end=row["resolved_time_end"],
            )
            for row in rows
        }

    def get_nodes_by_ids(
        self, user_id: str, memory_ids: list[str] | tuple[str, ...]
    ) -> tuple[NodeRecord, ...]:
        if not memory_ids:
            return ()
        unique_ids = list(dict.fromkeys(memory_ids))
        placeholders = ",".join("?" for _ in unique_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT memory_id, user_id, kind, title, content, event_time,
                       valid_from, valid_to,
                       created_at, updated_at, confidence, activity, status,
                       version, source_event_ids, canonical_key, evidence_group_id,
                       time_expression, resolved_time_start, resolved_time_end,
                       time_precision
                FROM memory_nodes
                WHERE user_id = ? AND memory_id IN ({placeholders})
                """,
                [user_id, *unique_ids],
            ).fetchall()
        by_id = {row["memory_id"]: _row_to_node(row) for row in rows}
        return tuple(by_id[memory_id] for memory_id in unique_ids if memory_id in by_id)

    def list_user_ids(self) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT user_id FROM memory_nodes ORDER BY user_id"
            ).fetchall()
        return tuple(row["user_id"] for row in rows)

    def latest_source_time(self, user_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(source_time) AS latest FROM raw_events WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row["latest"] if row and row["latest"] else None

    def get_indexable_nodes(self, user_id: str) -> tuple[NodeRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT memory_id, user_id, kind, title, content, event_time,
                       valid_from, valid_to, created_at, updated_at, confidence,
                       activity, status, version, source_event_ids,
                       canonical_key, evidence_group_id,
                       time_expression, resolved_time_start, resolved_time_end,
                       time_precision
                FROM memory_nodes
                WHERE user_id = ? AND status IN ('active', 'superseded')
                ORDER BY created_at, memory_id
                """,
                (user_id,),
            ).fetchall()
        return tuple(_row_to_node(row) for row in rows)

    def enqueue_enrichment(
        self, *, user_id: str, request_id: str, kind: str = "add"
    ) -> bool:
        now = utc_now()
        job_id = stable_structured_id(user_id, "enrichment", f"{kind}:{request_id}")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO enrichment_jobs (
                    job_id, user_id, request_id, kind, status, attempts,
                    error_type, created_at, started_at, completed_at, available_at
                ) VALUES (?, ?, ?, ?, 'pending', 0, NULL, ?, NULL, NULL, ?)
                """,
                (job_id, user_id, request_id, kind, now, now),
            )
        return cursor.rowcount == 1

    def claim_enrichment(
        self, *, user_id: str, request_id: str, kind: str = "add"
    ) -> bool:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE enrichment_jobs
                SET status = 'running', attempts = attempts + 1,
                    error_type = NULL, started_at = ?, completed_at = NULL
                WHERE user_id = ? AND request_id = ? AND kind = ?
                  AND status IN ('pending', 'failed') AND available_at <= ?
                """,
                (now, user_id, request_id, kind, now),
            )
        return cursor.rowcount == 1

    def complete_enrichment(
        self, *, user_id: str, request_id: str, kind: str = "add"
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE enrichment_jobs
                SET status = 'completed', error_type = NULL, completed_at = ?
                WHERE user_id = ? AND request_id = ? AND kind = ?
                """,
                (utc_now(), user_id, request_id, kind),
            )

    def fail_enrichment(
        self,
        *,
        user_id: str,
        request_id: str,
        error_type: str,
        kind: str = "add",
    ) -> None:
        retry_at = (
            datetime.now(UTC) + timedelta(seconds=30)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE enrichment_jobs
                SET status = 'failed', error_type = ?, completed_at = ?, available_at = ?
                WHERE user_id = ? AND request_id = ? AND kind = ?
                """,
                (error_type[:120], utc_now(), retry_at, user_id, request_id, kind),
            )

    def enrichment_status(
        self, user_id: str, request_id: str, kind: str = "add"
    ) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT status FROM enrichment_jobs
                WHERE user_id = ? AND request_id = ? AND kind = ?
                """,
                (user_id, request_id, kind),
            ).fetchone()
        return row["status"] if row else None

    def pending_enrichment_jobs(self, *, limit: int = 8) -> tuple[tuple[str, str], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id, request_id
                FROM enrichment_jobs
                WHERE kind = 'add' AND status IN ('pending', 'failed')
                  AND available_at <= ?
                ORDER BY created_at, job_id
                LIMIT ?
                """,
                (utc_now(), limit),
            ).fetchall()
        return tuple((row["user_id"], row["request_id"]) for row in rows)

    def start_maintenance(
        self,
        *,
        user_id: str,
        request_id: str,
        model: str,
        prompt_version: str,
    ) -> bool:
        maintenance_id = stable_structured_id(
            user_id, "maintenance", request_id
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO maintenance_runs (
                    maintenance_id, user_id, trigger_request_id, model,
                    prompt_version, status, error_type, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, 'running', NULL, ?, NULL)
                """,
                (
                    maintenance_id,
                    user_id,
                    request_id,
                    model,
                    prompt_version,
                    utc_now(),
                ),
            )
        return cursor.rowcount == 1

    def record_maintenance_failure(
        self, *, user_id: str, request_id: str, error_type: str
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE maintenance_runs
                SET status = 'failed', error_type = ?, completed_at = ?
                WHERE user_id = ? AND trigger_request_id = ?
                """,
                (error_type[:120], utc_now(), user_id, request_id),
            )
            connection.execute(
                """
                UPDATE enrichment_jobs
                SET status = 'failed', error_type = ?, completed_at = ?
                WHERE user_id = ? AND request_id = ? AND kind = 'add'
                """,
                (error_type[:120], utc_now(), user_id, request_id),
            )

    def maintenance_status(self, user_id: str, request_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT status FROM maintenance_runs
                WHERE user_id = ? AND trigger_request_id = ?
                """,
                (user_id, request_id),
            ).fetchone()
        return row["status"] if row else None

    def purge_before(self, cutoff: str) -> dict[str, int]:
        """Delete raw and all derived records older than an explicit UTC cutoff."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            old_events = connection.execute(
                "SELECT memory_id FROM raw_events WHERE ingested_at < ?",
                (cutoff,),
            ).fetchall()
            old_event_ids = {row["memory_id"] for row in old_events}
            old_nodes = connection.execute(
                "SELECT memory_id, kind, source_event_ids FROM memory_nodes "
                "WHERE created_at < ?",
                (cutoff,),
            ).fetchall()
            purge_ids = {row["memory_id"] for row in old_nodes}
            for row in connection.execute(
                "SELECT memory_id, source_event_ids FROM memory_nodes "
                "WHERE kind != 'daily'"
            ).fetchall():
                try:
                    sources = set(json.loads(row["source_event_ids"]))
                except (TypeError, ValueError):
                    sources = set()
                if sources & old_event_ids:
                    purge_ids.add(row["memory_id"])

            counts = {
                "memory_links": 0,
                "memory_embeddings": 0,
                "memory_fts": 0,
                "memory_nodes": 0,
                "raw_events": 0,
                "add_requests": 0,
                "maintenance_runs": 0,
                "enrichment_jobs": 0,
                "working_memory": 0,
            }
            if purge_ids:
                placeholders = ",".join("?" for _ in purge_ids)
                ids = list(purge_ids)
                for table, predicate in (
                    ("memory_links", "from_memory_id IN ({p}) OR to_memory_id IN ({p})"),
                    ("memory_embeddings", "memory_id IN ({p})"),
                    ("memory_fts", "memory_id IN ({p})"),
                    ("memory_nodes", "memory_id IN ({p})"),
                    ("raw_events", "memory_id IN ({p})"),
                ):
                    statement = f"DELETE FROM {table} WHERE {predicate.format(p=placeholders)}"
                    parameters = [*ids, *ids] if table == "memory_links" else ids
                    cursor = connection.execute(statement, parameters)
                    counts[table] = cursor.rowcount

            cursor = connection.execute(
                "DELETE FROM add_requests WHERE completed_at < ?", (cutoff,)
            )
            counts["add_requests"] = cursor.rowcount
            cursor = connection.execute(
                "DELETE FROM maintenance_runs WHERE COALESCE(completed_at, started_at) < ?",
                (cutoff,),
            )
            counts["maintenance_runs"] = cursor.rowcount
            cursor = connection.execute(
                "DELETE FROM enrichment_jobs WHERE COALESCE(completed_at, created_at) < ?",
                (cutoff,),
            )
            counts["enrichment_jobs"] = cursor.rowcount
            affected_users = [
                row["user_id"]
                for row in connection.execute(
                    "SELECT user_id FROM working_memory WHERE updated_at < ?",
                    (cutoff,),
                ).fetchall()
            ]
            for user_id in affected_users:
                connection.execute("DELETE FROM working_memory WHERE user_id = ?", (user_id,))
                self._refresh_working_memory(connection, user_id, utc_now())
            counts["working_memory"] = len(affected_users)
            connection.commit()
            return counts
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def apply_maintenance(
        self,
        *,
        user_id: str,
        request_id: str,
        events: tuple[EventRecord, ...],
        plan: "MaintenancePlan",
        watermark_request_id: str | None = None,
    ) -> tuple[NodeRecord, ...]:
        now = utc_now()
        event_by_ordinal = {event.ordinal: event for event in events}
        touched_ids: list[str] = []
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                """
                SELECT status FROM maintenance_runs
                WHERE user_id = ? AND trigger_request_id = ?
                """,
                (user_id, request_id),
            ).fetchone()
            if run is None or run["status"] != "running":
                raise ValueError("maintenance run is not active")

            for memory_id in plan.tombstone_memory_ids:
                self._require_owned_node(connection, user_id, memory_id)
                self._set_node_status(connection, memory_id, "tombstoned", now)

            for fact in plan.facts:
                try:
                    source_events = [
                        event_by_ordinal[ordinal]
                        for ordinal in fact.source_ordinals
                    ]
                except KeyError as error:
                    raise ValueError(
                        "maintenance fact cited an unknown source ordinal"
                    ) from error
                source_ids = [event.memory_id for event in source_events]
                canonical_key = fact.canonical_key or fact.content
                fact_id = stable_structured_id(user_id, "fact", canonical_key)
                fact_content = _fact_content(fact.content, source_events)
                fact_temporal = _fact_temporal_hint(fact, source_events)
                self._upsert_node(
                    connection,
                    memory_id=fact_id,
                    user_id=user_id,
                    kind="fact",
                    title=fact.title,
                    content=fact_content,
                    event_time=fact.event_time or (
                        fact_temporal.start if fact_temporal else None
                    ),
                    valid_from=fact.valid_from,
                    valid_to=fact.valid_to,
                    confidence=fact.confidence,
                    source_event_ids=source_ids,
                    canonical_key=canonical_key,
                    evidence_group_id=stable_evidence_group_id(
                        user_id, "fact", canonical_key
                    ),
                    time_expression=(
                        fact_temporal.expression if fact_temporal else fact.time_expression
                    ),
                    resolved_time_start=fact_temporal.start if fact_temporal else None,
                    resolved_time_end=fact_temporal.end if fact_temporal else None,
                    time_precision=fact_temporal.precision if fact_temporal else None,
                    now=now,
                )
                touched_ids.append(fact_id)

                for event in source_events:
                    self._insert_link(
                        connection, user_id, event.memory_id, fact_id, "supports", now
                    )

                for entity_name in fact.entities:
                    if not entity_name.strip():
                        continue
                    entity_id = stable_structured_id(
                        user_id, "entity", entity_name
                    )
                    self._upsert_node(
                        connection,
                        memory_id=entity_id,
                        user_id=user_id,
                        kind="entity",
                        title=entity_name,
                        content=_fact_content(
                            f"Entity: {entity_name}", source_events
                        ),
                        event_time=None,
                        valid_from=None,
                        valid_to=None,
                        confidence=fact.confidence,
                        source_event_ids=source_ids,
                        canonical_key=entity_name,
                        evidence_group_id=stable_evidence_group_id(
                            user_id, "entity", entity_name
                        ),
                        now=now,
                    )
                    touched_ids.append(entity_id)
                    self._insert_link(
                        connection, user_id, fact_id, entity_id, "about", now
                    )

                for concept_name in fact.concepts:
                    if not concept_name.strip():
                        continue
                    concept_id = stable_structured_id(
                        user_id, "concept", concept_name
                    )
                    self._upsert_node(
                        connection,
                        memory_id=concept_id,
                        user_id=user_id,
                        kind="concept",
                        title=concept_name,
                        content=_fact_content(
                            f"Concept: {concept_name}", source_events
                        ),
                        event_time=None,
                        valid_from=None,
                        valid_to=None,
                        confidence=fact.confidence,
                        source_event_ids=source_ids,
                        canonical_key=concept_name,
                        evidence_group_id=stable_evidence_group_id(
                            user_id, "concept", concept_name
                        ),
                        now=now,
                    )
                    touched_ids.append(concept_id)
                    self._insert_link(
                        connection,
                        user_id,
                        fact_id,
                        concept_id,
                        "related_to",
                        now,
                    )

                for previous_id in fact.supersedes_memory_ids:
                    self._require_owned_node(connection, user_id, previous_id)
                    self._set_node_status(
                        connection,
                        previous_id,
                        "superseded",
                        now,
                        valid_to=fact.valid_from or fact.event_time,
                    )
                    self._insert_link(
                        connection,
                        user_id,
                        fact_id,
                        previous_id,
                        "supersedes",
                        now,
                    )

            connection.execute(
                """
                UPDATE working_memory
                SET maintenance_watermark = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (watermark_request_id or request_id, now, user_id),
            )
            connection.execute(
                """
                UPDATE maintenance_runs
                SET status = 'completed', error_type = NULL, completed_at = ?
                WHERE user_id = ? AND trigger_request_id = ?
                """,
                (now, user_id, request_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get_nodes_by_ids(user_id, touched_ids)

    @staticmethod
    def _require_owned_node(
        connection: sqlite3.Connection, user_id: str, memory_id: str
    ) -> None:
        row = connection.execute(
            "SELECT 1 FROM memory_nodes WHERE user_id = ? AND memory_id = ?",
            (user_id, memory_id),
        ).fetchone()
        if row is None:
            raise ValueError("maintenance referenced an unknown memory ID")

    @staticmethod
    def _set_node_status(
        connection: sqlite3.Connection,
        memory_id: str,
        status: str,
        now: str,
        *,
        valid_to: str | None = None,
    ) -> None:
        connection.execute(
            """
            UPDATE memory_nodes
            SET status = ?, updated_at = ?, version = version + 1,
                valid_to = COALESCE(?, valid_to)
            WHERE memory_id = ?
            """,
            (status, now, valid_to, memory_id),
        )
        if status == "tombstoned":
            connection.execute(
                "UPDATE raw_events SET status = 'tombstoned' WHERE memory_id = ?",
                (memory_id,),
            )
            connection.execute(
                "DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,)
            )
            connection.execute(
                "DELETE FROM memory_embeddings WHERE memory_id = ?", (memory_id,)
            )

    @staticmethod
    def _insert_link(
        connection: sqlite3.Connection,
        user_id: str,
        from_memory_id: str,
        to_memory_id: str,
        relation: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO memory_links (
                user_id, from_memory_id, to_memory_id, relation, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, from_memory_id, to_memory_id, relation, now),
        )

    @staticmethod
    def _upsert_node(
        connection: sqlite3.Connection,
        *,
        memory_id: str,
        user_id: str,
        kind: str,
        title: str,
        content: str,
        event_time: str | None,
        valid_from: str | None,
        valid_to: str | None,
        confidence: float,
        source_event_ids: list[str],
        now: str,
        canonical_key: str | None = None,
        evidence_group_id: str | None = None,
        time_expression: str | None = None,
        resolved_time_start: str | None = None,
        resolved_time_end: str | None = None,
        time_precision: str | None = None,
    ) -> None:
        canonical_key = canonical_key or content
        evidence_group_id = evidence_group_id or stable_evidence_group_id(
            user_id, kind, canonical_key
        )
        existing = connection.execute(
            """
            SELECT source_event_ids FROM memory_nodes
            WHERE memory_id = ? AND user_id = ?
            """,
            (memory_id, user_id),
        ).fetchone()
        if existing is not None:
            previous_sources = json.loads(existing["source_event_ids"])
            source_event_ids = list(dict.fromkeys([*previous_sources, *source_event_ids]))
        encoded_sources = json.dumps(source_event_ids, ensure_ascii=False)
        connection.execute(
            """
            INSERT INTO memory_nodes (
                memory_id, user_id, kind, title, content, event_time,
                valid_from, valid_to,
                created_at, updated_at, confidence, activity, status,
                version, source_event_ids, canonical_key, evidence_group_id,
                time_expression, resolved_time_start, resolved_time_end, time_precision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', 1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                event_time = COALESCE(excluded.event_time, memory_nodes.event_time),
                valid_from = COALESCE(excluded.valid_from, memory_nodes.valid_from),
                valid_to = excluded.valid_to,
                updated_at = excluded.updated_at,
                confidence = MAX(memory_nodes.confidence, excluded.confidence),
                activity = memory_nodes.activity + 1,
                status = 'active',
                version = memory_nodes.version + 1,
                source_event_ids = excluded.source_event_ids,
                canonical_key = COALESCE(excluded.canonical_key, memory_nodes.canonical_key),
                evidence_group_id = COALESCE(excluded.evidence_group_id, memory_nodes.evidence_group_id),
                time_expression = COALESCE(excluded.time_expression, memory_nodes.time_expression),
                resolved_time_start = COALESCE(excluded.resolved_time_start, memory_nodes.resolved_time_start),
                resolved_time_end = COALESCE(excluded.resolved_time_end, memory_nodes.resolved_time_end),
                time_precision = COALESCE(excluded.time_precision, memory_nodes.time_precision)
            """,
            (
                memory_id,
                user_id,
                kind,
                title,
                content,
                event_time,
                valid_from,
                valid_to,
                now,
                now,
                confidence,
                encoded_sources,
                canonical_key,
                evidence_group_id,
                time_expression,
                resolved_time_start,
                resolved_time_end,
                time_precision,
            ),
        )
        connection.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        connection.execute(
            """
            INSERT INTO memory_fts (memory_id, user_id, kind, content)
            VALUES (?, ?, ?, ?)
            """,
            (memory_id, user_id, kind, f"{title}\n{content}"),
        )

    def replace_embeddings(
        self,
        *,
        user_id: str,
        chunks: list[EmbeddingChunk],
        vectors: list[list[float]],
        model: str,
        dimensions: int,
        replace_user: bool = False,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("embedding chunks and vectors must have equal length")
        if not chunks:
            return
        memory_ids = list(dict.fromkeys(chunk.memory_id for chunk in chunks))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if replace_user:
                connection.execute(
                    """
                    DELETE FROM memory_embeddings
                    WHERE user_id = ? AND model = ? AND dimensions = ?
                    """,
                    (user_id, model, dimensions),
                )
            for memory_id in memory_ids:
                self._require_owned_node(connection, user_id, memory_id)
                if not replace_user:
                    connection.execute(
                        """
                        DELETE FROM memory_embeddings
                        WHERE memory_id = ? AND model = ? AND dimensions = ?
                        """,
                        (memory_id, model, dimensions),
                    )
            now = utc_now()
            for chunk, vector in zip(chunks, vectors, strict=True):
                packed = _pack_vector(vector, dimensions)
                content_hash = hashlib.sha256(
                    chunk.content.encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO memory_embeddings (
                        memory_id, user_id, model, dimensions, chunk_no,
                        content_hash, vector, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.memory_id,
                        user_id,
                        model,
                        dimensions,
                        chunk.chunk_no,
                        content_hash,
                        packed,
                        now,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def semantic_search(
        self,
        *,
        user_id: str,
        query_vector: list[float],
        model: str,
        dimensions: int,
        limit: int,
        include_superseded: bool = False,
    ) -> list[SearchResult]:
        normalized_query = _normalize(query_vector, dimensions)
        best: dict[str, tuple[float, sqlite3.Row]] = {}
        status_filter = (
            "n.status IN ('active', 'superseded')"
            if include_superseded
            else "n.status = 'active'"
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT e.memory_id, e.vector, n.content, n.event_time, n.created_at
                FROM memory_embeddings AS e
                JOIN memory_nodes AS n ON n.memory_id = e.memory_id
                WHERE e.user_id = ? AND n.user_id = ?
                  AND e.model = ? AND e.dimensions = ?
                  AND {status_filter}
                """,
                (user_id, user_id, model, dimensions),
            ).fetchall()
        for row in rows:
            stored = struct.unpack(f"<{dimensions}f", row["vector"])
            similarity = math.fsum(
                left * right for left, right in zip(normalized_query, stored, strict=True)
            )
            previous = best.get(row["memory_id"])
            if previous is None or similarity > previous[0]:
                best[row["memory_id"]] = (similarity, row)
        ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)[:limit]
        return [
            SearchResult(
                id=row["memory_id"],
                content=row["content"],
                score=round(max(0.0, min(1.0, (similarity + 1.0) / 2.0)), 6),
                created_at=row["event_time"] or row["created_at"],
            )
            for similarity, row in ranked
        ]

    def temporal_search(
        self,
        *,
        user_id: str,
        hint: TemporalHint,
        limit: int,
        include_superseded: bool = False,
    ) -> list[SearchResult]:
        if not hint.start or not hint.end or limit < 1:
            return []
        status_filter = (
            "n.status IN ('active', 'superseded')"
            if include_superseded
            else "n.status = 'active'"
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT n.memory_id, n.content, n.event_time, n.created_at,
                       n.valid_from, n.valid_to, n.resolved_time_start,
                       n.resolved_time_end
                FROM memory_nodes AS n
                WHERE n.user_id = ? AND {status_filter}
                  AND COALESCE(
                        n.resolved_time_start,
                        substr(n.event_time, 1, 10),
                        substr(n.valid_from, 1, 10)
                      ) IS NOT NULL
                ORDER BY COALESCE(n.resolved_time_start, n.event_time, n.created_at)
                LIMIT 2000
                """,
                (user_id,),
            ).fetchall()
        matched: list[SearchResult] = []
        for row in rows:
            start = row["resolved_time_start"] or row["event_time"] or row["valid_from"]
            start = start[:10] if start else None
            end = row["resolved_time_end"] or row["valid_to"]
            if not ranges_overlap(start, end, hint.start, hint.end):
                continue
            matched.append(
                SearchResult(
                    id=row["memory_id"],
                    content=row["content"],
                    score=0.85,
                    created_at=row["event_time"] or row["created_at"],
                )
            )
            if len(matched) >= limit:
                break
        return matched

    def expand_links(
        self,
        *,
        user_id: str,
        seed_ids: list[str],
        limit: int,
        max_hops: int = 2,
        fanout_per_seed: int = 8,
        include_superseded: bool = False,
        query_text: str = "",
    ) -> list[SearchResult]:
        return [
            path.result
            for path in self.expand_link_paths(
                user_id=user_id,
                seed_ids=seed_ids,
                limit=limit,
                max_hops=max_hops,
                fanout_per_seed=fanout_per_seed,
                include_superseded=include_superseded,
                query_text=query_text,
            )
        ]

    def expand_link_paths(
        self,
        *,
        user_id: str,
        seed_ids: list[str],
        limit: int,
        max_hops: int = 2,
        fanout_per_seed: int = 8,
        include_superseded: bool = False,
        query_text: str = "",
    ) -> list[GraphPath]:
        frontier = list(dict.fromkeys(seed_ids[:20]))
        if not frontier or limit < 1:
            return []
        visited = set(frontier)
        discovered: list[GraphPath] = []
        status_filter = (
            "n.status IN ('active', 'superseded')"
            if include_superseded
            else "n.status = 'active'"
        )
        with self._connect() as connection:
            placeholders = ",".join("?" for _ in frontier)
            seed_rows = connection.execute(
                f"""
                SELECT memory_id, source_event_ids
                FROM memory_nodes
                WHERE user_id = ? AND memory_id IN ({placeholders})
                """,
                [user_id, *frontier],
            ).fetchall()
            source_ids_by_memory = {
                row["memory_id"]: _decode_source_event_ids(row["source_event_ids"])
                for row in seed_rows
            }
            paths_by_memory = {memory_id: (memory_id,) for memory_id in frontier}
            relations_by_memory = {memory_id: () for memory_id in frontier}
            path_sources_by_memory = {
                memory_id: source_ids_by_memory.get(memory_id, ())
                for memory_id in frontier
            }
            for hop in range(1, max_hops + 1):
                if not frontier or len(discovered) >= limit:
                    break
                next_frontier: list[str] = []
                for source_id in frontier[:40]:
                    rows = connection.execute(
                        f"""
                        SELECT n.memory_id, n.content, n.event_time, n.created_at,
                               n.source_event_ids, l.relation
                        FROM memory_links AS l
                        JOIN memory_nodes AS n
                          ON n.memory_id = CASE
                            WHEN l.from_memory_id = ?
                            THEN l.to_memory_id ELSE l.from_memory_id END
                        WHERE (l.to_memory_id = ? OR l.from_memory_id = ?)
                          AND l.user_id = ? AND n.user_id = ?
                          AND {status_filter}
                        ORDER BY n.updated_at DESC, n.memory_id
                        LIMIT ?
                        """,
                        (
                            source_id,
                            source_id,
                            source_id,
                            user_id,
                            user_id,
                            fanout_per_seed * 4,
                        ),
                    ).fetchall()
                    ranked_rows = sorted(
                        rows,
                        key=lambda row: (
                            _query_relevance(query_text, row["content"]),
                            _query_relevance(
                                query_text, str(row["relation"]).replace("_", " ")
                            ),
                            row["created_at"] or "",
                        ),
                        reverse=True,
                    )[:fanout_per_seed]
                    for row in ranked_rows:
                        memory_id = row["memory_id"]
                        if memory_id in visited:
                            continue
                        visited.add(memory_id)
                        next_frontier.append(memory_id)
                        relevance = _query_relevance(query_text, row["content"])
                        relation_relevance = _query_relevance(
                            query_text, str(row["relation"]).replace("_", " ")
                        )
                        path_ids = (*paths_by_memory[source_id], memory_id)
                        relations = (
                            *relations_by_memory[source_id],
                            str(row["relation"]),
                        )
                        source_event_ids = tuple(
                            dict.fromkeys(
                                [
                                    *path_sources_by_memory[source_id],
                                    *_decode_source_event_ids(row["source_event_ids"]),
                                ]
                            )
                        )
                        paths_by_memory[memory_id] = path_ids
                        relations_by_memory[memory_id] = relations
                        path_sources_by_memory[memory_id] = source_event_ids
                        discovered.append(
                            GraphPath(
                                result=SearchResult(
                                    id=memory_id,
                                    content=row["content"],
                                    score=round(
                                        (0.5 + 0.5 * relevance) / hop, 6
                                    ),
                                    created_at=(
                                        row["event_time"] or row["created_at"]
                                    ),
                                ),
                                hop=hop,
                                path_ids=path_ids,
                                relations=relations,
                                source_event_ids=source_event_ids,
                                query_relevance=relevance,
                                relation_relevance=relation_relevance,
                            )
                        )
                        if len(discovered) >= limit:
                            break
                    if len(discovered) >= limit:
                        break
                frontier = next_frontier[:40]
        return discovered[:limit]

    def search(
        self,
        request: SearchRequest,
        max_top_k: int,
        *,
        extra_terms: tuple[str, ...] = (),
        candidate_limit: int | None = None,
        include_superseded: bool = False,
    ) -> list[SearchResult]:
        result_limit = min(request.top_k, max_top_k)
        limit = candidate_limit or result_limit
        retrieval_text = request.query
        if request.options:
            retrieval_text += " " + " ".join(request.options)
        if extra_terms:
            retrieval_text += " " + " ".join(extra_terms)
        tokens = _query_tokens(retrieval_text)
        rows: list[sqlite3.Row] = []
        seen: set[str] = set()
        status_filter = (
            "n.status IN ('active', 'superseded')"
            if include_superseded
            else "n.status = 'active'"
        )
        with self._connect() as connection:
            if tokens:
                fts_query = " OR ".join(_quote_fts_token(token) for token in tokens)
                rows.extend(
                    connection.execute(
                        f"""
                        SELECT n.memory_id, n.content, n.event_time, n.created_at,
                               bm25(memory_fts) AS text_rank
                        FROM memory_fts
                        JOIN memory_nodes AS n ON n.memory_id = memory_fts.memory_id
                        WHERE memory_fts MATCH ?
                          AND memory_fts.user_id = ?
                          AND n.user_id = ?
                          AND {status_filter}
                        ORDER BY text_rank ASC, n.created_at DESC
                        LIMIT ?
                        """,
                        (fts_query, request.user_id, request.user_id, limit * 3),
                    ).fetchall()
                )

            candidates = [row for row in rows if not _seen(row, seen)]
            if len(candidates) < limit and tokens:
                like_tokens = tokens[:5]
                conditions = " OR ".join("lower(content) LIKE ?" for _ in like_tokens)
                parameters: list[object] = [request.user_id]
                parameters.extend(f"%{token.lower()}%" for token in like_tokens)
                parameters.append(limit * 5)
                fallback_rows = connection.execute(
                    f"""
                    SELECT memory_id, content, event_time, created_at, 0 AS text_rank
                    FROM memory_nodes AS n
                    WHERE user_id = ? AND {status_filter}
                      AND ({conditions})
                    ORDER BY COALESCE(event_time, created_at) DESC
                    LIMIT ?
                    """,
                    parameters,
                ).fetchall()
                candidates.extend(
                    row for row in fallback_rows if not _seen(row, seen)
                )

        scored = [
            SearchResult(
                id=row["memory_id"],
                content=row["content"],
                score=_lexical_score(retrieval_text, row["content"], index),
                created_at=row["event_time"] or row["created_at"],
            )
            for index, row in enumerate(candidates)
        ]
        scored.sort(key=lambda item: item.score or 0.0, reverse=True)
        return scored[:limit]


def _seen(row: sqlite3.Row, seen: set[str]) -> bool:
    memory_id = row["memory_id"]
    if memory_id in seen:
        return True
    seen.add(memory_id)
    return False


def _query_tokens(query: str) -> list[str]:
    raw_tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", query.lower())
    tokens: list[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            # Keep the full CJK span for exact phrase fallback and add short
            # n-grams so FTS/LIKE can match entities embedded in a sentence.
            if len(token) <= 24:
                _append_query_token(token, tokens, seen)
            for size in (3, 2):
                for start in range(0, max(0, len(token) - size + 1)):
                    _append_query_token(token[start : start + size], tokens, seen)
            if len(token) == 1:
                _append_query_token(token, tokens, seen)
        else:
            if token in _ENGLISH_QUERY_STOPWORDS:
                continue
            _append_query_token(token, tokens, seen)
    return tokens[:32]


def _append_query_token(token: str, tokens: list[str], seen: set[str]) -> None:
    if token and token not in seen:
        seen.add(token)
        tokens.append(token)


def _quote_fts_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _lexical_score(query: str, content: str, index: int) -> float:
    tokens = _query_tokens(query)
    if not tokens:
        return max(0.0, 1.0 - index * 0.01)
    lowered = content.lower()
    coverage = sum(token in lowered for token in tokens) / len(tokens)
    phrase_bonus = 0.15 if query.lower() in lowered else 0.0
    position_penalty = min(index * 0.0025, 0.15)
    return round(max(0.0, min(1.0, 0.4 + 0.45 * coverage + phrase_bonus - position_penalty)), 6)


def _query_relevance(query: str, content: str) -> float:
    tokens = _query_tokens(query)
    if not tokens:
        return 0.0
    lowered = content.lower()
    return round(sum(token in lowered for token in tokens) / len(tokens), 6)


def stable_structured_id(user_id: str, kind: str, identity: str) -> str:
    normalized = unicodedata.normalize("NFKC", identity).casefold().strip()
    normalized = " ".join(normalized.split())
    source = f"{user_id}\0{kind}\0{normalized}".encode("utf-8")
    prefix = {
        "entity": "ent",
        "concept": "con",
        "fact": "fact",
        "maintenance": "mnt",
        "enrichment": "job",
    }.get(kind, "node")
    return prefix + "_" + hashlib.blake2b(source, digest_size=16).hexdigest()


def stable_evidence_group_id(user_id: str, kind: str, identity: str) -> str:
    normalized = unicodedata.normalize("NFKC", identity).casefold().strip()
    normalized = " ".join(normalized.split())
    source = f"{user_id}\0{kind}\0{normalized}".encode("utf-8")
    return "group_" + hashlib.blake2b(source, digest_size=16).hexdigest()


def _decode_source_event_ids(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(
        dict.fromkeys(item for item in decoded if isinstance(item, str) and item)
    )


def _row_to_node(row: sqlite3.Row) -> NodeRecord:
    return NodeRecord(**dict(row))


def _fact_temporal_hint(fact: object, events: list[EventRecord]) -> TemporalHint | None:
    requested_expression = getattr(fact, "time_expression", None)
    hints = [
        hint
        for event in events
        if (hint := extract_temporal_hint(event.content, anchor_time=event.source_time))
    ]
    if requested_expression:
        for hint in hints:
            if hint.expression.casefold() == requested_expression.casefold():
                return hint
        return TemporalHint(requested_expression, None, None, "expression")
    unique = {(hint.expression, hint.start, hint.end): hint for hint in hints}
    if len(unique) == 1:
        return next(iter(unique.values()))
    event_time = getattr(fact, "event_time", None)
    if event_time:
        start = event_time[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
            return TemporalHint(
                start,
                start,
                _next_day_iso(start),
                "day",
            )
    return None


def _next_day_iso(value: str) -> str:
    try:
        from datetime import date, timedelta

        return (date.fromisoformat(value) + timedelta(days=1)).isoformat()
    except ValueError:
        return value


def _fact_content(content: str, events: list[EventRecord]) -> str:
    evidence = []
    for event in events:
        excerpt = event.content if len(event.content) <= 800 else event.content[:797] + "..."
        source_time = event.source_time or "time unknown"
        evidence.append(
            f"- [{source_time}][{event.role}][{event.memory_id}] {excerpt}"
        )
    return content + "\n\nEvidence:\n" + "\n".join(evidence)


def _normalize(vector: list[float], dimensions: int) -> list[float]:
    if len(vector) != dimensions:
        raise ValueError("vector dimensions do not match configured dimensions")
    values = [float(value) for value in vector]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("vector contains a non-finite value")
    norm = math.sqrt(math.fsum(value * value for value in values))
    if norm == 0:
        raise ValueError("vector norm must be positive")
    return [value / norm for value in values]


def _pack_vector(vector: list[float], dimensions: int) -> bytes:
    normalized = _normalize(vector, dimensions)
    return struct.pack(f"<{dimensions}f", *normalized)


def _ensure_column(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    existing = {
        row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
