from dataclasses import replace
from test_core_repairs import make, request
from amlink.packing import freeze_pack, pack_frozen, restrict_frozen
from amlink.schemas import SearchRequest
from amlink.errors import MemoryError
import pytest


def test_graph_support_stays_with_root_before_unrelated_candidate(make):
    engine, provider = make(mode='raw', search_model=True, search_steps=4)
    for i,text in enumerate(['Orchid is the meeting venue.', 'Orchid is also a flower.', 'The venue is in Florence.']):
        engine.add(request(str(i),[text]))
    sources = engine.store.raw('u')
    nodes = [dict(ref='memory:fact-a',kind='fact',text='Orchid venue',source_refs=[sources[0]['ref']]),
             dict(ref='memory:fact-b',kind='fact',text='Orchid flower',source_refs=[sources[1]['ref']]),
             dict(ref='memory:entity-c',kind='entity',text='Venue in Florence',source_refs=[sources[2]['ref']])]
    edge = dict(from_ref=nodes[0]['ref'],to_ref=nodes[2]['ref'],relation='about',source_refs=[sources[2]['ref']])
    engine.store.commit_mutation('u', {'items':nodes,'links':[edge],'forget':[]},watermark=3,fingerprint='x',vectors={})
    engine._search_refs = lambda *a,**k: [engine.store.get('u',n['ref']) for n in nodes[:2]]
    engine.config = replace(engine.config,mode='graph')
    actions = iter([nodes[0]['ref'],nodes[2]['ref'],None])
    def decide(purpose,payload):
        ref=next(actions)
        if ref is None:
            return 'bfs_action',{'action':'stop'}
        return 'bfs_action',{'action':'inspect','frontier_position':next(v['position'] for v in payload['context']['choices'] if v['ref']==ref)}
    provider.decide=decide
    result=engine.search(SearchRequest(user_id='u',query='Orchid venue',top_k=2))['data']
    assert 'Florence' in result[0]['content'] and '--about-->' in result[0]['content']
    assert result[0]['id']==nodes[0]['ref']
    assert len(result)<=2


def test_pack_partial_is_reported_and_offline_choices_cannot_invent(make):
    engine, _=make(mode='raw')
    engine.add(request('a',['Alpha '*600,'Beta '*600]))
    frozen=freeze_pack(engine.store,'u','Alpha Beta',engine.store.nodes('u'),{},engine.config)
    frozen['result_chars']=500
    frozen['context_chars']=500
    rows,audit=pack_frozen(frozen,1)
    assert sum(len(r['content']) for r in rows)<=500
    assert not rows or audit['decisions'][0]['closure']=='partial'
    with pytest.raises(MemoryError):
        restrict_frozen(frozen,{'groups':[{'position':0,'fragment_positions':[999]}]})


def test_conflict_group_keeps_both_sides_and_edge_provenance(make):
    engine,_=make(mode='raw')
    for i,text in enumerate(['Quota was 1000 daily.','Quota changed to 1200 daily.']):
        engine.add(request(str(i),[text]))
    sources=engine.store.raw('u')
    old=dict(ref='memory:fact-old',kind='fact',text='Quota 1000.',source_refs=[sources[0]['ref']])
    new=dict(ref='memory:fact-new',kind='fact',text='Quota 1200.',source_refs=[sources[1]['ref']])
    edge=dict(from_ref=new['ref'],to_ref=old['ref'],relation='supersedes',source_refs=[sources[1]['ref']])
    engine.store.commit_mutation('u',{'items':[old,new],'links':[edge],'forget':[]},watermark=2,fingerprint='x',vectors={})
    context={'query_roots':[new['ref']], 'paths':[{'from_ref':new['ref'],'to_ref':old['ref'], 'action':'inspect', 'edges':[edge]}]}
    frozen=freeze_pack(engine.store,'u','current quota',[new,old],context,engine.config)
    rows,audit=pack_frozen(frozen,1)
    assert '1000' in rows[0]['content'] and '1200' in rows[0]['content']
    assert 'superseded' in rows[0]['content']
    assert audit['decisions'][0]['path_closed']
