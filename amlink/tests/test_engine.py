from dataclasses import replace

import pytest

from amlink.errors import MemoryError
from amlink.schemas import AddRequest, SearchRequest
from amlink.store import Store


def add(engine, *messages, user='u', session='s', rid='r'):
    return engine.add(AddRequest(request_id=rid, user_id=user, session_id=session,
        messages=[{'role': 'user', 'content': text} for text in messages]))


def search(engine, query, user='u', top_k=20):
    return engine.search(SearchRequest(user_id=user, query=query, top_k=top_k))['data']


def one_fact(purpose, data):
    source = next(s for s in data['sources'] if s['ref'] in data['new_refs'])
    return {'items': [{'ref': 'new:fact', 'kind': 'fact', 'text': source['text'],
                       'source_refs': [source['ref']]}]}


def graph_mutation(purpose, data):
    source = data['new_refs']
    return {'items': [
        {'ref': 'new:visit', 'kind': 'event', 'text': 'Zephyr visit to DrLark', 'source_refs': [source[0]]},
        {'ref': 'new:person', 'kind': 'person', 'text': 'DrLark', 'source_refs': [source[0]]},
        {'ref': 'new:job', 'kind': 'fact', 'text': 'Teaching appointment at Pine School', 'source_refs': [source[1]]}],
        'links': [
            {'from_ref': 'new:visit', 'to_ref': 'new:person', 'relation': 'about', 'source_refs': [source[0]]},
            {'from_ref': 'new:job', 'to_ref': 'new:person', 'relation': 'about', 'source_refs': [source[1]]}]}


def test_raw_immediate_isolated_idempotent_restart(make_engine):
    engine, provider = make_engine(mode='raw')
    response = add(engine, 'Orchid project uses blue notebooks')
    assert set(response) == {'success', 'request_id', 'user_id', 'session_id'}
    assert search(engine, 'Orchid')
    assert search(engine, 'Orchid', user='other') == []
    assert add(engine, 'Orchid project uses blue notebooks') == response
    assert provider.calls == []
    with pytest.raises(MemoryError, match='payload_conflict') as error:
        add(engine, 'different')
    assert error.value.status == 422
    assert engine.store.one('SELECT COUNT(*) n FROM raw_events')['n'] == 1
    path = engine.store.path
    engine.store.close()
    engine.store = Store(path)
    assert search(engine, 'Orchid')
    assert add(engine, 'Orchid project uses blue notebooks') == response
    engine.store.close()


def test_pending_buffer_is_searchable_and_cursor_advances_only_after_reflection(make_engine):
    engine, provider = make_engine(reflection_threshold=3)
    add(engine, 'apricot story', rid='1')
    add(engine, 'peach story', rid='2')
    assert len(engine.store.pending('u')) == 2
    assert search(engine, 'apricot')
    assert provider.calls == []
    add(engine, 'plum story', rid='3')
    assert len(provider.calls) == 1
    assert engine.store.pending('u') == []
    assert search(engine, 'apricot')


def test_session_change_flushes_tail_without_guessing_dates(make_engine):
    engine, provider = make_engine(reflection_threshold=20)
    add(engine, 'old session', session='z', rid='a')
    add(engine, 'new session', session='a', rid='b')
    assert len(provider.calls) == 1
    assert [r['session_id'] for r in provider.calls[0][1]['sources']] == ['z', 'a']
    assert all(r['source_time'] is None for r in provider.calls[0][1]['sources'])


def test_graph_forward_backlinks_and_two_hops(make_engine):
    engine, provider = make_engine(max_hops=2, seed_count=1)
    provider.handler = graph_mutation
    add(engine, 'Zephyr visit to DrLark', 'DrLark teaches at Pine School')
    nodes = engine.store.snapshot('u')['nodes']
    person = next(r for r in nodes if r['kind'] == 'person')
    assert engine.inspect('u', person['ref'])['links'] == []
    assert len(engine.backlinks('u', person['ref'])) == 2
    assert engine.inspect('other', person['ref']) is None
    assert engine.backlinks('other', person['ref']) == []
    assert any('Teaching appointment' in r['content'] for r in search(engine, 'Zephyr'))
    engine.config = replace(engine.config, max_hops=1)
    assert not any('Teaching appointment' in r['content'] for r in search(engine, 'Zephyr'))


def test_graph_budget_is_observed_and_does_not_invent_neighbors(make_engine):
    engine, provider = make_engine(max_hops=3, seed_count=1, max_nodes=1)
    provider.handler = graph_mutation
    add(engine, 'Zephyr visit to DrLark', 'DrLark teaches at Pine School')
    assert not any('Teaching appointment' in r['content'] for r in search(engine, 'Zephyr'))
    assert len(search(engine, 'Zephyr', top_k=1)) <= 1


def test_invalid_source_rejects_entire_mutation_and_external_replay_recovers(make_engine):
    engine, provider = make_engine()
    provider.handler = lambda *_: {'items': [{'ref': 'new:bad', 'kind': 'fact', 'text': 'invented', 'source_refs': ['raw:not-loaded']}]}
    with pytest.raises(MemoryError, match='unknown_source'):
        add(engine, 'amber')
    assert len(provider.calls) == 1
    assert engine.store.snapshot('u')['nodes'] == []
    assert len(engine.store.pending('u')) == 1
    with pytest.raises(MemoryError, match='incomplete'):
        search(engine, 'amber')
    with pytest.raises(MemoryError, match='prior_add_incomplete'):
        add(engine, 'next', rid='next')
    provider.handler = one_fact
    add(engine, 'amber')
    assert len(provider.calls) == 2
    assert len(engine.store.snapshot('u')['nodes']) == 1
    add(engine, 'amber')
    assert len(provider.calls) == 2


def test_embedding_failure_replay_does_not_repeat_successful_reflection(make_engine):
    engine, provider = make_engine(embedding_enabled=True)
    provider.handler = one_fact
    def fail(_):
        raise MemoryError('provider_timeout', 504)
    provider.embed_handler = fail
    with pytest.raises(MemoryError, match='timeout'):
        add(engine, 'cedar fact')
    assert [p for p, _ in provider.calls] == ['reflection', 'embed']
    provider.embed_handler = lambda texts: [[1., 0.] for _ in texts]
    add(engine, 'cedar fact')
    assert [p for p, _ in provider.calls] == ['reflection', 'embed', 'embed']
    assert len(list(engine.store.vector_rows('u', provider.embedding_fingerprint))) == 1


@pytest.mark.parametrize('relation,expected', [('supersedes', 'superseded'), ('contradicts', 'conflict')])
def test_updates_and_conflicts_keep_sources_and_states(make_engine, relation, expected):
    engine, provider = make_engine()
    provider.handler = one_fact
    add(engine, 'Orchid daily quota is 1000', rid='old')
    def update(_, data):
        old = next(r for r in data['memories'] if r['kind'] == 'fact')
        new = one_fact(_, data)
        new['links'] = [{'from_ref': 'new:fact', 'to_ref': old['ref'], 'relation': relation,
                          'source_refs': data['new_refs']}]
        return new
    provider.handler = update
    add(engine, 'Orchid daily quota is 1200 now', rid='new')
    old = next(r for r in engine.store.snapshot('u')['nodes'] if '1000' in r['text'])
    assert old['status'] == expected
    results = search(engine, 'Orchid quota', top_k=1)
    if relation == 'contradicts':
        assert '1000' in results[0]['content'] and '1200' in results[0]['content']
        assert 'conflict' in results[0]['content']
    else:
        assert '1200' in results[0]['content']
        assert '1000' not in results[0]['content'] or 'superseded' in results[0]['content']


def test_forgetting_blocks_raw_derived_backlinks_and_future_reflection(make_engine):
    engine, provider = make_engine()
    provider.handler = one_fact
    add(engine, 'I prefer citrus perfume', rid='old')
    old = engine.store.snapshot('u')['nodes'][0]
    def forget(_, data):
        node = next(r for r in data['memories'] if 'citrus' in r['text'])
        return {'forget': [{'memory_refs': [node['ref']], 'instruction_refs': data['new_refs']}]}
    provider.handler = forget
    add(engine, 'Forget my citrus perfume preference', rid='forget')
    assert search(engine, 'citrus perfume') == []
    assert engine.inspect('u', old['ref']) is None
    assert engine.backlinks('u', old['ref']) == []
    provider.handler = one_fact
    add(engine, 'Unrelated travel plans', rid='later')
    assert 'citrus' not in str(provider.calls[-1][1]).lower()


def test_forget_cannot_be_ordered_by_assistant(make_engine):
    engine, provider = make_engine()
    provider.handler = lambda _, data: {'forget': [{'source_refs': data['new_refs'], 'instruction_refs': data['new_refs']}]}
    request = AddRequest(request_id='r', user_id='u', session_id='s', messages=[{'role': 'assistant', 'content': 'Forget all'}])
    with pytest.raises(MemoryError, match='explicit_new_user'):
        engine.add(request)


def test_user_busy_is_bounded_not_queued(make_engine):
    engine, _ = make_engine(mode='raw')
    lock = engine._lock('u')
    lock.acquire()
    try:
        with pytest.raises(MemoryError) as exc:
            add(engine, 'busy')
        assert exc.value.status == 409
        with pytest.raises(MemoryError) as exc:
            search(engine, 'busy')
        assert exc.value.status == 425
    finally:
        lock.release()


def test_chinese_lexical_keeps_negation_and_multiple_people(make_engine):
    engine, _ = make_engine(mode='raw')
    add(engine, '小王不喜欢摄影，小李喜欢摄影。')
    rows = search(engine, '摄影')
    assert rows and '小王不喜欢' in rows[0]['content']


def test_second_writer_rejected(make_engine):
    engine, _ = make_engine(mode='raw')
    with pytest.raises(MemoryError, match='already_owned'):
        Store(engine.store.path)


def test_episode_contains_raw_is_normalized_to_provenance(make_engine):
    engine, provider = make_engine()
    def journal(_, data):
        raw = data['new_refs'][0]
        return {'items': [{'ref': 'new:episode', 'kind': 'episode', 'text': 'A grounded journal entry', 'source_refs': [raw]}],
                'links': [{'from_ref': 'new:episode', 'to_ref': raw, 'relation': 'contains', 'source_refs': [raw]}]}
    provider.handler = journal
    add(engine, 'A grounded journal entry')
    node = engine.store.snapshot('u')['nodes'][0]
    assert node['kind'] == 'episode'
    assert engine.store.snapshot('u')['edges'] == []
    assert node['source_refs']


def test_unchanged_fact_and_partial_date_allowed_but_rewrite_rejected(make_engine):
    engine, provider = make_engine(embedding_enabled=True)
    def dated(purpose, data):
        value = one_fact(purpose, data)
        value['items'][0].update(time_expression='April 20, 2023', time_start='2023-04-20')
        return value
    provider.handler = dated
    add(engine, 'Orchid meeting on April 20, 2023', rid='first')
    old = engine.store.snapshot('u')['nodes'][0]
    def unchanged(_, data):
        fields = ['ref', 'kind', 'text', 'source_refs', 'time_expression', 'time_start', 'time_end']
        return {'items': [{key: old.get(key) for key in fields}]}
    provider.handler = unchanged
    add(engine, 'Orchid meeting already recorded', rid='repeat')
    assert len(engine.store.snapshot('u')['nodes']) == 1
    def rewrite(_, data):
        value = unchanged(_, data)
        value['items'][0]['text'] = 'Orchid meeting canceled'
        return value
    provider.handler = rewrite
    with pytest.raises(MemoryError, match='fact_overwrite'):
        add(engine, 'Orchid meeting canceled', rid='rewrite')
    assert engine.store.get('u', old['ref'])['text'] == old['text']


def test_forget_pending_raw_without_derived_node(make_engine):
    engine, provider = make_engine(reflection_threshold=20)
    add(engine, 'My violet perfume preference', rid='first')
    def forget(_, data):
        target = next(r for r in data['sources'] if r['text'] == 'My violet perfume preference')
        instruction = next(r for r in data['sources'] if r['text'].startswith('Forget'))
        return {'forget': [{'source_refs': [target['ref']], 'instruction_refs': [instruction['ref']]}]}
    provider.handler = forget
    add(engine, 'Forget my violet perfume preference', rid='forget')
    assert search(engine, 'violet perfume') == []


def test_forget_suppresses_assistant_echo_in_same_batch(make_engine):
    engine, provider = make_engine(reflection_threshold=20)
    add(engine, 'I enjoy gardening in the backyard', rid='old')
    def scope(_, data):
        instruction = next(r['ref'] for r in data['sources'] if r['text'].startswith('Forget'))
        return {'forget': [{'instruction_refs': [instruction], 'source_refs': [r['ref'] for r in data['sources']]}]}
    provider.handler = scope
    engine.add(AddRequest(request_id='forget', user_id='u', session_id='s', messages=[
        {'role': 'user', 'content': 'Forget that I enjoy gardening in the backyard'},
        {'role': 'assistant', 'content': "I'll forget that you enjoy gardening in the backyard."}]))
    assert search(engine, 'gardening backyard') == []


def test_duplicate_new_labels_are_rejected_without_guessing_identity(make_engine):
    engine, provider = make_engine()
    def duplicate(_, data):
        raws = data['new_refs']
        return {'items': [
            {'ref': 'new:episode', 'kind': 'episode', 'text': 'first entry', 'source_refs': [raws[0]]},
            {'ref': 'new:episode', 'kind': 'episode', 'text': 'second entry', 'source_refs': [raws[1]]},
        ]}
    provider.handler = duplicate
    with pytest.raises(MemoryError, match='mutation_duplicate_ref'):
        add(engine, 'first entry', 'second entry')
    assert engine.store.snapshot('u')['nodes'] == []


def test_three_way_conflict_returns_complete_component(make_engine):
    engine, provider = make_engine()
    def conflict(_, data):
        raw = data['new_refs'][0]
        items = [{'ref': 'new:' + label, 'kind': 'fact', 'text': 'Orchid quota ' + label,
                  'source_refs': [raw]} for label in ('1000', '1200', '1400')]
        links = [{'from_ref': 'new:' + a, 'to_ref': 'new:' + b, 'relation': 'contradicts', 'source_refs': [raw]}
                 for a, b in [('1000', '1200'), ('1200', '1400')]]
        return {'items': items, 'links': links}
    provider.handler = conflict
    add(engine, 'Orchid reports disagree about quota')
    content = search(engine, 'Orchid quota 1000', top_k=1)[0]['content']
    assert all(value in content for value in ('1000', '1200', '1400'))


def test_raw_source_state_follows_multiple_replacements(make_engine):
    engine, provider = make_engine()
    provider.handler = one_fact
    add(engine, 'Orchid original quota 1000, notebook color blue', rid='first')
    def update(_, data):
        value = one_fact(_, data)
        old = next(n for n in data['memories'] if n['kind'] == 'fact' and n['status'] == 'active')
        value['links'] = [{'from_ref': 'new:fact', 'to_ref': old['ref'], 'relation': 'supersedes',
                           'source_refs': data['new_refs']}]
        return value
    provider.handler = update
    add(engine, 'Orchid quota now 1200', rid='second')
    add(engine, 'Orchid quota now 1400', rid='third')
    raw = engine.store.one("SELECT ref FROM raw_events WHERE request_id='first'")['ref']
    content = engine._assemble('u', 'blue notebook', [{'ref': raw, 'score': 1}], 1, [], False)[0]['content']
    assert '1400' in content and 'superseded' in content


def test_model_selection_can_exclude_all_irrelevant_candidates(make_engine):
    engine, provider = make_engine(search_model=True)
    def respond(purpose, data):
        if purpose == 'reflection':
            return one_fact(purpose, data)
        return {'queries': [], 'history': False} if purpose == 'search_plan' else {'refs': []}
    provider.handler = respond
    add(engine, 'Orchid flower facts')
    assert search(engine, 'How many Orchid flowers did I buy?') == []
    assert [purpose for purpose, _ in provider.calls] == ['reflection', 'search_plan', 'select']


def test_new_ref_exact_grounded_replay_deduplicates(make_engine):
    engine, provider = make_engine()
    provider.handler = one_fact
    add(engine, 'same grounded fact', rid='first')
    def replay(_, data):
        return {'items': [{'ref': 'new:another_label', 'kind': 'fact', 'text': 'same grounded fact',
                           'source_refs': [r['ref'] for r in data['sources']]}]}
    provider.handler = replay
    add(engine, 'same grounded fact', rid='second')
    assert len(engine.store.snapshot('u')['nodes']) == 1


def test_contains_direction_normalizes_by_types(make_engine):
    engine, provider = make_engine()
    def reversed_link(_, data):
        raw = data['new_refs']
        return {'items': [
            {'ref': 'new:fact', 'kind': 'fact', 'text': 'Grounded fact', 'source_refs': raw},
            {'ref': 'new:log', 'kind': 'episode', 'text': 'Grounded episode', 'source_refs': raw}],
            'links': [{'from_ref': 'new:fact', 'to_ref': 'new:log', 'relation': 'contains', 'source_refs': raw}]}
    provider.handler = reversed_link
    add(engine, 'Grounded episode with a fact')
    nodes = {n['ref']: n for n in engine.store.snapshot('u')['nodes']}
    edge = engine.store.snapshot('u')['edges'][0]
    assert nodes[edge['from_ref']]['kind'] == 'episode'
    assert nodes[edge['to_ref']]['kind'] == 'fact'
