import json
import time

from test_core_repairs import make, request
from amlink.config import Config
from amlink.providers import tool_body
from amlink.packing import freeze_pack, pack_frozen
from amlink.evidence import fragment


def test_model_serialization_preserves_task_before_material_without_changing_hash_format():
    body = tool_body(Config(), 'select', 'Select evidence.', {'question': 'How much?', 'candidates': ['long material']}, [])
    text = body['messages'][1]['content']
    assert text.index('question') < text.index('candidates')
    assert json.loads(text)['data']['question'] == 'How much?'


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
