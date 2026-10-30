import json
import time

from test_core_repairs import make, request
from amlink.config import Config
from amlink.providers import tool_body
from amlink.packing import freeze_pack, pack_frozen
from amlink.evidence import fragment
from amlink.selection import contribution_groups


def test_model_serialization_preserves_task_before_material_without_changing_hash_format():
    body = tool_body(Config(), 'select', 'Select evidence.', {'question': 'How much?', 'candidates': ['long material']}, [])
    text = body['messages'][1]['content']
    assert text.index('QUESTION') < text.index('Card')
    assert 'QUESTION: How much?' in text


def test_select_exposes_independent_passages_and_carries_selected_range_to_pack(make):
    engine, provider = make(mode='raw')
    engine.add(request('a', ['I ride many miles.', 'My helmet cost $120.', 'My bicycle is red.']))
    node = engine.store.nodes('u')[0]
    def decide(purpose, payload):
        assert purpose == 'select'
        positions = [r['position'] for r in payload['candidates'] if '$120' in r['narrative']]
        assert positions and all('hit_fragments' not in r for r in payload['candidates'])
        return 'select', {'positions': positions, 'coverage': [{'evidence': 'helmet cost', 'positions': positions}]}
    provider.decide = decide
    selected = engine._select_refs('u', 'helmet cost', [node], {}, time.monotonic()+10, reason='query')
    assert len(selected) == 1 and len(selected[0]['selected_fragments']) == 1
    value = selected[0]['selected_fragments'][0]
    assert '$120' in value['text']
    reference = engine._reference(selected[0], 'helmet cost', 'query', 'u')
    assert reference['evidence_fragments'][0]['fragment_id'] == value['fragment_id']
    frozen = freeze_pack(engine.store, 'u', 'helmet cost', selected, {}, engine.config)
    assert frozen['groups'][0]['fragments'][0]['fragment_id'] == value['fragment_id']
    result, audit = pack_frozen(frozen, 1)
    assert '$120' in result[0]['content']


def test_selected_late_window_is_first_support_window_for_its_origin(make):
    engine, _ = make(mode='raw')
    text = 'General advice. ' * 300 + 'The exception is only on weekends.'
    engine.add(request('a', [text]))
    node, source = engine.store.nodes('u')[0], engine.store.raw('u')[0]
    selected = fragment(source, text.index('The exception'), len(text))
    frozen = freeze_pack(engine.store, 'u', 'advice', [{**node, 'selected_fragments': [selected]}], {}, engine.config)
    result, _ = pack_frozen(frozen, 1)
    assert 'The exception is only on weekends.' in result[0]['content']


def test_selected_passage_is_not_recropped_in_next_model_context(make):
    engine, _ = make(mode='raw')
    text = 'Supporting context. ' * 35 + 'The exact amount is $120.'
    engine.add(request('a', [text]))
    node, source = engine.store.nodes('u')[0], engine.store.raw('u')[0]
    selected = fragment(source, 0, len(text))
    reference = engine._reference({**node, 'selected_fragments': [selected]}, 'amount', 'query', 'u')
    projected = engine._model_context({'question': 'amount', 'references': {node['ref']: reference}})
    visible = projected['references'][node['ref']]['evidence_fragments'][0]
    assert visible['text'] == selected['text'] and '$120' in visible['text']
    assert visible['shown_range'] == selected['shown_range']


def test_many_page_winners_merge_without_losing_bound_original_ranges(make):
    engine, provider = make(mode='raw', model_input_chars=8000)
    cards, rows = [], []
    for i in range(9):
        row = {'ref': f'memory:fact-{i}', 'kind':'fact', 'text':f'Purchase {i}.'}
        text = (f'Purchase {i} has separate supporting details. ' * 35) + f' Its exact cost is {120+i} dollars.'
        value = fragment({'ref':f'raw:{i}', 'text':text}, 0, len(text))
        rows.append(row); cards.append({'row':row, 'fragment':value})
    phases = []
    def decide(purpose, payload):
        merged = payload['candidates'][0]['view'] == 'contribution summary'
        phases.append('merge' if merged else 'page')
        if merged:
            assert all(not c['complete_source'] for c in payload['candidates'])
        positions = list(range(len(payload['candidates'])))
        return 'select', {'positions':positions,'coverage':[
            {'evidence':f'Separate purchase {i}', 'positions':[i]} for i in positions]}
    provider.decide = decide
    selected = engine._select_cards('List all purchases and costs', rows, cards, {}, time.monotonic()+20, reason='query')
    assert phases.count('page') > 1 and phases[-1] == 'merge'
    actual = {f['fragment_id']:f for row in selected for f in row['selected_fragments']}
    assert actual == {c['fragment']['fragment_id']:c['fragment'] for c in cards}


def test_contribution_groups_preserve_uncovered_passages_and_overlap():
    cards = [{'row':{'ref':f'memory:{i}'}, 'fragment':{'fragment_id':f'f{i}'}} for i in range(3)]
    groups = contribution_groups(cards, [{'evidence':'connection', 'cards':cards[:2]}])
    assert groups[0]['members'] == cards[:2]
    assert groups[1]['members'] == cards[2:]
