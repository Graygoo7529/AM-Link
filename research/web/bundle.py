"""Build the unified research explorer without running a memory system."""
from __future__ import annotations

import argparse
import copy
import html
import json
import subprocess
import sys
from pathlib import Path

from research.cases.catalog import load_catalog, render_fragment
from research.web.sources import local_sources
from research.web.traces import attach_observations, read_run

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
        if not directory.is_relative_to(repo_root / "research/benchmark/data"):
            raise ValueError("registered run escaped research/benchmark/data")
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
            # None means an unrestricted selection, as in full-record studies.
            # The exact planned task and completed report below remain required.
            record_ids, task_ids = selection.get('record_ids'), selection.get('task_ids')
            if ((record_ids is not None and binding['record'] not in record_ids)
                or (task_ids is not None and binding['task'] not in task_ids)):
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
        from research.benchmark.workspace import registrations as registered_runs
        all_registrations = registered_runs()
        if workspace_runs and set(workspace_runs) - {r["run_id"] for r in all_registrations}:
            raise ValueError("unknown workspace run ID")
        registrations = [r for r in all_registrations if r["run_id"] in workspace_runs] if workspace_runs else all_registrations[-5:]
        specs += [(ROOT.parent.parent / r["directory"], r["kind"]) for r in registrations]
    bundle = {"schema_version": 1, "updated": profiles["updated"], "catalog": catalog,
        "profiles": profiles, "scope": "local" if local else "curated",
        "local": local_sources(profiles) if local else {"samples": {}, "stats": {}, "missing": []},
        "runs": [read_run(path, kind, max_queries=max_queries, max_spans=max_spans) for path, kind in specs]}
    bundle["case_observations"] = case_observation_index(all_registrations, catalog=catalog,
        profiles=profiles, runs=bundle["runs"], repo_root=ROOT.parent.parent)
    from research.benchmark.workspace import read_notes
    validation_runs = {}
    for run, (path, _) in zip(bundle["runs"], specs):
        # Validate every note/Answer before projecting a subset of questions.
        has_observations = observations or any(r['run_id'] == run['run_id'] and r.get('observations') for r in registrations)
        note_run = read_run(path, run["kind"], max_queries=100000) if ((path / "notes.jsonl").exists() or has_observations) and run["total_queries"] > run["shown_queries"] else run
        validation_runs[run['run_id']] = note_run
        notes = read_notes(path, note_run)
        for query in run["queries"]:
            query["notes"] = [n for n in notes if n["search_id"] == query["search_id"]]
    for row in registrations:
        run = next(r for r in bundle["runs"] if r["run_id"] == row["run_id"])
        if run["dataset_pack_sha256"] != row["dataset_pack_sha256"]:
            raise ValueError("registered pack identity changed")
        if row.get("observations"):
            attach_observations([validation_runs[run['run_id']]], ROOT.parent.parent / row["observations"])
    bundle["dataset_facts"] = json.loads((ROOT / "dataset-facts.json").read_text(encoding="utf-8"))
    bundle["workspace"] = {"runs": [{"run_id": r["run_id"], "directory": r["directory"]} for r in all_registrations],
        "shown": [r["run_id"] for r in registrations]}
    if len({r["run_id"] for r in bundle["runs"]}) != len(bundle["runs"]):
        raise ValueError("duplicate run ID")
    if observations:
        attach_observations(list(validation_runs.values()), observations)
    for run in bundle['runs']:
        validated = validation_runs[run['run_id']]
        if validated is run:
            continue
        by_id = {q['search_id']: q for q in validated['queries']}
        for query in run['queries']:
            for key in ('answer', 'evaluation', 'steps', 'observations_sha256'):
                if key in by_id[query['search_id']]:
                    query[key] = by_id[query['search_id']][key]
    return bundle


