import time
import pytest
from dataclasses import replace
from amlink import reading
from amlink.config import Config
from amlink.engine import Engine
from amlink.errors import MemoryError
from amlink.store import Store
from amlink.tests.test_clean_core import build, request, search, Fake


def episodes(store):return [r for r in store.corpus('u') if r['kind']=='episode']


def test_message_neighbors_do_not_depend_on_add_packet(build):
    e,_,s=build();f,_,t=build()
    e.add(request(messages=[{'role':'user','content':'Maya visited Paris.'},{'role':'assistant','content':'She stayed two days.'}]))
    f.add(request('a','Maya visited Paris.'))
    f.add(request('b',messages=[{'role':'assistant','content':'She stayed two days.'}]))
    a=sorted(episodes(s),key=lambda r:r['sequence']);b=sorted(episodes(t),key=lambda r:r['sequence'])
    assert [r['text'] for r in reading.nearby(a[0],a)]==[r['text'] for r in reading.nearby(b[0],b)]==['She stayed two days.']


def test_continuation_only_reaches_immediate_ranges(build):
    e,_,s=build();e.add(request(text=('Long neutral original sentence. '*250)))
    rows=sorted(episodes(s),key=lambda r:r['start'])
    assert len(rows)>3
    assert [r['ref'] for r in reading.nearby(rows[0],rows)]==[rows[1]['ref']]
    assert ''.join(r['text'] for r in rows)==('Long neutral original sentence. '*250)


def test_heading_survives_continuation_and_index_byte_limit(build):
    e,p,s=build()
    text='# First event\n'+('An old observation. '*100)+'\n# Second event\n'+('A later observation. '*180)
    e.add(request(text=text))
    rows=sorted(episodes(s),key=lambda r:r['start'])
    assert ''.join(r['text'] for r in rows)==text
    tail=rows[-1]
    assert tail['anchor']['text']=='# Second event'
    assert '# Second event' in reading.index_text(tail)
    assert all(len(t.encode('utf-8'))<=6000 for n,ts in p.calls if n=='embed' for t in ts)


def test_navigation_does_not_take_all_primary_slots(build):
    e,_,s=build(candidate_limit=2)
    for i in range(5):e.add(request(str(i),f'Original event {i}.',session=str(i)))
    rows=episodes(s)
    note={'ref':'memory:note/topic','kind':'note','title':'Broad topic','support_refs':[r['ref'] for r in rows[:4]],'score':1.0}
    ranked=[note,rows[4]|{'score':.5}]
    offered,_=e._disclose(ranked,rows+[note])
    assert [r['ref'] for r in offered[:2]]==[rows[0]['ref'],rows[4]['ref']]
    assert offered[0]['score']==0 and offered[0]['routes'][0]['kind']=='note'


def test_old_note_search_scope_excludes_current_original_competition(build):
    e,p,s=build(reflection_batch=2)
    e.add(request('a','Orchid project shipped.'));e.add(request('b','Orchid project completed.'))
    p.script['organize_memory']=lambda c,sc:{'notes':[]}
    e.add(request('c','Paris trip report.'));e.add(request('d','Paris memories.'))
    content=[c for n,c in p.calls if n=='organize_memory'][-1]
    assert 'Prior navigation notes (read-only, not new sources):\nParis trip: Maya visited Paris.' in content


def test_select_units_copy_originals_and_group_in_source_order(build):
    e,p,s=build();text='First fact. '+('Detail '*80)+'.\n\nSecond fact. '+('Other '*90)+'.\n\nThird fact. '+('Final '*90)+'.';e.add(request(text=text))
    p.script['select_memory']=lambda c,sc:{'positions':[3,1],'queries':[]}
    result=search(e)
    assert len(result)==1 and 'First fact. ' in result[0]['content'] and 'Third fact.' in result[0]['content']
    assert result[0]['content'].index('First fact. ',result[0]['content'].index('Selected original')) < result[0]['content'].index('Third fact.',result[0]['content'].index('Selected original'))
    assert '[unselected original text between ranges]' in result[0]['content']


def test_reading_units_keep_list_labels_and_short_context_together(build):
    e,_,s=build();e.add(request(text='1. A reported fact. It remains uncertain.\n2. A different fact.'))
    row=episodes(s)[0];units=reading.units(row)
    assert len(units)==1 and units[0]['text']==row['text']
    fine=reading.sentence_units(row)
    assert all(u['text'].strip() not in {'1.','2.'} for u in fine)
    _,content,_=e._menu([row])
    assert 'Original passage\n' in content and 'Passage 1' not in content


def test_empty_original_anchor_cannot_claim_a_nonempty_quote(build):
    e,_,s=build();e.add(request(text='\n\nThe surviving original statement.'))
    row=episodes(s)[0]
    assert row['anchor']['text']==''
    assert 'Original opening [0,0)' not in reading.header(row)
    assert 'The surviving original statement.' in reading.render_group(reading.units(row),1)


def test_pack_can_keep_later_short_unit_when_large_unit_does_not_fit(build):
    e,_,s=build();e.add(request(text='A'*1200+'.\n\nEssential short fact.'))
    offered=reading.units(episodes(s)[0]);budget=500
    data,omitted=reading.pack(offered,10,budget)
    assert any('Essential short fact.' in r['content'] for r in data)
    assert omitted and sum(len(r['content']) for r in data)<=budget


def test_read_more_with_no_unread_material_does_not_repeat_select(build):
    e,p,s=build()
    e.add(request('a','Known name.'));e.add(request('b','A neighboring statement.'))
    p.script['select_memory']=lambda c,sc:{'positions':[1],'queries':[],'read_more':[1]}
    search(e)
    assert sum(n=='finalize_evidence' for n,_ in p.calls)==0
    assert sum(n=='select_memory' for n,_ in p.calls)==1


def test_new_candidates_share_menu_with_carry_instead_of_blocking(build):
    e,_,s=build()
    for i in range(3):e.add(request(str(i),f'Independent original {i}.',session=str(i)))
    rows=episodes(s)
    menu,content,_=e._menu([rows[-1]],reading.units(rows[0])+reading.units(rows[1]))
    assert {u['row']['ref'] for u in menu}=={r['ref'] for r in rows}


@pytest.mark.parametrize('positions',[[True],[0],[999],[1,1],[{}]])
def test_invalid_selected_units_are_protocol_errors(build,positions):
    e,p,s=build();e.add(request())
    p.script['select_memory']=lambda c,sc:{'positions':positions,'queries':[]}
    with pytest.raises(MemoryError,match='selection_positions_invalid'):search(e)


def test_forget_confirmation_survives_restart_and_preserves_unrelated_sentence(tmp_path):
    cfg=Config(db_path=str(tmp_path/'confirmation.sqlite3'))
    p=Fake();s=Store(cfg.db_path);e=Engine(cfg,s,p)
    e.add(request('a','I visit the library weekly.'))
    e.add(request('b','Forget my library habit.'));s.close()
    p=Fake();p.script['forget_confirmation']=lambda c,sc:{'positions':[1]}
    s=Store(cfg.db_path);e=Engine(cfg,s,p)
    ack=request('c',messages=[{'role':'assistant','content':'I will forget your weekly library habit. General libraries offer public resources.'}])
    e.add(ack);calls=len(p.calls)
    assert e.add(ack)['success'] and len(p.calls)==calls
    result=search(e,'library')
    assert all('weekly' not in r['content'] for r in result)
    assert any('General libraries offer public resources.' in r['content'] for r in result)
    e.add(request('d','I now visit a new library on Fridays.'))
    assert s.confirmation('u') is None
    assert any('Fridays' in r['text'] for r in s.corpus('u'))
    s.close()


def test_confirmation_failure_and_index_failure_leave_state_and_receipt_unmodified(build):
    e,p,s=build();e.add(request('a','Forget my old preference.'))
    old=s.confirmation('u')
    ack=request('b',messages=[{'role':'assistant','content':'I will forget that preference.'}])
    p.fail_tool='forget_confirmation'
    with pytest.raises(MemoryError):e.add(ack)
    assert s.confirmation('u')==old and s.replay(ack) is None
    p.fail_tool=None;p.fail_embed=True
    fresh=request('c','A newly stated preference.')
    with pytest.raises(MemoryError):e.add(fresh)
    assert s.confirmation('u')==old and s.replay(fresh) is None
