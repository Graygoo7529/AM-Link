from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from benchmark.targets import TargetResponse


SCHEMA_VERSION = 1
TOP_K_LIMITS = (1, 5, 10)


class Target(Protocol):
    def add(self, request: dict[str, Any]) -> TargetResponse: ...

    def search(self, request: dict[str, Any]) -> TargetResponse: ...


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(payload)
    return payload


def validate_manifest(payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"manifest schema_version must be {SCHEMA_VERSION}")
    dataset = payload.get("dataset")
    if not isinstance(dataset, dict) or not isinstance(dataset.get("id"), str):
        raise ValueError("manifest dataset.id is required")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest requires at least one case")
    case_ids: set[str] = set()
    search_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not _nonempty_string(case.get("id")):
            raise ValueError("each manifest case requires a non-empty id")
        if case["id"] in case_ids:
            raise ValueError(f"duplicate case id: {case['id']}")
        case_ids.add(case["id"])
        adds = case.get("adds")
        searches = case.get("searches")
        if not isinstance(adds, list):
            raise ValueError(f"case {case['id']} requires an Add list")
        if not isinstance(searches, list) or not searches:
            raise ValueError(f"case {case['id']} requires at least one Search")
        request_ids: set[str] = set()
        for request in adds:
            _validate_add_request(request)
            if request["request_id"] in request_ids:
                raise ValueError(f"duplicate request_id in {case['id']}")
            request_ids.add(request["request_id"])
        for search in searches:
            _validate_search(search)
            if search["id"] in search_ids:
                raise ValueError(f"duplicate Search id: {search['id']}")
            search_ids.add(search["id"])


def _validate_add_request(request: Any) -> None:
    if not isinstance(request, dict):
        raise ValueError("Add request must be an object")
    for key in ("request_id", "user_id", "session_id"):
        if not _nonempty_string(request.get(key)):
            raise ValueError(f"Add request requires non-empty {key}")
    messages = request.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 20:
        raise ValueError("text Add messages must contain between 1 and 20 items")
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            raise ValueError("each message requires role user or assistant")
        if not _nonempty_string(message.get("content")):
            raise ValueError("each message requires non-empty text content")
        timestamp = message.get("timestamp")
        if timestamp is not None and (not isinstance(timestamp, int) or timestamp < 0):
            raise ValueError("message timestamp must be a non-negative integer")


def _validate_search(search: Any) -> None:
    if not isinstance(search, dict) or not _nonempty_string(search.get("id")):
        raise ValueError("each Search requires a non-empty id")
    request = search.get("request")
    if not isinstance(request, dict):
        raise ValueError("Search request must be an object")
    if not _nonempty_string(request.get("query")) or not _nonempty_string(request.get("user_id")):
        raise ValueError("Search request requires non-empty query and user_id")
    top_k = request.get("top_k")
    if not isinstance(top_k, int) or not 1 <= top_k <= 100:
        raise ValueError("Search top_k must be between 1 and 100")
    expected = search.get("expected", [])
    empty = search.get("expect_empty", False)
    grading = search.get("grading")
    if not isinstance(expected, list) or not isinstance(empty, bool):
        raise ValueError("Search expected and expect_empty have invalid types")
    if grading is None:
        grading = "empty" if empty else "evidence" if expected else None
    if grading not in {"evidence", "empty", "ungraded"}:
        raise ValueError("Search grading must be evidence, empty, or ungraded")
    if (grading == "evidence" and (not expected or empty)) or (
        grading in {"empty", "ungraded"} and expected
    ) or (grading == "empty" and not empty) or (grading != "empty" and empty):
        raise ValueError("Search grading conflicts with expected evidence")
    for target in expected:
        if not isinstance(target, dict):
            raise ValueError("each expected evidence target must be an object")
        ids = target.get("ids", [])
        fragments = target.get("contains_any", [])
        if not isinstance(ids, list) or not all(_nonempty_string(value) for value in ids):
            raise ValueError("evidence ids must be a list of non-empty strings")
        if not isinstance(fragments, list) or not all(_nonempty_string(value) for value in fragments):
            raise ValueError("evidence fragments must be a list of non-empty strings")
        if not ids and not fragments:
            raise ValueError("each evidence target requires ids or contains_any")
        source = target.get("source")
        if source is not None and (
            not isinstance(source, dict)
            or not _nonempty_string(source.get("add_request_id"))
        ):
            raise ValueError("evidence source requires add_request_id")


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def run_replay(
    *,
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
    target: Target,
    run_id: str,
    system: dict[str, Any],
    trace_path: Path,
) -> dict[str, Any]:
    validate_manifest({"schema_version": SCHEMA_VERSION, "dataset": manifest["dataset"], "cases": cases})
    started_at = _now()
    add_latencies: list[float] = []
    search_latencies: list[float] = []
    errors: Counter[str] = Counter()
    queries: list[dict[str, Any]] = []
    add_total = 0
    add_successes = 0
    search_successes = 0
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    with trace_path.open("w", encoding="utf-8", newline="\n") as trace:
        for case in cases:
            case_adds_succeeded = True
            add_outcomes: dict[str, dict[str, Any]] = {}
            source_by_add: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for turn_id, fragments in manifest.get("source_map", {}).get(case["id"], {}).items():
                for fragment in fragments:
                    source_by_add[fragment["add_request_id"]].append({
                        "turn_id": turn_id, "session_id": fragment["session_id"],
                        "char_start": fragment["char_start"], "char_end": fragment["char_end"],
                    })
            for original in case["adds"]:
                request = _namespace_add(original, run_id)
                if hasattr(target, "set_observation_context"):
                    target.set_observation_context(record_id=case["id"], task_id=None,
                        request_id=request["request_id"])
                started = time.perf_counter()
                response = _invoke(target.add, request)
                latency_ms = (time.perf_counter() - started) * 1000.0
                add_latencies.append(latency_ms)
                add_total += 1
                error = _add_error(response, request, system["target"])
                succeeded = error is None
                case_adds_succeeded = case_adds_succeeded and succeeded
                add_successes += int(succeeded)
                add_outcomes[original["request_id"]] = {
                    "ok": succeeded,
                    "error": error,
                    "status_code": response.status_code,
                }
                if error:
                    errors[f"add:{error}"] += 1
                _write_trace(
                    trace,
                    {
                        "event": "add",
                        "occurred_at": _now(),
                        "run_id": run_id,
                        "case_id": case["id"],
                        "request_id": request["request_id"],
                        "latency_ms": round(latency_ms, 3),
                        "ok": succeeded,
                        "error": error,
                        "status_code": response.status_code,
                        "request": request,
                        "dataset_sources": source_by_add.get(original["request_id"], []),
                        "response": response.body,
                        "target_response": response.raw_body,
                    },
                )

            for search in case["searches"]:
                request = _namespace_search(search["request"], run_id)
                if hasattr(target, "set_observation_context"):
                    target.set_observation_context(record_id=case["id"],
                        task_id=search["dataset_task"]["task_id"], request_id=search["id"])
                started = time.perf_counter()
                response = _invoke(target.search, request)
                latency_ms = (time.perf_counter() - started) * 1000.0
                search_latencies.append(latency_ms)
                error, results = _search_results(response, system["target"], request["top_k"])
                succeeded = error is None
                search_successes += int(succeeded)
                if error:
                    errors[f"search:{error}"] += 1
                observation = _observe_query(
                    case_id=case["id"],
                    search=search,
                    results=results,
                    latency_ms=latency_ms,
                    add_ok=case_adds_succeeded,
                    search_ok=succeeded,
                    add_outcomes=add_outcomes,
                    top_k=request["top_k"],
                )
                queries.append(observation)
                _write_trace(
                    trace,
                    {
                        "event": "search",
                        "occurred_at": _now(),
                        "run_id": run_id,
                        "case_id": case["id"],
                        "search_id": search["id"],
                        "dataset_task": search.get("dataset_task"),
                        "latency_ms": round(latency_ms, 3),
                        "add_setup_ok": case_adds_succeeded,
                        "ok": succeeded,
                        "error": error,
                        "status_code": response.status_code,
                        "request": request,
                        "expected": search.get("expected", []),
                        "expect_empty": search.get("expect_empty", False),
                        "grading": observation["grading"],
                        "target_ranks": observation["target_ranks"],
                        "evidence_diagnosis": observation["evidence_diagnosis"],
                        "matched_targets_by_result": observation["matched_targets_by_result"],
                        "results": results,
                        "target_response": response.raw_body,
                    },
                )

    metrics = _metrics(queries)
    return {
        "schema_version": 1,
        "run": {
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": _now(),
            "quality_role": "public-data-retrieval-diagnostic; not AML official score",
            "dataset": manifest["dataset"],
            "adapter": manifest.get("adapter"),
            "dataset_selection": manifest.get("selection"),
            "dataset_pack_sha256": manifest.get("dataset_pack_sha256"),
            "excluded": manifest.get("excluded", []),
            "manifest_sha256": _json_digest(manifest),
            "system": system,
            "run_selection": {"cases": len(cases), "queries": len(queries)},
        },
        "summary": {
            "add": {
                "success": add_successes,
                "total": add_total,
                "success_rate": _ratio(add_successes, add_total),
                "latency_ms": _latency_summary(add_latencies),
            },
            "search": {
                "success": search_successes,
                "total": len(queries),
                "success_rate": _ratio(search_successes, len(queries)),
                "latency_ms": _latency_summary(search_latencies),
            },
            "retrieval": metrics,
            "errors": dict(sorted(errors.items())),
            "calls": {"add": add_total, "search": len(queries)},
            "provider_usage": None,
        },
        "queries": queries,
    }


def _namespace_add(request: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = json.loads(json.dumps(request))
    result["request_id"] = _scoped_id(run_id, result["request_id"])
    result["user_id"] = _scoped_id(run_id, result["user_id"])
    result["session_id"] = _scoped_id(run_id, result["session_id"])
    return result


def _namespace_search(request: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = json.loads(json.dumps(request))
    result["user_id"] = _scoped_id(run_id, result["user_id"])
    return result


def _scoped_id(run_id: str, value: str) -> str:
    return f"arena:{run_id}:{value}"


def _invoke(operation, request: dict[str, Any]) -> TargetResponse:
    try:
        response = operation(request)
        if not isinstance(response, TargetResponse):
            return TargetResponse(None, error_type="invalid_adapter_response")
        return response
    except Exception as error:
        return TargetResponse(None, error_type=f"adapter_error:{type(error).__name__}")


def _add_error(response: TargetResponse, request: dict[str, Any], target_name: str) -> str | None:
    if response.error_type:
        return response.error_type
    status_ok = response.status_code == 200 if target_name == "aml-api" else bool(
        response.status_code and 200 <= response.status_code < 300
    )
    if not status_ok:
        return response.error_code or f"http_status_{response.status_code}"
    body = response.body
    if not isinstance(body, dict):
        return "invalid_add_response"
    expected = {
        "success": True,
        "request_id": request["request_id"],
        "user_id": request["user_id"],
        "session_id": request["session_id"],
    }
    if any(body.get(key) != value for key, value in expected.items()):
        return "invalid_add_response"
    return None


def _search_results(
    response: TargetResponse,
    target_name: str,
    top_k: int,
) -> tuple[str | None, list[dict[str, Any]]]:
    if response.error_type:
        return response.error_type, []
    status_ok = response.status_code == 200 if target_name == "aml-api" else bool(
        response.status_code and 200 <= response.status_code < 300
    )
    if not status_ok:
        return response.error_code or f"http_status_{response.status_code}", []
    body = response.body
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        return "invalid_search_response", []
    if len(body["data"]) > top_k:
        return "search_exceeded_top_k", []
    results = []
    for item in body["data"]:
        if not isinstance(item, dict) or not _nonempty_string(item.get("id")) or not _nonempty_string(item.get("content")):
            return "invalid_search_response", []
        score = item.get("score")
        if score is not None and (not isinstance(score, (int, float)) or isinstance(score, bool)):
            return "invalid_search_response", []
        result = {"id": item["id"], "content": item["content"]}
        if score is not None:
            result["score"] = float(score)
        created_at = item.get("created_at")
        if isinstance(created_at, str):
            result["created_at"] = created_at
        details = item.get("target_metadata")
        if isinstance(details, dict) and details:
            result["target_metadata"] = details
        results.append(result)
    return None, results


def _observe_query(
    *,
    case_id: str,
    search: dict[str, Any],
    results: list[dict[str, Any]],
    latency_ms: float,
    add_ok: bool,
    search_ok: bool,
    add_outcomes: dict[str, dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    ranks: list[int | None] = []
    matched_by_result: list[list[int]] = [[] for _ in results]
    evidence_diagnosis = []
    for target_index, evidence in enumerate(search.get("expected", [])):
        match_rank = None
        ids = evidence.get("ids", [])
        fragments = [fragment.casefold() for fragment in evidence.get("contains_any", [])]
        for result_index, result in enumerate(results):
            matched = result["id"] in ids or any(
                fragment in result["content"].casefold() for fragment in fragments
            )
            if matched:
                matched_by_result[result_index].append(target_index)
                if match_rank is None:
                    match_rank = result_index + 1
        ranks.append(match_rank)
        source = evidence.get("source")
        add_status = add_outcomes.get(source.get("add_request_id")) if isinstance(source, dict) else None
        if not search_ok:
            status = "search_failed"
        elif add_status is not None and not add_status["ok"]:
            status = "source_add_failed"
        elif match_rank is None:
            status = "no_literal_evidence_match"
        elif match_rank > min(5, top_k):
            status = "retrieved_below_top5"
        else:
            status = "retrieved"
        evidence_diagnosis.append(
            {
                "target_index": target_index,
                "source": source,
                "source_add": add_status,
                "rank": match_rank,
                "status": status,
                "interpretation": _diagnosis_interpretation(status),
            }
        )
    expect_empty = search.get("expect_empty", False)
    return {
        "case_id": case_id,
        "search_id": search["id"],
        "category": search.get("category", "general"),
        "latency_ms": round(latency_ms, 3),
        "result_count": len(results),
        "requested_top_k": top_k,
        "target_count": len(ranks),
        "target_ranks": ranks,
        "evidence_diagnosis": evidence_diagnosis,
        "first_relevant_rank": min((rank for rank in ranks if rank is not None), default=None),
        "add_setup_ok": add_ok,
        "search_ok": search_ok,
        "expect_empty": expect_empty,
        "grading": search.get(
            "grading",
            "empty" if expect_empty else "evidence" if search.get("expected") else "ungraded",
        ),
        "empty_correct": bool(expect_empty and search_ok and add_ok and not results),
        "duplicate_count": _duplicate_count(results),
        "matched_targets_by_result": matched_by_result,
    }


def _diagnosis_interpretation(status: str) -> str:
    return {
        "search_failed": "Search failed at the adapter/API boundary; inspect its error and response.",
        "source_add_failed": "The Add request containing this source evidence failed validation or returned an error.",
        "no_literal_evidence_match": "No literal source fragment or expected result ID matched; the target may omit, transform, or summarize it.",
        "retrieved_below_top5": "A literal source match was returned below rank 5.",
        "retrieved": "A literal source match was returned within rank 5.",
    }[status]


def _metrics(queries: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in queries:
        grouped[str(query["category"])].append(query)
    empty = [query for query in queries if query["expect_empty"]]
    diagnosis_counts = Counter(
        evidence["status"]
        for query in queries
        for evidence in query["evidence_diagnosis"]
    )
    return {
        "overall": _group_metrics(queries),
        "by_category": {
            name: _group_metrics(grouped[name]) for name in sorted(grouped)
        },
        "empty_result_accuracy": _ratio(
            sum(query["empty_correct"] for query in empty), len(empty)
        ),
        "empty_result_queries": len(empty),
        "duplicate_rate": _ratio(
            sum(query["duplicate_count"] for query in queries),
            sum(query["result_count"] for query in queries),
        ),
        "evidence_diagnosis_counts": dict(sorted(diagnosis_counts.items())),
        "ungraded_queries": sum(query["grading"] == "ungraded" for query in queries),
    }


def _group_metrics(queries: list[dict[str, Any]]) -> dict[str, Any]:
    graded = [query for query in queries if query["target_count"]]
    target_total = sum(query["target_count"] for query in graded)
    result: dict[str, Any] = {"queries": len(queries), "graded_queries": len(graded)}
    for cutoff in TOP_K_LIMITS:
        eligible = [query for query in graded if query.get("requested_top_k", 0) >= cutoff]
        target_hits = sum(
            rank is not None and rank <= cutoff
            for query in eligible
            for rank in query["target_ranks"]
        )
        query_hits = sum(
            any(rank is not None and rank <= cutoff for rank in query["target_ranks"])
            for query in eligible
        )
        complete_chains = sum(
            all(rank is not None and rank <= cutoff for rank in query["target_ranks"])
            for query in eligible
        )
        result[f"eligible_queries@{cutoff}"] = len(eligible)
        result[f"evidence_recall@{cutoff}"] = _ratio(target_hits, sum(q["target_count"] for q in eligible))
        result[f"hit_rate@{cutoff}"] = _ratio(query_hits, len(eligible))
        result[f"chain_coverage@{cutoff}"] = _ratio(complete_chains, len(eligible))
    first_ranks = [
        1.0 / query["first_relevant_rank"] if query["first_relevant_rank"] is not None else 0.0
        for query in graded
    ]
    result["mrr"] = round(statistics.fmean(first_ranks), 6) if first_ranks else None
    result["evidence_targets"] = target_total
    return result


def _duplicate_count(results: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for result in results:
        signature = " ".join(result["content"].casefold().split())
        if signature in seen:
            duplicates += 1
        seen.add(signature)
    return duplicates


def _latency_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p95": None, "max": None}
    return {
        "p50": round(_percentile(values, 0.5), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_trace(file, event: dict[str, Any]) -> None:
    file.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    file.flush()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
