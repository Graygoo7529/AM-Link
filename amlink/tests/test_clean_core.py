import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from amlink.config import Config
from amlink.engine import Engine
from amlink.errors import MemoryError
from amlink.providers import Providers, object_schema
from amlink.schemas import AddRequest, SearchRequest
from amlink.store import Store
from amlink.text import byte_chunks, digest, tokens

def request(rid='a',text='Maya visited Paris.',user='u',session='s',messages=None):
    return AddRequest(request_id=rid,user_id=user,session_id=session,
                      messages=messages or [{'role':'user','content':text,'timestamp':1683554160000}])

class Fake:
    embedding_fingerprint='fake-v4:1024'
    def __init__(self):
        self.calls=[]; self.fail_embed=False; self.fail_tool=None; self.script={}
    def embed(self,texts,deadline):
        self.calls.append(('embed',texts))
        if self.fail_embed:
            raise MemoryError('provider_network',502)
        vectors=[]
        for text in texts:
            v=[0.0]*1024
            for token in tokens(text):
                v[int(digest(token)[:8],16)%1024]+=1
            norm=sum(x*x for x in v)**.5 or 1
            vectors.append([x/norm for x in v])
        return vectors
    def tool(self,name,prompt,content,schema,deadline):
        self.calls.append((name,content))
        if self.fail_tool==name:
            raise MemoryError('model_tool_schema_invalid',502)
        if name in self.script:
            result=self.script[name](content,schema)
            if name=='select_memory':result.setdefault('read_more',[])
            return result
        if name=='organize_memory':
            return {'notes':[{'title':'Paris trip','text':'Maya visited Paris.','sources':[1]}]}
        if name in ('select_memory','finalize_evidence'):
            count=int(schema['properties']['positions']['description'].split('through ')[1].split(';')[0])
            return {'positions':list(range(1,count+1)),**({'queries':[],'read_more':[]} if 'queries' in schema['properties'] else {})}
        if name=='forget_intent':
            return {'action':'all' if 'all' in content.lower() else 'topic'}
        if name=='forget_scope':
            return {'positions':[1]}
        if name=='verify_forgetting':
            return {'matches':True}
        raise AssertionError(name)
    def close(self):
        pass

@pytest.fixture
def build(tmp_path):
    stores=[]
    def create(**overrides):
        cfg=replace(Config(),db_path=str(tmp_path/f'{len(stores)}.sqlite3'),**overrides)
        store=Store(cfg.db_path); stores.append(store); provider=Fake()
        return Engine(cfg,store,provider),provider,store
    yield create
    for store in stores:
        store.close()

def search(engine,q='Paris',user='u',top=10):
    return engine.search(SearchRequest(query=q,user_id=user,top_k=top))['data']

def test_atomic_intake_embedding_failure_and_explicit_redelivery(build):
    e,p,s=build(); p.fail_embed=True
    with pytest.raises(MemoryError,match='provider_network'): e.add(request())
    assert s.rows('SELECT * FROM requests')==[] and s.corpus('u')==[]
    p.fail_embed=False
    assert e.add(request())['success']
    assert 'Maya visited Paris' in search(e)[0]['content']

def test_idempotency_conflict_and_no_repeat_calls(build):
    e,p,s=build()
    first=e.add(request()); count=len(p.calls)
    assert e.add(request())==first and len(p.calls)==count
    with pytest.raises(MemoryError) as error: e.add(request(text='Different.'))
    assert error.value.status==422 and len(p.calls)==count

def test_receipt_survives_restart(tmp_path):
    cfg=Config(db_path=str(tmp_path/'restart.sqlite3'))
    p=Fake(); store=Store(cfg.db_path); e=Engine(cfg,store,p)
    response=e.add(request()); store.close()
    second=Store(cfg.db_path); q=Fake(); e=Engine(cfg,second,q)
    assert e.add(request())==response and q.calls==[]
    second.close()

def test_one_database_owner(tmp_path):
    s=Store(tmp_path/'single.sqlite3')
    with pytest.raises(MemoryError,match='database_already_owned'): Store(tmp_path/'single.sqlite3')
    s.close()

def test_legacy_db_rejected(tmp_path):
    import sqlite3
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db: db.execute('CREATE TABLE legacy(x)')
    with pytest.raises(MemoryError,match='incompatible_database'): Store(path)

def test_concurrent_replay_single_receipt(build):
    e,p,s=build()
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses=list(pool.map(lambda _:e.add(request()),range(4)))
    assert all(r==responses[0] for r in responses)
    assert len(s.active_sources('u'))==1
    assert len([c for c in p.calls if c[0]=='embed'])==1

def test_user_isolation(build):
    e,p,s=build()
    e.add(request(user='alice'))
    assert search(e,user='bob')==[]
    assert len(s.corpus('bob'))==0

def test_working_tail_is_already_searchable_without_reflection(build):
    e,p,s=build()
    e.add(request())
    assert search(e) and not any(name=='organize_memory' for name,_ in p.calls)
    assert s.stats('u')['working']==[{'state':'pending','count':1}]

def test_reflection_accumulates_and_returns_originals(build):
    e,p,s=build(reflection_batch=2)
    e.add(request('a')); assert not any(n=='organize_memory' for n,_ in p.calls)
    e.add(request('b','The trip was in June.'))
    assert any(n=='organize_memory' for n,_ in p.calls)
    assert any(r['kind']=='note' for r in s.corpus('u'))
    assert all('memory:episode/' in r['id'] for r in search(e))
    assert any('Maya visited Paris.' in r['content'] for r in search(e))


def test_reflection_drops_same_source_near_duplicate_notes(build):
    e,p,s=build(reflection_batch=1,reflection_min_adds=1)
    p.script['organize_memory']=lambda c,sc:{'notes':[
        {'title':'Paris trip','text':'Maya visited Paris in June.','sources':[1]},
        {'title':'Paris visit','text':'Maya visited Paris in June','sources':[1]},
    ]}
    e.add(request('a','Maya visited Paris in June.'))
    notes=[r for r in s.corpus('u') if r['kind']=='note']
    assert len(notes)==1


def test_select_prompt_exposes_question_evidence_shape(build):
    e,p,s=build()
    e.add(request(text='Yoga, painting, and swimming are my activities.'))
    search(e,'Besides yoga, what other activities do I have?')
    prompt=next(content for name,content in p.calls if name=='select_memory')
    assert 'distinct occurrences outside it' in prompt
    assert 'named topic is a boundary' in prompt

def test_failed_batch_does_not_block_or_retry_old_material(build):
    e,p,s=build(reflection_batch=2); p.fail_tool='organize_memory'
    e.add(request('a')); assert e.add(request('b','June trip.'))['success']
    assert len(s.rows("SELECT * FROM batches WHERE status='failed'"))==1
    p.fail_tool=None
    e.add(request('c','Tea preference.',session='next')); e.add(request('d','A blue cup.',session='next'))
    calls=[text for name,text in p.calls if name=='organize_memory']
    assert len(calls)==2 and 'June trip.' not in calls[-1]
    assert any('June trip.' in r['text'] for r in s.corpus('u'))

def test_bad_reflection_source_fails_batch_not_intake(build):
    e,p,s=build(reflection_batch=1,reflection_min_adds=1)
    p.script['organize_memory']=lambda c,s:{'notes':[{'title':'Wrong','text':'Wrong','sources':[99]}]}
    assert e.add(request())['success']
    assert [r['kind'] for r in s.corpus('u')]==['episode']
    assert s.rows('SELECT status FROM batches')[0]['status']=='failed'

@pytest.mark.parametrize('text',['中😀a'*3000,'abcdef '*2000,'尾部\n'*4000],ids=['unicode','english','lines'])
def test_lossless_unicode_chunking(text):
    chunks=byte_chunks(text)
    assert ''.join(chunks)==text
    assert all(len(c.encode('utf-8'))<=6000 for c in chunks)

def test_long_tail_retrieval_visible_and_not_truncated(build):
    e,p,s=build()
    text=('unrelated words '*600)+'TAIL-ORCHID amount 137.'
    e.add(request(text=text))
    assert ''.join(r['text'] for r in sorted(s.corpus('u'),key=lambda r:r['start']))==text
    result=search(e,'TAIL-ORCHID amount')
    assert 'TAIL-ORCHID amount 137.' in result[0]['content']

def test_search_failure_is_not_empty_success(build):
    e,p,s=build(); e.add(request()); p.fail_embed=True
    with pytest.raises(MemoryError,match='provider_network'): search(e)

def test_select_order_is_preserved(build):
    e,p,s=build(); e.add(request('a','Paris.')); e.add(request('b','Lyon.'))
    def select(content,schema):
        n=int(schema['properties']['positions']['description'].split('through ')[1].split(';')[0])
        return {'positions':list(range(n,0,-1)),'queries':[]}
    p.script['select_memory']=select
    result=search(e,'Paris or Lyon')
    shown=[c for n,c in p.calls if n=='select_memory'][-1]
    body=s.corpus('u');top=next(r for r in body if r['ref']==result[0]['id'])
    assert shown.index('[2]') < shown.index(top['text'],shown.index('[2]'))

def test_two_pass_search_from_observed_link(build):
    e,p,s=build(candidate_limit=1)
    e.add(request('a','Maya knows Rowan.',session='one'))
    e.add(request('b','Rowan lives in Ghent.',session='two'))
    rows=[r for r in s.corpus('u') if r['kind']=='episode']
    looked_up=[]
    def query(q,c,d):
        looked_up.append(q)
        return [next(r for r in rows if ('Ghent' if q=='Rowan lives' else 'Maya') in r['text'])|{'score':1}]
    e._query=query
    count=[0]
    def select(content,schema):
        count[0]+=1
        return {'positions':[1], 'queries':['Rowan lives'] if count[0]==1 else []}
    p.script['select_memory']=select
    search(e,'Where does the friend of Maya live?')
    assert count[0]==1 and sum(name=='finalize_evidence' for name,_ in p.calls)==1
    assert looked_up==['Where does the friend of Maya live?','Rowan lives']

def test_source_time_is_readable_and_unchanged(build):
    e,p,s=build(); e.add(request(text='I went yesterday.'))
    content=search(e,'yesterday')[0]['content']
    assert '2023-05-08T' in content and 'yesterday' in content

def test_forget_all_is_temporally_ordered_and_atomic(build):
    e,p,s=build()
    e.add(request('old','Blue notebook.'))
    e.add(request('change',messages=[
        {'role':'user','content':'Forget all prior memories.'},
        {'role':'user','content':'I now prefer black coffee.'}]))
    result=search(e,'notebook coffee')
    assert all('Blue notebook' not in r['content'] for r in result)
    assert any('black coffee' in r['content'] for r in result)

def test_forget_failure_rolls_back_request(build):
    e,p,s=build(); e.add(request('old','Secret code maple.'))
    p.fail_tool='forget_scope'
    with pytest.raises(MemoryError): e.add(request('forget','Forget my secret code.'))
    assert s.replay(request('forget','Forget my secret code.')) is None
    assert any('maple' in r['text'] for r in s.corpus('u'))

def test_noncommand_does_not_forget(build):
    e,p,s=build()
    e.add(request('a','I will never forget my family.'))
    assert not any(n.startswith('forget_') for n,_ in p.calls)

def test_native_without_credentials_refuses_silent_lexical_mode(tmp_path):
    from amlink.native import NativeTarget
    with pytest.raises(ValueError,match='credentials'):
        NativeTarget(Config(db_path=str(tmp_path/'never.sqlite3')))

def test_http_schema_auth_and_delivery(build):
    from amlink.api import create_app
    e,p,s=build(auth_scheme='bearer',api_key='test-secret')
    app=create_app(config=e.config,store=s,providers=p)
    with TestClient(app) as client:
        assert client.get('/health').status_code==200
        assert client.post('/v1/memory/add',json=request().model_dump()).status_code==401
        headers={'Authorization':'Bearer test-secret'}
        assert client.post('/v1/memory/add',json=request().model_dump(),headers=headers).status_code==200
        bad=client.post('/v1/memory/search',json={'user_id':'u','query':'Paris','top_k':True},headers=headers)
        assert bad.status_code==422

def test_protocol_rejects_length_wrong_tool_and_bad_schema():
    from amlink.tool_contract import parse_tool
    tool={'name':'x','parameters':object_schema({'positions':{'type':'array','items':{'type':'integer'}}})}
    base={'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'c','type':'function','function':{'name':'x','arguments':'{"positions":[1]}'}}]}}]}
    assert parse_tool(base,[tool]).arguments=={'positions':[1]}
    for mutate in ('length','tool','schema'):
        value=json.loads(json.dumps(base))
        if mutate=='length': value['choices'][0]['finish_reason']='length'
        if mutate=='tool': value['choices'][0]['message']['tool_calls'][0]['function']['name']='y'
        if mutate=='schema': value['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"positions":[true]}'
        with pytest.raises(MemoryError): parse_tool(value,[tool])

def test_provider_batches_ten_and_no_retry():
    bodies=[]
    def handler(req):
        body=json.loads(req.content); bodies.append(body)
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[1]+[0]*1023} for i,_ in enumerate(body['input'])],
                                       'usage':{'prompt_tokens':5}})
    p=Providers(Config(llm_api_key='test',embedding_api_key='test'),transport=httpx.MockTransport(handler))
    assert len(p.embed(['x']*21,time.monotonic()+10))==21
    assert [len(b['input']) for b in bodies]==[10,10,1] and p.calls==3
    p.close()
    p=Providers(Config(embedding_api_key='test'),transport=httpx.MockTransport(lambda req:httpx.Response(503)))
    with pytest.raises(MemoryError): p.embed(['x'],time.monotonic()+10)
    assert p.calls==1; p.close()

def test_native_observation_and_model_usage(tmp_path):
    from research.benchmark.instrumented import Artifacts,ObservedTarget
    from research.benchmark.observability import ObservationRecorder,validate_event
    from amlink.native import NativeTarget
    run=tmp_path/'run'; run.mkdir()
    with ObservationRecorder(run/'observability.jsonl',run_id='test',dataset_pack_sha256='a'*64) as recorder:
        artifacts=Artifacts(run)
        p=Fake()
        target=NativeTarget(Config(db_path=str(run/'memory.sqlite3')),recorder,artifacts,providers=p)
        wrapped=ObservedTarget(target,recorder,artifacts,'native')
        wrapped.set_observation_context(record_id='r',request_id='a',task_id=None)
        assert wrapped.add(request().model_dump()).status_code==200
        wrapped.set_observation_context(record_id='r',request_id='q',task_id='q')
        assert wrapped.search({'user_id':'u','query':'Paris','top_k':5}).status_code==200
        target.close()
    events=[json.loads(line) for line in (run/'observability.jsonl').read_text(encoding='utf-8').splitlines()]
    for event in events: validate_event(event)
    assert {'index','store','retrieve','select','context'} <= {e['operation'] for e in events}

def test_database_failure_rolls_back_receipt_and_originals(build):
    import sqlite3
    e,p,s=build()
    s.db.execute("CREATE TRIGGER reject_item BEFORE INSERT ON items BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError): e.add(request())
    assert s.replay(request()) is None and s.active_sources('u')==[]
    s.db.execute('DROP TRIGGER reject_item')
    assert e.add(request())['success']

def test_navigation_backlinks_only_expand_actual_support(build):
    e,p,s=build(reflection_batch=2)
    p.script['organize_memory']=lambda c,sc:{'notes':[{'title':'Meeting','text':'Maya knows Rowan in Ghent.','sources':[1,2]}]}
    e.add(request('a','Maya knows Rowan.')); e.add(request('b','Rowan lives in Ghent.'))
    corpus=s.corpus('u'); maya=next(r for r in corpus if r['kind']=='episode' and 'Maya' in r['text'])
    disclosed,_=e._disclose([maya|{'score':1.0}],corpus)
    assert len(disclosed)==2 and any('Ghent' in r['text'] for r in disclosed)

def test_note_is_never_delivered_as_fabricated_evidence(build):
    e,p,s=build(reflection_batch=2)
    p.script['organize_memory']=lambda c,sc:{'notes':[{'title':'Invented','text':'Maya owns a spaceship.','sources':[1]}]}
    e.add(request('a')); e.add(request('b','June trip.'))
    assert any('spaceship' in r['text'] for r in s.corpus('u'))
    assert all('spaceship' not in r['content'] for r in search(e,'spaceship'))

def test_empty_selection_is_valid_abstention(build):
    e,p,s=build(); e.add(request())
    p.script['select_memory']=lambda c,sc:{'positions':[],'queries':[]}
    assert search(e,'unknown')==[]

def test_model_observation_records_usage_and_redacts_key(tmp_path):
    from research.benchmark.instrumented import Artifacts
    from research.benchmark.observability import ObservationRecorder,validate_event
    from amlink.observation import Observer
    with ObservationRecorder(tmp_path/'events.jsonl',run_id='test',dataset_pack_sha256='a'*64) as recorder:
        observer=Observer(recorder,Artifacts(tmp_path))
        p=Providers(Config(embedding_api_key='secret-value'),observer,transport=httpx.MockTransport(
            lambda r:httpx.Response(200,json={'data':[{'index':0,'embedding':[1]+[0]*1023}],
                                            'usage':{'prompt_tokens':7}})))
        with recorder.span('add',name='test',record_id='r',task_id=None,request_id='a') as root:
            observer.bind(root); p.embed(['original'],time.monotonic()+10)
        p.close()
    events=[json.loads(l) for l in (tmp_path/'events.jsonl').read_text().splitlines()]
    for e in events: validate_event(e)
    model=next(e for e in events if e['operation']=='model')
    assert model['model']['input_tokens']==7 and model['status']=='ok'
    assert all('secret-value' not in f.read_text(encoding='utf-8') for f in tmp_path.rglob('*.json'))

def test_forget_candidate_requires_independent_same_subject_check(build):
    e,p,s=build(); e.add(request('a','A student left school.'))
    p.script['verify_forgetting']=lambda c,sc:{'matches':False}
    e.add(request('b','Please forget my friend dying.'))
    assert any('student left' in r['text'] for r in s.corpus('u'))
    assert sum(n=='verify_forgetting' for n,_ in p.calls)==1

def test_original_recorded_order_survives_across_adds(build):
    e,p,s=build(); e.add(request('a','Quota 1000.')); e.add(request('b','Quota 1200.'))
    rows=sorted((r for r in s.corpus('u') if r['kind']=='episode'),key=lambda r:r['sequence'])
    assert [r['text'] for r in rows]==['Quota 1000.','Quota 1200.']
    result=search(e,'quota')
    assert 'not an event date' in result[0]['content']
    earlier=next(r for r in result if 'Quota 1000.' in r['content'])
    later=next(r for r in result if 'Quota 1200.' in r['content'])
    assert 'Recorded before Evidence' in earlier['content'] and 'Latest of these' in later['content']
