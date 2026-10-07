"""Reproducible structural census; never sends annotations to a memory method."""
from __future__ import annotations

import argparse
import ast
import csv
import json
import statistics
from collections import Counter
from pathlib import Path

from dataset.prepare import iter_json_array, sha256_file, _context_task_record

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "dataset/data/raw"


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    return {"n": len(values), "min": values[0], "median": statistics.median(values),
            "p90": values[int((len(values)-1)*.9)], "max": values[-1], "sum": sum(values)}


def identity(path):
    receipt = path.with_name(path.name + ".receipt.json")
    result = {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
              "sha256": sha256_file(path)}
    if receipt.exists():
        data = json.loads(receipt.read_text(encoding="utf-8"))
        if data.get("sha256") != result["sha256"]:
            raise ValueError(f"receipt mismatch: {path.name}")
        result["receipt_verified"] = True
    return result


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def parquet_rows(path):
    import pyarrow.parquet as pq
    for batch in pq.ParquetFile(path).iter_batches(batch_size=1):
        yield from batch.to_pylist()


def longmem(path):
    types, evidence, sessions, turns, chars = Counter(), [], [], [], []
    marked_roles = Counter()
    answerable = duplicated = marked = 0
    for row in iter_json_array(path):
        types[row["question_type"]] += 1
        answerable += not row["question_id"].endswith("_abs")
        sessions.append(len(row["haystack_sessions"]))
        evidence.append(len(row["answer_session_ids"]))
        flat = [t for s in row["haystack_sessions"] for t in s]
        turns.append(len(flat)); chars.append(sum(len(t["content"]) for t in flat))
        duplicated += len(row["haystack_session_ids"]) != len(set(row["haystack_session_ids"]))
        for turn in flat:
            if turn.get("has_answer"):
                marked += 1; marked_roles[turn["role"]] += 1
    return {"question_types": dict(types), "questions": sum(types.values()), "answerable": answerable,
            "abstention": sum(types.values())-answerable, "sessions_per_question": distribution(sessions),
            "turns_per_question": distribution(turns), "history_chars": distribution(chars),
            "answer_sessions_per_question": distribution(evidence), "has_answer_turns": marked,
            "has_answer_roles": dict(marked_roles), "records_with_duplicate_session_ids": duplicated,
            "unit_note": "sessions/turns 按题目累计，不代表互不重叠的真实用户或会话。"}


def context_tasks(path):
    categories, subs, boundaries = Counter(), Counter(), Counter()
    rubric_counts, lengths, messages, contexts = [], [], [], set()
    for row in iter_json_array(path):
        meta = row["metadata"]
        categories[meta.get("context_category", "unknown")] += 1
        subs[meta.get("context_subcategory", meta.get("sub_category", "unknown"))] += 1
        contexts.add(meta.get("context_id", meta["task_id"]))
        rubric_counts.append(len(row["rubrics"]))
        messages.append(len(row["messages"]))
        lengths.append(sum(len(m["content"]) for m in row["messages"]))
        record = _context_task_record(row, meta["task_id"])
        separated = record and record["tasks"][0]["attributes"].get("context_task_boundary") != "unseparated"
        boundaries["可按当前规则拆分" if separated else "保持原输入，边界未认证"] += 1
    return {"tasks": len(messages), "context_groups": len(contexts), "categories": dict(categories),
            "subcategories": dict(subs), "boundaries": dict(boundaries),
            "rubrics_per_task": distribution(rubric_counts), "messages_per_task": distribution(messages),
            "input_chars": distribution(lengths), "gold_turn_evidence": False}


def persona2(path):
    rows = list(csv_rows(path))
    labels = {k: dict(Counter(r[k] for r in rows)) for k in
              ("who", "updated", "sensitive_info", "pref_type", "conversation_scenario")}
    return {"tasks": len(rows), "personas": len({r["persona_id"] for r in rows}), "labels": labels,
            "questions_per_persona": distribution(list(Counter(r["persona_id"] for r in rows).values())),
            "history_links": len({r[k] for r in rows for k in ("chat_history_32k_link", "chat_history_128k_link")}),
            "distance_32k_author_tokens": distribution([int(r["distance_from_related_snippet_to_query_32k"]) for r in rows]),
            "history_32k_author_tokens": distribution([int(r["total_tokens_in_chat_history_32k"]) for r in rows])}


def beam(path):
    types, fields = Counter(), Counter()
    turns, questions, chars = [], [], []
    for row in parquet_rows(path):
        def walk(value):
            if isinstance(value, dict):
                if value.get("role") in {"user", "assistant"} and isinstance(value.get("content"), str):
                    yield value
                else:
                    for child in value.values():
                        yield from walk(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child)
        # 10M chat uses plan -> batch -> turns, unlike the normal list-of-batches.
        flat = list(walk(row["chat"]))
        turns.append(len(flat)); chars.append(sum(len(t["content"]) for t in flat))
        probes = row["probing_questions"]
        if isinstance(probes, str):
            probes = ast.literal_eval(probes)
        questions.append(sum(len(v) for v in probes.values()))
        for typ, items in probes.items():
            types[typ] += len(items)
            for item in items:
                fields.update(item.keys())
    return {"histories": len(turns), "turns_per_history": distribution(turns),
            "history_chars": distribution(chars), "probes_per_history": distribution(questions),
            "probe_types": dict(types), "probe_field_presence": dict(fields)}


def mab(path):
    sources, fields = Counter(), Counter()
    lengths, questions = [], []
    for row in parquet_rows(path):
        if len(row["questions"]) != len(row["answers"]):
            raise ValueError("questions/answers length mismatch")
        lengths.append(len(row["context"])); questions.append(len(row["questions"]))
        meta = row["metadata"]
        sources[str(meta.get("source", "unknown"))] += 1
        fields.update(k for k, v in meta.items() if v is not None)
    return {"contexts": len(lengths), "questions_per_context": distribution(questions),
            "context_chars": distribution(lengths), "subsources": dict(sources), "metadata_nonnull": dict(fields)}


def persona3(directory):
    tasks, apps, interactions, evolutions = Counter(), Counter(), Counter(), Counter()
    personas, counts, query_counts = set(), Counter(), Counter()
    for row in csv_rows(directory / "persona_queries.csv"):
        tasks[row["task_type"]] += 1; query_counts[row["persona_id"]] += 1
    for row in csv_rows(directory / "persona_context.csv"):
        personas.add(row["persona_id"]); counts[row["persona_id"]] += 1
        apps[row["app"]] += 1; interactions[row["interaction_type"]] += 1
        if row["preference_evolution"]:
            evolutions["nonempty_rows"] += 1
            for label in ("reinforced", "similar", "branched", "deepened", "contradicted", "expired"):
                if label in row["preference_evolution"]: evolutions[label + "_rows"] += 1
    return {"personas": len(personas), "events": sum(counts.values()), "queries": sum(tasks.values()),
            "task_types": dict(tasks), "apps": dict(apps), "interaction_types": dict(interactions),
            "preference_evolution": dict(evolutions), "events_per_persona": distribution(list(counts.values())),
            "queries_per_persona": distribution(list(query_counts.values())),
            "input_policy": "仅 query.timestamp 之前可观察字段；preferences、profile、supporting_history、golden_response 等另存标注。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-m", action="store_true", help="also stream the 2.74 GB M file")
    parser.add_argument("--output", type=Path, default=ROOT / "dataset/data/research/survey.json")
    args = parser.parse_args()
    result = {"schema_version": 1, "date": "2026-10-07", "producer": "dataset.survey.v1", "datasets": {}}
    jobs = [("longmem", RAW / "longmemeval/longmemeval_s_cleaned.json", longmem),
            ("longmem-oracle", RAW / "longmemeval/longmemeval_oracle.json", longmem),
            ("cl", RAW / "clbench/CL-bench.jsonl", context_tasks),
            ("life", RAW / "clbench-life/CL-bench Life.jsonl", context_tasks),
            ("persona", RAW / "personamem-v2/benchmark.csv", persona2)]
    if args.include_m: jobs.append(("longmem-m", RAW / "longmemeval/longmemeval_m_cleaned.json", longmem))
    for ds, fn in [("beam", beam), ("beam-10m", beam), ("memoryagentbench", mab)]:
        for path in sorted((RAW / ds).rglob("*.parquet")):
            jobs.append((ds+":"+(path.stem if ds == "beam-10m" else path.stem.split("-000")[0]), path, fn))
    for key, path, fn in jobs:
        result["datasets"][key] = {"sources": [identity(path)], **fn(path)}
        print(key, "done", flush=True)
    directory = RAW / "personamem-v3/samples"
    result["datasets"]["pv3"] = {"sources": [identity(p) for p in sorted(directory.glob("*.csv"))], **persona3(directory)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
