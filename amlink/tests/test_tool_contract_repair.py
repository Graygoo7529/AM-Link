import json
import time
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest

from test_core_repairs import make, request
from amlink.config import Config
from amlink.drafts import decode_review, review_payload, check_review
from amlink.engine import _tool
from amlink.errors import MemoryError
from amlink.observation import Observer
from amlink.providers import Providers, tool_body
from amlink.tool_contract import parse_tool


TOOLS = [_tool('choose', 'Choose a shown position.', {'type': 'object', 'properties': {
    'position': {'type': 'integer', 'enum': [0, 2]}}})]


def response():
    return {'id': 'response-test', 'choices': [{'finish_reason': 'tool_calls', 'message': {
        'role': 'assistant', 'tool_calls': [{'id': 'call-test', 'type': 'function',
            'function': {'name': 'choose', 'arguments': '{"position":2}'}}]}}]}


@pytest.mark.parametrize('fault,code', [
    ('length', 'model_output_incomplete'), ('content_filter', 'model_output_incomplete'),
    ('json', 'model_tool_output_invalid'), ('duplicate', 'model_tool_output_invalid'),
    ('nonfinite', 'model_tool_output_invalid'), ('id', 'model_tool_output_invalid'),
    ('many', 'model_tool_output_invalid'), ('unknown', 'model_unknown_tool'),
    ('missing', 'model_tool_schema_invalid'), ('extra', 'model_tool_schema_invalid'),
    ('foreign', 'model_tool_schema_invalid'), ('boolean', 'model_tool_schema_invalid')])
def test_wire_failure_is_one_attempt_and_has_layer(fault, code):
    data = response()
    choice = data['choices'][0]
    call = choice['message']['tool_calls'][0]
    if fault in {'length', 'content_filter'}:
        choice['finish_reason'] = fault
    elif fault == 'id': del call['id']
    elif fault == 'many': choice['message']['tool_calls'].append(deepcopy(call))
    elif fault == 'unknown': call['function']['name'] = 'foreign'
    else:
        call['function']['arguments'] = {'json': '{', 'duplicate': '{"position":0,"position":2}',
            'nonfinite': '{"position":NaN}', 'missing': '{}', 'extra': '{"position":2,"extra":1}',
            'foreign': '{"position":1}', 'boolean': '{"position":true}'}[fault]
    sent = []
    provider = Providers(replace(Config(), llm_api_key='test'), Observer(), transport=httpx.MockTransport(
        lambda req: (sent.append(json.loads(req.content)) or httpx.Response(200, json=data))))
    with pytest.raises(MemoryError, match=code) as error:
        provider.tool('bfs', 'Choose.', {}, TOOLS, time.monotonic() + 10)
    assert len(sent) == 1 and provider.calls == 1
    assert error.value.detail['layer'] == ('incomplete' if fault in {'length', 'content_filter'} else 'protocol')
    assert sent[0]['max_completion_tokens'] == 1024 and 'max_tokens' not in sent[0]
    assert sent[0]['tool_choice']['function']['name'] == 'choose'
    provider.close()


def test_tool_result_preserves_real_pair_and_limits():
    result = parse_tool(response(), TOOLS)
    name, args = result
    assert (name, args, result.call_id) == ('choose', {'position': 2}, 'call-test')
    assert result.assistant['tool_calls'][0]['id'] == result.call_id
    body = tool_body(Config(), 'reflection_review', '', {}, TOOLS)
    assert body['max_completion_tokens'] == 5000 and body['parallel_tool_calls'] is False


def test_forced_tool_stop_requires_a_complete_valid_call():
    data = response()
    data['choices'][0]['finish_reason'] = 'stop'
    assert parse_tool(data, TOOLS).call_id == 'call-test'
    data['choices'][0]['message'] = {'role': 'assistant', 'content': '{"position":2}'}
    with pytest.raises(MemoryError, match='model_tool_output_invalid'):
        parse_tool(data, TOOLS)


def test_overflowing_json_number_is_rejected_before_schema():
    data = response()
    data['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{"position":1e999}'
    with pytest.raises(MemoryError, match='model_tool_output_invalid'):
        parse_tool(data, TOOLS)


def test_anyof_diagnostics_are_bounded_and_include_field_causes():
    tools = [_tool('choose', 'Pick.', {'type': 'object', 'properties': {
        'position': {'anyOf': [{'type': 'string', 'enum': ['x' * 10000 + str(i)]} for i in range(100)]}}})]
    with pytest.raises(MemoryError, match='model_tool_schema_invalid') as error:
        parse_tool(response(), tools)
    detail = error.value.detail
    assert len(json.dumps(detail)) < 10000
    assert detail['errors'][0]['causes'][0]['path'] == ['position']
    assert detail['errors'][0]['cause_count'] > len(detail['errors'][0]['causes'])


def args_fixture():
    return dict(items=[
        dict(ref='new:bike', kind='fact', text='Bike cost $25.', source_refs=['raw:a']),
        dict(ref='new:helmet', kind='fact', text='Helmet cost $120.', source_refs=['raw:a'])],
        links=[dict(from_ref='new:helmet', to_ref='new:bike', relation='supersedes', source_refs=['raw:a'])])


def test_drop_can_cite_evidence_but_creates_no_support():
    payload = review_payload({'items': [args_fixture()['items'][0]]}, {}, [dict(ref='raw:a', text='Hello.')])
    wire = {'u0': dict(text=None, time_expression='yesterday', time_start='2023-01-01', time_end=None,
        detail='Greeting does not support a bike price.', evidence_positions=[0]),
        'remaining_work': [], 'no_change_reason': 'Only a greeting.'}
    decisions, receipts = check_review(payload, decode_review(payload, wire))
    assert decisions[0]['after'] is None and receipts == []
    assert decisions[0]['evidence_positions'] == [0]


def test_invalid_edge_is_locally_withdrawn_without_rewriting_nodes(make):
    engine, provider = make(mode='raw')
    calls = []
    ordinary = provider.review
    def review(payload):
        calls.append(deepcopy(payload))
        output = ordinary(payload)
        if len(calls) == 1:
            output['reviews'][-1]['replacement_quote'] = 'not in original'
        else:
            assert [u['position'] for u in payload['units']] == [2]
            assert payload['repair_tasks'][0]['code'] == 'reflection_replacement_evidence_missing'
            output['reviews'][0].update(action='drop', detail='Separate purchases, no replacement.', source_positions=[0])
        return output
    provider.review = review
    context = {}
    result = engine._review_draft(args_fixture(), {}, [dict(ref='raw:a', text='Bike cost $25; helmet cost $120.')],
                                 time.monotonic() + 10, context=context)
    assert len(result['items']) == 2 and result['links'] == []
    assert len(calls) == 2 and context['_decision_count'] == 2
    assert engine.store.nodes('u') == []  # Review alone is not a partial commit.


def test_unchanged_bad_edge_stops_and_keeps_approved_nodes(make):
    engine, provider = make(mode='raw')
    context = {}
    with pytest.raises(MemoryError, match='reflection_no_evidence_progress'):
        engine._review_draft(args_fixture(), {}, [dict(ref='raw:a', text='Bike cost $25; helmet cost $120.')],
                             time.monotonic() + 10, context=context)
    assert len(context['pending_mutation']['items']) == 2
    assert len(context['review_checkpoint']['checks']) == 2
    assert len([p for p, _ in provider.calls if p == 'reflection_review']) == 2
    assert engine.store.nodes('u') == []


def test_valid_node_survives_another_nodes_time_repair(make):
    engine, provider = make(mode='raw')
    ordinary = provider.review
    calls = []
    def review(payload):
        calls.append([u['position'] for u in payload['units']])
        out = ordinary(payload)
        if len(calls) == 2:
            assert calls[-1] == [1]
            out['reviews'][0].update(action='revise', text='Jon visited on April 20th.',
                time=dict(time_expression='April 20th', time_start=None, time_end=None))
        return out
    provider.review = review
    args = {'items': [args_fixture()['items'][0], dict(ref='new:visit', kind='event',
        text='Jon visited on April 20, 2023.', source_refs=['raw:a'], time_expression='April 20th',
        time_start='2023-04-20', time_end='2023-04-20')]}
    result = engine._review_draft(args, {}, [dict(ref='raw:a', text='Bike cost $25. Jon visited on April 20th.')], time.monotonic()+10)
    assert calls == [[0, 1], [1]] and result['items'][1]['time_start'] is None


def test_protocol_failure_does_not_accept_partial_review(make):
    engine, provider = make(mode='raw')
    provider.tool = lambda *a: ('review', {'u0': {'text': 'Bike cost $25.'}})
    context = {}
    with pytest.raises(MemoryError, match='reflection_review_incomplete'):
        engine._review_draft(args_fixture(), {}, [dict(ref='raw:a', text='Bike cost $25.')],
                             time.monotonic()+10, context=context)
    assert not context['review_checkpoint']['checks']


def test_checkpoint_source_change_forces_review_and_unknown_version_rejects(make):
    engine, provider = make(mode='raw')
    args = {'items': [args_fixture()['items'][0]]}
    working = [dict(ref='raw:a', text='Bike cost $25.')]
    context = {}
    result = engine._review_draft(args, {}, working, time.monotonic()+10, context=context)
    calls = len(provider.calls)
    engine._review_draft(result, {}, working, time.monotonic()+10, context=context)
    assert len(provider.calls) == calls
    engine._review_draft(result, {}, [dict(ref='raw:a', text='Bike cost $25. Confirmed.')], time.monotonic()+10, context=context)
    assert len(provider.calls) == calls+1
    context['review_checkpoint']['version'] = 99
    with pytest.raises(MemoryError, match='reflection_review_version_unknown'):
        engine._review_draft(result, {}, working, time.monotonic()+10, context=context)


def test_review_decisions_share_main_budget(make):
    engine, provider = make(mode='raw', reflection_steps=1)
    context = {'_decision_count': 1}
    with pytest.raises(MemoryError, match='reflection_tool_budget'):
        engine._review_draft({'items': [args_fixture()['items'][0]]}, {},
                             [dict(ref='raw:a', text='Bike cost $25.')], time.monotonic()+10, context=context)
    assert provider.calls == []


def test_later_page_failure_preserves_earlier_page_repair_tasks(make, monkeypatch):
    engine, provider = make(mode='raw')
    ordinary = provider.review
    calls = []
    def review(payload):
        calls.append(payload)
        if len(calls) == 2:
            raise MemoryError('provider_network', 502)
        out = ordinary(payload)
        out['remaining_work'] = ['Verify the unanchored date before writing.']
        return out
    provider.review = review
    monkeypatch.setattr(engine, '_tool_size', lambda purpose, prompt, payload, tools:
                        len(payload['units']) * engine.config.model_input_chars)
    args = {'items': [dict(ref='new:visit', kind='event', text='Visited on April 20th.',
        source_refs=['raw:a'], time_expression='April 20th', time_start='2023-04-20', time_end=None),
        args_fixture()['items'][0]]}
    context = {}
    with pytest.raises(MemoryError, match='provider_network'):
        engine._review_draft(args, {}, [dict(ref='raw:a', text='Visited on April 20th. Bike cost $25.')],
                             time.monotonic()+10, context=context)
    assert context['review_checkpoint']['tasks'][0]['position'] == 0
    assert context['review_remaining'] == ['Verify the unanchored date before writing.']
    assert len(context['pending_mutation']['items']) == 2
    assert engine.store.nodes('u') == []


def test_changed_old_target_invalidates_saved_review(make):
    engine, provider = make(mode='raw')
    item = dict(ref='memory:alex', kind='person', text='Alex enjoys cycling.', source_refs=['raw:a'])
    projected = {'items': {'memory:alex': dict(item)}}
    working = [dict(ref='raw:a', text='Alex enjoys cycling.')]
    context = {}
    result = engine._review_draft({'items': [item]}, projected, working, time.monotonic()+10, context=context)
    calls = len(provider.calls)
    projected['items']['memory:alex']['text'] = 'Alex enjoys cycling and hiking.'
    engine._review_draft(result, projected, working, time.monotonic()+10, context=context)
    assert len(provider.calls) == calls + 1


def test_real_group_commits_valid_nodes_only_after_edge_repair(make):
    engine, provider = make(reflection_threshold=1)
    ordinary = provider.review
    reviews = []
    def review(payload):
        reviews.append([u['kind'] for u in payload['units']])
        assert all(n['kind'] == 'episode' for n in engine.store.nodes('u'))
        out = ordinary(payload)
        if len(reviews) == 2:
            assert reviews[-1] == ['relation']
            out['reviews'][0].update(action='drop', detail='Separate purchases.', source_positions=[0])
        return out
    def decide(purpose, payload):
        source = payload['working'][0]['ref']
        args = args_fixture()
        for value in args['items'] + args['links']:
            value['source_refs'] = [source]
        if not payload['context']['reflection_control'].get('pending_mutation'):
            return 'reflection_items', {'items': args['items']}
        return 'reflection_relations', {'links': [{**args['links'][0], 'support': 'Both are purchases.'}]}
    provider.decide, provider.review = decide, review
    result = engine.add(request('a', ['Bike cost $25; helmet cost $120.']))
    assert result['success'] and engine.store.state('u')['settled_through'] == 1
    assert len([n for n in engine.store.nodes('u') if n['kind'] == 'fact']) == 2
    assert engine.store.rows('SELECT * FROM edges') == []
    before = len(provider.calls)
    engine.add(request('a', ['Bike cost $25; helmet cost $120.']))
    assert len(provider.calls) == before


def test_schema_annotations_do_not_remove_named_argument_properties():
    tool = _tool('store', '', {'type': 'object', 'properties': {
        'title': {'type': 'string', 'default': ''}, 'default': {'type': 'boolean', 'default': False}}})
    assert set(tool['parameters']['properties']) == {'title', 'default'}
    assert 'default' not in tool['parameters']['properties']['title']
