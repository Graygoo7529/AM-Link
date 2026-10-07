"""Read observed API events; never invent inaccessible target internals."""
from __future__ import annotations

import json
from pathlib import Path

from dataset.pack import load_pack
from visualization.sources import digest, excerpt, file_digest
from visualization.spans import attach_spans


def read_run(path: Path, kind: str, max_queries: int = 20) -> dict:
    if kind not in {"fixture", "experiment"} or max_queries < 1:
        raise ValueError("explicit run kind and positive query limit required")
    report = json.loads((path / "report.json").read_text(encoding="utf-8"))
    plan = json.loads((path / "plan.json").read_text(encoding="utf-8"))
    pack = load_pack(path / "dataset-pack.json")
    run = report["run"]
    if report.get("schema_version") != 1 or plan.get("schema_version") != 1:
        raise ValueError("unsupported benchmark schema")
    pack_hash = digest(pack)
    if any(x.get("dataset_pack_sha256") != pack_hash for x in (run, plan)):
        raise ValueError("run/plan pack digest mismatch")
    if any(x["dataset"]["id"] != pack["dataset"]["id"] for x in (run, plan)):
        raise ValueError("run dataset mismatch")
    system = {k: run["system"].get(k) for k in ("name", "version", "target")}
    if kind == "experiment" and any(word in str(system).lower() for word in ("fixture", "test-only")):
        raise ValueError("test fixture cannot be labeled experiment")
    tasks = {(r["id"], t["id"]): t for r in pack["records"] for t in r["tasks"]}
    record_attributes = {r["id"]: r.get("attributes", {}) for r in pack["records"]}
    planned = {(c["id"], s["id"]): s for c in plan["cases"] for s in c["searches"]}
    add_plans = {(c["id"], a["request_id"]): a for c in plan["cases"] for a in c["adds"]}
    report_queries = {(q["case_id"], q["search_id"]): q for q in report["queries"]}
    events = [json.loads(line) for line in (path / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    prefix = f"arena:{run['run_id']}:"
    adds, queries, seen, request_scope = [], [], set(), {}
    for line, event in enumerate(events, 1):
        if event.get("run_id") != run["run_id"]:
            raise ValueError("mixed run IDs in trace")
        if event["event"] == "add":
            req = event["request"]
            if not req["request_id"].startswith(prefix):
                raise ValueError("unscoped Add request")
            original = add_plans.get((event["case_id"], req["request_id"][len(prefix):]))
            if original is None or req["messages"] != original["messages"] or any(
                req[k] != prefix + original[k] for k in ("request_id", "user_id", "session_id")):
                raise ValueError("Add differs from plan")
            adds.append({"id": req["request_id"], "record_id": event["case_id"], "line": line,
                "ok": event["ok"], "status_code": event.get("status_code"),
                "error": event.get("error"), "latency_ms": event["latency_ms"],
                "message_count": len(req["messages"]), "sources": event.get("dataset_sources", [])})
            request_scope[req["request_id"]] = (event["case_id"], None, {"add"})
        elif event["event"] == "search":
            key = event["case_id"], event["search_id"]
            if key in seen or key not in planned or key not in report_queries:
                raise ValueError("duplicate or unknown Search event")
            seen.add(key)
            search = planned[key]
            ref = search["dataset_task"]
            if event.get("dataset_task") != ref or (ref["record_id"], ref["task_id"]) not in tasks:
                raise ValueError("Search task mismatch")
            expected_request = {**search["request"], "user_id": prefix + search["request"]["user_id"]}
            if event["request"] != expected_request:
                raise ValueError("Search request differs from plan")
            if event["ok"] != report_queries[key]["search_ok"] or event["target_ranks"] != report_queries[key]["target_ranks"]:
                raise ValueError("Search report/trace mismatch")
            if event["search_id"] in request_scope:
                raise ValueError("ambiguous logical request ID")
            request_scope[event["search_id"]] = (ref["record_id"], ref["task_id"], {"search", "answer", "eval"})
            if len(queries) >= max_queries:
                continue
            matches = event.get("matched_targets_by_result", [])
            queries.append({"search_id": event["search_id"], "record_id": ref["record_id"],
                "task_id": ref["task_id"], "line": line, "query": event["request"]["query"],
                "top_k": event["request"]["top_k"], "ok": event["ok"], "error": event.get("error"),
                "status_code": event.get("status_code"), "latency_ms": event["latency_ms"],
                "grading": event["grading"], "target_ranks": event["target_ranks"],
                "adds": [a for a in adds if a["record_id"] == event["case_id"]],
                "expected": [{"source": e.get("source"), "content": excerpt(e.get("contains_any", []))}
                    for e in event.get("expected", [])],
                "results": [{"id": r["id"], "content": excerpt(r["content"]),
                    "matched_targets": matches[i] if i < len(matches) else [], "rank": i+1}
                    for i, r in enumerate(event["results"])],
                "answer": None, "evaluation": None, "steps": []})
            queries[-1]["research_case"] = {k: record_attributes[ref["record_id"]][k]
                for k in ("dataset_key", "case_id", "variant") if k in record_attributes[ref["record_id"]]}
        else:
            raise ValueError("unsupported trace event; explicit adapter required")
    if seen != set(report_queries):
        raise ValueError("missing Search events from trace")
    result = {"run_id": run["run_id"], "kind": kind, "system": system,
        "dataset_id": pack["dataset"]["id"], "dataset_pack_sha256": pack_hash,
        "source_sha256": pack["preparation"]["input"]["sha256"],
        "selection": run.get("dataset_selection"), "completed_at": run["completed_at"],
        "api_calls": report["summary"]["calls"], "provider_usage": report["summary"].get("provider_usage"),
        "total_queries": len(seen), "shown_queries": len(queries), "queries": queries,
        "artifacts": {n: file_digest(path/n) for n in ("plan.json", "dataset-pack.json", "trace.jsonl", "report.json")}}
    attach_spans(result, path, request_scope)
    return result


def attach_observations(runs: list[dict], path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError("unsupported observations schema")
    lookup = {(r["run_id"], q["record_id"], q["task_id"]): (r, q) for r in runs for q in r["queries"]}
    seen = set()
    for row in value["observations"]:
        key = row["run_id"], row["record_id"], row["task_id"]
        if key not in lookup or key in seen:
            raise ValueError("unknown or duplicate observation task")
        seen.add(key)
        run, query = lookup[key]
        if row["dataset_pack_sha256"] != run["dataset_pack_sha256"]:
            raise ValueError("observation pack mismatch")
        answer, evaluation = row.get("answer"), row.get("evaluation")
        if answer:
            for field in ("text", "model", "prompt_version", "source_artifact"):
                if not isinstance(answer.get(field), str) or not answer[field].strip():
                    raise ValueError(f"answer requires {field}")
            ranks = answer.get("context_result_ranks")
            if not isinstance(ranks, list) or any(type(r) is not int or not 1 <= r <= len(query["results"]) for r in ranks):
                raise ValueError("invalid Answer context ranks")
            query["answer"] = {k: answer[k] for k in ("model", "prompt_version", "source_artifact", "context_result_ranks")}
            query["answer"]["text"] = excerpt(answer["text"], 6000)
        if evaluation:
            if not answer or any(not isinstance(evaluation.get(k), str) or not evaluation[k].strip()
                for k in ("label", "metric", "evaluator", "source_artifact")):
                raise ValueError("evaluation requires Answer and provenance")
            query["evaluation"] = {k: evaluation[k] for k in ("label", "metric", "evaluator", "source_artifact")}
        for step in row.get("steps", []):
            if step.get("stage") not in {"add", "search", "answer"} or not step.get("source_artifact") or not step.get("description"):
                raise ValueError("step requires stage, description and provenance")
            query["steps"].append({k: step[k] for k in ("stage", "description", "source_artifact")})
        query["observations_sha256"] = file_digest(path)
