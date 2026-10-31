import re
import pytest
from amlink import reading
from amlink.errors import MemoryError
from amlink.tests.test_clean_core import build,request,search


def test_local_reference_does_not_expose_ingestion_or_offsets(build):
    e,p,s=build(reflection_batch=2)
    e.add(request('a','A name is not a relationship.'))
    e.add(request('b','Mira is a relative of Lea.'))
    content=next(c for n,c in p.calls if n=='organize_memory')
    assert 'Passage 1' in content and 'Passage 2' in content
    assert 'Source order' not in content and 'memory:episode/' not in content
    assert 'Original [' not in content
    assert 'Mira is a relative of Lea.' in content
    result=search(e)
    assert all('Source order' not in r['content'] and 'Selected original ranges' not in r['content'] for r in result)


def test_short_paragraphs_preserve_verbatim_text_and_boundaries():
    text='# Section\nComment.\n\nReply\n\nShare\n\nAnother comment.\n\n# Next\nDifferent matter.'
    row={'text':text,'start':100}
    units=reading.units(row)
    assert len(units)==2
    assert ''.join(u['text'] for u in units)==text
    for u in units:assert u['text']==text[u['start']-100:u['end']-100]


def test_context_closure_keeps_antecedent_for_short_answer():
    text='# Question\nWhat did I watch?\n\n# Reply\nYes, I watched it with her.'
    row={'ref':'memory:episode/test','text':text,'start':0,'end':len(text),
         'role':'user','sources':['source:test'],'time':0}
    units=reading.units(row)
    assert len(units)==2
    selected,additions=reading.context_closure([units[1]])
    assert [u['text'].strip() for u in additions]==['# Question\nWhat did I watch?']
    assert {reading.unit_key(u) for u in selected}=={reading.unit_key(units[0]),reading.unit_key(units[1])}
    assert additions[0]['selection_reason']=='context_closure'


def test_context_closure_never_crosses_episode():
    text='Yes, I watched it.'
    row={'ref':'memory:episode/second','text':text,'start':0,'end':len(text),
         'role':'user','sources':['source:second'],'time':0}
    selected,additions=reading.context_closure([reading.units(row)[0]])
    assert additions==[] and len(selected)==1


def test_context_closure_uses_only_disclosed_immediate_previous_episode():
    previous_text='What did I watch?'
    current_text='Yes, I watched it.'
    previous={'ref':'memory:episode/previous','text':previous_text,'start':0,'end':len(previous_text),
              'role':'user','sources':['source:previous'],'session_id':'s','sequence':1,
              'kind':'episode','time':0}
    current={'ref':'memory:episode/current','text':current_text,'start':0,'end':len(current_text),
             'role':'assistant','sources':['source:current'],'session_id':'s','sequence':2,
             'kind':'episode','time':0}
    selected,additions=reading.context_closure([reading.units(current)[0]],[previous,current])
    assert [u['text'] for u in additions]==[previous_text]
    assert additions[0]['closure_scope']=='adjacent_episode'


def test_unread_preview_opens_new_original_and_keeps_prior_evidence(build):
    e,p,s=build(candidate_limit=1)
    e.add(request('a','Known purchase: a pump for 18.',session='first'))
    e.add(request('b','Another purchase: a lamp for 37.',session='second'))
    rows=[r for r in s.corpus('u') if r['kind']=='episode']
    e._query=lambda q,c,d,**kwargs:[r|{'score':1-i*.1} for i,r in enumerate(rows)]
    def first(content,schema):
        n=int(re.search(r'\[(\d+)\] UNREAD preview',content)[1])
        return {'positions':[1],'queries':[],'read_more':[n]}
    p.script['select_memory']=first
    result=search(e,'What did I purchase?')
    assert any('18' in r['content'] for r in result)
    assert any('37' in r['content'] for r in result)
    assert sum(n=='finalize_evidence' for n,_ in p.calls)==1
    final=next(c for n,c in p.calls if n=='finalize_evidence')
    assert 'UNREAD preview' not in final


def test_selected_preview_must_be_opened_and_finalized_before_delivery(build):
    e,p,s=build(candidate_limit=1)
    for i in range(3):e.add(request(str(i),f'Private fact {i}.',session=str(i)))
    rows=[r for r in s.corpus('u') if r['kind']=='episode']
    e._query=lambda q,c,d,**kwargs:[r|{'score':1} for r in rows]
    p.script['select_memory']=lambda c,sc:{'positions':[int(re.search(r'\[(\d+)\] UNREAD preview',c)[1])],'queries':[]}
    p.script['finalize_evidence']=lambda c,sc:{'positions':[]}
    assert search(e)==[]
    assert sum(n=='finalize_evidence' for n,_ in p.calls)==1


def test_identical_query_and_already_read_neighbors_add_no_model_call(build):
    e,p,s=build();e.add(request())
    p.script['select_memory']=lambda c,sc:{'positions':[1],'queries':['Paris','Paris'],'read_more':[1]}
    search(e,'Paris')
    assert sum(n=='finalize_evidence' for n,_ in p.calls)==0
    assert sum(n=='embed' for n,_ in p.calls)==2 # intake + one question


def test_second_pass_excludes_read_unselected_blocks_and_keeps_selected(build):
    e,p,s=build();e.add(request(text='First. '+('A sentence. '*45)+'\n\nSecond. '+('B sentence. '*45)))
    row=next(r for r in s.corpus('u') if r['kind']=='episode');units=reading.units(row)
    menu,_,_=e._menu([row],carry=[units[0]],exclude={reading.unit_key(u) for u in units})
    assert [reading.unit_key(u) for u in menu]==[reading.unit_key(units[0])]
