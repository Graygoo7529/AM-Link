import copy
import gc
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from benchmark.core import run_replay, write_json
from benchmark.datasets import build_retrieval_manifest
from benchmark.instrumented import Artifacts, LexicalMemory, ObservedTarget
from benchmark.observability import ObservationRecorder, VERSION
from benchmark.workspace import make_note, append_note, read_notes
from dataset.selection import select_pack
from visualization.traces import read_run
from visualization.semantics import readable
from visualization.build import presentation_bundle


def source():
    return {"schema_version": 1, "dataset": {"id": "study-test"},
        "preparation": {"input": {"file": "test.json", "sha256": "a"*64}, "selection": {}},
        "records": [{"id": "r", "sessions": [{"id": "s", "turns": [
            {"id": "a", "role": "user", "content": "Bike chain costs 25 dollars.", "timestamp": 100},
            {"id": "b", "role": "assistant", "content": "Remember the receipt.", "timestamp": 200},
            {"id": "c", "role": "user", "content": "Bike helmet costs 120 dollars.", "timestamp": 300}]}],
            "tasks": [{"id": "q", "input": {"text": "Bike costs?"},
                "annotations": {"answer": "GOLD_NEVER_SENT", "evidence_turn_ids": ["a", "c"]}}]}]}


def run_local(directory, pack=None):
    pack = pack or source()
    plan = build_retrieval_manifest(pack, chunk_size=1, top_k=1)
    with ObservationRecorder(directory / "observability.jsonl", run_id="local-test", dataset_pack_sha256=plan["dataset_pack_sha256"]) as rec:
        files = Artifacts(directory)
        target = ObservedTarget(LexicalMemory(rec, files), rec, files, "lexical")
        report = run_replay(manifest=plan, cases=plan["cases"], target=target, run_id="local-test",
            system={"name": "local-bm25", "target": "lexical", "version": "v1"}, trace_path=directory / "trace.jsonl")
    for name, value in (("plan.json",plan),("dataset-pack.json",pack),("report.json",report)):
        write_json(directory / name, value)
    write_json(directory / "observability.meta.json", {"schema_version": VERSION, "run_id": "local-test",
        "dataset_pack_sha256": plan["dataset_pack_sha256"], "model_capture_complete": True, "producer": "test"})
    return read_run(directory, "experiment")


class StudyTests(unittest.TestCase):
    def test_selection_preserves_source_and_no_gold_leak(self):
        pack = source()
        snapshot = copy.deepcopy(pack)
        sliced = select_pack(pack, record_ids=["r"], task_ids=["q"], scope="anchors", turn_ids=["a", "c"])
        self.assertEqual(pack, snapshot)
        self.assertEqual([t["id"] for t in sliced["records"][0]["sessions"][0]["turns"]], ["a", "c"])
        plan = build_retrieval_manifest(sliced, chunk_size=20, top_k=5)
        requests = [c["adds"]+[s["request"] for s in c["searches"]] for c in plan["cases"]]
        self.assertNotIn("GOLD_NEVER_SENT", json.dumps(requests))
        self.assertTrue(sliced["preparation"]["selection"]["selection_assisted"])

    def test_partial_cutoff_keeps_gold_but_disables_grading(self):
        with self.assertRaisesRegex(ValueError,"excludes annotated"):
            select_pack(source(), before=300)
        sliced = select_pack(source(), before=300, allow_partial=True)
        task = sliced["records"][0]["tasks"][0]
        self.assertEqual(task["annotations"]["evidence_turn_ids"], ["a","c"])
        query = build_retrieval_manifest(sliced, chunk_size=20, top_k=5)["cases"][0]["searches"][0]
        self.assertEqual(query["grading"], "ungraded")
        self.assertEqual(query["expected"], [])
        self.assertFalse(query["expect_empty"])

    def test_unknown_ids_and_undated_cutoffs_fail(self):
        for kwargs in ({"record_ids":["missing"]},{"task_ids":["missing"]},
                       {"scope":"window", "turn_ids":["missing"]}):
            with self.assertRaises(ValueError): select_pack(source(), **kwargs)
        p=source();del p["records"][0]["sessions"][0]["turns"][0]["timestamp"]
        with self.assertRaisesRegex(ValueError,"undated"): select_pack(p,before=300)

    def test_window_is_in_source_order_and_local_to_session(self):
        p=source()
        r=select_pack(p,scope="window",turn_ids=["b"],radius=1)
        self.assertEqual(r["records"][0]["sessions"],p["records"][0]["sessions"])

    def test_real_pipeline_exposes_candidates_and_persistent_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp); run=run_local(path); q=run["queries"][0]
            self.assertIsNone(q["answer"])
            self.assertEqual(run["observability"]["model_calls"],0)
            retrieval=next(s for s in q["spans"] if s["operation"]=="retrieve")
            self.assertEqual([c["selected"] for c in retrieval["candidates"]],[True,False])
            self.assertTrue(q["span_previews"])
            note=make_note(run,search_id=q["search_id"],stage="retrieve",span_id=retrieval["span_id"],kind="observation",author="test",text="Only one evidence unit returned.")
            append_note(path,note)
            self.assertEqual(read_notes(path,run),[note])
            bad={**note,"id":"new","trace_sha256":"b"*64}
            with self.assertRaisesRegex(ValueError,"mismatch"): append_note(path,bad)
            bad={**note,"id":"new","stage":"store"}
            with self.assertRaisesRegex(ValueError,"span"): append_note(path,bad)
            revision={**note,"id":"revised","supersedes":note["id"],"text":"Revised with source evidence."}
            append_note(path,revision)
            self.assertEqual(len(read_notes(path,run)),2)

    def test_artifact_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp); run=run_local(path)
            span=next(s for s in run["queries"][0]["spans"] if s["operation"]=="store")
            (path/span["outputs"][0]["artifact"]).write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,"hash mismatch"): read_run(path,"experiment")

    def test_select_and_reflection_notes_can_be_saved_and_reloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp); run=run_local(path)
            for stage in ("select", "reflection"):
                note=make_note(run,search_id=run["queries"][0]["search_id"],stage=stage,
                    kind="observation",author="test",text="A source was lost at this stage.")
                append_note(path,note)
            self.assertEqual([n["stage"] for n in read_notes(path,run)],["select","reflection"])

    def test_store_is_isolated_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            with ObservationRecorder(path/'spans.jsonl',run_id='x',dataset_pack_sha256='a'*64) as rec:
                files=Artifacts(path);method=LexicalMemory(rec,files);target=ObservedTarget(method,rec,files,'lexical')
                target.set_observation_context(record_id='r',task_id=None,request_id='one')
                request={'request_id':'one','user_id':'alice','session_id':'s','messages':[{'role':'user','content':'tea'}]}
                target.add(request);target.add(request)
                self.assertEqual(len(method.users['alice']),1)
                conflict=copy.deepcopy(request);conflict['messages'][0]['content']='coffee'
                self.assertEqual(target.add(conflict).status_code,409)
                target.set_observation_context(record_id='r',task_id='q',request_id='query')
                self.assertEqual(target.search({'user_id':'bob','query':'tea','top_k':5}).body['data'],[])

    def test_semantics_decode_container_and_preserve_unknown_values(self):
        rows=readable({'conversation_json':'[{"role":"user","content":"hello\\nworld"}]','has_answer':False,'answer':None})
        self.assertIn('hello\nworld',[r['value'] for r in rows])
        self.assertIn('否（false）',[r['value'] for r in rows])
        self.assertTrue(any('null' in r['value'] for r in rows))

    def test_command_runs_selected_data_and_requests_publication(self):
        from benchmark.study import main
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); pack=root/'input.json';write_json(pack,source())
            with patch('benchmark.study.ROOT',root), patch('benchmark.study.register') as register, patch('benchmark.study.publish') as publish, patch('builtins.print'):
                main(['--dataset-pack',str(pack),'--record','r','--task','q','--run-id','e2e'])
            output=root/'benchmark/data/runs/e2e'
            register.assert_called_once_with(output)
            publish.assert_called_once_with()
            run=read_run(output,'experiment')
            self.assertEqual(run['queries'][0]['target_ranks'],[1,2])
            report=json.loads((output/'report.json').read_text(encoding='utf-8'))
            self.assertIsNone(report['summary']['retrieval']['overall']['evidence_recall@10'])

    def test_phase1_target_runs_archived_service_in_isolated_database(self):
        from benchmark.phase1 import Phase1Target
        with tempfile.TemporaryDirectory() as tmp:
            target=Phase1Target(db_path=Path(tmp)/'isolated.sqlite3')
            try:
                request={'request_id':'add-one','user_id':'sample','session_id':'session',
                    'messages':[{'role':'user','content':'The bike chain costs 25 dollars.'}]}
                added=target.add(request)
                self.assertEqual(added.status_code,200)
                self.assertTrue(added.body['success'])
                result=target.search({'user_id':'sample','query':'How much was the bike chain?', 'top_k':5})
                self.assertEqual(result.status_code,200)
                self.assertIn('25 dollars',result.body['data'][0]['content'])
                self.assertTrue(target.model_capture_complete)
                self.assertEqual(target.model_configuration['llm'],{'enabled':False,'name':None})
                self.assertEqual(target.model_configuration['embedding'],
                    {'enabled':False,'name':None,'dimensions':None})
            finally:
                target.close()
                del target
                gc.collect()

    def test_native_display_artifacts_and_compaction_preserve_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);run=run_local(path)
            # Convert this test run's store payload to the explicit native display format.
            events=[json.loads(line) for line in (path/'observability.jsonl').read_text(encoding='utf-8').splitlines()]
            store=next(s for s in events if s['operation']=='store')
            old=store['outputs'][0];ref=Artifacts(path).text('memory','Bike chain costs 25 dollars.',title='实际保存的测试事实')
            for e in events:
                for key in ('inputs','outputs'):
                    e[key]=[ref if r['id']==old['id'] else r for r in e[key]]
                for link in e['links']:
                    for key in ('from_id','to_id'):
                        if link[key]==old['id']:link[key]=ref['id']
            (path/'observability.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
            report=json.loads((path/'report.json').read_text(encoding='utf-8'));report['run']['system']['target']='native';write_json(path/'report.json',report)
            run=read_run(path,'experiment');q=run['queries'][0]
            self.assertEqual(q['span_previews'][store['span_id']][0]['content']['text'],'Bike chain costs 25 dollars.')
            compact=presentation_bundle({'runs':[run]})['runs'][0]
            restored={}
            refs={row[0]:dict(zip(('id','kind','artifact','sha256','locator'),row)) for row in compact['span_references']}
            for row in compact['span_table']:
                s=dict(zip(compact['span_columns'],row));s.update(run_id=run['run_id'],dataset_pack_sha256=run['dataset_pack_sha256'])
                for key in ('inputs','outputs'):s[key]=[refs[x] for x in s[key]]
                restored[s['span_id']]=s
            self.assertEqual([restored[x] for x in compact['queries'][0]['spans']],q['spans'])

    def test_multiple_questions_share_history_without_corrupting_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack=source();second=copy.deepcopy(pack['records'][0]['tasks'][0]);second['id']='q2'
            pack['records'][0]['tasks'].append(second)
            run=run_local(Path(tmp),pack)
            compact=presentation_bundle({'runs':[run]})['runs'][0]
            self.assertEqual(len(compact['queries']),2)
            self.assertEqual(compact['queries'][0]['adds'][0]['sources'],compact['queries'][1]['adds'][0]['sources'])
            self.assertEqual(compact['queries'][0]['adds'][0]['sources'][0][0],'a')


if __name__ == '__main__': unittest.main()
