from test_core_repairs import make, request
from amlink.drafts import review_payload, check_review
from amlink.reflection import prepare_mutation
from amlink.evidence import fragment
import time


def test_review_can_correct_citation_to_other_actually_visible_source():
    args = {'items': [{'ref':'new:gender','kind':'fact','text':'Maya is female.','source_refs':['raw:hobbies']}]}
    working = [{'ref':'raw:hobbies','text':'Maya likes tea.'}, {'ref':'raw:profile','text':'Maya is female.'}]
    payload = review_payload(args, {}, working)
    output = {'reviews':[{'position':0,'action':'keep','text':None,'detail':'Profile supplies gender; hobbies do not.', 'source_positions':[1]}]}
    edits, receipts = check_review(payload,output)
    assert edits[0]['after']['source_refs']==['raw:profile']
    assert receipts[0]['source_ref']=='raw:profile' and receipts[0]['quote']=='Maya is female.'


def test_alias_self_relation_is_deduplicated_but_explicit_self_relation_is_invalid(make):
    engine,_=make(mode='raw')
    engine.add(request('a',['The quota is 1000.']))
    source=engine.store.raw('u')[0]['ref']
    old={'ref':'memory:fact-quota','kind':'fact','text':'The quota is 1000.','source_refs':[source]}
    engine.store.commit_mutation('u',{'items':[old],'links':[],'forget':[]},watermark=1,fingerprint='test',vectors={})
    context={'sources':engine.store.raw('u'),'items':{old['ref']:engine.store.get('u',old['ref'])},'memories':[],'new_refs':[]}
    args={'items':[{**old,'ref':'new:quota'}], 'links':[{'from_ref':'new:quota','to_ref':old['ref'],'relation':'supersedes','source_refs':[source]}]}
    result=prepare_mutation(args,user='u',request_id='b',number=2,context=context,store=engine.store)
    assert not result['filtered_links'] and not result['links']
    assert result['deduplicated_links'][0]['reason']=='endpoints_resolve_to_same_memory'
    args['links'][0]['to_ref']='new:quota'
    result=prepare_mutation(args,user='u',request_id='b',number=2,context=context,store=engine.store)
    assert result['filtered_links'][0]['reason']=='self_link'


def test_relation_review_sees_corrected_node_endpoints(make):
    engine, provider = make(mode='raw')
    args = {'items': [
        {'ref':'new:maya','kind':'person','text':'Maya','source_refs':['raw:a']},
        {'ref':'new:tea','kind':'fact','text':'Maya likes coffee.','source_refs':['raw:a']}],
        'links':[{'from_ref':'new:tea','to_ref':'new:maya','relation':'about','source_refs':['raw:a']}]}
    ordinary = provider.review
    phases = []
    def review(payload):
        phases.append(payload['units'][0]['kind'])
        result = ordinary(payload)
        for unit, decision in zip(payload['units'], result['reviews']):
            if unit['kind'] == 'item' and unit['proposal']['ref'] == 'new:tea':
                decision.update(action='revise', text='Maya likes tea.')
            if unit['kind'] == 'relation':
                decision['revised_endpoints'] = ['new:tea']
        return result
    provider.review = review
    result = engine._review_draft(args, {}, [{'ref':'raw:a','text':'Maya likes tea.'}], time.monotonic()+10)
    assert phases == ['item', 'relation']  # Only the edge sees the final corrected endpoint again.
    assert result['items'][1]['text']=='Maya likes tea.' and result['links']


def test_conflict_source_todo_uses_same_visible_provenance_as_commit_gate(make):
    engine, _ = make(mode='raw')
    engine.add(request('a', ['The quota was 1000.']))
    source = engine.store.raw('u')[0]
    old = {'ref':'memory:fact-old','kind':'fact','text':'The quota was 1000.','source_refs':[source['ref']]}
    engine.store.commit_mutation('u', {'items':[old],'links':[],'forget':[]},watermark=1,fingerprint='x',vectors={})
    proposed = {'ref':'new:quota','kind':'fact','text':'The quota is 1200.','source_refs':['raw:new']}
    context = {'question':'quota','old_before':2,'new_refs':['raw:new'],'items':{old['ref']:old},
        'references':{old['ref']:engine._reference(old,'quota','required','u')},
        'pending_mutation':{'items':[proposed]},
        'pending_links':[{'from_ref':'new:quota','to_ref':old['ref'],'relation':'supersedes','source_refs':['raw:new']}],
        'last_gate_error':{'code':'reflection_orientation_required','missing':[
            {'ref':old['ref'],'need':'conflict_side_visible_provenance'}]}}
    projected = {'references':context['references'],'reflection_control':{'last_gate_error':context['last_gate_error']}}
    engine._visible_choices('u',context,projected,[old['ref']])
    need = projected['reflection_control']['required_actions'][0]
    assert not need['material_ready'] and need['pages'][0]['origin_ref'] == source['ref']
    projected['disclosures'] = [fragment(source,0,len(source['text']))]
    engine._visible_choices('u',context,projected,[old['ref']])
    assert projected['reflection_control']['required_actions'][0]['material_ready']
    assert not projected['reflection_control']['last_gate_error']['missing']


def test_review_can_clear_unsupported_event_date_and_sees_source_timestamp():
    item = {'ref':'new:campaign','kind':'fact','text':'Maya is campaigning.', 'source_refs':['raw:a'],
        'time_expression':'so far','time_start':'2023-01-01','time_end':'2023-01-01'}
    working = [{'ref':'raw:a','text':'Speaker: Maya\nI am campaigning.', 'source_time':1672531200,'role':'user'}]
    payload = review_payload({'items':[item]}, {}, working)
    assert payload['sources'][0]['source_time'] == 1672531200
    output = {'reviews':[{'position':0,'action':'revise','text':item['text'],'source_positions':[0],
        'detail':'Timestamp dates the message, not the whole activity.',
        'time':dict(time_expression=None,time_start=None,time_end=None)}]}
    edits,_=check_review(payload,output)
    assert edits[0]['after']['time_start'] is None and edits[0]['after']['time_end'] is None
