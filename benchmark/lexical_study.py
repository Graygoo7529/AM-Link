"""Deterministic BM25 source-unit diagnostic; gold is used only after ranking."""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from pathlib import Path

from dataset.prepare import iter_json_array, sha256_file

ROOT = Path(__file__).resolve().parents[1]
STOP = set("a an the is are was were i my me of to in on and or for with how what when where which do did does have has had it this that from at as by be been".split())


def tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.casefold()) if w not in STOP]


def rank(documents, query):
    counts = [Counter(tokens(text)) for _,text in documents]
    lengths = [sum(c.values()) for c in counts]
    avg = sum(lengths)/len(lengths) if lengths else 1
    df = Counter(w for c in counts for w in c)
    q = sorted(set(tokens(query))); scored = []
    for i,c in enumerate(counts):
        score = sum(math.log(1+(len(counts)-df[w]+.5)/(df[w]+.5)) * c[w]*2.2 /
                    (c[w]+1.2*(.25+.75*lengths[i]/(avg or 1))) for w in q if c[w])
        scored.append((score,i))
    return [(documents[i][0],score) for score,i in sorted(scored,key=lambda x:(-x[0],x[1])) if score>0]


def main():
    path = ROOT/"dataset/data/raw/longmemeval/longmemeval_s_cleaned.json"
    output = ROOT/"benchmark/data/research/lexical-longmem.json"
    started=time.perf_counter(); cases=[]
    for row in iter_json_array(path):
        docs=[]; gold=[]
        for si,(sid,session) in enumerate(zip(row["haystack_session_ids"],row["haystack_sessions"])):
            for ti,t in enumerate(session):
                key=f"{si}:{ti}"
                docs.append((key,t["content"]))
                if sid in row["answer_session_ids"] and t.get("has_answer"): gold.append(key)
        ranked=rank(docs,row["question"])
        # Identical annotated evidence texts count as one target, matching the pack adapter.
        gold_texts={" ".join(dict(docs)[k].casefold().split()) for k in gold}
        def matched(k):
            actual={" ".join(dict(docs)[tid].casefold().split()) for tid,_ in ranked[:k]}
            return len(gold_texts & actual)
        cases.append({"id":row["question_id"],"type":row["question_type"],"abstention":row["question_id"].endswith("_abs"),
            "question":row["question"],"gold_units":len(gold_texts),"matched5":matched(5),"matched10":matched(10),
            "top10":[{"id":tid,"score":round(score,5),"excerpt":dict(docs)[tid][:650]} for tid,score in ranked[:10]]})
    eligible=[c for c in cases if not c["abstention"] and c["gold_units"]]
    by_type={}
    for typ in sorted({c["type"] for c in eligible}):
        values=[c for c in eligible if c["type"]==typ]
        by_type[typ]={"questions":len(values),"any5":sum(c["matched5"]>0 for c in values),
            "complete5":sum(c["matched5"]==c["gold_units"] for c in values),
            "complete10":sum(c["matched10"]==c["gold_units"] for c in values)}
    result={"schema_version":1,"method":"BM25 original turns; k1=1.2 b=0.75; regex English tokenizer; no rewrite/stemming",
        "source_sha256":sha256_file(path),"source":path.relative_to(ROOT).as_posix(),"questions":len(cases),
        "graded_questions":len(eligible),"abstention_ungraded":sum(c["abstention"] for c in cases),
        "no_gold_ungraded":sum(not c["abstention"] and not c["gold_units"] for c in cases),
        "summary":{"any5":sum(c["matched5"]>0 for c in eligible),"complete5":sum(c["matched5"]==c["gold_units"] for c in eligible),
                   "complete10":sum(c["matched10"]==c["gold_units"] for c in eligible)},
        "by_type":by_type,"wall_seconds":round(time.perf_counter()-started,3),"model_calls":0,"cost_usd":0,
        "limits":"annotated exact source-unit coverage, not semantic support, answer accuracy, Mem0 or official score; no tuning/holdout claim",
        "cases":cases}
    # Additional one-query conflict-chain diagnostic; manually audited targets are labeled as such.
    p=ROOT/"dataset/data/prepared/memoryagentbench-cr-research.json"
    if p.exists():
        r=json.loads(p.read_text(encoding="utf-8"))["records"][0]
        docs=[(t["id"],t["content"]) for s in r["sessions"] for t in s["turns"]]
        ranked=rank(docs,r["tasks"][0]["input"]["text"])[:5]
        result["mab_case"]={"pack_sha256":sha256_file(p),"manually_audited_path":["fact-146","fact-335","fact-322"],
            "top5":[{"id":tid,"score":round(score,5),"text":dict(docs)[tid]} for tid,score in ranked]}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ["graded_questions","summary","by_type","wall_seconds"]},ensure_ascii=False))


if __name__=="__main__":
    main()
