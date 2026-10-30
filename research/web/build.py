"""One offline research page. Raw evidence stays in ignored local data paths."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from research.benchmark.workspace import registrations, read_notes
from research.web.bundle import build_bundle
from research.web.traces import read_run, attach_observations

ROOT = Path(__file__).resolve().parents[2]
WEB = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def safe_child(root, relative):
    candidate = (root / relative).resolve()
    if Path(relative).is_absolute() or not candidate.is_relative_to(root.resolve()):
        raise ValueError("path outside research workspace")
    return candidate


def script_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def artifact_view(directory, reference):
    path = safe_child(directory, reference["artifact"])
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != reference["sha256"]:
        raise ValueError("artifact digest mismatch")
    value = json.loads(blob)
    if isinstance(value, dict) and value.get("schema_version") == "amlink.artifact.v1":
        value = value["text"]
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            pass
    projected = False
    if isinstance(value, dict) and isinstance(value.get("data"), list) and value["data"] and all(
        isinstance(row, dict) and isinstance(row.get("embedding"), list) for row in value["data"]
    ):
        value = {**value, "data": [{**row, "embedding": f"向量数值省略，共 {len(row['embedding'])} 维；原始文件保留。"} for row in value["data"]]}
        projected = True
    return {"value": value, "projected": projected, "sha256": digest, "path": reference["artifact"]}


def run_payload(registration, reviews, coverage):
    directory = safe_child(ROOT, registration["directory"])
    verified = read_run(directory, registration["kind"], max_queries=100000)
    if verified["dataset_pack_sha256"] != registration["dataset_pack_sha256"]:
        raise ValueError("registered pack identity changed")
    if registration.get("observations"):
        observation_path = safe_child(ROOT, registration["observations"])
        attach_observations([verified], observation_path)
        # The legacy importer uses bounded text previews. This page promises the
        # complete Answer, so restore only the already validated text identity.
        full_answers = {(o['record_id'], o['task_id']): o.get('answer')
            for o in read_json(observation_path)['observations']}
        for query in verified['queries']:
            answer = full_answers.get((query['record_id'], query['task_id']))
            if answer:
                query['answer']['text'] = answer['text']
    events, traces = lines(directory / "observability.jsonl"), lines(directory / "trace.jsonl")
    artifacts = {}
    for event in events:
        for ref in event["inputs"] + event["outputs"]:
            if ref["id"] not in artifacts:
                artifacts[ref["id"]] = artifact_view(directory, ref)
    pack = read_json(directory / "dataset-pack.json")
    tasks = {(r["id"], t["id"]): t for r in pack["records"] for t in r["tasks"]}
    originals = {e["search_id"]: e for e in traces if e["event"] == "search"}
    notes = read_notes(directory, verified)
    queries = []
    for query in verified["queries"]:
        rid, tid = query["record_id"], query["task_id"]
        task = tasks[rid, tid]
        queries.append({"task_id": tid, "record_id": rid, "search_id": query["search_id"],
            "question": query["query"], "results": originals[query["search_id"]]["results"],
            "ok": query["ok"], "error": query["error"],
            "answer": query["answer"], "evaluation": query["evaluation"],
            "review": reviews.get((verified["run_id"], tid)), "annotations": task.get("annotations", {}),
            "category": task.get("category", task.get("attributes", {})),
            "coverage": [c for c in coverage if (c["run"], c["task_id"]) == (verified["run_id"], tid)],
            "notes": [n for n in notes if n["search_id"] == query["search_id"]]})
    return {"run_id": verified["run_id"], "system": verified["system"], "kind": verified["kind"],
        "directory": registration["directory"], "dataset_id": verified["dataset_id"],
        "dataset_pack_sha256": verified["dataset_pack_sha256"], "fingerprints": verified["artifacts"],
        "summary": read_json(directory / "report.json")["summary"], "events": events,
        "artifacts": artifacts, "queries": queries, "history": pack["records"],
        "adds": [e for e in traces if e["event"] == "add"]}


def validate_studies(catalog, questions):
    lookup = {(q["run_id"], q["record_id"], q["task_id"]): q for q in questions}
    for cid, case in catalog["cases"].items():
        binding = case.get("data", {})
        for study in case.get("studies", []):
            identity = study["run_id"], binding.get("record"), binding.get("task")
            if identity not in lookup:
                raise ValueError(f"unknown study task: {cid}")
            if study["dataset_pack_sha256"] != lookup[identity]["dataset_pack_sha256"]:
                raise ValueError(f"study pack mismatch: {cid}")
            if set(study.get('span_ids', [])) - set(lookup[identity].get('span_ids', [])):
                raise ValueError(f"unknown study span: {cid}")
            if not all(study.get(field) for field in ("theory", "observed", "limits")):
                raise ValueError(f"study needs theory, observation and limits: {cid}")


def build(output=None):
    output = (output or ROOT / "research/data/index.html").resolve()
    if not output.is_relative_to((ROOT / "research/data").resolve()):
        raise ValueError("raw research output must stay in ignored research/data")
    output.parent.mkdir(parents=True, exist_ok=True)
    (output.parent / "runs").mkdir(exist_ok=True)
    manifest = read_json(ROOT / "research/workspace.json")
    bundle = build_bundle(local=True)
    reviews, coverage, campaigns = {}, [], []
    for campaign in manifest["campaigns"]:
        plan = safe_child(ROOT, campaign["plan"])
        if not plan.is_dir():
            campaigns.append({**campaign, "available": False})
            continue
        audit = read_json(plan / "manual-audit.json")
        for row in audit["rows"]:
            identity = row["run"], row["task_id"]
            if identity in reviews:
                raise ValueError("duplicate manual review")
            reviews[identity] = row
        coverage += read_json(plan / "coverage.json")
        analysis = read_json(plan / "analysis.json")
        campaigns.append({**campaign, "available": True, "status": analysis["status"],
            "families": analysis["families"], "final_audit": read_json(plan / "final-audit.json"),
            "review_policy": audit["policy"], "reviews": dict(Counter(r["label"] for r in audit["rows"]))})
    runs, questions = [], []
    for registration in registrations():
        rid = registration["run_id"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", rid):
            raise ValueError("unsafe run ID")
        payload = run_payload(registration, reviews, coverage)
        shard = f"runs/{rid}.js"
        (output.parent / shard).write_text(f"window.AMLRun({script_json(rid)},{script_json(payload)});\n", encoding="utf-8")
        runs.append({k: payload[k] for k in ("run_id", "dataset_id", "system", "kind", "dataset_pack_sha256", "directory")})
        runs[-1].update(shard=shard, questions=len(payload["queries"]), adds=len(payload["adds"]), events=len(payload["events"]))
        for query in payload["queries"]:
            questions.append({k: query[k] for k in ("task_id", "record_id", "search_id", "question", "review", "category", "ok")}
                | {"run_id": rid, "dataset_id": payload["dataset_id"], "dataset_pack_sha256": payload["dataset_pack_sha256"],
                   "span_ids": [e['span_id'] for e in payload['events'] if e.get('task_id') == query['task_id'] and e.get('record_id') == query['record_id']]})
        print(f"Verified {rid}: {len(payload['queries'])} questions, {len(payload['events'])} spans", flush=True)
    validate_studies(bundle["catalog"], questions)
    issues = read_json(ROOT / "research/cases/issues.json")
    for issue in issues["items"]:
        if set(issue["cases"]) - set(bundle["catalog"]["cases"]):
            raise ValueError("unknown issue case")
    data = {"version": 1, "catalog": bundle["catalog"], "profiles": bundle["profiles"],
        "local": bundle["local"], "dataset_facts": bundle["dataset_facts"], "campaigns": campaigns, "runs": runs, "questions": questions, "issues": issues}
    template = (WEB / "page.html").read_text(encoding="utf-8")
    if template.count("/* RESEARCH_DATA */") != 1:
        raise ValueError("missing or repeated data placeholder")
    output.write_text(template.replace("/* RESEARCH_DATA */", "const DATA=" + script_json(data) + ";"), encoding="utf-8")
    report = {"entry": "research/data/index.html", "datasets": len(data["catalog"]["datasets"]),
        "cases": len(data["catalog"]["cases"]), "studies": sum(len(c.get("studies", [])) for c in data["catalog"]["cases"].values()),
        "runs": len(runs), "questions": len(questions), "adds": sum(r["adds"] for r in runs),
        "reviews": dict(Counter(q["review"]["label"] for q in questions if q["review"])),
        "page_bytes": output.stat().st_size, "source_integrity": "All run, plan, pack, trace and referenced span artifacts validated."}
    (output.parent / "build.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build(args.output)


if __name__ == "__main__":
    main()
