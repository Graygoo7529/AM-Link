import json

import httpx

from amlink.config import Config
from amlink.native import NativeTarget
from benchmark.core import run_replay, write_json
from benchmark.datasets import build_retrieval_manifest
from benchmark.instrumented import Artifacts, ObservedTarget
from benchmark.observability import ObservationRecorder, VERSION
from visualization.traces import read_run


def test_native_models_sources_and_graph_steps_reach_visualization(tmp_path):
    pack = {"schema_version": 1, "dataset": {"id": "amlink-test"},
        "preparation": {"input": {"file": "test.json", "sha256": "a"*64}, "selection": {}},
        "records": [{"id": "r", "sessions": [{"id": "s", "turns": [
            {"id": "t", "role": "user", "content": "Blue comet notebook."}]}],
            "tasks": [{"id": "q", "input": {"text": "comet"},
                       "annotations": {"answer": "GOLD_NOT_SENT", "evidence_turn_ids": ["t"]}}]}]}
    plan = build_retrieval_manifest(pack, chunk_size=20, top_k=5)
    captured = []
    def respond(request):
        payload = json.loads(request.content)
        captured.append(payload)
        context = json.loads(payload["messages"][1]["content"])["data"]
        result = {"items": [{"ref": "new:f", "kind": "fact", "text": "Blue comet notebook.", "source_refs": context["new_refs"]}]}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                                          "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
    with ObservationRecorder(tmp_path / "observability.jsonl", run_id="amlink-test", dataset_pack_sha256=plan["dataset_pack_sha256"]) as recorder:
        method = NativeTarget(Config(db_path=str(tmp_path / "memory.sqlite3"), reflection_threshold=1,
            search_model=False, llm_api_key="test"), recorder, Artifacts(tmp_path))
        method.providers.client.close()
        method.providers.client = httpx.Client(transport=httpx.MockTransport(respond))
        try:
            report = run_replay(manifest=plan, cases=plan["cases"],
                target=ObservedTarget(method, recorder, method.observer.artifacts, "native"),
                run_id="amlink-test", system={"name": "AM-Link", "target": "native", "version": "test"},
                trace_path=tmp_path / "trace.jsonl")
        finally:
            method.close()
    for filename, value in (("plan.json", plan), ("dataset-pack.json", pack), ("report.json", report)):
        write_json(tmp_path / filename, value)
    write_json(tmp_path / "observability.meta.json", {"schema_version": VERSION, "run_id": "amlink-test",
        "dataset_pack_sha256": plan["dataset_pack_sha256"], "model_capture_complete": True, "producer": "test-mock-transport"})
    assert "GOLD_NOT_SENT" not in json.dumps(captured)
    run = read_run(tmp_path, "experiment")
    assert run["observability"]["model_calls"] == 1
    assert report["summary"]["add"]["success"] == 1
    assert report["summary"]["search"]["success"] == 1
    names = {s["name"] for s in run["queries"][0]["spans"]}
    assert {"memory.inspect", "memory.backlinks", "bounded graph traversal", "assemble evidence and enforce state"} <= names
    assert run["queries"][0]["span_previews"]

