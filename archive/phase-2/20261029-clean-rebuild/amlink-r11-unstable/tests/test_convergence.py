import time
from dataclasses import replace
import pytest
from test_core_repairs import make, request
from amlink.evidence import fragment
from amlink.errors import MemoryError
from amlink.grounding import missing_material
from amlink.projection import range_receipt, visible_fragments
from amlink.packing import freeze_pack
from amlink.packing_experiment import compare
from amlink.text import digest


def stored_fact(engine, text='Cache lifetime is five minutes.', source='deployment api configuration cache '*100):
    engine.add(request('old', [source]))
    raw = engine.store.raw('u')[0]
    node = dict(ref='memory:fact-cache', kind='fact', text=text, source_refs=[raw['ref']],
                time_expression=None, time_start=None, time_end=None)
    engine.store.commit_mutation('u', {'items':[node], 'links':[], 'forget':[]},
                                watermark=1, fingerprint='x', vectors={})
    return engine.store.get('u', node['ref']), raw


def test_complete_auto_body_counts_as_visible_but_source_read_is_not_body_read(make):
    engine, _ = make(mode='raw')
    node, raw = stored_fact(engine)
    body = fragment(node,0,len(node['text']))
    context = {'items':{node['ref']:node}, 'read_ranges':[range_receipt(body)],
               'inspections':{node['ref']:digest(node['text'])}}
    projected = engine._model_context(context)
    assert 'text' not in projected['items'][node['ref']]['text_fragment']
    engine._record_visible(context,projected,'reflection')
    proposal={'items':[node]}
    # Strip store-only fields when making a tool proposal.
    proposal['items']=[{k:v for k,v in node.items() if k in {'ref','kind','text','source_refs','time_expression','time_start','time_end'}}]
    assert missing_material(proposal,context)==[]
    context['read_ranges']=[range_receipt(fragment(raw,0,len(raw['text'])))]
    assert missing_material(proposal,context)[0]['ref']==node['ref']


def test_hidden_page_is_offered_again_and_decoding_uses_frozen_pages(make):
    engine,_=make(mode='raw')
    node,_=stored_fact(engine,text='Prior fact details. '*90)
    body={**fragment(node,0,len(node['text'])),'item_ref':node['ref']}
    context={'question':'cache','references':{node['ref']:engine._reference(node,'cache','query')},
             'items':{node['ref']:node},'disclosures':[body], 'read_ranges':[range_receipt(body)]}
    for i in range(5):
        source={'ref':f'raw:other{i}','text':'unrelated '*100}
        context['disclosures'].append({**fragment(source,0,len(source['text'])),'item_ref':f'memory:other{i}'})
    projected=engine._model_context(context,max_chars=4000)
    assert not any(v['origin_ref']==node['ref'] for v in visible_fragments(projected))
    options=engine._page_options('u',node['ref'],context,visible_fragments(projected))
    assert any(v['origin_ref']==node['ref'] for v in options)
    # Freeze a page before a receipt changes the currently visible set.
    context['_page_choices']={node['ref']:[range_receipt(body)]}
    context['last_visible']=[range_receipt(body)]
    engine._read_page('u',node['ref'],context,0)
    assert context['disclosures'][-1]['origin_ref']==node['ref']


def test_reflection_reads_short_body_before_long_keyword_source(make):
    engine,_=make(mode='raw')
    node,_=stored_fact(engine)
    context={'question':'deployment api configuration cache','old_before':2,'items':{},'references':{}}
    assert engine._page_options('u',node['ref'],context)[0]['origin_ref']==node['ref']


def test_empty_scope_is_database_fact_and_new_person_needs_no_empty_query(make):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose, payload):
        control = payload['context']['reflection_control']
        assert control['old_scope']['empty'] and not control['old_scope']['query_performed']
        stage = control.get('pending_mutation', {}).get('stage')
        if stage == 'relations': return 'reflection_relations', {'links': []}
        return 'reflection_items', {'items': [dict(ref='new:maya', kind='person', text='Maya is the speaker.', source_refs=[payload['working'][0]['ref']])]}
    provider.decide = decide
    engine.add(request('a', ['Speaker: Maya\nI am Maya.']))
    assert len([c for c in provider.calls if c[0]=='reflection']) == 1  # No legal relation pair.
    assert engine.store.old_scope_empty('u', 1)
    assert not engine.store.old_scope_empty('u', 2)
    assert engine.store.old_scope_empty('another_user', 2)


def test_only_correct_relation_direction_is_offered_and_commits_atomically(make):
    engine, provider = make(reflection_threshold=1)
    names = []
    original = provider.tool
    def capture(purpose, prompt, payload, tools, deadline):
        if purpose == 'reflection': names.append([t['name'] for t in tools])
        return original(purpose, prompt, payload, tools, deadline)
    provider.tool = capture
    def decide(purpose, payload):
        source = payload['working'][0]['ref']; step = payload['step']
        assert engine.store.state('u')['settled_through'] == 0
        assert (all(n['kind']=='episode' for n in engine.store.nodes('u')) if step == 0 else
                len(engine.store.nodes('u')) == 3)
        if step == 0: return 'reflection_items', {'items': [dict(ref='new:maya',kind='person',text='Maya',source_refs=[source]),dict(ref='new:tea',kind='fact',text='Maya likes tea.',source_refs=[source])]}
        assert not any(m['from_ref']=='new:maya' and m['to_ref']=='new:tea' for m in payload['connection_menu'])
        a,b = 'new:tea','new:maya'
        return 'reflection_relations', {'links':[dict(from_ref=a,to_ref=b,relation='about',source_refs=[source],support='Maya says she likes tea.')]}
    provider.decide = decide
    engine.add(request('a',['Speaker: Maya\nI like tea.']))
    fact = next(n for n in engine.store.nodes('u') if n['kind']=='fact')
    assert len(engine.store.edges('u',fact['ref'])) == 1
    assert len(names) == 2


def test_invalid_relation_cannot_finish_by_noop(make):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose,payload):
        source = payload['working'][0]['ref']
        if payload['step']==0: return 'reflection_items', {'items':[dict(ref='new:e',kind='event',text='A meeting',source_refs=[source]),
            dict(ref='new:person',kind='person',text='Maya',source_refs=[source])]}
        if payload['step']==1: return 'reflection_relations', {'links':[dict(from_ref='new:e',to_ref='new:e',relation='same_event_as',source_refs=[source],support='A meeting.')]}
        return 'reflection_stop', {'reason': 'No additional semantic change is needed in this fixture.'}
    provider.decide=decide
    assert engine.add(request('a',['A meeting.']))['success']
    assert any(p.get('error') == 'reflection_relation_position_invalid' for plan in engine.store.reflection_plans('u') for p in plan['progress'].values())
    assert engine.store.state('u')['settled_through']==0


def test_missing_relation_sources_is_protocol_failure_without_retry(make):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose,payload):
        source=payload['working'][0]['ref']; step=payload['step']
        if step==0: return 'reflection_items', {'items':[dict(ref='new:f',kind='fact',text='A fact',source_refs=[source]),dict(ref='new:e',kind='entity',text='An entity',source_refs=[source])]}
        link=dict(from_ref='new:f',to_ref='new:e',relation='about',support='A fact concerns the entity.')
        assert step < 2
        return 'reflection_relations', {'links':[link]}
    provider.decide=decide
    engine.add(request('a',['A fact concerns an entity.']))
    assert any(n['kind']=='fact' for n in engine.store.nodes('u'))
    assert any(p.get('error') == 'reflection_relation_output_invalid' for plan in engine.store.reflection_plans('u') for p in plan['progress'].values())


def test_invalid_connection_position_is_rejected_without_rephrasing_retry(make):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose,payload):
        source=payload['working'][0]['ref']
        if payload['step']==0: return 'reflection_items', {'items':[dict(ref='new:p',kind='person',text='Maya',source_refs=[source]),dict(ref='new:f',kind='fact',text='Maya likes tea.',source_refs=[source])]}
        return 'reflection_relations', {'links':[dict(from_ref='new:p',to_ref='new:f',relation='about',source_refs=[source],support='Maya likes tea.')]}
    provider.decide=decide
    assert engine.add(request('a',['Speaker: Maya\nI like tea.']))['success']
    assert any(p.get('error') == 'reflection_relation_position_invalid' for plan in engine.store.reflection_plans('u') for p in plan['progress'].values())
    assert len(provider.calls)==3 and engine.store.state('u')['settled_through']==0


def test_tool_schema_distinguishes_node_identity_from_source_identity(make):
    engine, provider = make(reflection_threshold=1)
    captured = []
    original = provider.tool
    def tool(purpose, prompt, payload, tools, deadline):
        captured.extend(tools)
        return original(purpose, prompt, payload, tools, deadline)
    provider.tool = tool
    engine.add(request('a', ['A named project launched.']))
    import re
    schema = next(t['parameters'] for t in captured if t['name']=='reflection_items')
    props = schema['$defs']['ItemChange']['properties']
    assert re.match(props['ref']['pattern'], 'new:project-launch')
    assert not re.match(props['ref']['pattern'], 'raw:source')
    assert props['source_refs']['items']['enum'] == [engine.store.raw('u')[0]['ref']]


def test_update_cache_does_not_bypass_buffer_but_explicit_correction_does(make):
    engine,provider=make(reflection_min_adds=2,reflection_threshold=100)
    engine.add(request('a',['We make requests to update the cache regularly.']))
    assert not provider.calls and engine.store.state('u')['settled_through']==0
    engine.add(request('b',['Correction: the daily quota is 1200, replacing 1000.']))
    assert engine.store.state('u')['settled_through']==2


def test_offline_pack_rejects_too_many_groups_locally(make):
    engine,provider=make(mode='raw')
    for i in range(2):engine.add(request(str(i),[f'Fact {i}']))
    frozen=freeze_pack(engine.store,'u','Fact',engine.store.nodes('u'),{},engine.config)
    provider.decide=lambda *a: ('packing_comparison',{'groups':[{'position':i,'fragment_positions':[0]} for i in range(2)]})
    with pytest.raises(MemoryError,match='packing_selection_invalid'): compare(engine,frozen,1)


def test_long_orientation_does_not_repeat_full_question_in_every_source(make):
    engine, _ = make(mode='raw')
    engine.add(request('old', ['deploy config quota code '*400 for _ in range(6)]))
    engine.store.commit_mutation('u', {'items':[], 'links':[], 'forget':[]}, watermark=6, fingerprint='x', vectors={})
    engine.add(request('new', ['deploy config quota '*210]))
    context = engine._reflection_context('u', engine.store.raw('u',pending=True), time.monotonic()+10)
    node = engine.store.nodes('u')[0]
    engine._add_context_refs('u', context, [node], time.monotonic()+10)
    engine._explore('u', node['ref'], 'inspect', context, context['question'], time.monotonic()+10)
    engine._save_workspace('u', state='maintenance', context=context)
    projected = engine._model_context(context)
    assert context['disclosures'][0] in projected['disclosures']
    assert all(len(s['text_fragment']['query']) <= 160 for s in context['sources'] if s.get('text_fragment'))


def test_missing_body_feedback_becomes_ready_after_actual_inspect(make):
    engine, _ = make(mode='raw')
    node, _ = stored_fact(engine)
    context = {'old_before':2, 'question':'cache', 'items':{}, 'references':{}, 'edges':[],
               'last_gate_error':{'code':'reflection_orientation_required','missing':[
                   {'ref':node['ref'],'need':'same_version_inspect_full_body_in_final_call'}], 'invalid_links':[]}}
    engine._add_context_refs('u',context,[node],time.monotonic()+10)
    first=engine._model_context(context)
    engine._visible_choices('u',context,first,first['references'])
    assert not first['reflection_control']['required_actions'][0]['material_ready']
    engine._read_page('u',node['ref'],context,0)
    second=engine._model_context(context)
    engine._visible_choices('u',context,second,second['references'])
    assert second['reflection_control']['required_actions'][0]['material_ready']
    assert second['reflection_control']['last_gate_error']['missing']==[]
    assert context['last_gate_error']['missing']  # Observation of the rejected proposal stays intact.


def test_workspace_folds_optional_source_pages_without_losing_required_body(make):
    engine, _ = make(mode='raw', context_chars=2000)
    node, raw = stored_fact(engine)
    body={**fragment(node,0,len(node['text'])),'item_ref':node['ref']}
    optional={**fragment(raw,0,len(raw['text'])),'item_ref':node['ref']}
    context={'old_before':2, 'question':'cache', 'items':{node['ref']:node},
             'references':{},'disclosures':[optional,body], 'protected_bodies':[node['ref']],
             'read_ranges':[range_receipt(optional),range_receipt(body)]}
    engine._bound_workspace(context)
    assert context['disclosures']==[body]
    assert node['ref'] in context['items']
    assert any(v['fragment_id']==optional['fragment_id'] for v in context['read_ranges'])


@pytest.mark.parametrize('invalid_kind', ['overwrite_episode', 'about_episode'])
def test_impossible_old_episode_write_is_repaired_before_reading(make, invalid_kind):
    engine, provider = make(mode='raw')
    engine.add(request('old',['The project used an old configuration.']))
    old=engine.store.nodes('u')[0]
    engine.store.commit_mutation('u', {'items':[],'links':[],'forget':[]},watermark=1,fingerprint='x',vectors={})
    engine.config=replace(engine.config,mode='graph',reflection_threshold=1)
    def decide(purpose,payload):
        step=payload['step']; source=payload['working'][0]['ref']
        node=dict(ref='new:configuration',kind='fact',text='The project now uses a different configuration.',source_refs=[source])
        stage=payload['context']['reflection_control'].get('pending_mutation',{}).get('stage')
        if step==0:
            return 'reflection_items', {'items':[{**node,'ref':old['ref'],'kind':'episode'}] if invalid_kind=='overwrite_episode' else [node]}
        if invalid_kind=='overwrite_episode' and step==1:
            assert payload['context']['reflection_control']['last_gate_error']['missing']==[]
            return 'reflection_items', {'items':[node]}
        if invalid_kind=='about_episode' and step==1:
            assert not any(m['relation']=='about' and m['to_ref']==old['ref'] for m in payload['connection_menu'])
            return 'reflection_relations', {'links': []}
        return 'reflection_relations', {'links':[]}
    provider.decide=decide
    engine.add(request('new',['The project now uses a different configuration.']))
    assert engine.store.get('u',old['ref'])['text']==old['text']
    assert len([n for n in engine.store.nodes('u') if n['kind']=='fact'])==1


def test_relation_repair_cannot_drop_a_nonempty_link_list_silently(make):
    engine, provider=make(reflection_threshold=1)
    def decide(purpose,payload):
        source=payload['working'][0]['ref']
        if payload['step']==0: return 'reflection_items', {'items':[dict(ref='new:p',kind='person',text='Maya',source_refs=[source]),dict(ref='new:f',kind='fact',text='Maya likes tea.',source_refs=[source])]}
        return 'reflection_relations', {'drop_invalid':True,'links':[dict(from_ref='new:p',to_ref='new:f',relation='about',source_refs=[source],support='Maya likes tea.')]}
    provider.decide=decide
    assert engine.add(request('new',['Maya likes tea.']))['success']
    assert any(p.get('error') == 'reflection_relation_output_invalid' for plan in engine.store.reflection_plans('u') for p in plan['progress'].values())
    assert engine.store.state('u')['settled_through']==0


def test_item_tool_exposes_only_new_or_exact_mutable_identities(make):
    engine, _ = make(mode='raw')
    context = {'items': {
        'memory:episode-original': {'kind': 'episode', 'scope_omit_body': True},
        'memory:fact-old': {'kind': 'fact'},
        'memory:person-maya': {'kind': 'person'}}, 'sources': []}
    prop = engine._mutation_tool_schema(context)['$defs']['ItemChange']['properties']['ref']
    assert prop['anyOf'][0]['pattern'] == '^new:.+$'
    assert prop['anyOf'][1]['enum'] == ['memory:fact-old', 'memory:person-maya']
