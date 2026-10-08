from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from benchmark.core import run_replay, write_json
from benchmark.datasets import build_retrieval_manifest
from benchmark.targets import AmlApiTarget, Mem0LibraryTarget, Mem0OssTarget
from dataset.pack import load_pack


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "benchmark" / "data" / "runs"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan", help="build and inspect a replay plan without calling a target")
    plan_parser.add_argument("--dataset-pack", type=Path, required=True)
    plan_parser.add_argument("--chunk-size", type=int, default=20)
    plan_parser.add_argument("--top-k", type=int, default=10)
    plan_parser.add_argument("--output", type=Path, required=True)
    inspect_parser = commands.add_parser("inspect", help="inspect one case or Search with its trace")
    inspect_parser.add_argument("--report", type=Path, required=True)
    inspect_parser.add_argument("--trace", type=Path, required=True)
    selection = inspect_parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case-id")
    selection.add_argument("--search-id")

    run_parser = commands.add_parser("run", help="adapt a dataset pack and replay Add/Search")
    run_parser.add_argument("--dataset-pack", type=Path, required=True)
    run_parser.add_argument("--profile", choices=("evidence-retrieval",), default="evidence-retrieval")
    run_parser.add_argument("--chunk-size", type=int, default=20)
    run_parser.add_argument("--top-k", type=int, default=10)
    run_parser.add_argument("--target", choices=("aml-api", "mem0-oss", "mem0-library"), required=True)
    run_parser.add_argument("--base-url", default=None)
    run_parser.add_argument("--system-name", default=None)
    run_parser.add_argument("--system-version", default="unspecified")
    run_parser.add_argument("--auth-scheme", choices=("none", "token", "bearer", "x-api-key"), default="none")
    run_parser.add_argument("--api-key-env", default=None)
    run_parser.add_argument("--timeout", type=float, default=90.0)
    run_parser.add_argument("--run-id", default=None)
    run_parser.add_argument("--case-limit", type=int, default=None)
    run_parser.add_argument("--query-limit", type=int, default=None)
    run_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def _inspect(arguments: argparse.Namespace) -> None:
    report = json.loads(arguments.report.read_text(encoding="utf-8"))
    query_filter = (
        (lambda query: query.get("case_id") == arguments.case_id)
        if arguments.case_id
        else (lambda query: query.get("search_id") == arguments.search_id)
    )
    queries = [query for query in report.get("queries", []) if query_filter(query)]
    if not queries:
        selector = arguments.case_id or arguments.search_id
        raise ValueError(f"no report query found for {selector}")
    selected_ids = {(query["case_id"], query["search_id"]) for query in queries}
    with arguments.trace.open("r", encoding="utf-8") as source:
        events = [json.loads(line) for line in source if line.strip()]
    search_events = [
        event
        for event in events
        if event.get("event") == "search"
        and (event.get("case_id"), event.get("search_id")) in selected_ids
    ]
    source_add_ids = {
        diagnosis.get("source", {}).get("add_request_id")
        for event in search_events
        for diagnosis in event.get("evidence_diagnosis", [])
        if isinstance(diagnosis.get("source"), dict)
    }
    add_events = [
        event
        for event in events
        if event.get("event") == "add"
        and event.get("case_id") in {case_id for case_id, _ in selected_ids}
        and (not source_add_ids or any(
            isinstance(source_id, str)
            and event.get("request_id", "").endswith(f":{source_id}")
            for source_id in source_add_ids
        ))
    ]
    print(
        json.dumps(
            {
                "queries": queries,
                "source_add_events": add_events,
                "search_events": search_events,
                "diagnosis_scope": "API-boundary observations; no claim about inaccessible target internals",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base-url must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base-url must not include credentials, query, or fragment")
    return value.rstrip("/")


def _build_target(arguments: argparse.Namespace):
    if arguments.target == "mem0-library":
        if arguments.base_url or arguments.auth_scheme != "none" or arguments.api_key_env:
            raise ValueError("HTTP URL and authentication options do not apply to mem0-library")
        try:
            from mem0 import Memory
        except ImportError as error:
            raise ValueError("mem0-library requires the published 'mem0ai' package") from error
        return Mem0LibraryTarget(Memory())

    if not arguments.base_url:
        raise ValueError("--base-url is required for HTTP targets")
    key = None
    if arguments.auth_scheme != "none":
        if not arguments.api_key_env:
            raise ValueError("--api-key-env is required when auth is enabled")
        key = os.environ.get(arguments.api_key_env)
        if not key:
            raise ValueError(f"environment variable {arguments.api_key_env} is empty")

    options = {
        "base_url": _base_url(arguments.base_url),
        "timeout": arguments.timeout,
        "auth_scheme": arguments.auth_scheme,
        "api_key": key,
    }
    if arguments.target == "aml-api":
        return AmlApiTarget(**options)
    return Mem0OssTarget(**options)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] in {"study", "workspace", "answer"}:
        from benchmark.study import main as study_main, workspace_main
        from benchmark.answer import main as answer_main
        try:
            command = {"study": study_main, "workspace": workspace_main, "answer": answer_main}[sys.argv[1]]
            command(sys.argv[2:])
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            print(f"research command failed: {type(error).__name__}: {error}", file=sys.stderr)
            raise SystemExit(1) from error
        return
    arguments = _parser().parse_args()
    try:
        if arguments.command == "inspect":
            _inspect(arguments)
            return
        pack = load_pack(arguments.dataset_pack)
        manifest = build_retrieval_manifest(
            pack,
            chunk_size=arguments.chunk_size,
            top_k=arguments.top_k,
        )
        if arguments.command == "plan":
            write_json(arguments.output, manifest)
            print(json.dumps({"output": str(arguments.output), "cases": len(manifest["cases"]),
                "adds": sum(len(c["adds"]) for c in manifest["cases"]),
                "queries": sum(len(c["searches"]) for c in manifest["cases"]),
                "excluded": manifest.get("excluded", [])}, ensure_ascii=False))
            return
        run_id = arguments.run_id or uuid.uuid4().hex
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("run-id must be 1-64 ASCII letters, digits, dots, underscores, or hyphens")
        target = _build_target(arguments)
        cases = manifest["cases"]
        if arguments.case_limit is not None:
            if arguments.case_limit < 1:
                raise ValueError("case-limit must be positive")
            cases = cases[: arguments.case_limit]
        if arguments.query_limit is not None:
            if arguments.query_limit < 1:
                raise ValueError("query-limit must be positive")
            remaining = arguments.query_limit
            limited_cases = []
            for case in cases:
                if remaining == 0:
                    break
                selected = dict(case)
                selected["searches"] = case["searches"][:remaining]
                remaining -= len(selected["searches"])
                if selected["searches"]:
                    limited_cases.append(selected)
            cases = limited_cases
        if not cases:
            raise ValueError("run selection contains no cases")

        output_dir = arguments.output_dir / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        report_path = output_dir / "report.json"
        trace_path = output_dir / "trace.jsonl"
        pack_path = output_dir / "dataset-pack.json"
        write_json(pack_path, pack)
        write_json(output_dir / "plan.json", {**manifest, "cases": cases})
        report = run_replay(
            manifest=manifest,
            cases=cases,
            target=target,
            run_id=run_id,
            system={
                "name": arguments.system_name or arguments.target,
                "version": arguments.system_version,
                "target": arguments.target,
                "base_url": _base_url(arguments.base_url) if arguments.base_url else None,
                "api_version": {
                    "aml-api": "memory-api-v1.1",
                    "mem0-oss": "mem0-oss-rest",
                    "mem0-library": "mem0ai-python",
                }[arguments.target],
                "adapter_notes": {
                    "aml-api": [],
                    "mem0-oss": ["message timestamp and request_id are not forwarded by the OSS REST adapter"],
                    "mem0-library": ["per-message timestamp and request_id idempotency are not supported by the package adapter"],
                }[arguments.target],
            },
            trace_path=trace_path,
        )
        report["artifact_paths"] = {
            "report": str(report_path),
            "trace": str(trace_path),
            "dataset_pack": str(pack_path.resolve()),
            "dataset_pack_input": str(arguments.dataset_pack.resolve()),
        }
        write_json(report_path, report)
        print(json.dumps({"run_id": run_id, "report": str(report_path), "trace": str(trace_path), "summary": report["summary"]}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"benchmark failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
