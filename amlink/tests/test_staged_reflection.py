"""Staged drafts must not weaken grounding, atomicity or failed-Add replay."""
import pytest
from test_core_repairs import make, request
from amlink.errors import MemoryError


def proposal(payload, *, person=True):
    source = payload['working'][0]['ref']
    items = [dict(ref='new:tea', kind='fact', text='Maya likes tea.', source_refs=[source])]
    if person:
        items.append(dict(ref='new:maya', kind='person', text='Maya is the named speaker.', source_refs=[source]))
    return {'items': items}


def relations(payload):
    return {'links': [dict(from_ref='new:tea', to_ref='new:maya', relation='about',
        source_refs=[payload['working'][0]['ref']], support='Maya says she likes tea in this message.')]}


def test_draft_and_links_are_invisible_until_atomic_commit(make):
    engine, provider = make(reflection_threshold=1)
    stages = []
    def decide(purpose, payload):
        assert engine.store.state('u')['settled_through'] == 0
        assert all(n['kind'] == 'episode' for n in engine.store.nodes('u'))
        control = payload['context']['reflection_control']
        stage = control.get('pending_mutation', {}).get('stage', 'initial')
        stages.append(stage)
        if stage == 'initial': return 'reflection_items', proposal(payload)
        if stage == 'relations': return 'reflection_relations', relations(payload)
        assert control['pending_mutation']['items'] and control['pending_mutation']['links']
        assert control['pending_mutation']['links'][0]['support']
        raise AssertionError('Unexpected extra model control turn')
    provider.decide = decide
    req = request('a', ['Speaker: Maya\nI like tea.'])
    assert engine.add(req)['success']
    assert stages == ['initial', 'relations']
    fact = next(n for n in engine.store.nodes('u') if n['kind'] == 'fact')
    assert len(engine.store.edges('u', fact['ref'])) == 1
    assert engine.store.state('u')['settled_through'] == 1
    before = len(provider.calls)
    engine.add(req)
    assert len(provider.calls) == before


def test_failed_draft_replay_never_partially_writes_or_duplicates_nodes(make):
    engine, provider = make(reflection_threshold=1)
    failed = False
    def decide(purpose, payload):
        nonlocal failed
        stage = payload['context']['reflection_control'].get('pending_mutation', {}).get('stage')
        if not stage: return 'reflection_items', proposal(payload)
        if stage == 'relations':
            if not failed:
                failed = True
                raise MemoryError('provider_timeout', 504)
            return 'reflection_relations', relations(payload)
        raise AssertionError('Unexpected extra model control turn')
    provider.decide = decide
    req = request('a', ['Speaker: Maya\nI like tea.'])
    assert engine.add(req)['success']
    assert any(p.get('error') == 'provider_timeout' for plan in engine.store.reflection_plans('u') for p in plan['progress'].values())
    assert engine.store.state('u')['settled_through'] == 0
    assert all(n['kind'] == 'episode' for n in engine.store.nodes('u'))
    calls = len(provider.calls)
    engine.add(req)
    assert len(provider.calls) == calls
    assert len(engine.store.raw('u')) == 1
    assert not [n for n in engine.store.nodes('u') if n['kind'] == 'fact']
    progress = engine.store.reflection_plan('u')['progress']['0']
    assert progress['context']['pending_mutation']['items']
    assert progress['context']['draft_stage'] == 'relations'


def test_review_defect_can_patch_one_node_without_rewriting_others(make):
    engine, provider = make(reflection_threshold=1)
    ordinary_review = provider.review
    def review(payload):
        result = ordinary_review(payload)
        if payload['units'][0]['proposal'].get('text') == 'Maya likes coffee.':
            result['reviews'][0].update(action='revise', text='Maya likes tea.', detail='The source says tea, not coffee.')
            for unit, review in zip(payload['units'], result['reviews']):
                if unit['kind'] == 'relation': review['revised_endpoints'] = ['new:tea']
        return result
    provider.review = review
    def decide(purpose, payload):
        step = payload['step']
        if step == 0:
            value = proposal(payload)
            value['items'][0]['text'] = 'Maya likes coffee.'
            return 'reflection_items', value
        if step == 1: return 'reflection_relations', relations(payload)
        raise AssertionError('Unexpected extra model control turn')
    provider.decide = decide
    engine.add(request('a', ['Speaker: Maya\nI like tea.']))
    assert len(engine.store.nodes('u')) == 3
    assert next(n for n in engine.store.nodes('u') if n['kind']=='fact')['text']=='Maya likes tea.'


def test_uncommitted_draft_cannot_finish_via_stop(make):
    engine, provider = make(reflection_threshold=1)
    provider.decide = lambda purpose, payload: ('reflection_items', proposal(payload)) if payload['step'] == 0 else ('reflection_stop', {'reason': 'No additional semantic change is needed in this fixture.'})
    assert engine.add(request('a', ['Speaker: Maya\nI like tea.']))['success']
    assert any(p.get('error') == 'model_unknown_tool' for plan in engine.store.reflection_plans('u') for p in plan['progress'].values())
    assert engine.store.state('u')['settled_through'] == 0


def test_staged_invalid_relation_can_be_removed_but_not_committed(make):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose, payload):
        if payload['step'] == 0: return 'reflection_items', proposal(payload)
        if payload['step'] == 1:
            invalid = relations(payload)
            invalid['links'][0].update(from_ref='new:maya', to_ref='new:tea')
            return 'reflection_relations', invalid
        if payload['step'] == 2:
            assert payload['context']['reflection_control']['last_gate_error']['invalid_links']
            return 'reflection_relations', {'links': []}
        raise AssertionError('Unexpected extra model control turn')
    provider.decide = decide
    engine.add(request('a', ['Speaker: Maya\nI like tea.']))
    assert len(engine.store.nodes('u')) == 3
    assert all(not engine.store.edges('u', n['ref']) for n in engine.store.nodes('u'))


def test_accepted_nodes_cannot_be_silently_rewritten_in_relation_stage(make):
    engine, provider = make(reflection_threshold=1)
    provider.decide = lambda purpose, payload: ('reflection_items', proposal(payload))
    assert engine.add(request('a', ['Speaker: Maya\nI like tea.']))['success']
    assert any(p.get('error') == 'model_unknown_tool' for plan in engine.store.reflection_plans('u') for p in plan['progress'].values())
    assert engine.store.state('u')['settled_through'] == 0


def test_revision_must_change_the_node_draft(make):
    from amlink.drafts import patch_items
    draft = {'items': [dict(ref='new:maya', kind='person', text='Maya', source_refs=['raw:a'])]}
    with pytest.raises(MemoryError, match='reflection_no_draft_progress'):
        patch_items(draft, {'reason': 'Correct Maya.', 'upsert': draft['items'], 'remove_refs': []})


def test_relation_tool_limits_endpoint_kinds_before_model_generation(make):
    engine, provider = make(reflection_threshold=1)
    original = provider.tool
    seen = []
    def tool(purpose, prompt, payload, tools, deadline):
        for t in tools:
            if t['name'] == 'reflection_relations':
                props = t['parameters']['properties']
                assert 'drop_invalid' not in props
                for alternative in props['links']['items']['anyOf']:
                    p = alternative['properties']
                    if p['relation']['enum'] == ['about']:
                        seen.append(p)
                        assert p['from_ref']['enum'] == ['new:tea']
                        assert p['to_ref']['enum'] == ['new:maya']
        return original(purpose, prompt, payload, tools, deadline)
    provider.tool = tool
    provider.decide = lambda purpose, payload: [
        ('reflection_items', proposal(payload)), ('reflection_relations', relations(payload))][payload['step']]
    engine.add(request('a', ['Speaker: Maya\nI like tea.']))
    assert seen


def test_short_chinese_support_is_not_rejected_by_english_length_threshold(make):
    engine, provider = make(reflection_threshold=1)
    def decide(purpose, payload):
        if payload['step'] == 0: return 'reflection_items', proposal(payload)
        if payload['step'] == 1:
            value = relations(payload)
            value['links'][0]['support'] = '本人说爱茶'
            return 'reflection_relations', value
        raise AssertionError('Unexpected extra model control turn')
    provider.decide = decide
    engine.add(request('a', ['Speaker: Maya\n本人说爱茶。']))
    assert engine.store.state('u')['settled_through'] == 1
