import time
from dataclasses import replace

import pytest

from test_core_repairs import make, request
from amlink.errors import MemoryError
from amlink.local_reflection import freeze_groups
from amlink.narrative import render
from amlink.store import Store
from amlink.drafts import review_payload
from amlink.evidence import fragment


def test_group_commit_survives_failure_and_replay_skips_completed_group(make):
    engine, provider = make(reflection_threshold=1)
    ordinary = provider.tool
    planning, groups = [], []
    def tool(purpose, prompt, payload, tools, deadline):
        if purpose == 'reflection_plan':
            planning.append(1)
            return 'reflection_plan', {'groups': [
                {'title':'quota', 'question':'project quota', 'background_positions':[]},
                {'title':'trip', 'question':'trip destination', 'background_positions':[1]}], 'primary_groups': {'p0':0,'p1':0,'p2':1}}
        return ordinary(purpose, prompt, payload, tools, deadline)
    provider.tool = tool
    failed = False
    def decide(purpose, payload):
        nonlocal failed
        title = payload['local_group']['title']
        groups.append(title)
        if title == 'trip' and not failed:
            failed = True
            raise MemoryError('provider_timeout', 504)
        return 'reflection_stop', {'reason': 'No additional semantic change is needed in this fixture.'}
    provider.decide = decide
    req = request('a', ['Quota 1000.', 'Trip planning also mentions quota.', 'Trip to Paris.'])
    with pytest.raises(MemoryError, match='provider_timeout'):
        engine.add(req)
    plan = engine.store.reflection_plan('u')
    assert len(plan['receipts']) == 1
    assert engine.store.state('u')['settled_through'] == 0
    assert engine.store.request('u','a')['status'] == 'accepted'
    engine.add(req)
    assert groups == ['quota', 'trip', 'trip'] and len(planning) == 1
    assert engine.store.state('u')['settled_through'] == 3
    before = len(provider.calls)
    engine.add(req)
    assert len(provider.calls) == before


def test_plan_and_graph_commit_are_atomic_and_persist_after_reopen(tmp_path):
    path = tmp_path / 'progress.sqlite3'
    store = Store(path)
    store.start_add(request('a', ['first', 'second']))
    rows = store.raw('u')
    plan = freeze_groups({'groups':[{'title':'first','question':'first','positions':[0]},
                                   {'title':'second','question':'second','positions':[1]}]}, rows)
    store.freeze_plan('u', plan)
    item = dict(ref='memory:fact-first', kind='fact', text='first', source_refs=[rows[0]['ref']])
    mutation = dict(items=[item], links=[], forget=[])
    group = dict(plan_id=plan['plan_id'],index=0)
    with pytest.raises(MemoryError, match='reflection_group_out_of_order'):
        store.commit_mutation('u',mutation,watermark=2,fingerprint='x',vectors={},group={**group,'index':1})
    assert not store.nodes('u') and not store.reflection_plan('u')['receipts']
    store.commit_mutation('u',mutation,watermark=2,fingerprint='x',vectors={},group=group)
    store.close()
    store = Store(path)
    assert len(store.reflection_plan('u')['receipts']) == 1
    assert store.state('u')['settled_through'] == 0
    assert len(store.nodes('u')) == 1
    store.close()


def test_local_committed_nodes_are_found_by_next_group_without_future_episode(make):
    engine,_=make(mode='raw')
    engine.add(request('a',['Maya likes tea.','Maya travels to Paris.']))
    rows=engine.store.raw('u')
    plan=freeze_groups({'groups':[{'title':'Maya','question':'Maya','positions':[0]},
                                 {'title':'trip','question':'Maya trip','positions':[1]}]},rows)
    engine.store.freeze_plan('u',plan)
    node=dict(ref='memory:person-maya',kind='person',text='Maya likes tea.',source_refs=[rows[0]['ref']])
    engine.store.commit_mutation('u',dict(items=[node],links=[],forget=[]),watermark=0,fingerprint='x',vectors={},
        group=dict(plan_id=plan['plan_id'],index=0))
    context=engine._reflection_context('u',[rows[1]],time.monotonic()+10,
        group={**plan['groups'][1], 'from_ordinal':1, 'through_ordinal':2})
    assert node['ref'] in context['references']
    assert not context['old_scope']['empty']
    assert engine.store.request('u','a')['episode_ref'] not in context['orientation_refs']
    options=engine._page_options('u',node['ref'],context)
    assert any(v['origin_ref']==rows[0]['ref'] for v in options)


def test_incomplete_plan_does_not_silently_consume_unassigned_messages():
    rows=[dict(ref='raw:a',text='first',ordinal=1),dict(ref='raw:b',text='second',ordinal=2)]
    with pytest.raises(MemoryError,match='reflection_plan_incomplete'):
        freeze_groups({'groups':[dict(title='first',question='first',positions=[0])]},rows)


def test_select_more_than_24_short_cards_in_one_comparison(make):
    engine,provider=make()
    cards=[dict(ref=f'memory:fact-{i}',kind='fact',text=f'Purchase {i} costs {i} dollars.',source_refs=[]) for i in range(30)]
    provider.decide=lambda purpose,payload:('select',{'positions':[29,0]})
    selected=engine._select_refs('u','purchase costs',cards,{},time.monotonic()+10,reason='query')
    assert len(provider.calls)==1 and len(provider.calls[0][1]['candidates'])==30
    assert selected[0]['ref']==cards[-1]['ref']


def test_narrative_preserves_exact_material_and_omits_internal_hashes():
    text='Speaker: Maya\nOnly on weekends, not weekdays.'
    shown=render('reflection',{'local_group':{'title':'schedule'},'working':[
        dict(ref='raw:a',text=text,role='user',session_id='s',source_time=0,content_digest='INTERNAL-HASH')],
        'context':{'disclosures':[dict(origin_ref='raw:b',text='The old schedule.',content_digest='INTERNAL-HASH')]}})
    assert text in shown and '1970-01-01' in shown and 'raw:a' in shown
    assert 'INTERNAL-HASH' not in shown


def test_active_plan_finishes_when_prior_group_forgot_all_remaining_sources(make):
    engine,provider=make(reflection_threshold=1)
    req=request('a',['Please forget this secret.','Secret material.'])
    state,_=engine.store.start_add(req)
    engine._ensure_episode(req,state, __import__('json').loads(state['raw_refs']),time.monotonic())
    rows=engine.store.raw('u')
    plan=freeze_groups({'groups':[dict(title='forget',question='forget',positions=[0],background_positions=[1]),
                                 dict(title='secret',question='secret',positions=[1],background_positions=[0])]},rows)
    engine.store.freeze_plan('u',plan)
    engine.store.require_reflection('u','a',2)
    engine.store.commit_mutation('u',dict(items=[],links=[],forget=[dict(
        source_refs=[r['ref'] for r in rows],instruction_refs=[rows[0]['ref']],memory_refs=[])]),
        watermark=0,fingerprint='x',vectors={},group=dict(plan_id=plan['plan_id'],index=0))
    assert engine.store.raw('u',pending=True)==[]
    assert engine.add(req)['success']
    assert engine.store.state('u')['settled_through']==2
    assert not provider.calls


@pytest.mark.parametrize('bad_item', ['garbled item', {}, {'ref': 3}])
def test_malformed_node_output_is_explicit_error_without_advancing_group(make, bad_item):
    engine, provider = make(reflection_threshold=1)
    provider.decide = lambda purpose, payload: ('reflection_items', {'items': [bad_item]})
    with pytest.raises(MemoryError, match='reflection_item_draft_invalid'):
        engine.add(request('malformed', ['Maya likes tea.']))
    assert engine.store.state('u')['settled_through'] == 0
    assert engine.store.reflection_plan('u')['receipts'] == []
    assert all(node['kind'] == 'episode' for node in engine.store.nodes('u'))


def test_review_reads_both_endpoints_when_old_body_is_only_in_disclosures():
    old = dict(ref='memory:fact-movie', kind='fact', text='Nate enjoys movies.')
    new = dict(ref='new:shared', kind='fact', text='Nate and Joanna both enjoy movies.', source_refs=['raw:a'])
    edge = dict(from_ref=new['ref'], to_ref=old['ref'], relation='supersedes', source_refs=['raw:a'])
    projected = {'references': {old['ref']: {'kind': 'fact'}},
                 'disclosures': [fragment(old, 0, len(old['text']))]}
    payload = review_payload({'items': [new], 'links': [edge]}, projected,
                             [{'ref': 'raw:a', 'text': 'We both enjoy movies.'}])
    assert {n['ref']: n['text'] for n in payload['endpoints']}[old['ref']] == old['text']
    shown = render('reflection_review', payload)
    assert old['text'] in shown and new['text'] in shown
    assert 'Both being true or one adding detail is not replacement' in shown
    with pytest.raises(MemoryError, match='reflection_review_endpoint_missing'):
        review_payload({'items': [new], 'links': [edge]}, {}, [])
