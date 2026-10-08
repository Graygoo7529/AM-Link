"""Run a diagnostic Answer over the exact Search results saved by the arena."""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
import uuid
from pathlib import Path

from benchmark.core import write_json
from benchmark.instrumented import Artifacts
from benchmark.observability import ObservationRecorder
from benchmark.workspace import register, publish

MODEL = "gpt-5.6-luna"
PROMPT_VERSION = "amlink-answer-diagnostic-v1"
PROMPT = """Answer the question using only the retrieved memory evidence provided. Do not use outside knowledge to fill gaps. Preserve names, relationships, dates, ordering, quantities, units, and explicit updates. When evidence conflicts, explain the conflict instead of silently choosing. If the evidence is insufficient, say so plainly. Give a concise direct answer; do not show private reasoning."""
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def _provider_config(env_file: Path) -> tuple[str, str]:
    values = _read_env(env_file)
    key = values.get("AML_LLM_API_KEY") or values.get("OPENAI_API_KEY")
    base_url = values.get("AML_LLM_BASE_URL") or values.get("OPENAI_BASE_URL")
    if not key or not base_url:
        raise ValueError("Answer requires an explicit compatible LLM key and base URL")
    return key, base_url


def _search_inputs(trace_path: Path, run_id: str, limit: int) -> list[dict]:
    searches, seen = [], set()
    with trace_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event") != "search":
                continue
            if event.get("run_id") != run_id:
                raise ValueError("Search trace run ID mismatch")
            search_id = event.get("search_id")
            task = event.get("dataset_task")
            request = event.get("request")
            results = event.get("results")
            if not isinstance(search_id, str) or search_id in seen or not isinstance(task, dict):
                raise ValueError("invalid or duplicate Search identity")
            seen.add(search_id)
            if not event.get("ok"):
                searches.append({"search_id": search_id, "record_id": task.get("record_id"),
                    "task_id": task.get("task_id"), "status": "skipped", "reason": "search_failed"})
                continue
            if not isinstance(request, dict) or not isinstance(request.get("query"), str) or not isinstance(results, list):
                raise ValueError("successful Search requires a question and result list")
            memories = []
            for rank, result in enumerate(results, 1):
                if not isinstance(result, dict) or not isinstance(result.get("content"), str):
                    raise ValueError("Search results require text content")
                memories.append({"rank": rank, "content": result["content"]})
            searches.append({"search_id": search_id, "record_id": task.get("record_id"),
                "task_id": task.get("task_id"), "question": request["query"],
                "memories": memories, "status": "pending"})
            if sum(item["status"] != "skipped" for item in searches) >= limit:
                break
    return searches


def _artifact(artifacts: Artifacts, answer_id: str, kind: str, value: dict) -> dict:
    ref = artifacts.write(kind, value)
    ref["artifact"] = f"answers/{answer_id}/{ref['artifact']}"
    return ref


def _usage(response: dict, requested_model: str) -> dict:
    usage = response.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return {"provider": "configured-compatible-llm", "name": response.get("model") or requested_model,
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "cached_tokens": details.get("cached_tokens"),
        "cost_usd": None, "usage_source": "provider-response" if usage else "unavailable"}


def _complete(*, api_key: str, base_url: str, timeout: float, model: str,
        max_completion_tokens: int, messages: list[dict]) -> dict:
    body = json.dumps({"model": model, "max_completion_tokens": max_completion_tokens,
        "messages": messages}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m benchmark answer")
    parser.add_argument("--run", type=Path, required=True, help="an existing Add/Search run directory")
    parser.add_argument("--env-file", type=Path, required=True, help="explicit compatible-provider env file")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--answer-id", default=None)
    parser.add_argument("--max-questions", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--max-completion-tokens", type=int, default=700)
    parser.add_argument("--no-view", action="store_true")
    args = parser.parse_args(argv)
    run_dir = args.run.resolve()
    if not run_dir.is_dir() or not (run_dir / "trace.jsonl").is_file():
        parser.error("--run must point to an existing arena run")
    if not 1 <= args.max_questions <= 100 or args.timeout <= 0 or args.max_completion_tokens < 1:
        parser.error("question, timeout and output-token limits must be positive and bounded")
    answer_id = args.answer_id or f"answer-{uuid.uuid4().hex[:12]}"
    if not RUN_ID_PATTERN.fullmatch(answer_id):
        parser.error("invalid answer ID")
    meta = json.loads((run_dir / "observability.meta.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    run_id = report["run"]["run_id"]
    pack_hash = meta["dataset_pack_sha256"]
    if meta.get("run_id") != run_id:
        raise ValueError("run metadata identity mismatch")
    questions = _search_inputs(run_dir / "trace.jsonl", run_id, args.max_questions)
    if not any(item["status"] == "pending" for item in questions):
        raise ValueError("run has no successful Search results to answer")
    key, base_url = _provider_config(args.env_file)

    answer_dir = run_dir / "answers" / answer_id
    answer_dir.mkdir(parents=True, exist_ok=False)
    artifacts = Artifacts(answer_dir)
    observations = []
    rows = []
    usage_rows = []
    model_attempts = 0
    with ObservationRecorder(run_dir / "observability.jsonl", run_id=run_id,
            dataset_pack_sha256=pack_hash, append=True) as recorder:
        for item in questions:
            row = {k: v for k, v in item.items() if k != "memories"}
            if item["status"] == "skipped":
                rows.append(row)
                continue
            query_ref = _artifact(artifacts, answer_id, "query", {"question": item["question"]})
            context_value = {"question": item["question"], "retrieved_memories": item["memories"]}
            context_ref = _artifact(artifacts, answer_id, "context", context_value)
            try:
                with recorder.span("answer", name="诊断 Answer", record_id=item["record_id"],
                        task_id=item["task_id"], request_id=item["search_id"]) as answer_span:
                    answer_span["inputs"] = [query_ref, context_ref]
                    with recorder.span("model", name="Answer 生成模型", record_id=item["record_id"],
                            task_id=item["task_id"], request_id=item["search_id"], parent=answer_span) as model_span:
                        model_span["inputs"] = [query_ref, context_ref]
                        model_attempts += 1
                        response = _complete(api_key=key, base_url=base_url, timeout=args.timeout,
                            model=args.model, max_completion_tokens=args.max_completion_tokens,
                            messages=[{"role": "system", "content": PROMPT},
                                {"role": "user", "content": json.dumps(context_value, ensure_ascii=False)}])
                        model_span["model"] = _usage(response, args.model)
                        usage_rows.append(model_span["model"])
                        answer = response["choices"][0]["message"]["content"]
                        if not isinstance(answer, str) or not answer.strip():
                            raise ValueError("empty_answer")
                        answer = answer.strip()
                        answer_ref = _artifact(artifacts, answer_id, "answer", {
                            "text": answer, "model": response.get("model") or args.model,
                            "prompt_version": PROMPT_VERSION, "prompt": PROMPT})
                        model_span["outputs"] = [answer_ref]
                        model_span["links"] = [{"from_id": answer_ref["id"], "to_id": context_ref["id"],
                            "relation": "selected_from"}]
                    answer_span["outputs"] = [answer_ref]
                    answer_span["links"] = [{"from_id": answer_ref["id"], "to_id": context_ref["id"],
                        "relation": "selected_from"}]
                row.update(status="ok", answer=answer, model=response.get("model") or args.model,
                    context_result_ranks=[m["rank"] for m in item["memories"]])
                observations.append({"run_id": run_id, "record_id": item["record_id"],
                    "task_id": item["task_id"], "dataset_pack_sha256": pack_hash,
                    "answer": {"text": answer, "model": row["model"], "prompt_version": PROMPT_VERSION,
                        "source_artifact": answer_ref["artifact"],
                        "context_result_ranks": row["context_result_ranks"]}})
            except Exception as error:
                row.update(status="error", error_code=type(error).__name__)
            rows.append(row)
    (answer_dir / "answer.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    write_json(answer_dir / "observations.json", {"schema_version": 1, "observations": observations})
    write_json(answer_dir / "answer-run.json", {"schema_version": 1, "run_id": run_id,
        "answer_id": answer_id, "model_requested": args.model, "prompt_version": PROMPT_VERSION,
        "answer_count": sum(row["status"] == "ok" for row in rows),
        "failed_count": sum(row["status"] == "error" for row in rows),
        "skipped_count": sum(row["status"] == "skipped" for row in rows),
        "model_calls": model_attempts, "input_tokens": _sum_known(usage_rows, "input_tokens"),
        "output_tokens": _sum_known(usage_rows, "output_tokens"), "cost_usd": None,
        "timeout_seconds": args.timeout, "max_completion_tokens": args.max_completion_tokens,
        "request_retries": 0})
    register(run_dir, observations=answer_dir / "observations.json")
    if not args.no_view:
        publish()
    print(json.dumps({"run": str(run_dir), "answer_id": answer_id,
        "answers": sum(row["status"] == "ok" for row in rows),
        "failed": sum(row["status"] == "error" for row in rows),
        "observations": str(answer_dir / "observations.json")}, ensure_ascii=False))


def _sum_known(rows: list[dict], field: str):
    values = [row[field] for row in rows]
    return sum(values) if values and all(type(value) is int for value in values) else None


if __name__ == "__main__":
    main()
