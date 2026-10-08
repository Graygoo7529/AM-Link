"""Synthetic fixtures only: no downloaded datasets, servers, or model calls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from benchmark.core import run_replay
from benchmark.datasets import build_retrieval_manifest
from benchmark.observability import ObservationRecorder, VERSION
from benchmark.tests.test_replay import FakeTarget
from visualization.build import build_bundle, case_observations, case_observation_index
from visualization.sources import excerpt
from visualization.traces import read_run, attach_observations
from visualization.spans import read_memory_snapshot
from visualization.sources import file_digest


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(path):
    pack = {"schema_version": 1, "dataset": {"id": "synthetic"},
        "preparation": {"input": {"file": "synthetic.json", "sha256": "a"*64}, "selection": {}},
        "records": [{"id": "u", "sessions": [{"id": "s", "turns": [
            {"id": "t", "role": "user", "content": "Alice prefers tea."}]}],
            "tasks": [{"id": "q", "input": {"text": "What does Alice prefer?"},
                "annotations": {"answer": "tea", "evidence_turn_ids": ["t"]}}]}]}
    plan = build_retrieval_manifest(pack, chunk_size=20, top_k=3)
    report = run_replay(manifest=plan, cases=plan["cases"], target=FakeTarget(), run_id="test",
        system={"name": "synthetic-fixture", "version": "test-only", "target": "aml-api"}, trace_path=path/"trace.jsonl")
    for name, value in (("dataset-pack.json", pack), ("plan.json", plan), ("report.json", report)):
        write(path/name, value)
    return plan["dataset_pack_sha256"]


def span_fixture(path, pack_hash):
    run = read_run(path, "fixture")
    q = run["queries"][0]
    with ObservationRecorder(path/"observability.jsonl", run_id="test", dataset_pack_sha256=pack_hash) as recorder:
        with recorder.span("add", name="add", record_id="u", request_id=q["adds"][0]["id"]):
            pass
        with recorder.span("search", name="search", record_id="u", task_id="q", request_id=q["search_id"]) as parent:
            with recorder.span("retrieve", name="retrieve", record_id="u", task_id="q", request_id=q["search_id"], parent=parent):
                pass


class ImportTests(unittest.TestCase):
    def test_case_observation_index_requires_catalog_source_identity(self):
        catalog={"cases":{"lm4":{"data":{"dataset":"locomo","record":"conv-42","task":"qa-1"}}},
            "datasets":{"locomo":{"cases":["lm4"]}}}
        profiles={"datasets":{"locomo":{"dataset_id":"locomo-v1"}}}
        runs=[{"run_id":"right","dataset_id":"locomo-v1","system":{"name":"phase1","target":"phase1","version":"0.3.0"},"queries":[
                {"search_id":"q1","record_id":"conv-42","task_id":"qa-1"},
                {"search_id":"q2","record_id":"conv-42","task_id":"other"}]},
            {"run_id":"wrong-dataset","dataset_id":"beam-v1","queries":[
                {"search_id":"q3","record_id":"conv-42","task_id":"qa-1"}]}]
        self.assertEqual(case_observations("lm4",catalog=catalog,profiles=profiles,runs=runs),
            [{"run_id":"right","search_id":"q1","system":{"name":"phase1","target":"phase1","version":"0.3.0"},"loaded":True}])

    def test_case_observation_index_finds_registered_archived_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); directory=root/'benchmark/data/runs/archived';directory.mkdir(parents=True)
            write(directory/'report.json',{"schema_version":1,"run":{"run_id":"archived",
                "dataset_pack_sha256":"a"*64,"dataset":{"id":"locomo-v1"},
                "dataset_selection":{"record_ids":["conv-42"],"task_ids":["qa-1"]},
                "system":{"name":"phase1","version":"0.3.0","target":"phase1"}},
                "queries":[{"case_id":"conv-42","search_id":"q1"}]})
            write(directory/'plan.json',{"schema_version":1,"dataset_pack_sha256":"a"*64,
                "cases":[{"id":"conv-42","searches":[{"id":"q1","dataset_task":
                    {"record_id":"conv-42","task_id":"qa-1"}}]}]})
            rows=case_observation_index([{"run_id":"archived","directory":"benchmark/data/runs/archived",
                "dataset_pack_sha256":"a"*64}],catalog={"cases":{"lm4":{"data":{"dataset":"locomo",
                    "record":"conv-42","task":"qa-1"}}},"datasets":{"locomo":{"cases":["lm4"]}}},
                profiles={"datasets":{"locomo":{"dataset_id":"locomo-v1"}}},runs=[],repo_root=root)
            self.assertEqual(rows["lm4"],[{"run_id":"archived","search_id":"q1",
                "system":{"name":"phase1","version":"0.3.0","target":"phase1"},"loaded":False}])

    def test_memory_snapshot_is_bounded_and_checks_artifact_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            file=path/"snapshot.json"
            write(file,{"memories":{"results":[{"id":"a","memory":"Tea","metadata":{"private":"excluded"}}]},
                        "response":{"results":[{"id":"a","event":"ADD","extra":"excluded"}]}})
            ref={"artifact":"snapshot.json","sha256":file_digest(file)}
            result=read_memory_snapshot(path,ref)
            self.assertNotIn("excluded",json.dumps(result))
            self.assertEqual(result["memories"][0]["content"]["text"],"Tea")
            file.write_text("{}")
            with self.assertRaisesRegex(ValueError,"hash"):
                read_memory_snapshot(path,ref)

    def test_public_bundle_has_no_local_samples_or_runs(self):
        bundle = build_bundle()
        self.assertEqual(bundle["local"]["samples"], {})
        self.assertEqual(bundle["runs"], [])
        self.assertEqual(set(bundle["profiles"]["bindings"]), set(bundle["catalog"]["cases"]))
        value = excerpt("abcdefghij", 6)
        self.assertEqual(value["ranges"], [[0, 3], [7, 10]])
        self.assertTrue(value["omitted"])

    def test_trace_identity_and_no_fabricated_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            fixture(path)
            run = read_run(path, "fixture")
            self.assertEqual(run["queries"][0]["target_ranks"], [2])
            self.assertIsNone(run["queries"][0]["answer"])
            self.assertEqual(run["observability"]["status"], "missing")
            with self.assertRaisesRegex(ValueError, "fixture"):
                read_run(path, "experiment")
            pack = json.loads((path/"dataset-pack.json").read_text())
            pack["records"][0]["tasks"][0]["input"]["text"] = "changed"
            write(path/"dataset-pack.json", pack)
            with self.assertRaisesRegex(ValueError, "digest"):
                read_run(path, "fixture")

    def test_complete_declaration_required_for_zero_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            pack_hash = fixture(path)
            span_fixture(path, pack_hash)
            run = read_run(path, "fixture")
            self.assertEqual(len(run["queries"][0]["spans"]), 3)
            self.assertIsNone(run["observability"]["model_calls"])
            write(path/"observability.meta.json", dict(schema_version=VERSION, run_id="test", dataset_pack_sha256=pack_hash,
                model_capture_complete=True, producer="synthetic-test"))
            run = read_run(path, "fixture")
            self.assertEqual(run["observability"]["model_calls"], 0)
            self.assertEqual(run["observability"]["cost_usd"], 0)

    def test_orphan_detected_and_wrong_identity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            pack_hash = fixture(path)
            span_fixture(path, pack_hash)
            file = path/"observability.jsonl"
            events = [json.loads(line) for line in file.read_text().splitlines()]
            orphan = next(e for e in events if e["operation"] == "retrieve")
            file.write_text(json.dumps(orphan)+"\n")
            self.assertEqual(read_run(path, "fixture")["observability"]["status"], "incomplete")
            orphan["record_id"] = "other"
            file.write_text(json.dumps(orphan)+"\n")
            with self.assertRaisesRegex(ValueError, "record/task"):
                read_run(path, "fixture")

    def test_answer_context_and_evaluation_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            pack_hash = fixture(path)
            run = read_run(path, "fixture")
            row = dict(run_id="test", record_id="u", task_id="q", dataset_pack_sha256=pack_hash,
                answer=dict(text="Tea", model="synthetic", prompt_version="test", context_result_ranks=[2], source_artifact="answers.json#0"),
                evaluation=dict(label="correct", metric="test", evaluator="synthetic", source_artifact="eval.json#0"))
            file = path/"answers.json"
            write(file, dict(schema_version=1, observations=[row]))
            attach_observations([run], file)
            self.assertEqual(run["queries"][0]["answer"]["text"]["text"], "Tea")
            row["answer"]["context_result_ranks"] = [100]
            write(file, dict(schema_version=1, observations=[row]))
            with self.assertRaisesRegex(ValueError, "context ranks"):
                attach_observations([copy.deepcopy(run)], file)
