"""Local run registry and append-only research comments, outside tracked sources."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from benchmark.core import write_json

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "benchmark/data/research/workspace.json"
STAGES = {"add", "search", "answer", "eval", "extract", "store", "index", "retrieve", "rerank", "context", "model"}


def registrations(path=REGISTRY):
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported research workspace")
    seen = set()
    for row in payload["runs"]:
        if set(row) != {"run_id", "directory", "kind", "dataset_pack_sha256", "observations"} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", row["run_id"]) or row["run_id"] in seen or row["kind"] not in {"experiment", "fixture"} or not re.fullmatch(r"[a-f0-9]{64}",row["dataset_pack_sha256"]):
            raise ValueError("invalid registered run identity")
        directory = (ROOT / row["directory"]).resolve()
        if Path(row["directory"]).is_absolute() or not directory.is_relative_to(ROOT / "benchmark/data"):
            raise ValueError("registered run path escapes benchmark/data")
        if row["observations"] and (Path(row["observations"]).is_absolute() or not (ROOT / row["observations"]).resolve().is_relative_to(directory)):
            raise ValueError("registered observations escape run directory")
        seen.add(row["run_id"])
    return payload["runs"]


def register(directory, *, kind="experiment", observations=None, registry=REGISTRY):
    from visualization.traces import read_run, attach_observations
    directory = directory.resolve()
    if not directory.is_relative_to(ROOT / "benchmark/data"):
        raise ValueError("registered runs must be inside ignored benchmark/data")
    run = read_run(directory, kind)
    if observations:
        observations = observations.resolve()
        if not observations.is_relative_to(directory):
            raise ValueError("observations must be inside the run directory")
        attach_observations([run], observations)
    rows = registrations(registry)
    previous = next((x for x in rows if x["run_id"] == run["run_id"]), None)
    row = {"run_id": run["run_id"], "directory": directory.relative_to(ROOT).as_posix(),
        "kind": kind, "dataset_pack_sha256": run["dataset_pack_sha256"],
        "observations": observations.relative_to(ROOT).as_posix() if observations else None}
    if previous and (previous["directory"] != row["directory"] or previous["dataset_pack_sha256"] != row["dataset_pack_sha256"]):
        raise ValueError("run ID is already registered with a different identity")
    if previous and not observations:
        row["observations"] = previous.get("observations")
    write_json(registry, {"schema_version": 1, "runs": [x for x in rows if x["run_id"] != run["run_id"]]+[row]})


def read_notes(directory, run):
    path = directory / "notes.jsonl"
    notes, seen = [], set()
    if not path.exists():
        return notes
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        note = json.loads(line)
        validate_note(note, run, notes)
        if note["id"] in seen:
            raise ValueError("duplicate note ID")
        seen.add(note["id"])
        notes.append(note)
    return notes


def validate_note(note, run, previous=()):
    required = {"schema_version", "id", "created_at", "run_id", "dataset_pack_sha256", "trace_sha256",
        "search_id", "stage", "span_id", "kind", "author", "text", "supersedes"}
    if set(note) != required or note["schema_version"] != "amlink.note.v1":
        raise ValueError("invalid research note fields/version")
    for field in ("id", "created_at", "author", "text"):
        if not isinstance(note[field], str) or not note[field].strip() or len(note[field]) > (6000 if field == "text" else 200):
            raise ValueError(f"invalid note {field}")
    if datetime.fromisoformat(note["created_at"]).utcoffset() is None:
        raise ValueError("note timestamp needs timezone")
    if (note["run_id"], note["dataset_pack_sha256"], note["trace_sha256"]) != (run["run_id"], run["dataset_pack_sha256"], run["artifacts"]["trace.jsonl"]):
        raise ValueError("note run/pack/trace mismatch")
    query = next((q for q in run["queries"] if q["search_id"] == note["search_id"]), None)
    if not query or note["stage"] not in STAGES or note["kind"] not in {"observation", "hypothesis", "next_experiment"}:
        raise ValueError("unknown note query/stage/kind")
    if note["span_id"] is not None:
        span = next((s for s in query["spans"] if s["span_id"] == note["span_id"]), None)
        if span is None or span["operation"] != note["stage"]:
            raise ValueError("note span must belong to this query and stage")
    if note["supersedes"] is not None and not any(n["id"] == note["supersedes"] and n["search_id"] == note["search_id"] for n in previous):
        raise ValueError("superseded note must exist for this query")


def append_note(directory, note):
    from visualization.traces import read_run
    run = read_run(directory, "experiment", max_queries=100000)
    notes = read_notes(directory, run)
    validate_note(note, run, notes)
    if any(n["id"] == note["id"] for n in notes):
        raise ValueError("note already imported")
    with (directory / "notes.jsonl").open("a", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps(note, ensure_ascii=False) + "\n")


def make_note(run, *, search_id, stage, kind, author, text, span_id=None, supersedes=None):
    return {"schema_version": "amlink.note.v1", "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(), "run_id": run["run_id"],
        "dataset_pack_sha256": run["dataset_pack_sha256"], "trace_sha256": run["artifacts"]["trace.jsonl"],
        "search_id": search_id, "stage": stage, "span_id": span_id, "kind": kind,
        "author": author, "text": text, "supersedes": supersedes}


def publish():
    import subprocess
    import sys
    subprocess.run([sys.executable, "-X", "utf8", "-m", "visualization.build", "--local", "--workspace", "--web"],
        cwd=ROOT, check=True)
