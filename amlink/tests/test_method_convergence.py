import time

import pytest

from test_core_repairs import make, request
from amlink.drafts import check_review, review_payload, review_schema
from amlink.errors import MemoryError
from amlink.local_reflection import passages, freeze_groups, group_rows, decode_plan
from amlink.narrative import render
from amlink.projection import visible_fragments
from amlink.text import digest
from amlink.evidence import fragment


def test_long_source_is_lossless_and_groups_preserve_global_ranges():
    text = ('Maya travelled with her sister.\n' * 80) + 'They returned in June.'
    rows = [dict(ref='raw:a', text=text, ordinal=1)]
    parts = passages(rows)
    assert len(parts) > 1 and ''.join(p['text'] for p in parts) == text
    plan = freeze_groups({'groups': [
        dict(title='first', question='journey', positions=[0]),
        dict(title='second', question='return', positions=list(range(1,len(parts))), background_positions=[0])]}, rows)
    working = group_rows(plan['groups'][1], rows)
    assert working[0]['primary'] is False and working[1]['primary'] is True
    for value in visible_fragments({}, working):
        assert value['content_digest'] == digest(text)
        assert value['text'] == text[value['start']:value['end']]
    with pytest.raises(MemoryError, match='reflection_plan_source_changed'):
        group_rows(plan['groups'][1], [{**rows[0], 'text': text+'changed'}])
    with pytest.raises(MemoryError, match='reflection_plan_version'):
        group_rows({**plan['groups'][1], 'version':1}, rows)
    with pytest.raises(MemoryError, match='reflection_plan_invalid'):
        freeze_groups({'groups': [dict(title='a', question='a', positions=list(range(len(parts)))),
                                 dict(title='b', question='b', positions=[0])]}, rows)


def test_complete_assignment_cannot_use_shared_background_as_primary_coverage():
    rows=[dict(ref='raw:a',text='First.',ordinal=1),dict(ref='raw:b',text='Second.',ordinal=2)]
    result={'assignments': {'p0':dict(question='both',background_positions=[1])}}
    with pytest.raises(MemoryError,match='reflection_plan_incomplete'): decode_plan(result,rows)
    result['assignments']['p1']=dict(question='both',background_positions=[])
    plan=decode_plan(result,rows)
    assert all(v['primary'] for v in plan['groups'][0]['ranges'])


def test_split_source_replay_skips_finished_ranges_without_advancing_whole_message(make):
    engine,provider=make(reflection_threshold=1)
    original=provider.tool
    planned=[]; seen=[]
    def tool(purpose,prompt,payload,tools,deadline):
        if purpose=='reflection_plan':
            planned.append(1)
            return 'reflection_plan', {'assignments': {f'p{i}':dict(question='first' if i == 0 else 'rest',background_positions=[]) for i in range(len(payload['messages']))}}
        return original(purpose,prompt,payload,tools,deadline)
    provider.tool=tool
    fail=True
    def decide(purpose,payload):
        nonlocal fail
        seen.append((payload['local_group']['title'],payload['working']))
        if payload['local_group']['title']=='rest' and fail:
            fail=False
            raise MemoryError('provider_timeout',504)
        return 'reflection_stop', {'reason':'This group repeats a greeting only.'}
    provider.decide=decide
    text='Hello again.\n'*180
    req=request('long',[text])
    assert engine.add(req)['success']
    assert any(p.get('error') == 'provider_timeout' for plan in engine.store.reflection_plans('u') for p in plan['progress'].values())
    receipt=engine.store.reflection_plan('u')['receipts'][0]
    assert receipt['completion']['outcome']=='episode_only' and receipt['completion']['reason']
    assert engine.store.state('u')['settled_through']==0
    engine.add(req)
    assert len(planned)==1 and [v[0] for v in seen]==['first','rest']
    assert all(len(r['text'])<len(text) for _,rows in seen for r in rows)
    assert engine.store.state('u')['settled_through']==0


def test_control_tools_removed_and_noop_receipt_is_explained(make):
    engine, provider = make(reflection_threshold=1, batch_messages=1)
    original = provider.tool
    def tool(purpose, prompt, payload, tools, deadline):
        assert not {'reflection_commit','reflection_validate'}.intersection(t['name'] for t in tools)
        return original(purpose,prompt,payload,tools,deadline)
    provider.tool = tool
    # Fail second group so the first atomic receipt remains inspectable.
    provider.decide = lambda p, data: ('reflection_stop', {'reason':'This is only a repeated greeting.'})
    engine.add(request('a',['Hello again.']))
    assert engine.store.state('u')['settled_through'] == 1
    before = len(provider.calls)
    engine.add(request('a',['Hello again.']))
    assert len(provider.calls) == before
    provider.decide = lambda p, data: ('reflection_stop', {})
    assert engine.add(request('b',['Hello again.']))['success']
    assert any(p.get('error') == 'reflection_completion_invalid' for plan in engine.store.reflection_plans('u') for p in plan['progress'].values())
    assert engine.store.state('u')['settled_through'] == 1


def test_review_noncontiguous_source_positions_and_endpoint_revision():
    args = {'items': [dict(ref='new:tea',kind='fact',text='Maya likes coffee.',source_refs=['raw:a']),
                      dict(ref='new:maya',kind='person',text='Maya',source_refs=['raw:a'])],
            'links':[dict(from_ref='new:tea',to_ref='new:maya',relation='about',source_refs=['raw:a'])]}
    payload = review_payload(args,{},[dict(ref='raw:a',text='Maya likes tea.')])
    payload['sources'][0]['position'] = 7
    for u in payload['units']: u['source_positions'] = [7]
    result={'reviews':[dict(position=u['position'],action='keep',text=None,source_positions=[7]) for u in payload['units']]}
    result['reviews'][0].update(action='revise',text='Maya likes tea.')
    edits,receipts=check_review(payload,result)
    assert edits[0]['after']['text']=='Maya likes tea.'
    assert edits[-1]['after'] is not None
    # Endpoint version invalidation is owned by the review session, not a model acknowledgement.


def test_review_protocol_requires_replacement_text_for_revision():
    payload=review_payload({'items':[dict(ref='new:a',kind='fact',text='Maya likes coffee.',source_refs=['raw:a'])]},
                          {},[dict(ref='raw:a',text='Maya likes tea.')])
    schema=review_schema(payload)
    fields=schema['properties']['u0']['properties']
    assert fields['text']['type']==['string','null'] and 'anyOf' not in schema['properties']['u0']
    with pytest.raises(MemoryError,match='reflection_review_invalid'):
        check_review(payload,{'reviews':[dict(position=0,action='revise',text=None,
            detail='Maya likes tea.',source_positions=[0])]})


def test_conflict_review_keeps_old_provenance_even_when_edge_cites_only_new():
    source=dict(ref='raw:old',text='Quota is 1000.')
    old=dict(ref='memory:fact-old',kind='fact',text='Quota is 1000.',source_refs=[source['ref']])
    new=dict(ref='new:quota',kind='fact',text='Quota is now 1200.',source_refs=['raw:new'])
    edge=dict(from_ref=new['ref'],to_ref=old['ref'],relation='supersedes',source_refs=['raw:new'])
    projected={'references':{old['ref']:old},'disclosures':[fragment(old,0,len(old['text'])),fragment(source,0,len(source['text']))]}
    payload=review_payload(dict(items=[new],links=[edge]),projected,[dict(ref='raw:new',text='Quota is now 1200.')])
    relation=payload['units'][-1]
    assert {v['source_ref'] for v in payload['sources'] if v['position'] in relation['source_positions']}=={'raw:old','raw:new'}


def test_identity_comparison_is_really_rendered_in_final_review(make):
    engine,provider=make()
    old=dict(ref='memory:person-maya',kind='person',text='Maya is the teacher, not the musician.')
    shown={**fragment(old,0,len(old['text'])),'item_ref':old['ref']}
    context={'identity_queries':{'new:maya':{'refs':[old['ref']]}},'inspections':{old['ref']:digest(old['text'])}}
    projected={'references':{old['ref']:old},'disclosures':[shown]}
    args={'items':[dict(ref='new:maya',kind='person',text='Maya is a musician.',source_refs=['raw:new'])]}
    engine._review_draft(args,projected,[dict(ref='raw:new',text='Maya is a musician.')],time.monotonic()+10,context=context)
    payload=provider.calls[0][1]
    text=render('reflection_review',payload)
    assert 'EXISTING IDENTITY READ FOR COMPARISON' in text and old['text'] in text
    assert any(v['origin_ref']==old['ref'] for v in context['last_visible'])


def test_no_legal_pair_goes_directly_to_content_review(make):
    engine,provider=make(reflection_threshold=1)
    provider.decide=lambda p,data:('reflection_items',dict(items=[dict(ref='new:visit',kind='event',
        text='Maya visited Paris.',source_refs=[data['working'][0]['ref']])]))
    engine.add(request('a',['Maya visited Paris.']))
    assert [p for p,_ in provider.calls]==['reflection','reflection_review']
    assert any(n['kind']=='event' for n in engine.store.nodes('u'))


def test_all_withdrawn_review_requires_explicit_episode_only_and_no_update(make):
    engine,provider=make()
    args={'basis':'new_information','items':[dict(ref='new:greet',kind='fact',text='Hello.',source_refs=['raw:a'])]}
    provider.review=lambda p: dict(resolution='episode_only',reason='Only a greeting; no new factual change.',
        reviews=[dict(position=0,action='drop',text=None,detail='Not a useful fact.',source_positions=[])])
    context={}
    result=engine._review_draft(args,{},[dict(ref='raw:a',text='Hello.')],time.monotonic()+10,context=context)
    assert not result['items'] and context['_completion']['outcome']=='episode_only'
    with pytest.raises(MemoryError,match='reflection_unresolved_evidence'):
        engine._review_draft({**args,'basis':'update_existing'},{},[dict(ref='raw:a',text='Hello.')],time.monotonic()+10)
    provider.review=lambda p: dict(resolution='commit',reason='Rejected.',
        reviews=[dict(position=0,action='drop',detail='Not a fact.',source_positions=[])])
    with pytest.raises(MemoryError,match='reflection_review_empty'):
        engine._review_draft(args,{},[dict(ref='raw:a',text='Hello.')],time.monotonic()+10)


def test_unchanged_body_reuses_vector_but_changed_body_or_model_does_not(make):
    engine,provider=make(mode='raw',embedding_enabled=True,embedding_dimensions=2)
    engine.add(request('a',['Maya likes tea.']))
    source=engine.store.raw('u')[0]['ref']
    item=dict(ref='memory:person-maya',kind='person',text='Maya likes tea.',source_refs=[source])
    prepared=dict(items=[item],links=[],forget=[],filtered_links=[])
    def commit(): engine._commit_reflection('u',prepared,1,time.monotonic()+10)
    commit()
    before=len(provider.calls)
    commit()
    assert len(provider.calls)==before
    assert item['ref'] in {n['ref'] for n,_ in engine.store.vector_rows('u',provider.embedding_fingerprint)}
    item['text']='Maya likes tea and coffee.'
    commit()
    assert len(provider.calls)==before+1
    provider.embedding_fingerprint='changed-model'
    commit()
    assert len(provider.calls)==before+2


def test_query_vector_reuse_does_not_cache_results_or_cross_contexts(make):
    engine,provider=make(mode='raw',embedding_enabled=True,embedding_dimensions=2)
    engine.add(request('a',['Maya likes tea.']))
    context={}
    before=len(provider.calls)
    first=engine._search_refs('u','Maya',context,time.monotonic()+10,mode='search')
    engine._search_refs('u','Maya',context,time.monotonic()+10,mode='search')
    assert len(provider.calls)==before+1
    engine.add(request('b',['Maya travels to Paris.']))
    before=len(provider.calls)
    second=engine._search_refs('u','Maya',context,time.monotonic()+10,mode='search')
    assert len(second)>len(first) and len(provider.calls)==before
    engine._search_refs('u','Maya',{},time.monotonic()+10,mode='search')
    assert len(provider.calls)==before+1


def test_select_only_propagates_coverage_for_chosen_passages(make):
    engine,provider=make()
    rows=[dict(ref=f'memory:fact-{i}',kind='fact',text=f'Purchase {i} cost {i} dollars.',source_refs=[]) for i in range(3)]
    provider.decide=lambda p,data:('select',dict(positions=[2,0],coverage=[
        dict(evidence='Second purchase amount',positions=[2]),dict(evidence='Unchosen amount',positions=[1])]))
    context={}
    chosen=engine._select_refs('u','purchase costs',rows,context,time.monotonic()+10,reason='query')
    assert [r['ref'] for r in chosen]==[rows[2]['ref'],rows[0]['ref']]
    assert len(context['selection_coverage'])==1
    context['references']={r['ref']:engine._reference(r,'purchase costs','query') for r in chosen}
    shown=render('bfs',{'context':engine._model_context(context)})
    assert 'Second purchase amount' in shown and 'Unchosen amount' not in shown
    assert 'verify against quoted passages' in shown
    context['references'].pop(rows[2]['ref'])
    assert 'Second purchase amount' not in render('bfs',{'context':engine._model_context(context)})
