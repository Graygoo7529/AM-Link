from __future__ import annotations

import hashlib
import logging
import re
import threading
import time

from .maintenance import (
    MAINTENANCE_PROMPT_VERSION,
    MemoryMaintainer,
    QueryPlanner,
)
from .models import AddRequest, AddResponse, SearchRequest, SearchResponse, SearchResult
from .projection import MarkdownProjector
from .providers import EmbeddingProvider, JsonModelProvider
from .repository import (
    EmbeddingChunk,
    EventRecord,
    GraphPath,
    NodeRecord,
    RankingFeatures,
    SQLiteMemoryRepository,
)
from .temporal import extract_temporal_hint


LOGGER = logging.getLogger(__name__)


class MemoryService:
    def __init__(
        self,
        repository: SQLiteMemoryRepository,
        projector: MarkdownProjector,
        *,
        max_top_k: int,
        enrichment_mode: str = "sync",
        maintenance_event_threshold: int = 1,
        maintenance_char_threshold: int = 1,
        add_deadline_seconds: float = 120.0,
        search_deadline_seconds: float = 30.0,
        model_provider: JsonModelProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.repository = repository
        self.projector = projector
        self.max_top_k = max_top_k
        self.enrichment_mode = enrichment_mode
        self.maintenance_event_threshold = maintenance_event_threshold
        self.maintenance_char_threshold = maintenance_char_threshold
        self.add_deadline_seconds = add_deadline_seconds
        self.search_deadline_seconds = search_deadline_seconds
        self.model_provider = model_provider
        self.embedding_provider = embedding_provider
        self.maintainer = (
            MemoryMaintainer(model_provider) if model_provider is not None else None
        )
        self.query_planner = (
            QueryPlanner(model_provider) if model_provider is not None else None
        )
        self._user_locks = tuple(threading.Lock() for _ in range(256))
        self._worker_stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._metrics_lock = threading.Lock()
        self._metrics: dict[str, int] = {
            "llm_maintenance_calls": 0,
            "llm_search_calls": 0,
            "embedding_context_calls": 0,
            "embedding_search_calls": 0,
            "embedding_index_calls": 0,
            "embedding_index_texts": 0,
        }

    def metrics_snapshot(self) -> dict[str, int]:
        with self._metrics_lock:
            return dict(self._metrics)

    def _increment_metric(self, key: str, amount: int = 1) -> None:
        with self._metrics_lock:
            self._metrics[key] = self._metrics.get(key, 0) + amount

    def start_worker(self) -> None:
        if self.enrichment_mode != "async" or self._worker_thread is not None:
            return
        self._worker_stop.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="aml-enrichment",
            daemon=True,
        )
        self._worker_thread.start()

    def stop_worker(self) -> None:
        self._worker_stop.set()
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5.0)
            self._worker_thread = None

    def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            processed = self.process_pending_enrichment(limit=4)
            self._worker_stop.wait(0.1 if processed else 0.5)

    def process_pending_enrichment(self, *, limit: int = 8) -> int:
        processed = 0
        for user_id, request_id in self.repository.pending_enrichment_jobs(
            limit=limit
        ):
            lock_index = _user_lock_index(user_id, len(self._user_locks))
            with self._user_locks[lock_index]:
                if not self.repository.claim_enrichment(
                    user_id=user_id, request_id=request_id
                ):
                    continue
                events = self.repository.events_for_request(user_id, request_id)
                nodes = self._process_enrichment_job(
                    user_id=user_id,
                    request_id=request_id,
                    events=events,
                )
                if self.projector.enabled:
                    try:
                        self.projector.project(
                            user_id=user_id,
                            working_memory=self.repository.get_working_memory(user_id),
                            events=(),
                            nodes=nodes,
                        )
                    except OSError:
                        LOGGER.warning(
                            "async markdown projection degraded user_scope=%s "
                            "request_id=%s",
                            _short_hash(user_id),
                            request_id,
                        )
                processed += 1
        return processed

    def add(self, request: AddRequest) -> AddResponse:
        lock_index = _user_lock_index(request.user_id, len(self._user_locks))
        with self._user_locks[lock_index]:
            return self._add_serialized(request)

    def _add_serialized(self, request: AddRequest) -> AddResponse:
        outcome = self.repository.add(request)
        structured_nodes: tuple[NodeRecord, ...] = ()
        maintenance_due = self.maintainer is not None and self._maintenance_due(
            request.user_id
        )
        if not outcome.replayed and (
            maintenance_due or self.embedding_provider is not None
        ):
            self.repository.enqueue_enrichment(
                user_id=request.user_id,
                request_id=request.request_id,
            )
            if self.enrichment_mode == "sync" and self.repository.claim_enrichment(
                user_id=request.user_id,
                request_id=request.request_id,
            ):
                structured_nodes = self._process_enrichment_job(
                    user_id=request.user_id,
                    request_id=request.request_id,
                    events=outcome.events,
                )

        if self.projector.enabled:
            try:
                self.projector.project(
                    user_id=request.user_id,
                    working_memory=self.repository.get_working_memory(request.user_id),
                    events=outcome.events,
                    nodes=structured_nodes,
                )
            except OSError:
                LOGGER.exception(
                    "markdown projection failed user_scope=%s request_id=%s",
                    _short_hash(request.user_id),
                    request.request_id,
                )
        return outcome.response

    def _maintenance_due(self, user_id: str) -> bool:
        event_count, char_count = self.repository.maintenance_backlog(user_id)
        return (
            event_count >= self.maintenance_event_threshold
            or char_count >= self.maintenance_char_threshold
        )

    def _process_enrichment_job(
        self,
        *,
        user_id: str,
        request_id: str,
        events: tuple[EventRecord, ...],
    ) -> tuple[NodeRecord, ...]:
        deadline = time.monotonic() + self.add_deadline_seconds
        structured_nodes: tuple[NodeRecord, ...] = ()
        enrichment_error: str | None = None
        maintenance_due = self.maintainer is not None and self._maintenance_due(user_id)
        maintenance_events = (
            self.repository.pending_maintenance_events(user_id)
            if maintenance_due
            else ()
        )
        if maintenance_due and maintenance_events and time.monotonic() < deadline:
            started = self.repository.start_maintenance(
                user_id=user_id,
                request_id=request_id,
                model=self.maintainer.provider.model,
                prompt_version=MAINTENANCE_PROMPT_VERSION,
            )
            if started:
                structured_nodes = self._run_maintenance(
                    user_id=user_id,
                    request_id=request_id,
                    events=maintenance_events,
                )
            if self.repository.maintenance_status(user_id, request_id) == "failed":
                enrichment_error = "maintenance_failed"
        elif maintenance_due and maintenance_events:
            enrichment_error = "add_deadline_exceeded"
            started = self.repository.start_maintenance(
                user_id=user_id,
                request_id=request_id,
                model=self.maintainer.provider.model,
                prompt_version=MAINTENANCE_PROMPT_VERSION,
            )
            if started:
                self.repository.record_maintenance_failure(
                    user_id=user_id,
                    request_id=request_id,
                    error_type="DeadlineExceeded",
                )

        if self.embedding_provider is not None:
            if time.monotonic() >= deadline:
                enrichment_error = enrichment_error or "add_deadline_exceeded"
            else:
                raw_nodes = self.repository.get_nodes_by_ids(
                    user_id,
                    [event.memory_id for event in events],
                )
                try:
                    self._index_nodes((*raw_nodes, *structured_nodes))
                except Exception as error:
                    enrichment_error = type(error).__name__
                    LOGGER.warning(
                        "embedding indexing degraded user_scope=%s request_id=%s "
                        "error_type=%s",
                        _short_hash(user_id),
                        request_id,
                        type(error).__name__,
                    )

        if enrichment_error:
            self.repository.fail_enrichment(
                user_id=user_id,
                request_id=request_id,
                error_type=enrichment_error,
            )
        else:
            self.repository.complete_enrichment(
                user_id=user_id,
                request_id=request_id,
            )
        return structured_nodes

    def retry_failed_maintenance(self, *, user_id: str, request_id: str) -> bool:
        """Retry only a recorded failed run; normal Add replay remains idempotent."""
        if self.maintainer is None:
            raise RuntimeError("LLM maintenance is disabled")
        lock_index = _user_lock_index(user_id, len(self._user_locks))
        with self._user_locks[lock_index]:
            events = self.repository.pending_maintenance_events(user_id)
            if not events:
                return False
            claimed = self.repository.claim_failed_maintenance(
                user_id=user_id,
                request_id=request_id,
                model=self.maintainer.provider.model,
                prompt_version=MAINTENANCE_PROMPT_VERSION,
            )
            if not claimed:
                return False
            nodes = self._run_maintenance(
                user_id=user_id,
                request_id=request_id,
                events=events,
                watermark_request_id=events[-1].request_id,
            )
            if self.embedding_provider is not None and nodes:
                try:
                    raw_nodes = self.repository.get_nodes_by_ids(
                        user_id, [event.memory_id for event in events]
                    )
                    self._index_nodes((*raw_nodes, *nodes))
                except Exception as error:
                    LOGGER.warning(
                        "maintenance retry embedding degraded user_scope=%s "
                        "request_id=%s error_type=%s",
                        _short_hash(user_id),
                        request_id,
                        type(error).__name__,
                    )
            if self.projector.enabled:
                try:
                    self.projector.project(
                        user_id=user_id,
                        working_memory=self.repository.get_working_memory(user_id),
                        events=events,
                        nodes=nodes,
                    )
                except OSError:
                    LOGGER.warning(
                        "maintenance retry projection degraded user_scope=%s "
                        "request_id=%s",
                        _short_hash(user_id),
                        request_id,
                    )
            completed = (
                self.repository.maintenance_status(user_id, request_id) == "completed"
            )
            if completed:
                self.repository.complete_enrichment(
                    user_id=user_id,
                    request_id=request_id,
                )
            return completed

    def _run_maintenance(
        self,
        *,
        user_id: str,
        request_id: str,
        events: tuple[EventRecord, ...],
        watermark_request_id: str | None = None,
    ) -> tuple[NodeRecord, ...]:
        try:
            context_text = "\n".join(event.content for event in events)[:2400]
            preferred_ids: tuple[str, ...] = ()
            if self.embedding_provider is not None:
                try:
                    self._increment_metric("embedding_context_calls")
                    context_vector = self.embedding_provider.embed([context_text])[0]
                    preferred_ids = tuple(
                        item.id
                        for item in self.repository.semantic_search(
                            user_id=user_id,
                            query_vector=context_vector,
                            model=self.embedding_provider.model,
                            dimensions=self.embedding_provider.dimensions,
                            limit=20,
                        )
                    )
                except Exception as error:
                    LOGGER.warning(
                        "maintenance context semantic recall degraded "
                        "user_scope=%s request_id=%s error_type=%s",
                        _short_hash(user_id),
                        request_id,
                        type(error).__name__,
                    )
            context_nodes, context_links = self.repository.get_maintenance_context(
                user_id=user_id,
                retrieval_text=context_text,
                preferred_ids=preferred_ids,
            )
            self._increment_metric("llm_maintenance_calls")
            plan = self.maintainer.plan(
                events=events,
                context=context_nodes,
                links=context_links,
                working_memory=self.repository.get_working_memory(user_id),
            )
            return self.repository.apply_maintenance(
                user_id=user_id,
                request_id=request_id,
                events=events,
                plan=plan,
                watermark_request_id=watermark_request_id,
            )
        except Exception as error:
            LOGGER.warning(
                "maintenance degraded user_scope=%s request_id=%s error_type=%s",
                _short_hash(user_id),
                request_id,
                type(error).__name__,
            )
            try:
                self.repository.record_maintenance_failure(
                    user_id=user_id,
                    request_id=request_id,
                    error_type=type(error).__name__,
                )
            except Exception as record_error:
                LOGGER.warning(
                    "maintenance failure record failed user_scope=%s "
                    "request_id=%s error_type=%s",
                    _short_hash(user_id),
                    request_id,
                    type(record_error).__name__,
                )
            return ()

    def search(self, request: SearchRequest) -> SearchResponse:
        deadline = time.monotonic() + self.search_deadline_seconds
        candidate_limit = min(400, max(100, request.top_k * 4))
        planner_enabled = self.query_planner is not None
        query_temporal = extract_temporal_hint(
            request.query,
            anchor_time=self.repository.latest_source_time(request.user_id),
        )
        detected_intent = _infer_search_intent(request.query)
        if query_temporal is not None and detected_intent == "general":
            detected_intent = "temporal"
        initial_include_superseded = planner_enabled or detected_intent in {
            "historical",
            "temporal",
        }
        initial_lexical = self.repository.search(
            request,
            max_top_k=self.max_top_k,
            candidate_limit=candidate_limit,
            include_superseded=initial_include_superseded,
        )
        query_vector: list[float] | None = None
        initial_semantic = []
        if self.embedding_provider is not None and time.monotonic() < deadline:
            query_parts = [request.query, *(request.options or [])]
            try:
                self._increment_metric("embedding_search_calls")
                query_vector = self.embedding_provider.embed(
                    ["\n".join(query_parts)[:2400]]
                )[0]
                initial_semantic = self.repository.semantic_search(
                    user_id=request.user_id,
                    query_vector=query_vector,
                    model=self.embedding_provider.model,
                    dimensions=self.embedding_provider.dimensions,
                    limit=candidate_limit,
                    include_superseded=initial_include_superseded,
                )
            except Exception as error:
                LOGGER.warning(
                    "semantic search degraded user_scope=%s error_type=%s",
                    _short_hash(request.user_id),
                    type(error).__name__,
                )
        initial_temporal = (
            self.repository.temporal_search(
                user_id=request.user_id,
                hint=query_temporal,
                limit=candidate_limit,
                include_superseded=initial_include_superseded,
            )
            if query_temporal
            else []
        )
        initial_by_id = {
            item.id: item
            for item in [*initial_lexical, *initial_semantic, *initial_temporal]
        }
        planner_candidates = [
            {
                "id": item.id,
                "content": item.content[:800],
                "created_at": item.created_at,
            }
            for item in list(initial_by_id.values())[:40]
        ]
        extra_terms: tuple[str, ...] = ()
        include_superseded = detected_intent in {"historical", "temporal"}
        intent = detected_intent
        preferred_ids: tuple[str, ...] = ()
        if self.query_planner is not None and time.monotonic() < deadline:
            try:
                self._increment_metric("llm_search_calls")
                plan = self.query_planner.plan(
                    query=request.query,
                    options=request.options,
                    candidates=planner_candidates,
                )
                extra_terms = tuple(
                    dict.fromkeys(
                        [
                            *plan.retrieval_queries,
                            *plan.keywords,
                            *plan.entity_names,
                            *plan.time_hints,
                        ]
                    )
                )
                if plan.intent != "general" or detected_intent == "general":
                    intent = plan.intent
                include_superseded = intent in {"historical", "temporal"}
                preferred_ids = tuple(
                    memory_id
                    for memory_id in plan.preferred_memory_ids
                    if memory_id in initial_by_id
                )
            except Exception as error:
                LOGGER.warning(
                    "search planning degraded user_scope=%s error_type=%s",
                    _short_hash(request.user_id),
                    type(error).__name__,
                )

        lexical = initial_lexical
        if extra_terms or include_superseded != initial_include_superseded:
            lexical = self.repository.search(
                request,
                max_top_k=self.max_top_k,
                extra_terms=extra_terms,
                candidate_limit=candidate_limit,
                include_superseded=include_superseded,
            )

        semantic = initial_semantic
        if (
            query_vector is not None
            and include_superseded != initial_include_superseded
            and time.monotonic() < deadline
        ):
            try:
                semantic = self.repository.semantic_search(
                    user_id=request.user_id,
                    query_vector=query_vector,
                    model=self.embedding_provider.model,
                    dimensions=self.embedding_provider.dimensions,
                    limit=candidate_limit,
                    include_superseded=include_superseded,
                )
            except Exception as error:
                LOGGER.warning(
                    "semantic status filter degraded user_scope=%s error_type=%s",
                    _short_hash(request.user_id),
                    type(error).__name__,
                )
        temporal = initial_temporal
        if query_temporal and include_superseded != initial_include_superseded:
            temporal = self.repository.temporal_search(
                user_id=request.user_id,
                hint=query_temporal,
                limit=candidate_limit,
                include_superseded=include_superseded,
            )
        seed_ids = list(
            dict.fromkeys(
                [item.id for item in lexical[:20]]
                + [item.id for item in semantic[:20]]
                + [item.id for item in temporal[:20]]
            )
        )
        graph_paths = (
            self.repository.expand_link_paths(
                user_id=request.user_id,
                seed_ids=seed_ids,
                limit=candidate_limit,
                include_superseded=include_superseded,
                query_text=" ".join(
                    [request.query, *(request.options or []), *extra_terms]
                ),
            )
            if time.monotonic() < deadline
            else []
        )
        graph = [path.result for path in graph_paths]
        available_ids = {
            item.id for item in [*lexical, *semantic, *temporal, *graph]
        }
        model_ranking = [
            item for item in (initial_by_id[memory_id] for memory_id in preferred_ids)
            if item.id in available_ids
        ]
        features = self.repository.get_ranking_features(
            request.user_id,
            list(available_ids),
        )
        return SearchResponse(
            data=_fuse_rankings(
                lexical,
                semantic,
                temporal,
                graph,
                graph_paths,
                model_ranking,
                features,
                intent=intent,
                limit=min(request.top_k, self.max_top_k),
            )
        )

    def rebuild_embeddings(self, user_id: str | None = None) -> tuple[int, int]:
        if self.embedding_provider is None:
            raise RuntimeError("embedding provider is disabled")
        user_ids = (user_id,) if user_id is not None else self.repository.list_user_ids()
        rebuilt_users = 0
        rebuilt_nodes = 0
        for target_user_id in user_ids:
            nodes = self.repository.get_indexable_nodes(target_user_id)
            if not nodes:
                continue
            self._index_nodes(nodes, replace_user=True)
            rebuilt_users += 1
            rebuilt_nodes += len(nodes)
        return rebuilt_users, rebuilt_nodes

    def _index_nodes(
        self, nodes: tuple[NodeRecord, ...], *, replace_user: bool = False
    ) -> None:
        if self.embedding_provider is None or not nodes:
            return
        chunks: list[EmbeddingChunk] = []
        for node in nodes:
            for chunk_no, content in enumerate(_chunk_text(f"{node.title}\n{node.content}")):
                chunks.append(
                    EmbeddingChunk(
                        memory_id=node.memory_id,
                        chunk_no=chunk_no,
                        content=content,
                    )
                )
        self._increment_metric("embedding_index_calls")
        self._increment_metric("embedding_index_texts", len(chunks))
        vectors = self.embedding_provider.embed([chunk.content for chunk in chunks])
        self.repository.replace_embeddings(
            user_id=nodes[0].user_id,
            chunks=chunks,
            vectors=vectors,
            model=self.embedding_provider.model,
            dimensions=self.embedding_provider.dimensions,
            replace_user=replace_user,
        )

    def close(self) -> None:
        self.stop_worker()
        if self.model_provider is not None:
            self.model_provider.close()
        if self.embedding_provider is not None:
            self.embedding_provider.close()


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _user_lock_index(user_id: str, lock_count: int) -> int:
    return int.from_bytes(
        hashlib.sha256(user_id.encode("utf-8")).digest()[:2], "big"
    ) % lock_count


def _chunk_text(text: str, *, size: int = 2400, overlap: int = 200) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        if start + size >= len(text):
            break
        start += size - overlap
    return chunks


def _fuse_rankings(
    lexical: list[SearchResult],
    semantic: list[SearchResult],
    temporal: list[SearchResult],
    graph: list[SearchResult],
    graph_paths: list[GraphPath],
    model_ranking: list[SearchResult],
    features: dict[str, RankingFeatures],
    *,
    intent: str,
    limit: int,
) -> list[SearchResult]:
    path_ranking = _rank_graph_paths(graph_paths)
    by_id = {
        item.id: item
        for item in [
            *lexical,
            *semantic,
            *temporal,
            *graph,
            *path_ranking,
            *model_ranking,
        ]
    }
    scores: dict[str, float] = {}
    path_weight = 1.0 if intent == "multi_hop" else 0.35
    for weight, ranking in (
        (1.0, lexical),
        (0.9, semantic),
        (0.85, temporal),
        (0.7, graph),
        (path_weight, path_ranking),
        (1.2, model_ranking),
    ):
        for rank, item in enumerate(ranking, start=1):
            scores[item.id] = scores.get(item.id, 0.0) + weight / (60 + rank)
    for memory_id, feature in features.items():
        if memory_id not in scores:
            continue
        kind_bonus = {
            "daily": 0.0035,
            "fact": 0.003,
            "entity": 0.001,
            "concept": 0.0005,
        }.get(feature.kind, 0.0)
        confidence_bonus = max(0.0, min(feature.confidence or 0.0, 1.0)) * 0.001
        activity_bonus = min(feature.activity / 10.0, 1.0) * 0.001
        status_bonus = 0.0015 if feature.status == "active" else 0.0005
        if intent in {"historical", "temporal"} and feature.status == "superseded":
            status_bonus = 0.0015
        scores[memory_id] += (
            kind_bonus + confidence_bonus + activity_bonus + status_bonus
        )
    maximum = max(scores.values(), default=1.0)
    ordered_ids = sorted(
        scores,
        key=lambda memory_id: (scores[memory_id], by_id[memory_id].created_at or ""),
        reverse=True,
    )
    results: list[SearchResult] = []
    seen_groups: set[str] = set()
    for memory_id in ordered_ids:
        item = by_id[memory_id]
        feature = features.get(memory_id)
        group_id = _evidence_group_key(memory_id, feature)
        if group_id in seen_groups:
            continue
        seen_groups.add(group_id)
        results.append(
            item.model_copy(update={"score": round(scores[memory_id] / maximum, 6)})
        )
        if len(results) >= limit:
            break
    return results


def _rank_graph_paths(paths: list[GraphPath]) -> list[SearchResult]:
    if not paths:
        return []
    by_id = {path.result.id: path.result for path in paths}
    scores: dict[str, float] = {}
    for path in paths:
        source_coverage = min(len(path.source_event_ids), 4) / 4.0
        route_quality = (
            (path.result.score or 0.0)
            + 0.2 * path.query_relevance
            + 0.1 * path.relation_relevance
            + 0.08 * max(0, path.hop - 1)
            + 0.08 * source_coverage
        )
        for position, memory_id in enumerate(path.path_ids[1:], start=1):
            if memory_id not in by_id:
                continue
            propagated = route_quality - 0.005 * (position - 1)
            scores[memory_id] = max(scores.get(memory_id, 0.0), propagated)
    return [
        by_id[memory_id].model_copy(update={"score": round(scores[memory_id], 6)})
        for memory_id in sorted(
            scores,
            key=lambda memory_id: (
                scores[memory_id],
                by_id[memory_id].created_at or "",
            ),
            reverse=True,
        )
    ]


def _evidence_group_key(
    memory_id: str, feature: RankingFeatures | None
) -> str:
    if feature is None:
        return memory_id
    if feature.kind != "daily" and feature.source_event_ids:
        return "sources\0" + "\0".join(sorted(set(feature.source_event_ids)))
    return feature.evidence_group_id or memory_id


def _infer_search_intent(query: str) -> str:
    """Infer only high-confidence temporal intent for planner-free fallback."""
    lowered = query.casefold()
    if re.search(
        r"\b(previously|before|used to|historical|history|past)\b"
        r"|过去|之前|曾经|以前|原来|历史",
        lowered,
    ):
        return "historical"
    if re.search(
        r"\b(when|what date|what time|how long|which year)\b"
        r"|什么时候|何时|哪天|哪年|多久|时间",
        lowered,
    ):
        return "temporal"
    if re.search(
        r"\b(now|currently|current|today|latest)\b"
        r"|现在|目前|当前|如今|最新",
        lowered,
    ):
        return "current"
    if re.search(
        r"\b(why|how did|what caused|relationship)\b"
        r"|为什么|原因|关系|如何导致",
        lowered,
    ):
        return "multi_hop"
    return "general"
