"""Case/dataset selection -> experiment -> validated local research view."""
from __future__ import annotations

import argparse
import importlib
import json
import uuid
from pathlib import Path

from benchmark.core import run_replay, write_json
from benchmark.datasets import build_retrieval_manifest
from benchmark.instrumented import Artifacts, LexicalMemory, ObservedTarget
from benchmark.observability import ObservationRecorder, VERSION
from benchmark.workspace import ROOT, register, publish, append_note, make_note
from dataset.pack import load_pack
from dataset.selection import select_pack


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m benchmark study")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--case")
    source.add_argument("--dataset-pack", type=Path)
    parser.add_argument("--record", action="append")
    parser.add_argument("--task", action="append")
    parser.add_argument("--turn", action="append")
    parser.add_argument("--scope", choices=("full", "anchors", "window"), default="full")
    parser.add_argument("--radius", type=int, default=1)
    parser.add_argument("--before", type=int, help="exclusive source timestamp in milliseconds")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--target", choices=("lexical", "aml-api", "native"), default="lexical")
    parser.add_argument("--factory", help="native local method module:factory(recorder, artifacts)")
    parser.add_argument("--base-url")
    parser.add_argument("--auth-scheme", choices=("none", "token", "bearer", "x-api-key"), default="none")
    parser.add_argument("--api-key-env")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--system-name")
    parser.add_argument("--system-version", default="v1")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--no-view", action="store_true")
    args = parser.parse_args(argv)
    if args.case and any((args.record, args.task, args.turn)):
        parser.error("case binding supplies record/task/turn IDs")
    key = None
    if args.case:
        from casestudies.build import load_catalog
        case = load_catalog()["cases"].get(args.case)
        if not case or not case.get("data"):
            parser.error("case has no runnable source binding")
        data = case["data"]
        args.dataset_pack = ROOT / data["pack"]
        args.record, args.task = [data["record"]], [data["task"]]
        args.turn = data["turns"] if args.scope != "full" else None
        key = data["dataset"]
    pack = select_pack(load_pack(args.dataset_pack), record_ids=args.record, task_ids=args.task,
        turn_ids=args.turn, scope=args.scope, radius=args.radius, before=args.before,
        allow_partial=args.allow_partial, case_id=args.case, dataset_key=key)
    manifest = build_retrieval_manifest(pack, chunk_size=args.chunk_size, top_k=args.top_k)
    run_id = args.run_id or "study-"+uuid.uuid4().hex[:12]
    from benchmark.__main__ import RUN_ID_PATTERN, _build_target
    if not RUN_ID_PATTERN.fullmatch(run_id):
        parser.error("invalid run ID")
    if args.target != "aml-api" and (args.base_url or args.api_key_env or args.auth_scheme != "none"):
        parser.error("HTTP options apply only to aml-api")
    if (args.target == "native") != bool(args.factory):
        parser.error("native requires --factory; other targets do not accept it")
    output = ROOT / "benchmark/data" / ("plans" if args.plan_only else "runs") / run_id
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "dataset-pack.json", pack)
    write_json(output / "plan.json", manifest)
    write_json(output / "selection.json", pack["preparation"]["selection"])
    if args.plan_only:
        print(json.dumps({"plan": str(output), "selection": manifest["selection"]}, ensure_ascii=False))
        return
    with ObservationRecorder(output / "observability.jsonl", run_id=run_id,
            dataset_pack_sha256=manifest["dataset_pack_sha256"]) as recorder:
        artifacts = Artifacts(output)
        if args.target == "lexical":
            method = LexicalMemory(recorder, artifacts)
        elif args.target == "native":
            module, name = args.factory.split(":", 1)
            method = getattr(importlib.import_module(module), name)(recorder=recorder, artifacts=artifacts)
        else:
            method = _build_target(args)
        target = ObservedTarget(method, recorder, artifacts, args.target)
        report = run_replay(manifest=manifest, cases=manifest["cases"], target=target, run_id=run_id,
            system={"name": args.system_name or args.target, "version": args.system_version, "target": args.target},
            trace_path=output / "trace.jsonl")
    write_json(output / "report.json", report)
    write_json(output / "observability.meta.json", {"schema_version": VERSION, "run_id": run_id,
        "dataset_pack_sha256": manifest["dataset_pack_sha256"], "model_capture_complete": args.target == "lexical" or (args.target == "native" and getattr(method, "model_capture_complete", False) is True),
        "producer": "benchmark.study.v1"})
    write_json(output / "method.json", {"target": args.target, "factory": args.factory,
        "name": args.system_name or args.target, "version": args.system_version,
        "ranking": "English regex BM25 k1=1.2 b=0.75; raw message bodies only; no semantic rewrite" if args.target == "lexical" else "method-defined",
        "answer": "not executed by this runner", "retries": "none in arena; native method must declare its own policy",
        "metric_cutoffs": "only queries requested at least k results are eligible for @k"})
    register(output)
    if not args.no_view:
        publish()
    print(json.dumps({"run": str(output), "summary": report["summary"],
        "view": str(ROOT / "visualization/data/local/index.html") if not args.no_view else None}, ensure_ascii=False))


def workspace_main(argv):
    parser = argparse.ArgumentParser(prog="python -m benchmark workspace")
    parser.add_argument("action", choices=("publish", "register", "note", "import-note"))
    parser.add_argument("--run", type=Path)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--search")
    parser.add_argument("--stage", default="search")
    parser.add_argument("--span")
    parser.add_argument("--kind", choices=("observation", "hypothesis", "next_experiment"), default="observation")
    parser.add_argument("--author")
    parser.add_argument("--text")
    parser.add_argument("--supersedes")
    parser.add_argument("--no-view", action="store_true")
    args = parser.parse_args(argv)
    if args.action != "publish" and not args.run:
        parser.error("--run is required")
    if args.action == "register":
        register(args.run, observations=args.observations)
    elif args.action in {"note", "import-note"}:
        if args.action == "import-note":
            if not args.file or args.file.stat().st_size > 20000:
                parser.error("provide a note file smaller than 20 KB")
            note = json.loads(args.file.read_text(encoding="utf-8"))
        else:
            from visualization.traces import read_run
            if not all((args.search, args.author, args.text)):
                parser.error("note requires --search, --author and --text")
            note = make_note(read_run(args.run, "experiment", max_queries=100000), search_id=args.search,
                stage=args.stage, span_id=args.span, kind=args.kind, author=args.author,
                text=args.text, supersedes=args.supersedes)
        append_note(args.run, note)
        register(args.run)
    if not args.no_view:
        publish()


if __name__ == "__main__":
    main()
