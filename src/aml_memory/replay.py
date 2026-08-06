from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import AddRequest, SearchRequest, SearchResult
from .repository import SQLiteMemoryRepository


class ReplayModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceTarget(ReplayModel):
    ids: list[str] = Field(default_factory=list)
    contains_any: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_matcher(self) -> "EvidenceTarget":
        if not self.ids and not self.contains_any:
            raise ValueError("evidence target requires ids or contains_any")
        return self


class ReplaySearch(ReplayModel):
    id: str = Field(min_length=1)
    request: SearchRequest
    expected: list[EvidenceTarget] = Field(default_factory=list)
    expect_empty: bool = False
    category: Literal[
        "general",
        "single_hop",
        "temporal",
        "multi_hop",
        "open_domain",
        "adversarial",
        "historical",
    ] = "general"

    @model_validator(mode="after")
    def validate_expectation(self) -> "ReplaySearch":
        if self.expect_empty == bool(self.expected):
            raise ValueError("set either expected evidence or expect_empty")
        return self


class ReplayCase(ReplayModel):
    id: str = Field(min_length=1)
    adds: list[AddRequest] = Field(min_length=1)
    searches: list[ReplaySearch] = Field(min_length=1)


class ReplayManifest(ReplayModel):
    version: Literal[1] = 1
    cases: list[ReplayCase] = Field(min_length=1)


class HttpClient(Protocol):
    def post(self, path: str, *, json: dict[str, Any]) -> Any: ...


class ReplayRunner:
    def __init__(
        self,
        client: HttpClient,
        *,
        repository: SQLiteMemoryRepository | None = None,
        add_path: str = "/v1/memory/add",
        search_path: str = "/v1/memory/search",
        settle_seconds: float = 0.0,
        add_interval_seconds: float = 0.0,
        metrics_supplier: Callable[[], dict[str, int]] | None = None,
    ) -> None:
        self.client = client
        self.repository = repository
        self.add_path = add_path
        self.search_path = search_path
        self.settle_seconds = settle_seconds
        self.add_interval_seconds = add_interval_seconds
        self.metrics_supplier = metrics_supplier

    def run(self, manifest: ReplayManifest) -> dict[str, Any]:
        provider_before = self.metrics_supplier() if self.metrics_supplier else {}
        add_latencies: list[float] = []
        query_observations: list[dict[str, Any]] = []
        add_successes = 0
        add_total = 0

        for case in manifest.cases:
            case_add_ok = True
            for request in case.adds:
                add_total += 1
                started = time.perf_counter()
                response = self.client.post(
                    self.add_path,
                    json=request.model_dump(mode="json"),
                )
                add_latencies.append((time.perf_counter() - started) * 1000.0)
                if response.status_code == 200:
                    add_successes += 1
                else:
                    case_add_ok = False
                if self.add_interval_seconds > 0:
                    time.sleep(self.add_interval_seconds)
            if self.settle_seconds > 0:
                time.sleep(self.settle_seconds)

            for search in case.searches:
                started = time.perf_counter()
                response = self.client.post(
                    self.search_path,
                    json=search.request.model_dump(mode="json"),
                )
                latency_ms = (time.perf_counter() - started) * 1000.0
                results: list[SearchResult] = []
                error = None
                if response.status_code == 200:
                    try:
                        body = response.json()
                        results = [
                            SearchResult.model_validate(item)
                            for item in body.get("data", [])
                        ]
                    except (AttributeError, TypeError, ValueError) as exc:
                        error = type(exc).__name__
                else:
                    error = f"HTTP_{response.status_code}"
                query_observations.append(
                    _observe_query(
                        case_id=case.id,
                        search=search,
                        results=results,
                        latency_ms=latency_ms,
                        repository=self.repository,
                        add_ok=case_add_ok,
                        error=error,
                    )
                )

        provider_after = self.metrics_supplier() if self.metrics_supplier else {}
        provider_delta = {
            key: provider_after.get(key, 0) - provider_before.get(key, 0)
            for key in set(provider_before) | set(provider_after)
        }
        return _aggregate_report(
            manifest=manifest,
            observations=query_observations,
            add_latencies=add_latencies,
            add_successes=add_successes,
            add_total=add_total,
            provider_calls=provider_delta,
        )


def load_manifest(path: Path) -> ReplayManifest:
    return ReplayManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _observe_query(
    *,
    case_id: str,
    search: ReplaySearch,
    results: list[SearchResult],
    latency_ms: float,
    repository: SQLiteMemoryRepository | None,
    add_ok: bool,
    error: str | None,
) -> dict[str, Any]:
    target_ranks: list[int | None] = []
    for target in search.expected:
        rank = next(
            (
                index
                for index, result in enumerate(results, start=1)
                if _matches_target(result, target)
            ),
            None,
        )
        target_ranks.append(rank)

    duplicate_count = _duplicate_count(
        user_id=search.request.user_id,
        results=results,
        repository=repository,
    )
    return {
        "case_id": case_id,
        "search_id": search.id,
        "category": search.category,
        "latency_ms": round(latency_ms, 3),
        "result_count": len(results),
        "target_ranks": target_ranks,
        "expect_empty": search.expect_empty,
        "empty_correct": search.expect_empty and not results,
        "duplicate_count": duplicate_count,
        "add_ok": add_ok,
        "error": error,
    }


def _matches_target(result: SearchResult, target: EvidenceTarget) -> bool:
    if result.id in target.ids:
        return True
    content = result.content.casefold()
    return any(fragment.casefold() in content for fragment in target.contains_any)


def _duplicate_count(
    *,
    user_id: str,
    results: list[SearchResult],
    repository: SQLiteMemoryRepository | None,
) -> int:
    if not results:
        return 0
    if repository is not None:
        features = repository.get_ranking_features(
            user_id,
            [result.id for result in results],
        )
        signatures = [
            (
                features[result.id].evidence_group_id
                if result.id in features and features[result.id].evidence_group_id
                else result.id
            )
            for result in results
        ]
    else:
        signatures = [_content_signature(result.content) for result in results]
    return len(signatures) - len(set(signatures))


def _content_signature(content: str) -> str:
    return " ".join(content.casefold().split())[:1000]


def _aggregate_report(
    *,
    manifest: ReplayManifest,
    observations: list[dict[str, Any]],
    add_latencies: list[float],
    add_successes: int,
    add_total: int,
    provider_calls: dict[str, int],
) -> dict[str, Any]:
    scored = [item for item in observations if item["target_ranks"]]
    empty_cases = [item for item in observations if item["expect_empty"]]
    result_total = sum(item["result_count"] for item in observations)
    duplicate_total = sum(item["duplicate_count"] for item in observations)

    quality: dict[str, float | int | None] = {}
    for cutoff in (1, 5, 10):
        quality[f"evidence_recall_at_{cutoff}"] = _mean(
            _recall_at(item["target_ranks"], cutoff) for item in scored
        )
        quality[f"hit_rate_at_{cutoff}"] = _mean(
            1.0 if any(rank is not None and rank <= cutoff for rank in item["target_ranks"])
            else 0.0
            for item in scored
        )
    quality["mrr"] = _mean(_reciprocal_rank(item["target_ranks"]) for item in scored)
    quality["empty_accuracy"] = _mean(
        1.0 if item["empty_correct"] else 0.0 for item in empty_cases
    )
    quality["duplicate_rate"] = (
        round(duplicate_total / result_total, 6) if result_total else 0.0
    )
    quality["temporal_recall_at_10"] = _category_recall(
        observations, category="temporal", cutoff=10
    )
    quality["single_hop_recall_at_10"] = _category_recall(
        observations, category="single_hop", cutoff=10
    )
    quality["open_domain_recall_at_10"] = _category_recall(
        observations, category="open_domain", cutoff=10
    )
    quality["adversarial_recall_at_10"] = _category_recall(
        observations, category="adversarial", cutoff=10
    )
    quality["multi_hop_recall_at_10"] = _category_recall(
        observations, category="multi_hop", cutoff=10
    )
    quality["historical_recall_at_10"] = _category_recall(
        observations, category="historical", cutoff=10
    )
    quality["multi_hop_chain_coverage_at_10"] = _chain_coverage(
        observations, cutoff=10
    )

    search_latencies = [item["latency_ms"] for item in observations]
    errors = [item for item in observations if item["error"]]
    return {
        "manifest_version": manifest.version,
        "cases": len(manifest.cases),
        "adds": {
            "total": add_total,
            "success_rate": round(add_successes / add_total, 6) if add_total else 0.0,
            "latency_ms": _latency_summary(add_latencies),
        },
        "searches": {
            "total": len(observations),
            "success_rate": round(
                (len(observations) - len(errors)) / len(observations), 6
            )
            if observations
            else 0.0,
            "latency_ms": _latency_summary(search_latencies),
        },
        "quality": quality,
        "provider_calls": provider_calls,
        "errors": [
            {
                "case_id": item["case_id"],
                "search_id": item["search_id"],
                "error": item["error"],
            }
            for item in errors
        ],
        "queries": observations,
    }


def _recall_at(ranks: list[int | None], cutoff: int) -> float:
    return sum(rank is not None and rank <= cutoff for rank in ranks) / len(ranks)


def _reciprocal_rank(ranks: list[int | None]) -> float:
    matched = [rank for rank in ranks if rank is not None]
    return 1.0 / min(matched) if matched else 0.0


def _category_recall(
    observations: list[dict[str, Any]], *, category: str, cutoff: int
) -> float | None:
    values = [
        _recall_at(item["target_ranks"], cutoff)
        for item in observations
        if item["category"] == category and item["target_ranks"]
    ]
    return _mean(values)


def _chain_coverage(
    observations: list[dict[str, Any]], *, cutoff: int
) -> float | None:
    values = [
        1.0
        if all(rank is not None and rank <= cutoff for rank in item["target_ranks"])
        else 0.0
        for item in observations
        if item["category"] == "multi_hop" and item["target_ranks"]
    ]
    return _mean(values)


def _mean(values: Any) -> float | None:
    items = list(values)
    return round(sum(items) / len(items), 6) if items else None


def _latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "p50": round(_percentile(values, 0.50), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


def _auth_headers(scheme: str, api_key: str) -> dict[str, str]:
    if scheme == "none":
        return {}
    if scheme == "token":
        return {"Authorization": f"Token {api_key}"}
    if scheme == "bearer":
        return {"Authorization": f"Bearer {api_key}"}
    if scheme == "x-api-key":
        return {"X-Api-Key": api_key}
    raise ValueError("unsupported auth scheme")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Add/Search benchmark manifest")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--add-path", default="/v1/memory/add")
    parser.add_argument("--search-path", default="/v1/memory/search")
    parser.add_argument(
        "--auth-scheme",
        choices=("none", "token", "bearer", "x-api-key"),
        default="none",
    )
    parser.add_argument("--api-key-env", default="AML_API_KEY")
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--settle-seconds", type=float, default=0.0)
    parser.add_argument("--add-interval-seconds", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    api_key = os.environ.get(arguments.api_key_env, "")
    if arguments.auth_scheme != "none" and not api_key:
        raise SystemExit(f"set {arguments.api_key_env} for authenticated replay")
    manifest = load_manifest(arguments.manifest)
    repository = (
        SQLiteMemoryRepository(arguments.db_path) if arguments.db_path else None
    )
    with httpx.Client(
        base_url=arguments.base_url.rstrip("/"),
        headers=_auth_headers(arguments.auth_scheme, api_key),
        timeout=1200.0,
    ) as client:
        report = ReplayRunner(
            client,
            repository=repository,
            add_path=arguments.add_path,
            search_path=arguments.search_path,
            settle_seconds=arguments.settle_seconds,
            add_interval_seconds=arguments.add_interval_seconds,
        ).run(manifest)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
