from visualization.spans import evidence_panel


def test_unknown_or_old_evidence_fields_stay_unknown():
    assert evidence_panel({}) is None
    panel=evidence_panel({'packing_unit':'evidence_group','decisions':[{'ref':'memory:a'}]})
    assert panel['rows'][0]['closure']=='unknown'


def test_disclosure_panel_is_bounded_and_marks_display_counts():
    panel=evidence_panel({'disclosures':[{'origin_ref':'raw:a','shown_range':[10,510],
        'content_digest':'v','text':'x'*500}]*22,'status':'call_returned'})
    assert panel['total']==22 and panel['shown']==20
    assert len(panel['rows'][0]['text'])==350


def test_relation_rejection_and_database_scope_remain_distinct():
    rejected={'accepted':False,'invalid_links':[{'reason':'relation_type_mismatch'}]}
    assert evidence_panel(rejected)['rows'][0]['accepted'] is False
    scope={'old_scope':{'empty':True,'query_performed':False},'orientation_only':True}
    assert evidence_panel(scope)['title']=='旧记忆范围核验'


def test_review_rejection_evidence_is_not_shown_as_stored_support():
    panel = evidence_panel({'format_version': 2, 'committed': False, 'decisions': [
        {'before': {'ref': 'new:claim', 'text': 'Unsupported.'}, 'after': None,
         'detail': 'The source contradicts it.', 'evidence_positions': [2]}]})
    assert panel['rows'][0]['审查依据位置'] == [2]
    assert panel['rows'][0]['写入支持'] == []
    assert '尚未提交' in panel['title']


def test_successful_api_can_display_unfinished_maintenance_and_partial_search(tmp_path):
    import json
    from visualization.test_imports import fixture
    from visualization.traces import read_run
    from benchmark.observability import ObservationRecorder
    from benchmark.instrumented import Artifacts
    pack_hash = fixture(tmp_path)
    report_path = tmp_path/'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    report['run']['system']['target'] = 'native'
    report_path.write_text(json.dumps(report), encoding='utf-8')
    query = read_run(tmp_path, 'fixture')['queries'][0]
    artifact = Artifacts(tmp_path)
    with ObservationRecorder(tmp_path/'observability.jsonl', run_id='test', dataset_pack_sha256=pack_hash) as recorder:
        with recorder.span('add', name='add', record_id='u', request_id=query['adds'][0]['id']) as parent:
            try:
                with recorder.span('reflection', name='failed review', record_id='u', request_id=parent['request_id'], parent=parent):
                    raise RuntimeError('test')
            except RuntimeError:
                pass
            with recorder.span('store', name='add delivery outcome', record_id='u', request_id=parent['request_id'], parent=parent) as delivery:
                delivery['outputs'] = [artifact.text('result', json.dumps({'intake':'committed',
                    'reflection':'unfinished', 'maintenance_error':'reflection_no_evidence_progress',
                    'progress': {'groups_completed':1, 'groups_unfinished':1}}), title='delivery')]
        with recorder.span('search', name='search', record_id='u', task_id='q', request_id=query['search_id']) as parent:
            with recorder.span('retrieve', name='search final pack', record_id='u', task_id='q', request_id=parent['request_id'], parent=parent) as packed:
                packed['outputs'] = [artifact.text('result', json.dumps({'completion':'partial',
                    'stop_reason':'model_tool_output_invalid'}), title='result')]
    result = read_run(tmp_path, 'fixture')['queries'][0]
    assert result['adds'][0]['delivery']['reflection'] == 'unfinished'
    assert result['adds'][0]['internal_errors'] == 1
    assert result['delivery'] == {'completion':'partial', 'stop_reason':'model_tool_output_invalid'}
