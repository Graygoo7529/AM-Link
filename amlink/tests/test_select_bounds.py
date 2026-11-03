"""Approved Select bounds: real menus, schema validation, and retained postchecks."""
import json
import time

import pytest
from jsonschema import Draft202012Validator

from amlink.errors import MemoryError
from amlink.schemas import SearchRequest
from amlink.tool_contract import parse_tool
from amlink.tests.test_clean_core import build, request


def capture(build, count=5, unread=0, final=False):
    engine, provider, store=build()
    if count:
        engine.add(request(messages=[{'role':'user','content':f'Observation {i}.'} for i in range(count)]))
    rows=[r for r in store.corpus('u') if r['kind']=='episode']
    schemas=[]
    name='finalize_evidence' if final else 'select_memory'
    def respond(content,schema):
        schemas.append(schema)
        return {'positions':[],**({} if final else {'queries':[],'read_more':[]})}
    provider.script[name]=respond
    engine._select(SearchRequest(query='What was observed?',user_id='u',top_k=10),
                   rows[:count-unread],time.monotonic()+30,final,
                   unread=rows[count-unread:])
    return engine,provider,rows,schemas[0]


@pytest.mark.parametrize('count,unread,final',[(0,0,False),(0,0,True),(1,0,False),
                                             (5,2,False),(5,0,True),(26,2,False)])
def test_schema_tracks_actual_read_and_unread_menu(build,count,unread,final):
    _,_,_,schema=capture(build,count,unread,final)
    Draft202012Validator.check_schema(schema)
    props=schema['properties']
    for name in ('positions',) if final else ('positions','read_more'):
        if count:
            assert props[name]['items']['type']=='integer'
            assert props[name]['items']['enum']==list(range(1,count+1))
            assert f'1 to {count}.' in props[name]['items']['description']
            assert 'THIS call' in props[name]['items']['description']
        else:
            assert props[name]['maxItems']==0
    if not final:
        assert props['queries']['maxItems']==2
        assert props['read_more']['maxItems']==(4 if count else 0)
    valid={'positions':([count,1] if count>1 else list(range(1,count+1)))}
    if not final:valid.update(queries=['first missing fact','second missing fact'],read_more=list(range(1,min(4,count)+1)))
    assert Draft202012Validator(schema).is_valid(valid)
    empty={'positions':[],**({} if final else {'queries':[],'read_more':[]})}
    assert Draft202012Validator(schema).is_valid(empty)
    for values in ([0],[count+1]):
        assert not Draft202012Validator(schema).is_valid(empty|{'positions':values})
        if not final:
            assert not Draft202012Validator(schema).is_valid(empty|{'read_more':values})


@pytest.mark.parametrize('change',[{'positions':[0]},{'positions':[6]},
    {'queries':['one','two','three']},{'read_more':[0]},
    {'read_more':[6]},{'read_more':[1,2,3,4,5]}])
def test_provider_parser_rejects_out_of_contract_tool_returns(build,change):
    _,_,_,schema=capture(build)
    arguments={'positions':[],'queries':[],'read_more':[]}|change
    response={'choices':[{'finish_reason':'stop','message':{'tool_calls':[
        {'id':'synthetic-call','type':'function','function':{'name':'select_memory','arguments':json.dumps(arguments)}}]}}]}
    with pytest.raises(MemoryError,match='model_tool_schema_invalid'):
        parse_tool(response,[{'name':'select_memory','parameters':schema}])


@pytest.mark.parametrize('change,code',[
    ({'positions':[0]},'selection_positions_invalid'),
    ({'positions':[6]},'selection_positions_invalid'),
    ({'positions':[1,1]},'selection_positions_invalid'),
    ({'queries':['one','two','three']},'selection_queries_invalid'),
    ({'queries':[' ']},'selection_queries_invalid'),
    ({'queries':['x'*301]},'selection_queries_invalid'),
    ({'read_more':[0]},'selection_read_more_invalid'),
    ({'read_more':[1,1]},'selection_read_more_invalid'),
    ({'read_more':[1,2,3,4,5]},'selection_read_more_invalid'),
])
def test_postchecks_remain_when_provider_ignores_schema(build,change,code):
    engine,provider,rows,_=capture(build)
    before=len(provider.calls)
    provider.script['select_memory']=lambda content,schema:{'positions':[],'queries':[],'read_more':[]}|change
    with pytest.raises(MemoryError,match=code):
        engine._select(SearchRequest(query='What was observed?',user_id='u',top_k=10),rows,time.monotonic()+30,False)
    assert len(provider.calls)==before+1  # No retry or coercion of invalid output.


def test_final_pass_recomputes_bounds_for_its_own_menu(build):
    engine,provider,rows,first=capture(build,5,2)
    captured=[]
    def final(content,schema):
        captured.append(schema)
        return {'positions':[2,1]}
    provider.script['finalize_evidence']=final
    chosen,queries,actions,_=engine._select(SearchRequest(query='Observed facts?',user_id='u',top_k=10),
        rows[:2],time.monotonic()+30,True)
    assert first['properties']['positions']['items']['enum']==[1,2,3,4,5]
    assert captured[0]['properties']['positions']['items']['enum']==[1,2]
    assert len(chosen)==2 and queries==[] and actions==[]


@pytest.mark.parametrize('count,final',[(0,False),(0,True),(2,False),(2,True),(26,False)])
def test_schema_summary_uses_current_bounds_without_repeating_enumeration(build,count,final):
    _,_,_,schema=capture(build,count,final=final)
    assert (f'labels 1 to {count} only' if count else 'menu is empty') in schema['description']
    if final:
        assert 'queries' not in schema['description'] and 'read_more' not in schema['description']
    else:
        assert 'queries <= 2; read_more <= 4' in schema['description']
    assert len(schema['description'])<200
