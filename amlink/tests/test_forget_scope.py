import pytest
from test_core_repairs import make, request
from amlink.errors import MemoryError
from amlink.intake import explicit_all_memory
from amlink.schemas import SearchRequest


def install_scope(provider, *, reject=False, malformed=False):
    original=provider.tool
    def tool(purpose,prompt,payload,tools,deadline):
        if purpose=='forget_intent':
            source=next(s for s in payload['messages'] if s['text'].startswith('Please forget'))
            return purpose,{'requests':[{'instruction_ref':source['ref'],'instruction_quote':source['text'],
                                        'all_memory':False}]}
        if purpose=='forget_scope':
            row=next(s for s in payload['sources'] if 'secret code is orchid' in s['text'])
            return purpose,{'matches':None if malformed else [{'position':row['position'], 'reason':'The same secret code.'}]}
        if purpose=='forget_verify':
            assert 'proposed_matches' not in payload
            assert len(payload['sources'])==1 and 'My secret code is orchid.' in payload['sources'][0]['text']
            return purpose,{'matches':not reject,'evidence_quote':None if reject else 'My secret code is orchid.',
                'reason':'The proposed topic does not match.' if reject else 'Same subject and secret code.'}
        return original(purpose,prompt,payload,tools,deadline)
    provider.tool=tool


def test_forget_preserves_unrelated_messages_in_old_and_new_episodes(make):
    engine,provider=make(mode='raw',search_model=False,embedding_enabled=True)
    engine.add(request('old',['My secret code is orchid.','My bicycle is blue.']))
    original=engine.store.request('u','old')['episode_ref'];body=engine.store.get('u',original)['text']
    install_scope(provider)
    engine.add(request('delete',['Please forget my secret code.','I prefer green tea.']))
    old=engine.store.get('u',original,include_blocked=True)
    assert old['text']==body and old['status']=='tombstoned'
    active=engine.store.nodes('u')
    assert len(active)==2 and all('orchid' not in n['text'] and 'Please forget' not in n['text'] for n in active)
    assert any('blue' in n['text'] for n in active) and any('green tea' in n['text'] for n in active)
    results=engine.search(SearchRequest(user_id='u',query='bicycle green tea',top_k=10))['data']
    assert 'blue' in str(results) and 'green tea' in str(results) and 'orchid' not in str(results)
    assert all(engine.store.rows('select 1 from vectors where ref=?',(n['ref'],)) for n in active)


def test_same_add_forgets_only_information_before_instruction(make):
    engine,provider=make(mode='raw',search_model=False);install_scope(provider)
    engine.add(request('batch',['My secret code is orchid.','Please forget my secret code.',
                                'My new secret code is tulip.']))
    assert [s['text'] for s in engine.store.raw('u')]==['My new secret code is tulip.']
    assert 'tulip' in engine.store.nodes('u')[0]['text']


def test_invalid_scope_list_rolls_back_add(make):
    engine,provider=make(mode='raw');engine.add(request('old',['My secret code is orchid.']))
    install_scope(provider,malformed=True)
    with pytest.raises(MemoryError,match='forget_scope_invalid'):
        engine.add(request('delete',['Please forget my secret code.']))
    assert engine.store.request('u','delete') is None
    assert not engine.store.rows('select * from blocks') and len(engine.store.raw('u'))==1


def test_correspondence_can_reject_selection_without_removing_original(make):
    engine,provider=make(mode='raw');engine.add(request('old',['My secret code is orchid.']))
    install_scope(provider,reject=True)
    engine.add(request('delete',['Please forget my secret code.']))
    assert [s['text'] for s in engine.store.raw('u')]==['My secret code is orchid.']
    assert len(engine.store.nodes('u'))==1


def test_retained_episode_embedding_failure_is_atomic(make):
    engine,provider=make(mode='raw',embedding_enabled=True);engine.add(request('old',['My secret code is orchid.','My bicycle is blue.']))
    install_scope(provider);original=provider.embed
    def embed(texts,deadline):
        if any('bicycle' in text for text in texts):raise MemoryError('provider_timeout',504)
        return original(texts,deadline)
    provider.embed=embed
    with pytest.raises(MemoryError,match='provider_timeout'):
        engine.add(request('delete',['Please forget my secret code.']))
    assert engine.store.request('u','delete') is None
    assert not engine.store.rows('select * from blocks')
    assert len(engine.store.nodes('u'))==1 and len(engine.store.raw('u'))==2


def test_forget_discovery_preserves_literal_topic_without_generated_question(make):
    engine,provider=make(mode='raw');engine.add(request('old',['My secret code is orchid.']))
    install_scope(provider)
    search=engine._search_refs;queries=[]
    def capture(user,query,*args,**kwargs):
        queries.append(query)
        return search(user,query,*args,**kwargs)
    engine._search_refs=capture
    engine.add(request('delete',['Please forget my secret code.']))
    assert queries and all('Please forget my secret code.' in q for q in queries)
    assert not engine.store.raw('u')


def test_scope_outside_source_position_is_rejected_without_partial_deletion(make):
    engine,provider=make(mode='raw');engine.add(request('old',['My secret code is orchid.','My bicycle is blue.']))
    install_scope(provider);original=provider.tool
    def tool(purpose,*args):
        name,result=original(purpose,*args)
        if purpose=='forget_scope':result['matches'][0]['position']=999
        return name,result
    provider.tool=tool
    with pytest.raises(MemoryError,match='forget_scope_evidence_invalid'):
        engine.add(request('delete',['Please forget my secret code.']))
    assert engine.store.request('u','delete') is None
    assert not engine.store.rows('select * from blocks') and len(engine.store.raw('u'))==2


def test_single_source_verification_cannot_quote_a_nearby_paraphrase(make):
    engine,provider=make(mode='raw');engine.add(request('old',['My secret code is orchid.','My bicycle is blue.']))
    install_scope(provider);original=provider.tool
    def tool(purpose,*args):
        name,result=original(purpose,*args)
        if purpose=='forget_verify':result['evidence_quote']='My code is an orchid.'
        return name,result
    provider.tool=tool
    with pytest.raises(MemoryError,match='forget_verification_invalid'):
        engine.add(request('delete',['Please forget my secret code.']))
    assert engine.store.request('u','delete') is None
    assert not engine.store.rows('select * from blocks') and len(engine.store.raw('u'))==2


@pytest.mark.parametrize('quote,expected',[
    ('Please forget everything.',True),('Delete all my memories.',True),('请删除所有记忆。',True),
    ('Please forget all my addresses.',False),('Please forget my secret code.',False),
    ('Please forget everything about my old address.',False),('请删除所有记忆中关于旧地址的部分。',False)])
def test_all_memory_requires_explicit_global_scope(quote,expected):
    assert explicit_all_memory(quote)==expected
