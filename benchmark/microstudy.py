"""Bounded Mem0 diagnostic on source excerpts, with actual Answer and model spans.

Run explicitly: python -m benchmark.microstudy --run-id <new-id> --env-file <private env>
Requires the optional research environment. Never starts a deployed service.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path

from benchmark.core import run_replay, write_json
from benchmark.datasets import build_retrieval_manifest
from benchmark.observability import ObservationRecorder, VERSION
from benchmark.targets import TargetResponse
from dataset.pack import load_pack

ROOT = Path(__file__).resolve().parents[1]
PROMPT = "Answer the question using only the provided memory evidence. Do not invent missing facts. If the evidence is insufficient, say what is unknown. Distinguish the user from people quoted in the conversation. Respect explicit requests to forget. Be concise."


class ObservedMem0:
    def __init__(self, memory, recorder, directory, plan, run_id):
        self.memory, self.recorder, self.directory = memory, recorder, directory
        self.active = None
        self.count, self.input_chars, self.failures = 0, 0, 0
        self.call_lock = threading.Lock()
        self.usage = []
        self.adds = {f"arena:{run_id}:"+a["request_id"]: c["id"] for c in plan["cases"] for a in c["adds"]}
        self.searches = {(f"arena:{run_id}:"+s["request"]["user_id"],s["request"]["query"]):
            (c["id"], s["id"], s["dataset_task"]["task_id"]) for c in plan["cases"] for s in c["searches"]}

    def artifact(self, name, value, kind, locator="/"):
        # Record IDs may contain source separators such as ``:``.  Keep the
        # logical artifact ID in the event, but make its on-disk name portable
        # across Windows and POSIX so Answer capture cannot abort a run.
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "artifact"
        path = self.directory / (safe_name + ".json")
        suffix = 1
        while path.exists():
            path = self.directory / (safe_name + f"-{suffix}.json")
            suffix += 1
        write_json(path, value)
        return {"id": name, "kind": kind, "artifact": path.relative_to(self.directory).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "locator": locator}

    def capture(self, resource, provider, model, embedding=False):
        original = resource.create
        def create(**kwargs):
            chars = len(json.dumps(kwargs.get("input", kwargs.get("messages", [])), ensure_ascii=False))
            with self.call_lock:
                if self.count >= 100 or self.input_chars + chars > 500_000:
                    raise RuntimeError("bounded experiment call/input limit exceeded")
                self.count += 1
                self.input_chars += chars
                call_id = self.count
            p = self.active
            if p is None: raise RuntimeError("model call without operation span")
            with self.recorder.span("model", name="embedding" if embedding else "completion", parent=p,
                record_id=p["record_id"], task_id=p["task_id"], request_id=p["request_id"]) as span:
                span["model"] = {"provider": provider, "name": model, "input_tokens": None, "output_tokens": None,
                                 "cached_tokens": None, "cost_usd": None, "usage_source": "provider response; prices not inferred"}
                span["inputs"] = [self.artifact("model-input-"+str(call_id),
                    {k: kwargs[k] for k in ("messages", "input", "model", "dimensions", "response_format") if k in kwargs}, "source")]
                try:
                    response = original(**kwargs)
                except Exception:
                    self.failures += 1
                    raise
                usage = response.usage
                if usage:
                    span["model"].update(input_tokens=getattr(usage,"prompt_tokens",None),
                        output_tokens=0 if embedding else getattr(usage,"completion_tokens",None),
                        cached_tokens=getattr(getattr(usage,"prompt_tokens_details",None),"cached_tokens",None))
                payload = {"model": response.model, "usage": usage.model_dump() if usage else None}
                if not embedding: payload["response"] = response.choices[0].message.content
                else: payload["vectors"] = len(response.data)
                span["outputs"] = [self.artifact("model-output-"+str(call_id), payload, "memory")]
                self.usage.append(dict(span["model"]))
                return response
        resource.create = create

    def add(self, request):
        rid = self.adds[request["request_id"]]
        with self.recorder.span("add", name="mem0.add", record_id=rid, request_id=request["request_id"]) as span:
            self.active = span
            span["inputs"] = [self.artifact("input-"+span["span_id"], request, "source")]
            before = self.failures
            # user scope spans all source sessions; session identity is metadata, not a query filter.
            raw = self.memory.add([{k:m[k] for k in ("role","content")} for m in request["messages"]],
                user_id=request["user_id"], metadata={"source_session_id": request["session_id"]})
            if self.failures != before: raise RuntimeError("internal model failure, not a successful empty extraction")
            snapshot = self.memory.get_all(filters={"user_id": request["user_id"]}, limit=100)
            span["outputs"] = [self.artifact("after-add-"+span["span_id"], {"response":raw,"memories":snapshot}, "memory")]
            # Empty extraction is a real observed no-op; do not infer useful memory from API success.
            if not isinstance(raw,dict) or not isinstance(raw.get("results"),list): raise ValueError("invalid Mem0 result")
            print("add",rid,"memories",len(snapshot.get("results",[])),flush=True)
            return TargetResponse(200, body={"success": True, **{k:request[k] for k in ("request_id","user_id","session_id")}},raw_body=raw)

    def search(self, request):
        rid, search_id, task_id = self.searches[(request["user_id"],request["query"])]
        with self.recorder.span("search", name="mem0.search", record_id=rid, task_id=task_id, request_id=search_id) as span:
            self.active = span
            span["inputs"] = [self.artifact("query-"+span["span_id"], request, "query")]
            raw = self.memory.search(request["query"],filters={"user_id":request["user_id"]},top_k=request["top_k"],explain=True)
            results=[{"id":r["id"],"content":r["memory"],"score":r.get("score")} for r in raw["results"]]
            ref = self.artifact("search-"+span["span_id"], raw, "result")
            span["outputs"] = [ref]
            print("search",rid,"results",len(results),flush=True)
            return TargetResponse(200,body={"data":results},raw_body=raw)


def read_env(path):
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line: continue
        k,v=line.split("=",1); values[k.strip()]=v.strip().strip('"').strip("'")
    return values


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id",required=True)
    parser.add_argument("--env-file",type=Path,required=True)
    parser.add_argument("--dataset-pack",type=Path,default=ROOT/"dataset/data/prepared/memory-microstudy.json",
                        help="prepared diagnostic pack; source annotations are never sent to the target")
    parser.add_argument("--chunk-size",type=int,default=20)
    parser.add_argument("--top-k",type=int,default=5)
    args=parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}",args.run_id): raise ValueError("invalid run ID")
    directory=ROOT/"benchmark/data/runs"/args.run_id
    directory.mkdir(parents=True,exist_ok=False)
    os.environ["MEM0_TELEMETRY"]="False"
    os.environ["MEM0_DIR"]=str(directory/"mem0")
    os.environ.pop("OPENROUTER_API_KEY",None)
    logging.disable(logging.CRITICAL)  # Provider exception messages can contain request contents.
    from mem0 import Memory
    from importlib.metadata import version
    env=read_env(args.env_file)
    llm_key = env.get("AML_LLM_API_KEY") or env.get("OPENAI_API_KEY")
    llm_url = env.get("AML_LLM_BASE_URL") or env.get("OPENAI_BASE_URL")
    emb_key = env.get("AML_EMBEDDING_API_KEY") or env.get("ZHIPU_API_KEY")
    emb_url = env.get("AML_EMBEDDING_BASE_URL") or env.get("ZHIPU_BASE_URL")
    if not all((llm_key, llm_url, emb_key, emb_url)):
        raise ValueError("env file must provide LLM and embedding key/base URL pairs")
    config={"llm":{"provider":"openai","config":{"model":"gpt-4o-mini","temperature":0,"max_tokens":1800,
        "api_key":llm_key,"openai_base_url":llm_url}},
        "embedder":{"provider":"openai","config":{"model":"embedding-3","embedding_dims":512,
        "api_key":emb_key,"openai_base_url":emb_url}},
        "vector_store":{"provider":"qdrant","config":{"collection_name":"microstudy","embedding_model_dims":512,"path":str(directory/"qdrant")}},
        "history_db_path":str(directory/"history.db")}
    memory=Memory.from_config(config)
    for component in (memory.llm,memory.embedding_model):
        component.client.max_retries=0
        component.client.timeout=45
    pack_path=args.dataset_pack if args.dataset_pack.is_absolute() else ROOT/args.dataset_pack
    pack=load_pack(pack_path.resolve())
    plan=build_retrieval_manifest(pack,chunk_size=args.chunk_size,top_k=args.top_k)
    write_json(directory/"dataset-pack.json",pack);write_json(directory/"plan.json",plan)
    pack_hash = plan["dataset_pack_sha256"]
    with ObservationRecorder(directory/"observability.jsonl",run_id=args.run_id,dataset_pack_sha256=pack_hash) as recorder:
        target=ObservedMem0(memory,recorder,directory,plan,args.run_id)
        target.capture(memory.llm.client.chat.completions,"configured-compatible-llm","gpt-4o-mini")
        target.capture(memory.embedding_model.client.embeddings,"configured-compatible-embedding","embedding-3",True)
        report=run_replay(manifest=plan,cases=plan["cases"],target=target,run_id=args.run_id,
            system={"name":"Mem0 controlled excerpts","version":version("mem0ai"),"target":"mem0-research",
                    "adapter_notes":["user-only scope; session as metadata; timestamps sent only in dated variant",
                    "gold-selected microcases; no full-history or population accuracy claim"]},trace_path=directory/"trace.jsonl")
        write_json(directory/"report.json",report)
        events=[json.loads(s) for s in (directory/"trace.jsonl").read_text(encoding="utf-8").splitlines()]
        observations=[]
        for event in events:
            if event["event"]!="search" or not event["ok"] or not event["add_setup_ok"]: continue
            rid,tid=event["dataset_task"]["record_id"],event["dataset_task"]["task_id"]
            with recorder.span("answer",name="local diagnostic answer",record_id=rid,task_id=tid,request_id=event["search_id"]) as span:
                target.active=span
                context=[r["content"] for r in event["results"]]
                span["inputs"]=[target.artifact("answer-context-"+rid,{"query":event["request"]["query"],"memories":context},"context")]
                response=memory.llm.client.chat.completions.create(model="gpt-4o-mini",temperature=0,max_tokens=450,
                    messages=[{"role":"system","content":PROMPT},{"role":"user","content":json.dumps({"question":event["request"]["query"],"memory_evidence":context},ensure_ascii=False)}])
                answer=response.choices[0].message.content
                ref=target.artifact("answer-"+rid,{"text":answer,"prompt":PROMPT},"answer")
                span["outputs"]=[ref]
                observations.append({"run_id":args.run_id,"record_id":rid,"task_id":tid,"dataset_pack_sha256":pack_hash,
                    "answer":{"text":answer,"model":"gpt-4o-mini","prompt_version":"microstudy-v1",
                              "source_artifact":ref["artifact"],"context_result_ranks":list(range(1,len(context)+1))}})
                print("answer",rid,"saved",flush=True)
        def total_tokens(field):
            if target.failures or any(u[field] is None for u in target.usage):
                return None
            return sum(u[field] for u in target.usage)
        report["summary"]["provider_usage"]={"calls":target.count,"failed_calls":target.failures,
            "input_tokens":total_tokens("input_tokens"),
            "output_tokens":total_tokens("output_tokens"),"cost_usd":None}
        write_json(directory/"report.json",report)
        write_json(directory/"observations.json",{"schema_version":1,"observations":observations})
        write_json(directory/"observability.meta.json",{"schema_version":VERSION,"run_id":args.run_id,"dataset_pack_sha256":pack_hash,
            "model_capture_complete":True,"producer":"benchmark.microstudy.v1 (Mem0 2.2.1 components wrapped; no SDK retries)"})
        write_json(directory/"method.json",{"mem0ai":version("mem0ai"),"openai_sdk":version("openai"),"llm":"gpt-4o-mini",
            "embedding":"embedding-3","dimensions":512,"top_k":5,"reranker":None,"telemetry":False,
            "max_provider_calls":100,"max_input_chars":500000,"timeout_seconds":45,"sdk_retries":0,
            "answer_prompt":PROMPT,"quality_role":"manual diagnostic; not official scorer"})
    memory.vector_store.client.close()
    print(json.dumps(report["summary"]["provider_usage"]))


if __name__=="__main__":
    main()
