"""Build source-linked research slices. These are diagnostic selections, not test sets."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

from dataset.prepare import build_longmemeval, build_personamem_v2, sha256_file
from dataset.pack import write_pack
from dataset.survey import RAW, ROOT, csv_rows, parquet_rows

OUT = ROOT / "dataset/data/prepared"
LM_IDS = ["6a1eabeb", "gpt4_59149c77", "0862e8bf_abs"]


def pack(dataset_id, path, records, selection):
    return {"schema_version": 1, "dataset": {"id": dataset_id},
            "preparation": {"input": {"file": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)},
                            "selection": selection, "producer": "dataset.research_cases.v1"}, "records": records}


def microstudy(longmem, persona):
    """No gold text in history. Gold is used only to select the short diagnostic cuts."""
    records = []
    def add_record(key, dataset, case, task, sessions, provenance, variant="source excerpt"):
        records.append({"id": key, "sessions": sessions, "tasks": [copy.deepcopy(task)],
            "attributes": {"dataset_key": dataset, "case_id": case, "variant": variant, "provenance": provenance}})

    for r in longmem["records"]:
        tid = r["id"]; task = r["tasks"][0]
        evidence = set(task["annotations"]["evidence_turn_ids"])
        if tid.endswith("_abs"):
            evidence = {"answer_c6fd8ebd_abs:10"}
        sessions = []
        for s in r["sessions"]:
            turns = [copy.deepcopy(t) for t in s["turns"] if t["id"] in evidence]
            if turns: sessions.append({**s, "turns": turns})
        sessions.sort(key=lambda s: s.get("timestamp", 0))
        case = {LM_IDS[0]: "lm1", LM_IDS[1]: "lm2", LM_IDS[2]: "lm3"}[tid]
        if case == "lm2":
            add_record("time-plain", "longmem", case, task, copy.deepcopy(sessions), tid, "原文，不将日期编码进正文")
        for session in sessions:
            from datetime import datetime, timezone
            date = datetime.fromtimestamp(session["timestamp"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            for turn in session["turns"]:
                turn["content"] = f"[Conversation date: {date}]\n" + turn["content"]
        add_record({"lm1": "update", "lm2": "time-dated", "lm3": "abstention"}[case], "longmem", case, task, sessions, tid,
                   "原文 + 来源会话日期")
    for rid, task_id, indices, key, case in [("persona-521", "row-7", [107,108], "other-person", "pv1"),
                                             ("persona-737", "row-32", [49,50,51,52], "forget", "pv2")]:
        r = next(r for r in persona["records"] if r["id"] == rid)
        task = next(t for t in r["tasks"] if t["id"] == task_id)
        task = copy.deepcopy(task); task["input"]["text"] = ast.literal_eval(task["input"]["text"])["content"]
        turns = [copy.deepcopy(t) for t in r["sessions"][0]["turns"] if int(t["id"]) in indices]
        if len(turns) != len(indices): raise ValueError("missing PersonaMem source turns")
        # Ingestion is staged before/after the explicit forgetting request.
        sessions = [{"id": "source-"+str(i), "turns": turns[i:i+2]} for i in range(0,len(turns),2)]
        add_record(key, "persona", case, task, sessions, rid+":"+task_id)
    return pack("memory-microstudy", RAW / "longmemeval/longmemeval_s_cleaned.json", records,
                {"scope": "gold-selected source excerpts; no distractor history; NOT full-dataset benchmark",
                 "source_packs": {"longmem": sha256_file(OUT / "longmemeval-research.json"),
                                  "persona": sha256_file(OUT / "personamem-v2-research.json")},
                 "time_variants": "same two source turns, with/without conversation-date prefix"})


def mab_case():
    path = next((RAW / "memoryagentbench").rglob("Conflict*.parquet"))
    row = next(parquet_rows(path))
    turns = [{"id": "fact-"+line.split(".",1)[0], "role": "user", "content": line}
             for line in row["context"].splitlines() if line and line.split(".",1)[0].isdigit()]
    return pack("memoryagentbench-cr", path, [{"id": "cr-0", "sessions": [{"id": "facts", "turns": turns}],
        "tasks": [{"id": "q0", "input": {"text": row["questions"][0]}, "kind": "question_answering",
                   "annotations": {"answers": row["answers"][0], "metadata": row["metadata"]}}]}],
        {"row": 0, "question_indices": [0], "context": "all numbered source facts, original order",
         "evidence_status": "manual case references, not certified upstream evidence"})


OBSERVABLE_PV3 = ["event_id", "timestamp", "datetime", "app", "action", "user_message",
    "content_type", "title", "caption", "media_description", "audio_transcript", "hashtags", "conversation_json",
    "author", "recipient_id", "is_dm", "is_ad", "is_trending", "location"]


def visible_events(rows, persona_id, cutoff):
    """Strict pre-query window. Never copy source-side inferred preferences or generation extras."""
    output = []
    for row in rows:
        if row["persona_id"] != persona_id or int(row["timestamp"]) >= cutoff:
            continue
        projected = {k: row[k] for k in OBSERVABLE_PV3 if row.get(k)}
        if projected.get("conversation_json"):
            messages = json.loads(projected["conversation_json"])
            if not isinstance(messages, list):
                raise ValueError("conversation_json must be a list")
            # Nested embeds_pref_idx and similar generator labels are not observable text.
            projected["conversation_json"] = json.dumps([
                {k: m[k] for k in ("role", "content") if k in m} for m in messages], ensure_ascii=False)
        output.append(projected)
    return output


def persona3_cases():
    path = RAW / "personamem-v3/samples/persona_queries.csv"
    queries = list(csv_rows(path))
    selected = [next(q for q in queries if q["persona_id"] == pid and q["task_type"] == typ)
                for pid, typ in [("36", "personalized_recommendation"), ("68", "preference_shift_followthrough")]]
    rows = list(csv_rows(RAW / "personamem-v3/samples/persona_context.csv"))
    records = []
    for query in selected:
        cutoff = int(query["timestamp"])
        visible = sorted(visible_events(rows, query["persona_id"], cutoff), key=lambda r: (int(r["timestamp"]), r["event_id"]))
        turns = [{"id": "event-"+r["event_id"], "role": "user", "timestamp": int(r["timestamp"]) * 1000,
                  "content": json.dumps(r, ensure_ascii=False),
                  "attributes": {"source_event_id": r["event_id"], "input_kind": "observed_activity"}} for r in visible]
        records.append({"id": query["query_id"], "group_id": "persona-"+query["persona_id"], "sessions": [{"id": "before-query", "turns": turns}],
            "tasks": [{"id": query["query_id"], "input": {"text": query["user_query"], "prior_conversation": query["prior_conversation"]},
                       "kind": query["task_type"], "annotations": {k:v for k,v in query.items() if k not in
                         {"user_query", "prior_conversation", "persona_id", "persona_html", "query_id", "timestamp", "datetime", "app"}}}],
            "attributes": {"cutoff": cutoff, "visible_events": len(visible), "excluded_same_or_later": sum(1 for r in rows if r["persona_id"] == query["persona_id"])-len(visible),
                           "total_persona_events": sum(1 for r in rows if r["persona_id"] == query["persona_id"]), "protocol": "local conservative projection, not original evaluator parity"}})
    result = pack("personamem-v3", path, records, {"persona_ids": ["36", "68"], "query_ids": [r["id"] for r in records],
                  "cutoff": "timestamp < query.timestamp", "history_fields": OBSERVABLE_PV3,
                  "limitations": "samples flatten original metadata; local study, not full backend evaluation"})
    result["preparation"]["context_source"] = {"file": "persona_context.csv", "sha256": sha256_file(RAW / "personamem-v3/samples/persona_context.csv")}
    return result


def main():
    longmem = build_longmemeval(dataset_id="longmemeval-s", path=RAW / "longmemeval/longmemeval_s_cleaned.json",
        question_ids=LM_IDS, question_limit=None, session_limit=None, question_type=None)
    write_pack(OUT / "longmemeval-research.json", longmem)
    persona = build_personamem_v2(path=RAW / "personamem-v2/benchmark.csv", history_root=RAW / "personamem-v2",
        persona_ids=["521", "737"], task_limit=None)
    write_pack(OUT / "personamem-v2-research.json", persona)
    write_pack(OUT / "memory-microstudy.json", microstudy(longmem, persona))
    write_pack(OUT / "memoryagentbench-cr-research.json", mab_case())
    write_pack(OUT / "personamem-v3-research.json", persona3_cases())
    print("5 research packs built; controlled excerpts are separate from full histories")


if __name__ == "__main__":
    main()
