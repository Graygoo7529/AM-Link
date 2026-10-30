import json
import pytest
from research.benchmark.broad import choose_tasks, run


def test_broad_root_locates_production_sources_after_research_move():
    from research.benchmark.broad import ROOT,source_hashes
    assert (ROOT/'amlink/engine.py').is_file()
    assert 'amlink/engine.py' in source_hashes()


def test_task_selection_is_independent_of_gold_answer_and_balances_categories():
    record = dict(id='r', tasks=[dict(id=str(i), input={'text':f'Question {i}'},
        attributes={'category':i % 3}, annotations={'answer':'gold'}) for i in range(12)])
    selected = choose_tasks(record, 6, 17)
    for t in record['tasks']:
        t['annotations']['answer'] = 'a different gold'
    assert choose_tasks(record, 6, 17) == selected
    assert sorted(int(i) % 3 for i in selected) == [0,0,1,1,2,2]


def test_version_change_blocks_execution_before_credentials_or_model(tmp_path):
    plan = tmp_path / 'suite.json'
    plan.write_text(json.dumps({'source_sha256':{}}), encoding='utf-8')
    with pytest.raises(ValueError, match='source changed'):
        run(plan, [0], 'changed', tmp_path / 'nonexistent-key.env')


def test_status_counts_completed_calls_before_report_and_ignores_partial_tail(tmp_path,monkeypatch):
    import research.benchmark.broad as broad
    monkeypatch.setattr(broad,'ROOT',tmp_path)
    plan=tmp_path/'suite.json'
    plan.write_text(json.dumps({'records':[dict(index=0,family='sample',record_id='r',adds=3,questions=1)]}),encoding='utf-8')
    directory=tmp_path/'research/benchmark/data/runs/p-00-sample';directory.mkdir(parents=True)
    (directory/'trace.jsonl').write_text('{"event":"add","ok":true}\n{"event":"add","ok":false}\n{"event":',encoding='utf-8')
    value=broad.status(plan,'p')['records'][0]
    assert value['state']=='unfinished' and value['add_success']==1
    (directory/'interrupted.json').write_text('{}',encoding='utf-8')
    assert broad.status(plan,'p')['records'][0]['state']=='interrupted'
