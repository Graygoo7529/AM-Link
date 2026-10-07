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


def build_bundle(local: bool = False, run_specs: list[tuple[Path, str]] | None = None,
    observations: Path | None = None, workspace: bool = False, workspace_runs: list[str] | None = None) -> dict:
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
        "runs": [read_run(path, kind) for path, kind in specs]}
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
    bundle = build_bundle(args.local, list(zip(args.run, args.run_kind)), args.observations, args.workspace, args.workspace_run)
    fragment = render_fragment(presentation_bundle(bundle), (ROOT / "view.template.html").read_text(encoding="utf-8"))
    while len(fragment.encode("utf-8")) >= 1_000_000 and args.workspace and not args.workspace_run and not args.run and len(bundle["runs"]) > 1:
        omitted = bundle["runs"].pop(0)
        bundle["workspace"]["shown"].remove(omitted["run_id"])
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
