from research.web.spans import evidence_panel


def test_clean_notes_and_final_pack_preserve_distinction():
    panel=evidence_panel({'status':'completed','notes':[{'ref':'memory:note/x','text':'Navigation','support_refs':['episode:a']}]})
    assert '导航' in panel['title'] and panel['rows'][0]['指向的原文']==['episode:a']
    assert evidence_panel({'status':'failed','notes':[]}) is None
    panel=evidence_panel({'returned':[{'id':'a','content':'exact text'}],'budget_omitted':['b']})
    assert panel['rows'][0]['完整正文字符数']==10 and panel['rows'][1]['装箱未交付的引用']==['b']


def test_select_merge_summary_does_not_claim_full_original_visibility():
    panel = evidence_panel({'view':'contribution_summary','model_input':{'candidates':[
        {'position':0,'narrative':'A partial navigation summary.'}]},'member_fragment_map':{'0':[{},{}]}})
    assert panel['rows'][0]['绑定的完整原文卡数'] == 2
    assert '不是新证据' in panel['rows'][0]['说明']


def test_unknown_or_old_evidence_fields_stay_unknown():
    assert evidence_panel({}) is None
    panel=evidence_panel({'packing_unit':'evidence_group','decisions':[{'ref':'memory:a'}]})
    assert panel['rows'][0]['closure']=='unknown'


def test_node_checkpoint_is_displayed_as_saved_but_not_a_completed_group():
    value = {'group_complete':False,'committed_node_refs':['memory:a'],
        'mutation':{'items':[{'ref':'memory:a','kind':'fact','text':'A supported fact.','source_refs':['raw:a']}]}}
    panel = evidence_panel(value)
    assert '尚未完成' in panel['title'] and panel['rows'][0]['已保存正文'] == 'A supported fact.'


def test_increment_panel_distinguishes_support_from_new_nodes_and_requires_commit():
    value = {'increment': {'created': [], 'support_added': [{'ref': 'memory:a', 'added_source_refs': ['raw:new']}],
                           'navigation_updated': []}, 'no_item_change': False}
    assert evidence_panel(value) is None
    panel = evidence_panel({**value, 'committed': True})
    assert panel['rows'][0]['数量'] == 0
    assert panel['rows'][1]['数量'] == 1 and '非草案' in panel['title']


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
    from research.web.test_imports import fixture
    from research.web.traces import read_run
    from research.benchmark.observability import ObservationRecorder
    from research.benchmark.instrumented import Artifacts
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
