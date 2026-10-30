"""Faults at the public delivery boundary, independent of model quality."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3
import time

import pytest

from test_core_repairs import make, request, Scripted
from amlink.engine import Engine
from amlink.errors import MemoryError
from amlink.observation import Observer
from amlink.store import Store
from amlink.schemas import SearchRequest, BfsAction
from amlink.providers import Providers
from amlink.drafts import decode_review, merge_visible
from amlink.evidence import fragment
from amlink.text import digest


def counts(store):
    return {t: store.one(f'SELECT count(*) AS n FROM {t}')["n"] for t in
            ('requests', 'raw_events', 'working', 'nodes', 'vectors', 'lexical', 'blocks')}


@pytest.mark.parametrize('failure', ['embedding', 'index', 'commit'])
def test_failed_intake_leaves_no_new_material_and_preserves_prior_user(make, monkeypatch, failure):
    engine, provider = make(mode='raw', embedding_enabled=True, embedding_dimensions=2)
    engine.add(request('prior', ['Tea is green.']))
    before = counts(engine.store), engine.store.snapshot('u')
    if failure == 'embedding':
        provider.fail_embedding = True
    elif failure == 'index':
        monkeypatch.setattr(engine.store, '_index', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('fault')))
    else:
        engine.store.db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON requests BEGIN SELECT RAISE(ABORT, 'fault'); END")
    with pytest.raises((MemoryError, sqlite3.Error)):
        engine.add(request('failed', ['New unseen secret.']))
    assert before == (counts(engine.store), engine.store.snapshot('u'))
    assert engine.store.request('u', 'failed') is None


def test_committed_receipt_survives_response_loss_and_reopen(make, tmp_path):
    template, _ = make(mode='raw', embedding_enabled=True, embedding_dimensions=2)
    path = tmp_path / 'receipt.sqlite3'
    provider = Scripted()
    first = Engine(template.config, Store(path), provider, Observer()); provider.engine = first
    req = request('durable', ['The observatory opens on Friday.'])
    first.add(req)  # Imagine the transport loses this response.
    first.store.close()
    provider = Scripted()
    second = Engine(template.config, Store(path), provider, Observer()); provider.engine = second
    try:
        assert second.add(req)['success']
        assert provider.calls == [] and len(second.store.raw('u')) == 1
        assert second.search(SearchRequest(user_id='u', top_k=5, query='observatory'))['data']
    finally:
        second.store.close()


def test_concurrent_replay_has_one_embedding_and_conflict_changes_nothing(make):
    engine, provider = make(mode='raw', embedding_enabled=True, embedding_dimensions=2)
    req = request('same', ['The exact same message.'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(r['success'] for r in pool.map(engine.add, [req] * 4))
    assert len(provider.calls) == 1 and len(engine.store.raw('u')) == 1
    before = counts(engine.store)
    with pytest.raises(MemoryError, match='idempotency_payload_conflict'):
        engine.add(request('same', ['Different payload.']))
    assert counts(engine.store) == before


def test_failed_group_does_not_block_other_groups_or_repeat_on_replay(make):
    engine, provider = make(reflection_threshold=1)
    ordinary = provider.tool
    def tool(purpose, prompt, payload, tools, deadline):
        if purpose == 'reflection_plan':
            return purpose, {'assignments': {f'p{i}': {'question': f'group {i}', 'background_positions': []}
                                            for i in range(len(payload['messages']))}}
        return ordinary(purpose, prompt, payload, tools, deadline)
    provider.tool = tool
    def decide(purpose, payload):
        if payload['local_group']['title'] == 'group 0':
            raise MemoryError('model_tool_output_invalid', 502)
        return 'reflection_stop', {'reason': 'This is a repeated greeting with no additional assertion.'}
    provider.decide = decide
    req = request('grouped', ['One greeting.', 'Another greeting.'])
    assert engine.add(req)['success']
    plan = engine.store.reflection_plan('u')
    assert [r['index'] for r in plan['receipts']] == [1]
    assert plan['progress']['0']['error'] == 'model_tool_output_invalid'
    assert engine.store.state('u')['settled_through'] == 0
    calls = len(provider.calls)
    engine.add(req)
    assert len(provider.calls) == calls
    assert engine._run_reflection(req, [], time.monotonic(), plan=plan) is False
    assert len(provider.calls) == calls  # No input delta means no identical reattempt.


@pytest.mark.parametrize('failure', ['provider_timeout', 'model_tool_output_invalid', 'select_merge_budget'])
def test_search_optional_failure_retains_last_complete_evidence(make, monkeypatch, failure):
    engine, provider = make(mode='raw')
    engine.add(request('a', ['Maya visited Paris in June.']))
    monkeypatch.setattr(engine, '_next_bfs_action', lambda *a: BfsAction(action='inspect', ref=next(iter(a[2]['references']))))
    def fail(*args):
        args[3]['references']['memory:failed-leak'] = {'text': 'Not valid evidence.'}
        args[3]['paths'] = [{'from_ref': 'memory:failed-leak'}]
        raise MemoryError(failure, 504)
    monkeypatch.setattr(engine, '_explore_step', fail)
    captured = []
    assemble = engine._assemble
    def pack(*args, **kw):
        captured.append(deepcopy(kw['context']))
        return assemble(*args, **kw)
    monkeypatch.setattr(engine, '_assemble', pack)
    assert engine.search(SearchRequest(user_id='u', top_k=5, query='Maya Paris'))['data']
    assert 'memory:failed-leak' not in captured[0]['references']
    assert not captured[0].get('paths') and captured[0]['bfs_terminal_reason'] == failure


def test_mandatory_query_failure_and_storage_failure_are_not_empty_success(make, monkeypatch):
    engine, provider = make(mode='raw', embedding_enabled=True, embedding_dimensions=2)
    engine.add(request('a', ['Blue notebook.']))
    provider.fail_embedding = True
    with pytest.raises(MemoryError, match='provider_timeout'):
        engine.search(SearchRequest(user_id='u', top_k=5, query='Blue'))
    monkeypatch.setattr(engine, '_next_bfs_action', lambda *a: (_ for _ in ()).throw(sqlite3.DatabaseError('fault')))
    with pytest.raises(sqlite3.DatabaseError):
        engine.search(SearchRequest(user_id='u', top_k=5, query='Blue'))


def test_nonempty_evidence_cannot_be_reported_as_empty_due_to_packing(make, monkeypatch):
    engine, _ = make(mode='raw')
    engine.add(request('a', ['Blue notebook.']))
    monkeypatch.setattr(engine, '_assemble', lambda *a, **kw: [])
    with pytest.raises(MemoryError, match='search_evidence_pack_empty'):
        engine.search(SearchRequest(user_id='u', top_k=5, query='Blue'))


def test_forgetting_is_atomic_and_quoted_instruction_is_not_authorization(make):
    engine, provider = make(mode='raw')
    engine.add(request('old', ['My secret code is orchid.']))
    ordinary = provider.tool
    def tool(purpose, prompt, payload, tools, deadline):
        if purpose == 'forget_intent':
            return purpose, {'requests': [{'instruction_ref': payload['messages'][0]['ref'],
                'instruction_quote': 'Please forget my secret code.',
                'all_memory': False}]}
        if purpose == 'forget_scope':
            from amlink.narrative import render
            assert 'My secret code is orchid.' in render(purpose, payload)
            return purpose, {'matches': [{'position':0,'reason':'The exact code requested.'}]}
        if purpose == 'forget_verify':
            return purpose, {'matches':True,'evidence_quote':'My secret code is orchid.','reason':'The same secret code.'}
        return ordinary(purpose, prompt, payload, tools, deadline)
    provider.tool = tool
    assert engine.add(request('forget', ['Please forget my secret code.']))['success']
    assert engine.store.raw('u') == [] and engine.store.nodes('u') == []
    assert engine.search(SearchRequest(user_id='u', top_k=5, query='secret code'))['data'] == []
    calls = len(provider.calls)
    engine.add(request('forget', ['Please forget my secret code.']))
    assert len(provider.calls) == calls
    provider.tool = lambda *a: ('forget_intent', {'requests': []})
    engine.add(request('quote', ['The book says "Please forget my secret code." It is fiction.']))
    assert len(engine.store.nodes('u')) == 1


def test_forget_failure_does_not_accept_or_remove_old_sources(make):
    engine, provider = make(mode='raw')
    engine.add(request('old', ['My secret code is orchid.']))
    before = counts(engine.store)
    provider.tool = lambda *a: (_ for _ in ()).throw(MemoryError('provider_timeout', 504))
    with pytest.raises(MemoryError, match='provider_timeout'):
        engine.add(request('forget', ['Please forget my secret code.']))
    assert counts(engine.store) == before and engine.store.request('u', 'forget') is None


def test_review_keys_cannot_repeat_or_silently_omit_proposals():
    payload = {'units': [{'position': 3}, {'position': 9}]}
    with pytest.raises(MemoryError, match='reflection_review_incomplete'):
        decode_review(payload, {'reviews': {'u3': {}}, 'remaining_work': [], 'no_change_reason': None})
    data = {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [{'function': {
        'name': 'review', 'arguments': '{"reviews":{"u3":{},"u3":{}}}'}}]}}]}
    with pytest.raises(MemoryError, match='model_tool_output_invalid'):
        from amlink.tool_contract import parse_tool
        parse_tool(data, [{'name': 'review', 'parameters': {'type': 'object'}}])


def test_review_sources_merge_overlap_without_inventing_gap():
    source = {'ref': 'raw:a', 'text': 'ABCDEFGHIJKLMN'}
    values = merge_visible([fragment(source, 0, 5), fragment(source, 3, 8), fragment(source, 11, 14)])
    assert [(v['start'], v['end'], v['text']) for v in values] == [(0, 8, 'ABCDEFGH'), (11, 14, 'LMN')]


def test_review_applies_corrections_then_local_patch_completes_remaining_work(make):
    engine, provider = make(reflection_threshold=1)
    default_review, seen = provider.review, []
    def review(payload):
        result = default_review(payload)
        if len(payload['units']) == 1 and payload['units'][0]['proposal']['ref'] == 'new:tea':
            result['reviews'][0].update(action='revise', text='Maya likes tea.')
            result['remaining_work'] = ['Also retain the explicitly stated Paris visit.']
        return result
    provider.review = review
    def decide(purpose, payload):
        draft = payload['context']['reflection_control'].get('pending_mutation')
        source = payload['working'][0]['ref']
        if not draft:
            return 'reflection_items', {'items': [dict(ref='new:tea', kind='fact', text='Maya likes coffee.', source_refs=[source])]}
        seen.append(deepcopy(draft))
        if draft['stage'] == 'items':
            assert draft['items'][0]['text'] == 'Maya likes tea.'
            return 'reflection_patch_items', {'reason': 'Add the unhandled visit without rewriting the corrected tea fact.',
                'remove_refs': [], 'upsert': [dict(ref='new:visit', kind='event', text='Maya visited Paris.', source_refs=[source])]}
        return 'reflection_relations', {'links': []}
    provider.decide = decide
    assert engine.add(request('a', ['Maya likes tea. Maya visited Paris.']))['success']
    assert engine.store.state('u')['settled_through'] == 1
    assert {n['text'] for n in engine.store.nodes('u') if n['kind'] != 'episode'} == {'Maya likes tea.', 'Maya visited Paris.'}
    assert len([p for p, _ in provider.calls if p == 'reflection_review']) == 2


def test_failed_embedding_preserves_reviewed_draft_for_later_evidence(make):
    engine, provider = make(reflection_threshold=1, embedding_enabled=True, embedding_dimensions=2)
    default_review = provider.review
    def review(payload):
        provider.fail_embedding = True  # Fail derived-node embedding after valid review.
        return default_review(payload)
    provider.review = review
    provider.decide = lambda p, data: ('reflection_items', {'items': [dict(ref='new:tea', kind='fact',
        text='Maya likes tea.', source_refs=[data['working'][0]['ref']])]})
    assert engine.add(request('a', ['Maya likes tea.']))['success']
    plan = engine.store.reflection_plan('u')
    progress = plan['progress']['0']
    assert progress['error'] == 'provider_timeout'
    assert progress['context']['pending_mutation']['items'][0]['text'] == 'Maya likes tea.'
    assert all(n['kind'] == 'episode' for n in engine.store.nodes('u'))


def test_stale_saved_draft_is_not_restored_over_changed_old_node(make):
    from amlink.local_reflection import freeze_groups
    engine, _ = make(mode='raw')
    engine.add(request('a', ['Maya likes tea.']))
    source = engine.store.raw('u')[0]
    plan = freeze_groups({'groups': [dict(title='tea', question='tea', positions=[0])]}, [source])
    engine.store.freeze_plan('u', plan)
    node = engine.store.nodes('u')[0]
    group = {**plan['groups'][0], 'plan_id': plan['plan_id'], 'index': 0, 'from_ordinal': 1, 'through_ordinal': 1}
    engine.store.group_progress('u', group, {'context': {'pending_mutation': {'items': ['STALE']}},
        'versions': {node['ref']: 'wrong-old-version'}})
    context = engine._reflection_context('u', [source], time.monotonic()+10, group=group)
    assert 'pending_mutation' not in context


def test_distinct_events_with_same_proposed_ref_require_semantic_repair(make):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose, payload):
        if payload['context']['reflection_control'].get('pending_mutation', {}).get('stage') == 'relations':
            return 'reflection_relations', {'links': []}
        repaired = bool(payload['context']['reflection_control'].get('last_gate_error'))
        source = payload['working'][0]['ref']
        return 'reflection_items', {'items': [dict(ref='new:game-' + (opponent if repaired else 'same-day'),
            kind='event', text=f'Maya won against {opponent} on Monday.', source_refs=[source]) for opponent in ('Jon', 'Ana')]}
    provider.decide = decide
    assert engine.add(request('a', ['Maya won against Jon and Ana in separate games on Monday.']))['success']
    assert engine.store.state('u')['settled_through'] == 1
    assert len([n for n in engine.store.nodes('u') if n['kind'] == 'event']) == 2


def test_select_can_keep_more_than_four_independent_originals_through_context_and_pack(make):
    engine, provider = make(mode='raw')
    engine.add(request('costs', [f'Purchase {i} cost {10+i} dollars.' for i in range(7)]))
    node = engine.store.nodes('u')[0]
    provider.decide = lambda p, data: ('select', {'positions': list(range(len(data['candidates'])))})
    selected = engine._select_refs('u', 'List purchases and costs', [node], {}, time.monotonic()+20, reason='query')
    assert len(selected[0]['selected_fragments']) == 7
    ref = engine._reference(selected[0], 'purchases', 'query', 'u')
    context = {'references': {node['ref']: ref}, 'items': {}, 'edges': []}
    projected = engine._model_context(context)
    assert len(projected['references'][node['ref']]['evidence_fragments']) == 7
    rows = engine._assemble('u', 'purchases', selected, 5, 'purchases', context=context)
    assert all(f'{10+i} dollars' in '\n'.join(r['content'] for r in rows) for i in range(7))


def test_http_and_native_agree_on_accepted_but_unfinished_add(make, tmp_path):
    from fastapi.testclient import TestClient
    from amlink.api import create_app
    from amlink.native import NativeTarget
    template, _ = make(reflection_threshold=1)
    request_data = request('a', ['Maya likes tea.']).model_dump()
    provider = Scripted()
    provider.close = lambda: None
    provider.decide = lambda *a: (_ for _ in ()).throw(MemoryError('provider_timeout', 504))
    config = replace(template.config, db_path=str(tmp_path/'native.sqlite3'))
    native = NativeTarget(config, providers=provider); provider.engine = native.engine
    try:
        direct = native.add(request_data)
        assert direct.status_code == 200
        assert native.store.state('u')['state'] == 'stopped'
        assert native.store.maintenance_summary('u')['groups_unfinished'] == 1
    finally:
        native.close()
    provider = Scripted(); provider.close = lambda: None
    provider.decide = lambda *a: (_ for _ in ()).throw(MemoryError('provider_timeout', 504))
    app = create_app(config=replace(config, db_path=str(tmp_path/'http.sqlite3')), providers=provider)
    with TestClient(app) as client:
        provider.engine = app.state.engine
        response = client.post('/v1/memory/add', json=request_data)
        assert response.status_code == 200 and response.json()['success']
        assert app.state.engine.store.maintenance_summary('u')['groups_unfinished'] == 1
        calls = len(provider.calls)
        assert client.post('/v1/memory/add', json=request_data).json() == response.json()
        assert len(provider.calls) == calls


@pytest.mark.parametrize('fault', ['missing_source', 'stale_fragment', 'other_user_source'])
def test_final_evidence_rejects_missing_stale_or_foreign_provenance(make, fault):
    from amlink.packing import freeze_pack
    engine, _ = make(mode='raw')
    engine.add(request('a', ['Maya visited Paris.']))
    node = engine.store.nodes('u')[0]
    source = engine.store.raw('u')[0]
    if fault == 'missing_source':
        engine.store.db.execute('DELETE FROM raw_events WHERE ref=?', (source['ref'],))
    elif fault == 'other_user_source':
        engine.store.db.execute('UPDATE raw_events SET user_id=? WHERE ref=?', ('other', source['ref']))
    else:
        node['selected_fragments'] = [fragment(source, 0, len(source['text']))]
        node['selected_fragments'][0]['text'] = 'Invented evidence.'
    with pytest.raises(MemoryError, match='search_evidence_integrity'):
        freeze_pack(engine.store, 'u', 'Paris', [node], {}, engine.config)


def test_duplicate_episode_does_not_displace_an_independent_evidence_card(make):
    from amlink.packing import freeze_pack, pack_frozen
    engine, _ = make(mode='raw')
    engine.add(request('a', ['Maya likes tea.']))
    engine.add(request('b', ['Maya visited Paris.']))
    sources = engine.store.raw('u')
    fact = dict(ref='memory:fact-tea', kind='fact', text='Maya likes tea.', source_refs=[sources[0]['ref']])
    engine.store.commit_mutation('u', {'items': [fact], 'links': [], 'forget': []}, watermark=2, fingerprint='test', vectors={})
    episodes = sorted([n for n in engine.store.nodes('u') if n['kind']=='episode'], key=lambda n: n['source_refs'] != [sources[0]['ref']])
    frozen = freeze_pack(engine.store, 'u', 'Maya', [fact, *episodes], {}, engine.config)
    rows, audit = pack_frozen(frozen, 2)
    assert len(rows) == 2 and 'Paris' in rows[1]['content']
    assert audit['decisions'][1]['reason'] == 'source_ranges_already_returned'
