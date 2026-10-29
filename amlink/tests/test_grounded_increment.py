"""Behavioral checks for provenance, conversation framing and explicit reuse."""
import pytest
from dataclasses import replace

from test_core_repairs import make, request
from amlink.drafts import review_payload, review_units
from amlink.evidence import fragment
from amlink.errors import MemoryError
from amlink.grounding import reusable_items
from amlink.local_reflection import freeze_groups, group_rows
from amlink.reflection import preflight_mutation, prepare_mutation
from amlink.text import digest


def source_graph(engine):
    engine.add(request('chair', ['I selected a safe high chair.']))
    engine.add(request('food', ['I prefer eco-friendly groceries.']))
    sources = engine.store.raw('u')
    episodes = engine.store.nodes('u')
    chair = next(n for n in episodes if sources[0]['ref'] in n['source_refs'])
    fact = dict(ref='new:groceries', kind='fact', text=sources[1]['text'], source_refs=[sources[1]['ref']])
    link = dict(from_ref=chair['ref'], to_ref=fact['ref'], relation='contains', source_refs=[sources[1]['ref']])
    context = dict(items={n['ref']: n for n in episodes}, sources=sources, new_refs=[sources[1]['ref']])
    return sources, chair, fact, link, context


def test_disjoint_contains_is_rejected_before_read_and_at_final_prepare(make):
    engine, _ = make(mode='raw')
    _, _, fact, link, context = source_graph(engine)
    proposal = dict(items=[fact], links=[link])
    errors = preflight_mutation(proposal, user='u', store=engine.store)
    assert errors[0]['reason'] == 'contains_source_mismatch'
    result = prepare_mutation(proposal, user='u', store=engine.store, request_id='x', number=0, context=context)
    assert not result['links'] and result['filtered_links'][0]['reason'] == 'contains_source_mismatch'
    assert not any(n['kind'] == 'fact' for n in engine.store.nodes('u'))


def test_contains_may_reference_one_of_many_target_supports_but_not_outside_episode(make):
    engine, _ = make(mode='raw')
    sources, chair, fact, link, context = source_graph(engine)
    fact['source_refs'] = [r['ref'] for r in sources]
    fact['text'] = 'This example has supporting passages in two episodes.'
    link['source_refs'] = [sources[0]['ref']]
    proposal = dict(items=[fact], links=[link])
    assert preflight_mutation(proposal, user='u', store=engine.store) == []
    result = prepare_mutation(proposal, user='u', store=engine.store, request_id='x', number=0, context=context)
    assert len(result['links']) == 1
    link['source_refs'].append(sources[1]['ref'])
    assert preflight_mutation(proposal, user='u', store=engine.store)[0]['reason'] == 'contains_source_mismatch'


def test_review_cannot_move_contains_to_unrelated_source(make):
    engine, _ = make(mode='raw')
    sources, chair, fact, link, context = source_graph(engine)
    fact['source_refs'] = [r['ref'] for r in sources]
    link['source_refs'] = [sources[0]['ref']]
    payload = review_payload(dict(items=[fact], links=[link]), context, sources)
    unit = next(u for u in payload['units'] if u['kind'] == 'relation')
    bad = next(s['position'] for s in payload['sources'] if s['source_ref'] == sources[1]['ref'])
    review = dict(position=unit['position'], action='keep', detail='Wrong support.', source_positions=[bad])
    edits, receipts, issues = review_units({**payload, 'units': [unit]}, dict(reviews=[review]))
    assert not edits and not receipts
    assert issues[0]['code'] == 'reflection_contains_source_mismatch'
    review.update(action='drop', detail='This episode does not contain the grocery claim.')
    edits, receipts, issues = review_units({**payload, 'units': [unit]}, dict(reviews=[review]))
    assert edits[0]['after'] is None and not issues and not receipts


def test_split_reply_keeps_its_same_session_request_as_background_only():
    rows = [dict(ref='raw:request', text='Polish this fictional story: I sailed to Mars.', role='user', session_id='a', ordinal=1),
            dict(ref='raw:other', text='My own Mars research.', role='user', session_id='b', ordinal=2),
            dict(ref='raw:reply', text='I sailed to Mars in a red ship.', role='assistant', session_id='a', ordinal=3)]
    plan = freeze_groups({'groups': [dict(title=str(i), question=str(i), positions=[i]) for i in range(3)]}, rows)
    reply = group_rows(plan['groups'][2], rows)
    assert [(r['ref'], r['primary']) for r in reply] == [('raw:request', False), ('raw:reply', True)]
    assert sum(v['primary'] for g in plan['groups'] for v in g['ranges']) == 3
    assert all(v['text'] == rows[0]['text'] for v in reply if not v['primary'])


def reuse_context(engine):
    engine.add(request('first', ['Maya adopted a cat named Luna.']))
    engine.add(request('again', ['Maya: To confirm, Luna is my adopted cat.']))
    old, new = engine.store.raw('u')
    node = dict(ref='memory:fact-luna', kind='fact', text='Maya adopted a cat named Luna.',
                source_refs=[old['ref']], time_expression=None, time_start=None, time_end=None)
    engine.store.commit_mutation('u', dict(items=[node], links=[], forget=[]), watermark=1, fingerprint='test', vectors={})
    context = dict(items={node['ref']: node}, sources=[old, new], new_refs=[new['ref']],
        visible_source_refs=[new['ref']], inspections={node['ref']: digest(node['text'])},
        last_visible=[fragment(node, 0, len(node['text']))])
    return node, old, new, context


def test_reuse_ready_menu_does_not_authorize_changing_old_statement(make):
    engine, _ = make(mode='raw')
    node, old, new, context = reuse_context(engine)
    assert list(reusable_items(context, context['last_visible'])) == [node['ref']]
    expanded = dict(items=[{**node, 'source_refs': [new['ref']]}])
    prepared = prepare_mutation(expanded, user='u', store=engine.store, context=context, request_id='r', number=0)
    assert prepared['items'][0]['ref'] == node['ref']
    assert set(prepared['items'][0]['source_refs']) == {old['ref'], new['ref']}
    expanded['items'][0]['text'] = 'A different adoption.'
    with pytest.raises(MemoryError, match='mutation_fact_overwrite'):
        preflight_mutation(expanded, user='u', store=engine.store)


@pytest.mark.parametrize('fault', ['not_read', 'not_shown', 'partial', 'stale', 'episode'])
def test_reuse_menu_never_claims_hidden_memory_has_been_read(make, fault):
    engine, _ = make(mode='raw')
    node, old, new, context = reuse_context(engine)
    if fault == 'not_read': context['inspections'] = {}
    if fault == 'not_shown': context['last_visible'] = []
    if fault == 'partial': context['last_visible'] = [fragment(node, 0, 5)]
    if fault == 'stale': context['items'][node['ref']] = {**node, 'text': 'A different assertion.'}
    if fault == 'episode': context['items'][node['ref']]['kind'] = 'episode'
    assert reusable_items(context, context['last_visible']) == {}


def test_reuse_withdrawal_in_review_does_not_add_support(make):
    engine, _ = make(mode='raw')
    node, old, new, context = reuse_context(engine)
    expanded = dict(items=[{**node, 'source_refs': [new['ref']]}])
    payload = review_payload(expanded, context, [new])
    edits, receipts, issues = review_units(payload, dict(reviews=[dict(position=0, action='drop',
        detail='Actually a different cat; no shared event.', source_positions=[])]))
    assert edits[0]['after'] is None and not receipts and not issues
    assert engine.store.get('u', node['ref'])['source_refs'] == [old['ref']]


def test_add_inspects_then_reuses_without_creating_duplicate_fact(make):
    engine, provider = make(mode='raw')
    node, old, _, _ = reuse_context(engine)
    # Preparation is explicitly outside the tested Add. Start a new pending prefix.
    engine.store.commit_mutation('u', dict(items=[], links=[], forget=[]), watermark=2,
                                 fingerprint='test', vectors={})
    engine.config = replace(engine.config, mode='graph', reflection_threshold=1)
    tools_seen = []
    menus = []
    original = provider.tool
    def tool(purpose, prompt, payload, tools, deadline):
        if purpose == 'reflection':
            tools_seen.append({t['name']: t['parameters'] for t in tools})
            menus.append(payload['reuse_options'])
        return original(purpose, prompt, payload, tools, deadline)
    provider.tool = tool
    def decide(purpose, payload):
        if payload['step'] == 0:
            row = next(c for c in payload['context']['choices'] if c['ref'] == node['ref'])
            return 'reflection_inspect', {'reference_position': row['position'], 'page_position': None}
        if payload['decision']['stage'] == 'relations':
            return 'reflection_relations', {'links': []}
        return 'reflection_items', {'items': [{**node, 'source_refs': [payload['working'][0]['ref']]}]}
    provider.decide = decide
    assert engine.add(request('confirmation', ['Maya adopted a cat named Luna. It is the same adoption.']))['success']
    saved = engine.store.get('u', node['ref'])
    assert saved['text'] == node['text'] and len(saved['source_refs']) == 2
    assert old['ref'] in saved['source_refs']
    assert len([n for n in engine.store.nodes('u') if n['kind'] == 'fact']) == 1
    assert engine.store.state('u')['settled_through'] == 3
    assert 'anyOf' not in tools_seen[0]['reflection_items']['properties']['items']['items']
    assert 'anyOf' not in tools_seen[1]['reflection_items']['properties']['items']['items']
    assert menus[0]['refs'] == [] and menus[1]['refs'] == [node['ref']]
    assert 'reuse' not in tools_seen[1]['reflection_items']['properties']
