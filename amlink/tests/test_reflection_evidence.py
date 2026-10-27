import time
from dataclasses import replace
import pytest
from test_core_repairs import make, request
from amlink.errors import MemoryError
from amlink.engine import Engine
from amlink.reflection import prepare_mutation
from amlink.evidence import fragment
from amlink.text import digest, dumps


def test_visible_source_remains_citable_after_duplicate_workspace_copy_is_folded(make):
    engine, _ = make(mode='raw')
    engine.add(request('a', ['Maya likes tea.']))
    source = engine.store.raw('u')[0]
    context = {'sources': [], 'items': {}, 'old_before': 2, 'new_refs': [],
               'visible_source_refs': [source['ref']]}
    proposal = {'items': [dict(ref='new:tea', kind='fact', text='Maya likes tea.', source_refs=[source['ref']])]}
    prepared = prepare_mutation(proposal, user='u', request_id='b', number=2, context=context, store=engine.store)
    assert prepared['items'][0]['source_refs'] == [source['ref']]
    context['visible_source_refs'] = []
    with pytest.raises(MemoryError, match='mutation_unknown_source'):
        prepare_mutation(proposal, user='u', request_id='b', number=2, context=context, store=engine.store)
    context.update(visible_source_refs=[source['ref']], old_before=1)
    with pytest.raises(MemoryError, match='mutation_unknown_source'):
        prepare_mutation(proposal, user='u', request_id='b', number=2, context=context, store=engine.store)


def test_new_identity_queries_old_scope_and_can_commit_without_old_match(make):
    engine,provider=make(mode='raw',reflection_threshold=1)
    engine.add(request('old',['A previous unrelated note.']))
    engine.store.commit_mutation('u',{'items':[],'links':[],'forget':[]},watermark=1,fingerprint='x',vectors={})
    engine.config=replace(engine.config,mode='graph')
    engine._search_refs=lambda *a,**kw: []
    def decide(purpose,payload):
        step=payload['step']
        if step==0: return 'reflection_items', {'no_prior_match':True,'items':[dict(ref='new:maya',kind='person',text='Maya is the named speaker.',source_refs=[payload['working'][0]['ref']])]}
        if step==1: return 'reflection_search', {'question':'Maya identity','for_new_ref':'new:maya'}
        if step==2:
            assert 'new:maya' in payload['context']['reflection_control']['identity_queries']
            return 'reflection_relations', {'links':[]}
        raise AssertionError('No control-only call expected')
    provider.decide=decide
    engine.add(request('a',['Speaker: Maya\nMy name is Maya.']))
    assert any(n['kind']=='person' for n in engine.store.nodes('u'))
    assert engine.store.state('u')['settled_through']==2


def test_missing_identity_query_cannot_be_hidden_by_noop(make):
    engine, provider = make(mode='raw', reflection_threshold=1)
    engine.add(request('old', ['An older person note.']))
    engine.store.commit_mutation('u', {'items': [], 'links': [], 'forget': []}, watermark=1, fingerprint='x', vectors={})
    engine.config = replace(engine.config, mode='graph')
    def decide(purpose, payload):
        if payload['step'] == 0:
            return 'reflection_items', {'no_prior_match': True, 'items': [
                {'ref': 'new:maya', 'kind': 'person', 'text': 'Maya', 'source_refs': [payload['working'][0]['ref']]}]}
        return 'reflection_stop', {'reason': 'No additional semantic change is needed in this fixture.'}
    provider.decide = decide
    with pytest.raises(MemoryError, match='model_unknown_tool'):
        engine.add(request('a',['Speaker: Maya']))
    assert engine.store.state('u')['settled_through'] == 1


def test_full_replacement_requires_same_version_full_body_visible():
    node = {'ref': 'memory:entity-x', 'text': 'long old description ' * 150, 'source_refs': ['raw:a']}
    proposal = {'items': [{'ref': node['ref'], 'kind': 'entity', 'text': 'New description', 'source_refs': ['raw:a']}]}
    context = {'items': {node['ref']: node}, 'inspections': {node['ref']: digest(node['text'])},
               'last_visible': [fragment(node,0,100)]}
    with pytest.raises(MemoryError):
        Engine._check_reflection_basis(proposal, context)
    context['last_visible'] = [fragment(node,0,len(node['text']))]
    Engine._check_reflection_basis(proposal,context)
    node['text'] += 'changed'
    with pytest.raises(MemoryError):
        Engine._check_reflection_basis(proposal,context)


def test_old_candidate_filter_applies_before_limit(make):
    engine, _ = make(mode='raw')
    engine.add(request('old',['Maya visited the park']))
    old = engine.store.nodes('u')[0]['ref']
    for i in range(6):
        engine.add(request(str(i),['Maya Maya Maya']))
    rows = engine.store.lexical('u', 'Maya', 1, before=2)
    assert [r['ref'] for r in rows] == [old]


def test_disclosed_page_is_pinned_until_main_call_and_version_invalidates(make):
    engine, provider = make(mode='raw')
    engine.add(request('a',['Original claim. ' * 300]))
    node = engine.store.nodes('u')[0]
    context = {'question':'claim','references':{node['ref']:engine._reference(node,'claim','query','u')},'items':{},'edges':[]}
    engine._explore('u',node['ref'],'inspect',context,'claim',time.monotonic()+10)
    assert context['pinned']
    projected = engine._model_context(context)
    assert context['disclosures'][0] in projected['disclosures']
    engine._record_visible(context,projected,'bfs')
    assert not context['pinned']
    before = len(context['disclosures'])
    engine._explore('u',node['ref'],'inspect',context,'claim',time.monotonic()+10)
    assert len(context['disclosures']) == before+1
    assert context['depths'].get(node['ref'],0) == 0
    raw = engine.store.raw('u')[0]['ref']
    engine.store.commit_mutation('u',{'items':[],'links':[],'forget':[{'source_refs':[raw], 'memory_refs':[], 'instruction_refs':[]}]},watermark=1,fingerprint='x',vectors={})
    engine._refresh_context('u', context)
    assert not context['disclosures'] and not context['last_visible'] and not context['references']


def test_protected_page_budget_errors_instead_of_silent_omission(make):
    engine, _ = make(mode='raw')
    raw = {'ref':'raw:a','text':'x'*5000}
    value = {**fragment(raw,0,5000), 'item_ref':'memory:a'}
    engine.config = replace(engine.config,context_chars=1000)
    with pytest.raises(MemoryError,match='protected_context_budget'):
        engine._model_context({'disclosures':[value], 'pinned':[value['fragment_id']]})


def test_mixed_minimum_episode_discloses_only_old_portion_for_orientation(make):
    engine, _ = make(mode='raw')
    engine.add(request('a',['old identity Maya', 'FUTURE_SECRET_NOTE']))
    node=engine.store.nodes('u')[0]
    context={'old_before':2,'question':'Maya','references':{},'items':{},'edges':[]}
    engine._add_context_refs('u',context,[node],time.monotonic()+10)
    projected=engine._model_context(context)
    assert 'FUTURE_SECRET_NOTE' not in dumps(projected)
    assert all('FUTURE_SECRET_NOTE' not in page['text'] for page in engine._page_options('u',node['ref'],context))
    assert engine.store.lexical('u','FUTURE_SECRET_NOTE',1,before=2)==[]
    rows=engine.store.lexical('u','Maya',1,before=2)
    assert len(rows)==1 and 'FUTURE_SECRET_NOTE' not in rows[0]['text']


def test_workspace_unknown_version_and_protected_capacity_fail(make):
    engine,_=make(mode='raw')
    engine.add(request('a',['A note']))
    engine.store.save_workspace('u',context={'format_version':999})
    with pytest.raises(MemoryError,match='workspace_version_unknown'):
        engine._reflection_context('u',engine.store.raw('u'),time.monotonic()+10)
    context={'items':{'memory:a':{'text':'x'*60000}},'protected_refs':['memory:a']}
    with pytest.raises(MemoryError,match='protected_workspace_budget'):
        engine._bound_workspace(context)


def test_pinned_episode_page_does_not_pin_entire_hidden_episode(make):
    engine,_=make(mode='raw')
    source={'ref':'raw:a','text':'Long original. '*5000}
    page={**fragment(source,0,1800),'item_ref':'memory:episode-a'}
    context={'items':{'memory:episode-a':{'text':source['text'],'scope_omit_body':True}},
             'disclosures':[page],'pinned':[page['fragment_id']]}
    engine._bound_workspace(context)
    assert context['disclosures']==[page]
    assert len(dumps(context))<2*engine.config.context_chars


def test_workspace_does_not_duplicate_full_current_working_sources(make):
    engine,_=make(mode='raw')
    engine.add(request('a',['Current working. '*2000]))
    sources=engine.store.raw('u')
    context={'sources':sources,'new_refs':[s['ref'] for s in sources], 'items':{},'references':{}}
    engine._save_workspace('u',context=context)
    assert engine.store.state('u')['context']['sources']==[]
    assert context['sources']==sources
    assert engine.store.raw('u',pending=True)[0]['text']==sources[0]['text']


def test_completed_old_episode_can_be_read_as_relation_endpoint(make):
    engine,_=make(mode='raw')
    engine.add(request('a',['Old completed source.']))
    node=engine.store.nodes('u')[0]
    context={'old_before':2,'question':'Old','references':{},'items':{},'edges':[], 'new_refs':[]}
    engine._add_context_refs('u',context,[node],time.monotonic()+10)
    options=engine._page_options('u',node['ref'],context)
    pos=next(i for i,v in enumerate(options) if v['origin_ref']==node['ref'])
    engine._explore('u',node['ref'],'inspect',context,'Old',time.monotonic()+10,pos)
    engine._bound_workspace(context)
    engine._record_visible(context,engine._model_context(context),'reflection')
    proposal={'links':[{'from_ref':node['ref'],'to_ref':'new:fact','relation':'contains','source_refs':node['source_refs']}]}
    engine._check_reflection_basis(proposal,context)
