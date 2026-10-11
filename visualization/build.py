"""Build the unified research explorer without running a memory system."""
from __future__ import annotations

import argparse
import copy
import html
import json
import subprocess
import sys
from pathlib import Path

from casestudies.build import find_renderer, load_catalog, render_fragment
from visualization.sources import local_sources
from visualization.traces import attach_observations, read_run

ROOT = Path(__file__).resolve().parent


def presentation_bundle(bundle):
    """Deduplicate repeated span references for the self-contained view only.

    The validated full bundle and on-disk traces keep the public observation schema.
    The browser restores the same objects; no observed step is dropped.
    """
    compact = copy.deepcopy(bundle)
    for run in compact["runs"]:
        events, references = {}, {}
        converted_adds = set()
        for query in run["queries"]:
            for add in query["adds"]:
                if id(add) not in converted_adds:
                    add["sources"] = [[s.get(k) for k in ("turn_id", "session_id", "char_start", "char_end")] for s in add["sources"]]
                    converted_adds.add(id(add))
            for event in query["spans"]:
                events[event["span_id"]] = event
                for ref in event["inputs"]+event["outputs"]:
                    references[ref["id"]] = ref
            query["spans"] = [e["span_id"] for e in query["spans"]]
        columns = sorted(set().union(*(set(e) for e in events.values())) - {"run_id", "dataset_pack_sha256"}) if events else []
        rows = []
        for event in events.values():
            row = dict(event)
            for key in ("inputs", "outputs"):
                row[key] = [ref["id"] for ref in row[key]]
            rows.append([row.get(k) for k in columns])
        run["span_columns"], run["span_table"] = columns, rows
        run["span_references"] = [[ref[k] for k in ("id", "kind", "artifact", "sha256", "locator")] for ref in references.values()]
    return compact


def case_observations(case_id, *, catalog, profiles, runs):
    """Return only run queries aligned to the catalog's source binding."""
    case = catalog["cases"].get(case_id)
    if not case:
        return []
    binding = case.get("data")
    dataset_key = next(
        (key for key, dataset in catalog["datasets"].items() if case_id in dataset["cases"]),
        None,
    )
    if dataset_key is None:
        return []
    matches = []
    for run in runs:
        if binding:
            if run["dataset_id"] != profiles["datasets"][dataset_key]["dataset_id"]:
                continue
            for query in run["queries"]:
                if query["record_id"] == binding["record"] and query["task_id"] == binding["task"]:
                    matches.append({"run_id": run["run_id"], "search_id": query["search_id"],
                        "system": run["system"], "loaded": True})
        else:
            for query in run["queries"]:
                if query.get("research_case", {}).get("case_id") == case_id:
                    matches.append({"run_id": run["run_id"], "search_id": query["search_id"],
                        "system": run["system"], "loaded": True})
    return matches


def case_observation_index(registrations, *, catalog, profiles, runs, repo_root):
    """Index registered queries without embedding unloaded traces in the page."""
    index = {case_id: case_observations(case_id, catalog=catalog, profiles=profiles, runs=runs)
        for case_id in catalog["cases"]}
    loaded_ids = {run["run_id"] for run in runs}
    for row in registrations:
        if row["run_id"] in loaded_ids:
            continue
        directory = (repo_root / row["directory"]).resolve()
        if not directory.is_relative_to(repo_root / "benchmark/data"):
            raise ValueError("registered run escaped benchmark/data")
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
        run = report.get("run", {})
        if (report.get("schema_version") != 1 or plan.get("schema_version") != 1
            or run.get("run_id") != row["run_id"]
            or run.get("dataset_pack_sha256") != row["dataset_pack_sha256"]
            or plan.get("dataset_pack_sha256") != row["dataset_pack_sha256"]):
            raise ValueError(f"registered run identity mismatch: {row['run_id']}")
        dataset_id = run.get("dataset", {}).get("id")
        for case_id, case in catalog["cases"].items():
            binding = case.get("data")
            if not binding:
                continue
            dataset_key = binding["dataset"]
            if dataset_id != profiles["datasets"][dataset_key]["dataset_id"]:
                continue
            selection = run.get("dataset_selection") or {}
            if (binding["record"] not in selection.get("record_ids", [])
                or binding["task"] not in selection.get("task_ids", [])):
                continue
            for planned_case in plan.get("cases", []):
                for search in planned_case.get("searches", []):
                    source = search.get("dataset_task", {})
                    if (source.get("record_id"), source.get("task_id")) != (binding["record"], binding["task"]):
                        continue
                    search_id = search.get("id")
                    if not any(q.get("case_id") == binding["record"] and q.get("search_id") == search_id
                        for q in report.get("queries", [])):
                        continue
                    index[case_id].append({"run_id": row["run_id"], "search_id": search_id,
                        "system": {k: run.get("system", {}).get(k) for k in ("name", "version", "target")},
                        "loaded": False})
    return index


def build_bundle(local: bool = False, run_specs: list[tuple[Path, str]] | None = None,
    observations: Path | None = None, workspace: bool = False, workspace_runs: list[str] | None = None,
    max_queries: int = 20, max_spans: int | None = None) -> dict:
    if max_queries < 1 or (max_spans is not None and max_spans < 1):
        raise ValueError("max_queries and max_spans must be positive")
    catalog = load_catalog()
    profiles = json.loads((ROOT / "profiles.json").read_text(encoding="utf-8"))
    profiles["bindings"] = {k: c["data"] for k, c in catalog["cases"].items() if c.get("data")}
    if profiles.get("schema_version") != 1 or set(profiles["datasets"]) != set(catalog["datasets"]):
        raise ValueError("profiles must cover the case catalog datasets")
    for key, profile in profiles["datasets"].items():
        if "fieldsFrom" in profile:
            profile["fields"] = copy.deepcopy(profiles["datasets"][profile["fieldsFrom"]]["fields"])
        for field in profile["fields"]:
            if len(field) != 4 or field[1] not in {"history", "task", "annotations", "auxiliary", "metadata"}:
                raise ValueError(f"invalid field routing in {key}")
    for key, binding in profiles["bindings"].items():
        if key not in catalog["cases"] or key not in catalog["datasets"][binding["dataset"]]["cases"]:
            raise ValueError(f"case binding mismatch: {key}")
    if (run_specs or observations or workspace) and not local:
        raise ValueError("raw samples and traces require --local")
    specs = list(run_specs or [])
    registrations = []
    all_registrations = []
    if workspace:
        from benchmark.workspace import registrations as registered_runs
        all_registrations = registered_runs()
        if workspace_runs and set(workspace_runs) - {r["run_id"] for r in all_registrations}:
            raise ValueError("unknown workspace run ID")
        registrations = [r for r in all_registrations if r["run_id"] in workspace_runs] if workspace_runs else all_registrations[-5:]
        specs += [(ROOT.parent / r["directory"], r["kind"]) for r in registrations]
    bundle = {"schema_version": 1, "updated": profiles["updated"], "catalog": catalog,
        "profiles": profiles, "scope": "local" if local else "curated",
        "local": local_sources(profiles) if local else {"samples": {}, "stats": {}, "missing": []},
        "runs": [read_run(path, kind, max_queries=max_queries, max_spans=max_spans) for path, kind in specs]}
    bundle["case_observations"] = case_observation_index(all_registrations, catalog=catalog,
        profiles=profiles, runs=bundle["runs"], repo_root=ROOT.parent)
    from benchmark.workspace import read_notes
    for run, (path, _) in zip(bundle["runs"], specs):
        # Validate every note even when the view limits the query projection.
        note_run = read_run(path, run["kind"], max_queries=100000) if (path / "notes.jsonl").exists() and run["total_queries"] > run["shown_queries"] else run
        notes = read_notes(path, note_run)
        for query in run["queries"]:
            query["notes"] = [n for n in notes if n["search_id"] == query["search_id"]]
    for row in registrations:
        run = next(r for r in bundle["runs"] if r["run_id"] == row["run_id"])
        if run["dataset_pack_sha256"] != row["dataset_pack_sha256"]:
            raise ValueError("registered pack identity changed")
        if row.get("observations"):
            attach_observations([run], ROOT.parent / row["observations"])
    bundle["research"] = json.loads((ROOT / "research.json").read_text(encoding="utf-8"))
    bundle["workspace"] = {"runs": [{"run_id": r["run_id"], "directory": r["directory"]} for r in all_registrations],
        "shown": [r["run_id"] for r in registrations]}
    if len({r["run_id"] for r in bundle["runs"]}) != len(bundle["runs"]):
        raise ValueError("duplicate run ID")
    if observations:
        attach_observations(bundle["runs"], observations)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--workspace", action="store_true", help="load the persistent local run registry and comments")
    parser.add_argument("--workspace-run", action="append", help="registered run ID to include; default: latest five")
    parser.add_argument("--max-queries", type=int, default=20,
        help="maximum Search queries projected into one page (full run artifacts remain available)")
    parser.add_argument("--max-spans", type=int,
        help="maximum internal steps projected per Search query (full observations remain available)")
    parser.add_argument("--run", type=Path, action="append", default=[])
    parser.add_argument("--run-kind", choices=("fixture", "experiment"), action="append", default=[])
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--renderer", type=Path)
    parser.add_argument("--inline-output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if len(args.run) != len(args.run_kind):
        parser.error("each --run requires one --run-kind")
    if args.workspace_run and not args.workspace:
        parser.error("--workspace-run requires --workspace")
    if args.max_queries < 1 or (args.max_spans is not None and args.max_spans < 1):
        parser.error("--max-queries and --max-spans must be positive")
    bundle = build_bundle(args.local, list(zip(args.run, args.run_kind)), args.observations,
        args.workspace, args.workspace_run, args.max_queries, args.max_spans)
    fragment = render_fragment(presentation_bundle(bundle), (ROOT / "view.template.html").read_text(encoding="utf-8"))
    while len(fragment.encode("utf-8")) >= 1_000_000 and args.workspace and not args.workspace_run and not args.run and len(bundle["runs"]) > 1:
        omitted = bundle["runs"].pop(0)
        bundle["workspace"]["shown"].remove(omitted["run_id"])
        for matches in bundle["case_observations"].values():
            for match in matches:
                if match["run_id"] == omitted["run_id"]:
                    match["loaded"] = False
        fragment = render_fragment(presentation_bundle(bundle), (ROOT / "view.template.html").read_text(encoding="utf-8"))
    if len(fragment.encode("utf-8")) >= 1_000_000:
        raise ValueError("view exceeds 1 MB; select fewer runs or reduce projection size")
    directory = ROOT / "data/local" if args.local else ROOT
    view, webpage = directory / "view.html", directory / "index.html"
    if args.check:
        if args.web or args.inline_output:
            parser.error("--check cannot write outputs")
        if not view.exists() or view.read_text(encoding="utf-8") != fragment:
            raise SystemExit("view is stale; rebuild")
        if not webpage.exists() or fragment not in html.unescape(webpage.read_text(encoding="utf-8")):
            raise SystemExit("webpage is stale; rebuild with --web")
        print("Profiles, cases and both views are consistent.")
        return
    if args.inline_output:
        dest = args.inline_output.resolve()
        # An inline copy must not overwrite source files or local research artifacts.
        repo = ROOT.parent
        if dest.is_relative_to(repo) and not dest.is_relative_to(ROOT / "data"):
            raise ValueError("inline copy must be outside tracked project sources")
    directory.mkdir(parents=True, exist_ok=True)
    view.write_text(fragment, encoding="utf-8", newline="\n")
    if args.local:
        (directory / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if args.inline_output:
        args.inline_output.parent.mkdir(parents=True, exist_ok=True)
        args.inline_output.write_text(fragment, encoding="utf-8", newline="\n")
    if args.web:
        subprocess.run([sys.executable, "-X", "utf8", str(args.renderer or find_renderer()), str(view),
            str(webpage), "--title", "AM-Link 研究可视化", "--force"], check=True)
    print(f"{view}: {len(bundle['catalog']['datasets'])} datasets, {len(bundle['local']['samples'])} local samples, {len(bundle['runs'])} runs")


if __name__ == "__main__":
    main()
