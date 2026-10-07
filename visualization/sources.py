"""Bounded, provenance-preserving projections of local dataset packs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dataset.pack import load_pack
from visualization.semantics import readable

REPO = Path(__file__).resolve().parents[1]


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def excerpt(value: object, limit: int = 3000) -> dict:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return {"text": text, "total_chars": len(text), "omitted": False, "ranges": [[0, len(text)]]}
    half = limit // 2
    return {"text": text[:half] + "\n…〔展示省略中间内容〕…\n" + text[-half:],
        "total_chars": len(text), "omitted": True, "ranges": [[0, half], [len(text)-half, len(text)]]}


def local_sources(profiles: dict) -> dict:
    samples, stats, missing = {}, {}, []
    packs = {}
    for key, profile in profiles["datasets"].items():
        if not profile.get("pack"):
            continue
        path = (REPO / profile["pack"]).resolve()
        if not path.is_relative_to(REPO / "dataset/data/prepared"):
            raise ValueError("pack must be in dataset/data/prepared")
        if not path.exists():
            missing.append(profile["pack"])
            continue
        pack = load_pack(path)
        if pack["dataset"]["id"] != profile["dataset_id"]:
            raise ValueError(f"dataset mismatch in profile {key}")
        packs[key] = pack
        records = pack["records"]
        stats[key] = {"pack_path": profile["pack"], "pack_file_sha256": file_digest(path),
            "dataset_pack_sha256": digest(pack), "source": pack["preparation"]["input"],
            "records": len(records), "sessions": sum(len(r["sessions"]) for r in records),
            "units": sum(len(s["turns"]) for r in records for s in r["sessions"]),
            "tasks": sum(len(r["tasks"]) for r in records)}
        # Receipt details can contain local acquisition plumbing; expose only identity.
        stats[key]["source"] = {k: stats[key]["source"][k] for k in ("file", "sha256")}
    for case_id, binding in profiles["bindings"].items():
        binding_path = (REPO / binding.get("pack", profiles["datasets"][binding["dataset"]]["pack"])).resolve()
        if not binding_path.is_relative_to(REPO / "dataset/data/prepared"):
            raise ValueError("case pack must be in dataset/data/prepared")
        if not binding_path.exists():
            continue
        pack = packs.get(str(binding_path))
        if pack is None:
            pack = load_pack(binding_path)
            packs[str(binding_path)] = pack
        if pack["dataset"]["id"] != profiles["datasets"][binding["dataset"]]["dataset_id"]:
            raise ValueError("case dataset identity mismatch")
        record = next((r for r in pack["records"] if r["id"] == binding["record"]), None)
        if record is None:
            raise ValueError(f"missing record for {case_id}")
        task = next((t for t in record["tasks"] if t["id"] == binding["task"]), None)
        if task is None:
            raise ValueError(f"missing task for {case_id}")
        turns = {t["id"]: (s["id"], t) for s in record["sessions"] for t in s["turns"]}
        selected = binding["turns"] or list(turns)[:1]
        if set(selected) - turns.keys():
            raise ValueError(f"missing source turn for {case_id}")
        samples[case_id] = {"record_id": record["id"], "task_id": task["id"],
            "readable_input": readable(task["input"]), "readable_annotations": readable(task.get("annotations", {})),
            "history_unit_count": len(turns), "shown_unit_count": len(selected),
            "input": excerpt(task["input"], 5000), "annotations": excerpt(task.get("annotations", {}), 6000),
            "annotation_keys": list(task.get("annotations", {})),
            "units": [{"id": tid, "session": turns[tid][0],
                "speaker": turns[tid][1].get("speaker", turns[tid][1].get("role")),
                "timestamp": turns[tid][1].get("timestamp"),
                "readable": readable(turns[tid][1]["content"]),
                "content": excerpt(turns[tid][1]["content"]),
                "source_pointer": turns[tid][1].get("attributes", {}).get("source_pointer")}
                for tid in selected]}
    return {"samples": samples, "stats": stats, "missing": missing}
