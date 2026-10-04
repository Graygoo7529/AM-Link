from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from benchmark.core import load_manifest, run_replay, write_json
from benchmark.targets import AmlApiTarget, Mem0OssTarget


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "dataset" / "data" / "runs"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="replay one dataset manifest")
    run_parser.add_argument("--manifest", type=Path, required=True)
    run_parser.add_argument("--target", choices=("aml-api", "mem0-oss"), required=True)
    run_parser.add_argument("--base-url", required=True)
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


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base-url must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base-url must not include credentials, query, or fragment")
    return value.rstrip("/")


def _build_target(arguments: argparse.Namespace):
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
    arguments = _parser().parse_args()
    try:
        manifest = load_manifest(arguments.manifest)
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
        report = run_replay(
            manifest=manifest,
            cases=cases,
            target=target,
            run_id=run_id,
            system={
                "name": arguments.system_name or arguments.target,
                "version": arguments.system_version,
                "target": arguments.target,
                "base_url": _base_url(arguments.base_url),
                "api_version": "memory-api-v1.1" if arguments.target == "aml-api" else "mem0-oss-rest",
                "adapter_notes": (
                    []
                    if arguments.target == "aml-api"
                    else ["message timestamp and request_id are not forwarded by the OSS REST adapter"]
                ),
            },
            trace_path=trace_path,
        )
        report["artifact_paths"] = {
            "report": str(report_path),
            "trace": str(trace_path),
        }
        write_json(report_path, report)
        print(json.dumps({"run_id": run_id, "report": str(report_path), "trace": str(trace_path), "summary": report["summary"]}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"benchmark failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
