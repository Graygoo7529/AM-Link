"""Disclosure and incremental review must agree with actual writes."""
from copy import deepcopy
import time

import pytest

from test_core_repairs import make, request
from amlink.drafts import review_payload, review_units
from amlink.evidence import fragment
from amlink.errors import MemoryError
from amlink.narrative import context_text, render
from amlink.reflection import immutable_change_details


def test_visible_forward_neighbor_survives_packing_without_redundant_inspect(make):
    from amlink.packing import freeze_pack, pack_frozen
    from amlink.projection import range_receipt
    engine, _ = make(mode='raw')
    for i, text in enumerate(['Dana won the Lark Prize.', 'The ceremony is held in Bremen.']):
        engine.add(request(str(i), [text]))
    sources = engine.store.raw('u')
    nodes = [dict(ref='memory:event-win', kind='event', text=sources[0]['text'], source_refs=[sources[0]['ref']]),
             dict(ref='memory:entity-prize', kind='entity', text=sources[1]['text'], source_refs=[sources[1]['ref']])]
    edge = dict(from_ref=nodes[0]['ref'], to_ref=nodes[1]['ref'], relation='about', source_refs=[s['ref'] for s in sources])
    engine.store.commit_mutation('u', {'items': nodes, 'links': [edge], 'forget': []}, watermark=2, fingerprint='x', vectors={})
    context = {'query_roots': [nodes[0]['ref']], 'paths': [dict(from_ref=nodes[0]['ref'], to_ref=nodes[1]['ref'],
               action='inspect', edges=[edge], selected=False)],
               'last_visible': [range_receipt(fragment(nodes[1], 0, len(nodes[1]['text'])))]}
    frozen = freeze_pack(engine.store, 'u', 'Where was the ceremony?', nodes, context, engine.config)
    output, audit = pack_frozen(frozen, 1)
    assert 'Bremen' in output[0]['content'] and audit['decisions'][0]['path_closed']
    assert audit['decisions'][0]['visible_graph_refs'] == [nodes[1]['ref']]
    # A link label or an obsolete disclosure cannot silently qualify as a read body.
    context['last_visible'][0]['content_digest'] = 'old-version'
    hidden = freeze_pack(engine.store, 'u', 'Where was the ceremony?', nodes, context, engine.config)
    assert hidden['groups'][0]['members'] == [nodes[0]['ref']]


def old_event():
    return dict(ref='memory:event-meeting', kind='event', text='Mara attended the April 20th meeting.',
                source_refs=['raw:old'], time_expression='April 20th', time_start=None, time_end=None)


def test_old_time_survives_disclosure_and_review_without_message_date_inference():
    old = old_event()
    page = fragment(old, 0, len(old['text']))
    projected = dict(disclosures=[page], references={old['ref']: old})
    text = context_text(projected)
    assert '"time_expression":"April 20th"' in text and '"time_start":null' in text
    wrong = deepcopy(projected)
    wrong['disclosures'][0]['time_expression'] = None
    assert context_text(wrong) != text
    payload = review_payload({'items': [{**old, 'source_refs': ['raw:new']}]}, projected,
                             [dict(ref='raw:new', text='Mara confirms the same April 20th meeting.')])
    assert payload['old_targets'][0]['time_expression'] == 'April 20th'
    assert payload['units'][0]['review_task'] == 'support_addition'


def test_immutable_feedback_names_different_fields_but_does_not_disclose_unread_body():
    old = old_event()
    page = fragment(old, 0, len(old['text']))
    context = dict(items={old['ref']: old}, last_visible=[page], read_ranges=[page])
    proposal = {'items': [{**old, 'time_expression': None}]}
    issues = immutable_change_details(proposal, context)
    assert issues[0]['changed_fields'] == {'time_expression': {'submitted': None, 'stored': 'April 20th'}}
    proposal['items'][0]['text'] = 'A different meeting.'
    context['read_ranges'] = []
    hidden = immutable_change_details(proposal, context)
    assert old['text'] not in str(hidden) and not hidden[0]['old_body_read_and_visible']


def test_changed_proposal_is_progress_even_if_error_category_unchanged(make):
    engine, _ = make(mode='raw')
    context = dict(question='test', items={}, references={}, sources=[], last_visible=[], read_ranges=[])
    issue = [{'reason': 'mutation_fact_overwrite'}]
    with engine.observer.span('reflection', 'test') as event:
        engine._reflection_feedback('u', context, {'items': [{'ref': 'new:a', 'text': 'first'}]}, [], issue, event, 0, 'mutation_fact_overwrite')
        changed = {'items': [{'ref': 'new:a', 'text': 'second'}]}
        engine._reflection_feedback('u', context, changed, [], issue, event, 1, 'mutation_fact_overwrite')
        with pytest.raises(MemoryError, match='reflection_no_evidence_progress'):
            engine._reflection_feedback('u', context, changed, [], issue, event, 2, 'mutation_fact_overwrite')


def test_support_review_cannot_use_old_sources_to_approve_new_sources():
    old = old_event()
    working = [dict(ref='raw:old', text=old['text']), dict(ref='raw:new', text='Mara attended a different meeting.')]
    payload = review_payload({'items': [{**old, 'source_refs': ['raw:old','raw:new']}]},
                             {'items': {old['ref']: old}}, working)
    unit = payload['units'][0]
    assert unit['added_source_refs'] == ['raw:new']
    pos = {s['source_ref']: s['position'] for s in payload['sources']}
    assert unit['source_positions'] == [pos['raw:new']]
    review = dict(position=0, action='keep', source_positions=[pos['raw:old']], detail='Old text is true.')
    with pytest.raises(MemoryError, match='reflection_review_invalid'):
        review_units(payload, {'reviews': [review]})
    narrative = render('reflection_review', payload)
    assert 'CHECK ONLY THE NEW SUPPORT' in narrative


def test_reuse_review_cannot_change_time_even_if_new_source_quotes_it():
    old = old_event()
    payload = review_payload({'items': [{**old, 'source_refs': ['raw:new']}]}, {'items': {old['ref']: old}},
        [dict(ref='raw:new', text='Mara attended the April 20th meeting. It was in 2024.')])
    edits, receipts, issues = review_units(payload, {'reviews': [dict(position=0, action='revise',
        source_positions=payload['units'][0]['source_positions'], detail='New year.', text=old['text'],
        time=dict(time_expression='April 20th', time_start='2024-04-20', time_end=None))]})
    assert not edits and not receipts and issues[0]['code'] == 'reflection_review_immutable_target'


def test_same_event_confirmation_keeps_original_time_supported_by_old_source():
    old = old_event()
    payload = review_payload({'items': [{**old, 'source_refs': ['raw:new']}]}, {'items': {old['ref']: old}},
        [dict(ref='raw:new', text='Mara confirms attending that same meeting; its date has not changed.')])
    edits, receipts, issues = review_units(payload, {'reviews': [dict(position=0, action='keep',
        source_positions=payload['units'][0]['source_positions'], detail='Explicit same event confirmation.')]})
    assert not issues and edits[0]['after']['time_expression'] == 'April 20th'
    assert edits[0]['after']['source_refs'] == ['raw:new'] and len(receipts) == 1


@pytest.mark.parametrize('basis,remaining,accepted', [('update_existing', [], True),
    ('resolve_conflict', [], False), ('update_existing', ['A distinct event still needs its own node.'], False)])
def test_withdrawn_support_can_finish_without_erasing_old_memory_or_unresolved_work(make, basis, remaining, accepted):
    engine, provider = make(mode='raw')
    old = old_event()
    proposal = dict(basis=basis, items=[{**old, 'source_refs': ['raw:new']}], links=[])
    provider.review = lambda payload: dict(reviews=[dict(position=0, action='drop', detail='Another subject.',
        source_positions=[])], remaining_work=remaining, no_change_reason='No additional support for this old statement.')
    context = {}
    if basis == 'resolve_conflict':
        with pytest.raises(MemoryError, match='reflection_unresolved_evidence'):
            engine._review_draft(proposal, {'items': {old['ref']: old}},
                [dict(ref='raw:new',text='Another subject.')], time.monotonic()+10, context=context)
    else:
        result = engine._review_draft(proposal, {'items': {old['ref']: old}},
            [dict(ref='raw:new',text='Another subject.')], time.monotonic()+10, context=context)
        assert not result['items']
    assert bool(context.get('_completion')) is accepted
    assert context.get('review_remaining', []) == remaining


def test_navigation_review_compares_old_identity_and_time_feedback_quotes_source():
    old = {**old_event(), 'kind':'person', 'text':'Mara is the speaker.', 'time_expression':None}
    proposal = {**old, 'text':'Mara decided to swim this Saturday.', 'source_refs':['raw:new'], 'time_expression':'this Saturday'}
    payload = review_payload({'items':[proposal]}, {'items':{old['ref']:old}},
        [dict(ref='raw:new',text='Mara: 我决定这周六去游泳。')])
    assert payload['units'][0]['review_task'] == 'navigation_update'
    assert 'SAME real person/entity' in render('reflection_review', payload)
    _, _, issues = review_units(payload, {'reviews':[dict(position=0,action='keep',detail='Time translated.',
        source_positions=payload['units'][0]['source_positions'])]})
    assert issues[0]['code'] == 'mutation_time_not_quoted'
    assert '这周六' in issues[0]['selected_originals'][0]['text']
