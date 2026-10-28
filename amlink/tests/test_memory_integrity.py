"""Regression cases for observed episode drift and review delivery failures."""
import pytest

from test_core_repairs import make, request
from review_fixture import review_output
from amlink.drafts import check_review, decode_review, review_payload, review_schema
from amlink.errors import MemoryError
from amlink.reflection import preflight_mutation, prepare_mutation


def fixture_memory(engine, kind):
    engine.add(request('old', ['Chain replacement cost $25; bike lights cost $40.']))
    engine.add(request('new', ['A helmet cost $120. I might just go back.']))
    old_source, new_source = engine.store.raw('u')
    node = dict(ref=f'memory:{kind}-bike', kind=kind, text=old_source['text'],
                source_refs=[old_source['ref']], time_expression=None, time_start=None, time_end=None)
    engine.store.commit_mutation('u', dict(items=[node], links=[], forget=[]),
                                watermark=1, fingerprint='test', vectors={})
    context = dict(sources=[old_source, new_source], items={node['ref']: node}, new_refs=[new_source['ref']])
    return node, old_source, new_source, context


@pytest.mark.parametrize('kind', ['episode', 'fact', 'event'])
@pytest.mark.parametrize('field,value', [('text', 'A helmet cost $120.'), ('time_expression', 'yesterday')])
def test_existing_statement_cannot_drift_before_or_after_review(make, kind, field, value):
    engine, _ = make(mode='raw')
    node, old_source, new_source, context = fixture_memory(engine, kind)
    proposal = {**node, field: value, 'source_refs': [new_source['ref']]}
    for check in (
        lambda: preflight_mutation(dict(items=[proposal]), user='u', store=engine.store),
        lambda: prepare_mutation(dict(items=[proposal]), user='u', request_id='r', number=1,
                                 context=context, store=engine.store),
    ):
        with pytest.raises(MemoryError, match='mutation_(episode|fact)_overwrite'):
            check()
    assert engine.store.get('u', node['ref'])['text'] == old_source['text']


def test_new_episode_summary_is_rejected_but_distinct_event_can_be_stored(make):
    engine, _ = make(mode='raw')
    _, _, new, context = fixture_memory(engine, 'episode')
    proposal = dict(ref='new:helmet', kind='episode', text='A helmet cost $120.', source_refs=[new['ref']])
    with pytest.raises(MemoryError, match='mutation_episode_creation'):
        prepare_mutation(dict(items=[proposal]), user='u', request_id='r', number=2, context=context, store=engine.store)
    proposal['kind'] = 'event'
    result = prepare_mutation(dict(items=[proposal]), user='u', request_id='r', number=2, context=context, store=engine.store)
    assert result['items'][0]['text'] == proposal['text']


@pytest.mark.parametrize('kind', ['person', 'entity', 'concept'])
def test_changed_navigation_keeps_reviewed_support_not_historical_sources(make, kind):
    engine, _ = make(mode='raw')
    node, old, new, context = fixture_memory(engine, kind)
    proposal = {**node, 'text': 'The cyclist is considering returning.', 'source_refs': [new['ref']]}
    result = prepare_mutation(dict(items=[proposal]), user='u', request_id='r', number=1, context=context, store=engine.store)
    assert result['items'][0]['source_refs'] == [new['ref']]
    # Provenance history and the old source are still present until an actual commit.
    assert engine.store.get('u', old['ref'])['text'] == old['text']


def test_identical_fact_adds_support_without_new_node(make):
    engine, _ = make(mode='raw')
    node, old, _, context = fixture_memory(engine, 'fact')
    engine.add(request('repeat', [node['text']]))
    new = engine.store.raw('u')[-1]
    context['sources'].append(new)
    proposal = {**node, 'source_refs': [new['ref']]}
    result = prepare_mutation(dict(items=[proposal]), user='u', request_id='r', number=1, context=context, store=engine.store)
    assert result['items'][0]['ref'] == node['ref']
    assert set(result['items'][0]['source_refs']) == {old['ref'], new['ref']}


def review_case():
    items = [dict(ref='new:visit', kind='event', text='Maya plans to return on April 20, 2023.', source_refs=['raw:a']),
             dict(ref='new:maya', kind='person', text='Maya is the speaker.', source_refs=['raw:a'])]
    payload = review_payload(dict(items=items, links=[dict(from_ref='new:visit', to_ref='new:maya',
        relation='about', source_refs=['raw:a'])]), {}, [dict(ref='raw:a', text='Maya: I might return on April 20th.')])
    output = review_output(payload, {'reviews': [dict(position=u['position'], action='keep', text=None,
        source_positions=[0], detail='Supported.') for u in payload['units']]})
    output['u0'].update(text='Maya might return on April 20th.', time_expression='April 20th')
    return payload, output


def test_flat_review_applies_statement_time_support_and_edge_together():
    payload, output = review_case()
    edits, receipts = check_review(payload, decode_review(payload, output))
    assert edits[0]['after']['text'] == 'Maya might return on April 20th.'
    assert edits[0]['after']['time_start'] is None
    assert edits[2]['after'] is not None
    assert len(receipts) == 3
    fields = review_schema(payload)['properties']
    assert 'reviews' not in fields and 'anyOf' not in fields['u0']
    assert 'replacement_quote' not in fields['u0']['properties']
    assert 'text' not in fields['u2']['properties']


@pytest.mark.parametrize('fault', ['nested', 'missing', 'extra', 'unknown_source', 'boolean_source',
                                  'duplicate_source', 'empty_revision', 'keep_rewrite', 'edge_revision', 'foreign_endpoint'])
def test_invalid_flat_review_never_guessed_or_partially_accepted(fault):
    payload, output = review_case()
    if fault == 'nested': output['u0']['u1'] = output.pop('u1')
    if fault == 'missing': output.pop('u1')
    if fault == 'extra': output['u0']['position'] = 0
    if fault == 'unknown_source': output['u0']['evidence_positions'] = [99]
    if fault == 'boolean_source': output['u0']['evidence_positions'] = [False]
    if fault == 'duplicate_source': output['u0']['evidence_positions'] = [0, 0]
    if fault == 'empty_revision': output['u0']['text'] = ''
    if fault == 'keep_rewrite': output['u0']['action'] = 'keep'
    if fault == 'edge_revision': output['u2']['action'] = 'revise'
    if fault == 'foreign_endpoint': output['u2']['revised_endpoints'] = ['memory:other']
    with pytest.raises(MemoryError, match='reflection_review_(incomplete|invalid)'):
        decode_review(payload, output)


def test_invented_time_quote_rejected_even_when_calendar_date_looks_valid(make):
    payload, output = review_case()
    output['u0'].update(time_expression='April 20, 2023', time_start='2023-04-20', time_end='2023-04-20')
    with pytest.raises(MemoryError, match='mutation_time_not_quoted'):
        check_review(payload, decode_review(payload, output))
    engine, _ = make(mode='raw')
    engine.add(request('date', ['Maya: I might return on April 20th.']))
    raw = engine.store.raw('u')[0]
    proposal = {**payload['units'][0]['proposal'], 'source_refs': [raw['ref']], 'time_expression': 'April 20, 2023'}
    with pytest.raises(MemoryError, match='mutation_time_not_quoted'):
        prepare_mutation(dict(items=[proposal]), user='u', request_id='r', number=1,
                         context=dict(sources=[raw], new_refs=[raw['ref']]), store=engine.store)


def test_time_expression_must_occur_in_selected_visible_support():
    payload, output = review_case()
    payload['sources'].append({**payload['sources'][0], 'position': 1, 'text': 'April 20, 2023'})
    payload['units'][0]['source_positions'].append(1)
    output['u0']['time_expression'] = 'April 20, 2023'
    # Visible elsewhere does not make it a quotation of the chosen source.
    with pytest.raises(MemoryError, match='mutation_time_not_quoted'):
        check_review(payload, decode_review(payload, output))


def test_exact_quote_does_not_authorize_year_from_message_metadata():
    payload, output = review_case()
    payload['sources'][0]['source_time'] = 1683246780000
    output['u0'].update(time_start='2023-04-20', time_end='2023-04-20')
    with pytest.raises(MemoryError, match='mutation_time_precision'):
        check_review(payload, decode_review(payload, output))
    output['u0'].update(time_start=None, time_end=None)
    assert check_review(payload, decode_review(payload, output))[0][0]['after']['time_expression'] == 'April 20th'


def test_explicit_year_stays_usable_with_original_quote():
    payload, output = review_case()
    payload['sources'][0]['text'] = 'Maya: I might return on April 20, 2023.'
    output['u0'].update(text='Maya might return on April 20, 2023.', time_expression='April 20, 2023',
                        time_start='2023-04-20', time_end='2023-04-20')
    assert check_review(payload, decode_review(payload, output))[0][0]['after']['time_start'] == '2023-04-20'


def test_time_feedback_names_draft_fields_and_local_patch_can_finish(make):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose, payload):
        control = payload['context']['reflection_control']
        issue = control.get('last_gate_error')
        if not issue:
            return 'reflection_items', dict(items=[dict(ref='new:visit', kind='event',
                text='Maya visited the shop.', source_refs=[payload['working'][0]['ref']],
                time_expression='2023-05-05', time_start=None, time_end=None)])
        diagnostic = issue['invalid_links'][0]
        assert diagnostic['reason'] == 'mutation_time_not_quoted'
        assert diagnostic['draft_time_fields'][0]['ref'] == 'new:visit'
        assert diagnostic['draft_time_fields'][0]['time_expression'] == '2023-05-05'
        node = {**control['pending_mutation']['items'][0], 'time_expression': None,
                'time_start': None, 'time_end': None}
        return 'reflection_patch_items', dict(reason='Remove a date absent from the source.', remove_refs=[], upsert=[node])
    provider.decide = decide
    assert engine.add(request('visit', ['Maya visited the shop.']))['success']
    event = next(n for n in engine.store.nodes('u') if n['kind'] == 'event')
    assert event['time_expression'] is None
    assert engine.store.maintenance_summary('u')['groups_unfinished'] == 0
    assert sum(p == 'reflection' for p, _ in provider.calls) == 2  # Initial content, then actual patch.
