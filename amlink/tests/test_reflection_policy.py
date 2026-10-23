from dataclasses import replace
import pytest
from test_core_repairs import make, request
from amlink.errors import MemoryError
from amlink.schemas import SearchRequest
from amlink.reflection_policy import plan_prefix
from amlink.config import Config


def test_multiple_message_add_accumulates_and_search_leaves_tail(make):
    engine, provider = make(reflection_min_adds=2)
    engine.add(request('first', ['I am now reading. I never liked rain.'] * 12))
    assert not provider.calls
    assert engine.store.state('u')['settled_through'] == 0
    engine.search(SearchRequest(user_id='u', query='reading', top_k=5))
    assert engine.store.state('u')['settled_through'] == 0
    engine.add(request('second', ['The notebook is blue.']))
    assert engine.store.state('u')['settled_through'] == 13


def test_boundary_only_consumes_previous_contiguous_session(make):
    engine, provider = make(reflection_min_adds=2, reflection_threshold=100)
    for rid, session in [('one','A'), ('two','B'), ('three','A')]:
        req = request(rid, [f'Note in {session}'])
        engine.add(req.model_copy(update={'session_id': session}))
    assert engine.store.state('u')['settled_through'] == 2
    assert [r['ordinal'] for r in engine.store.raw('u', pending=True)] == [3]
    assert engine.store.request('u', 'two')['reflection_watermark'] == 1


def test_failed_retry_keeps_promised_watermark_after_later_add(make):
    engine, provider = make(reflection_min_adds=2, reflection_threshold=2)
    engine.add(request('a', ['A note']))
    provider.decide = lambda *a: (_ for _ in ()).throw(MemoryError('provider_timeout', 504))
    req = request('b', ['Another note'])
    with pytest.raises(MemoryError):
        engine.add(req)
    assert engine.store.request('u','b')['reflection_watermark'] == 2
    # A subsequent accepted request is not silently adopted by this retry.
    engine.config = replace(engine.config, mode='raw')
    engine.add(request('c', ['Later note']))
    engine.config = replace(engine.config, mode='graph')
    provider.decide = lambda *a: ('reflection_stop', {})
    engine.add(req)
    assert engine.store.state('u')['settled_through'] == 2
    assert [r['ordinal'] for r in engine.store.raw('u', pending=True)] == [3]


def test_single_add_capacity_and_noninstruction_forget():
    rows = [dict(ordinal=i+1, request_id='a', session_id='s', role='user', text='I forgot my umbrella. now never.') for i in range(64)]
    assert not plan_prefix(rows[:12], 12, 0, 0, Config())['trigger']
    assert plan_prefix(rows,64,0,0,Config())['reasons'] == ['capacity']
