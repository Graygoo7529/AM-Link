import json
import time
from dataclasses import replace

import pytest
from test_core_repairs import make, request, graph
from amlink.projection import Choices
from amlink.text import dumps
from amlink.schemas import SearchRequest
from amlink.errors import MemoryError


def test_choices_decode_wire_positions_not_sorted_dictionary_keys():
    choices = Choices.freeze([{"ref": "memory:z", "narrative": "Zulu"}, {"ref": "memory:a", "narrative": "Alice"}])
    wire = json.loads(dumps(list(choices.rows)))
    assert choices.resolve(wire[0]["position"]) == wire[0]["ref"] == "memory:z"
    assert choices.subset([1, 1, 0]) == ["memory:a", "memory:z"]
    with pytest.raises(MemoryError):
        choices.subset([0, True])


def test_bfs_positions_follow_budgeted_serialized_choices(make):
    engine, provider = make(mode="raw", context_chars=5000)
    for i in range(12):
        engine.add(request(str(i), [f"Marker {i} " + 'Narrative. ' * 500]))
    rows = engine.store.nodes('u')
    context = {"question": "Marker", "references": {}, "items": {}, "edges": [], "frontier": [r['ref'] for r in rows]}
    engine._add_context_refs('u', context, rows, time.monotonic() + 10)
    engine.config = replace(engine.config, mode='graph', search_model=True)
    selected = []
    def decide(purpose, payload):
        actual = json.loads(dumps(payload))['context']['choices']
        assert actual and len(actual) < len(rows)
        selected.append(actual[0]['ref'])
        return 'bfs_action', {'action': 'inspect', 'frontier_position': actual[0]['position'], 'page_position': None}
    provider.decide = decide
    action = engine._next_bfs_action('u', 'Marker', context, time.monotonic() + 10)
    assert action.ref == selected[0]


def test_backlink_select_then_inspect_uses_result_in_next_decision(make):
    engine, provider = make(mode='raw', search_model=True, max_neighbors=1, search_steps=5)
    items = graph(engine)
    root = items[0]['ref']
    source = engine.store.raw('u')[0]['ref']
    extra = {'ref': 'memory:event-noise', 'kind': 'event', 'text': 'An unrelated visit.', 'source_refs': [source]}
    engine.store.commit_mutation('u', {'items': [extra], 'links': [{'from_ref': extra['ref'], 'to_ref': root, 'relation': 'about', 'source_refs': [source]}], 'forget': []}, watermark=1, fingerprint='x', vectors={})
    engine.config = replace(engine.config, mode='graph')
    engine._search_refs = lambda *a, **k: [engine.store.get('u', root)]
    seen = []
    def decide(purpose, payload):
        seen.append(purpose)
        if purpose == 'select':
            return 'select', {'positions': [row['position'] for row in payload['candidates'] if row['ref'] == items[1]['ref']]}
        choices = json.loads(dumps(payload))['context']['choices']
        count = seen.count('bfs')
        if count == 1:
            return 'bfs_action', {'action': 'backlinks', 'frontier_position': next(r['position'] for r in choices if r['ref'] == root)}
        if count == 2:
            return 'bfs_action', {'action': 'inspect', 'frontier_position': next(r['position'] for r in choices if r['ref'] == items[1]['ref'])}
        assert payload['context']['disclosures']
        return 'bfs_action', {'action': 'stop'}
    provider.decide = decide
    engine.search(SearchRequest(user_id='u', query='Caroline', top_k=2))
    assert seen[:3] == ['bfs', 'select', 'bfs']


def test_bfs_malformed_followup_stops_with_existing_evidence(make):
    engine, provider = make(mode='raw', search_model=True)
    item = graph(engine)[0]
    engine.config = replace(engine.config, mode='graph')
    engine._search_refs = lambda *a, **k: [engine.store.get('u', item['ref'])]
    calls = []

    def decide(purpose, payload):
        calls.append(purpose)
        if purpose == 'bfs':
            return 'bfs_inspect', {
                'action': 'inspect', 'reason': 'read the item',
                'target': {'frontier_position': 0, 'page_position:null': None},
            }
        return 'bfs_stop', {'action': 'stop'}

    provider.decide = decide
    result = engine.search(SearchRequest(user_id='u', query='Caroline', top_k=1))
    assert calls == ['bfs']
    assert result['data']


def test_bfs_stale_position_stops_with_existing_evidence(make):
    engine, provider = make(mode='raw', search_model=True)
    item = graph(engine)[0]
    engine.config = replace(engine.config, mode='graph')
    engine._search_refs = lambda *a, **k: [engine.store.get('u', item['ref'])]

    def decide(purpose, payload):
        if purpose == 'bfs':
            return 'bfs_backlinks', {'action': 'backlinks', 'frontier_position': 99, 'reason': 'stale'}
        return 'bfs_stop', {'action': 'stop'}

    provider.decide = decide
    result = engine.search(SearchRequest(user_id='u', query='Caroline', top_k=1))
    assert result['data']


def test_bfs_invalid_provider_tool_output_stops_with_existing_evidence(make):
    engine, provider = make(mode='raw', search_model=True)
    item = graph(engine)[0]
    engine.config = replace(engine.config, mode='graph')
    engine._search_refs = lambda *a, **k: [engine.store.get('u', item['ref'])]
    original = provider.tool

    def invalid_bfs_output(purpose, prompt, payload, tools, deadline):
        if purpose == 'bfs':
            raise MemoryError('model_tool_output_invalid', 502)
        return original(purpose, prompt, payload, tools, deadline)

    provider.tool = invalid_bfs_output
    result = engine.search(SearchRequest(user_id='u', query='Caroline', top_k=1))
    assert result['data']
def test_query_expansion_discards_invented_dates_without_retry(make):
    engine, provider = make(search_model=True)
    seen = []
    engine.store.lexical = lambda user, branch, limit, **kw: seen.append(branch) or []
    provider.decide = lambda *args: ('query_expansion', {'queries': [
        'purchases in 2023', 'repair expenses this year']})
    engine._search_refs('u', 'What was my total spending this year?', {}, time.monotonic() + 10)
    assert seen == ['What was my total spending this year?', 'repair expenses this year']
    assert len(provider.calls) == 1


def test_query_expansion_preserves_explicit_numeric_constraints(make):
    engine, provider = make(search_model=True)
    seen = []
    engine.store.lexical = lambda user, branch, limit, **kw: seen.append(branch) or []
    provider.decide = lambda *args: ('query_expansion', {'queries': ['purchases in 2023']})
    engine._search_refs('u', 'What was my total spending in 2023?', {}, time.monotonic() + 10)
    assert seen[-1] == 'purchases in 2023'
