"""Bounded, checkpointed draft editing. Only the caller can commit the whole group."""
from copy import deepcopy

from .drafts import REVIEW_PROMPT, decode_review, review_payload, review_schema, review_units
from .errors import MemoryError
from .projection import visible_fragments
from .local_reflection import completion
from .text import digest


def unit_key(unit):
    p = unit['proposal']
    return ('item:' + p['ref'] if unit['kind'] == 'item' else
            'relation:' + digest([p['from_ref'], p['relation'], p['to_ref']]))


def consume_decision(context, limit):
    used = context.get('_decision_count', 0)
    if used >= limit:
        raise MemoryError('reflection_tool_budget', 504)
    context['_decision_count'] = used + 1


def review_draft(engine, arguments, projected, working, deadline, context, tool):
    state = context.setdefault('review_checkpoint', {'version': 1, 'keys': {}, 'checks': {}, 'rounds': 0})
    if state.get('version') != 1:
        raise MemoryError('reflection_review_version_unknown', 503)
    current = deepcopy(arguments)
    identities = [ref for item in current.get('items', []) if item['kind'] == 'person'
        for ref in context.get('identity_queries', {}).get(item['ref'], {}).get('refs', [])
        if ref in context.get('inspections', {}) and any(v.get('item_ref') == ref for v in visible_fragments(projected))]
    all_decisions, shown, tasks = [], [], state.get('tasks', [])
    initial = review_payload(arguments, projected, working, identities)
    support_only = bool(initial['units']) and not arguments.get('forget') and all(
        u.get('review_task') == 'support_addition' for u in initial['units'])

    def save_draft():
        context['pending_mutation'] = {k: v for k, v in current.items() if k != 'links'}
        context['pending_links'] = current.get('links', [])

    def build():
        full = review_payload(current, projected, working, identities)
        source_keys = state.setdefault('source_keys', {})
        positions = {}
        for source in full['sources']:
            key = digest([source['source_ref'], source['content_digest'], source['start'], source['end']])
            if key not in source_keys:
                source_keys[key] = len(source_keys)
            positions[source['position']] = source_keys[key]
            source['position'] = source_keys[key]
        for u in full['units']:
            u['source_positions'] = [positions[p] for p in u['source_positions']]
            key = unit_key(u)
            if key not in state['keys']:
                state['keys'][key] = len(state['keys'])
            u['position'] = state['keys'][key]
        return full

    def fingerprint(unit, full):
        refs = {unit['proposal'].get('from_ref'), unit['proposal'].get('to_ref')}
        return digest([unit['proposal'], unit.get('review_task'), unit.get('added_source_refs'),
            [s for s in full['sources'] if s['position'] in unit['source_positions']],
            [e for e in full['endpoints'] if e['ref'] in refs or e['ref'] in identities],
            [e for e in full['old_targets'] if e['ref'] == unit['proposal'].get('ref')]])

    def payload_for(page, full):
        refs = {ref for u in page for ref in (u['proposal'].get('from_ref'), u['proposal'].get('to_ref')) if ref}
        refs.update(u['proposal']['ref'] for u in page if u['kind'] == 'item' and u['proposal']['ref'].startswith('memory:'))
        refs.update(identities)
        positions = {i for u in page for i in u['source_positions']}
        keys = {u['position'] for u in page}
        return {'task': ('Edit only these unresolved draft units. These changes are uncommitted; other approved draft units persist. '
                        'Previously saved independent nodes remain stored: ' + ', '.join(context.get('committed_node_refs', []))),
            'repair_tasks': [t for t in tasks if t['position'] in keys],
            'units': [{**u, 'review_key': f"u{u['position']}"} for u in page],
            'sources': [s for s in full['sources'] if s['position'] in positions],
            'endpoints': [e for e in full['endpoints'] if e['ref'] in refs],
            'old_targets': [e for e in full['old_targets'] if e['ref'] in refs],
            'identity_targets': [e for e in full['endpoints'] if e['ref'] in identities]}

    def offered(payload):
        return [tool('review', 'Write final faithful statements; keep or withdraw supported connections.', review_schema(payload))]

    try:
        while True:
            full = build()
            pending = [u for u in full['units'] if state['checks'].get(unit_key(u)) != fingerprint(u, full)]
            if not pending:
                break
            if state['rounds'] >= 3:
                raise MemoryError('reflection_review_repair_budget', 409, detail={
                    'format_version': 1, 'layer': 'business', 'committed': False, 'tasks': tasks})
            signature = digest([pending, tasks, [fingerprint(u, full) for u in pending]])
            if signature == state.get('last_request'):
                raise MemoryError('reflection_no_evidence_progress', 409)
            state['last_request'] = signature
            state['rounds'] += 1
            # First try a joint review. Split only by the actual serialized input limit.
            pages, rest = [], pending[:]
            while rest:
                page = rest[:]
                while len(page) > 1 and engine._tool_size('reflection_review', REVIEW_PROMPT,
                        payload_for(page, full), offered(payload_for(page, full))) > engine.config.model_input_chars:
                    page = page[:-1]
                if engine._tool_size('reflection_review', REVIEW_PROMPT, payload_for(page, full),
                                    offered(payload_for(page, full))) > engine.config.model_input_chars:
                    raise MemoryError('reflection_review_budget', 413)
                pages.append(page)
                rest = rest[len(page):]
            new_tasks, resolutions, processed = [], [], set()
            for page in pages:
                # Reconstruct endpoints after any preceding page changed nodes.
                live = build()
                live_by_key = {unit_key(u): u for u in live['units']}
                page = [live_by_key[unit_key(u)] for u in page if unit_key(u) in live_by_key]
                if not page:
                    continue
                payload = payload_for(page, live)
                consume_decision(context, engine.config.reflection_steps)
                with engine.observer.span('reflection', 'statement source review', inputs=payload) as event:
                    _, wire = engine._call_tool('reflection_review', REVIEW_PROMPT, payload, offered(payload), deadline)
                    # Decode the WHOLE wire before accepting any individual business result.
                    output = decode_review(payload, wire)
                    decisions, receipts, issues = review_units(payload, output)
                    resolutions.append(output)
                    new_tasks.extend(issues)
                    processed.update(u['position'] for u in page)
                    changed, removed = set(), set()
                    items = {i['ref']: i for i in current.get('items', [])}
                    links = {unit_key({'kind': 'relation', 'proposal': e}): e for e in current.get('links', [])}
                    for d in decisions:
                        if d['kind'] != 'item':
                            continue
                        ref = d['before']['ref']
                        if d['after'] is None:
                            items.pop(ref, None)
                            removed.add(ref)
                        else:
                            items[ref] = d['after']
                            if digest(d['before']) != digest(d['after']):
                                changed.add(ref)
                    # Invalid nodes stay as draft, never as approved units.
                    for d in decisions:
                        if d['kind'] != 'relation':
                            continue
                        edge = d['before']
                        key = unit_key({'kind': 'relation', 'proposal': edge})
                        affected = {edge['from_ref'], edge['to_ref']} & changed
                        if d['after'] is None or {edge['from_ref'], edge['to_ref']} & removed:
                            links.pop(key, None)
                            d.update(after=None, action='drop')
                        elif affected:
                            d['recheck_required'] = True
                            new_tasks.append({'position': d['position'], 'kind': 'relation',
                                'code': 'endpoint_changed', 'committed': False,
                                'next_action': 'Evaluate this connection against the FINAL endpoint statements now displayed.'})
                        else:
                            links[key] = d['after']
                    for key, edge in list(links.items()):
                        if {edge['from_ref'], edge['to_ref']} & removed:
                            links.pop(key)
                            all_decisions.append({'kind': 'relation', 'before': edge, 'after': None,
                                'action': 'drop', 'detail': 'Dependent draft endpoint was withdrawn.'})
                    current['items'], current['links'] = list(items.values()), list(links.values())
                    after = build()
                    by_key = {unit_key(u): u for u in after['units']}
                    for d in decisions:
                        key = unit_key({'kind': d['kind'], 'proposal': d['before']})
                        if d['after'] and not d.get('recheck_required') and key in by_key:
                            state['checks'][key] = fingerprint(by_key[key], after)
                        else:
                            state['checks'].pop(key, None)
                    # Any pre-existing edge review depending on changed nodes becomes stale.
                    for key, u in by_key.items():
                        if u['kind'] == 'relation' and {u['proposal']['from_ref'], u['proposal']['to_ref']} & changed:
                            state['checks'].pop(key, None)
                    accepted = {d['position'] for d in decisions if d['after'] and not d.get('recheck_required')}
                    receipts = [r for r in receipts if r['position'] in accepted]
                    engine.observer.output(event, {'format_version': 2, 'round': state['rounds'],
                        'committed': False, 'reviews': output, 'decisions': decisions, 'issues': issues,
                        'source_receipts': receipts, 'remaining_work': output['remaining_work'],
                        'semantic_status': 'model_reviewed_not_ground_truth'}, kind='context', title='局部审查：保留、修订与待办')
                    all_decisions.extend(decisions)
                    for source in payload['sources']:
                        row = {'ref': source['source_ref'], 'text': source['text'], 'text_fragment': {
                            'origin_ref': source['source_ref'], 'content_digest': source['content_digest'],
                            'start': source['start'], 'end': source['end'],
                            'fragment_id': digest([source['source_ref'], source['content_digest'], source['start'], source['end']])}}
                        shown.extend(visible_fragments({}, [row]))
                    shown.extend(v for v in visible_fragments(projected) if any(
                        n['ref'] == v['origin_ref'] and v['text'] in n['text']
                        for n in [*payload['endpoints'], *payload['old_targets']]))
                    save_draft()
                    # A later page may fail: retain this page's precise tasks and
                    # all still-unvisited work along with its accepted draft.
                    state['tasks'] = [t for t in tasks if t['position'] not in processed] + new_tasks
                    context['review_remaining'] = list(dict.fromkeys([
                        *context.get('review_remaining', []), *output['remaining_work']]))
            tasks = new_tasks
            state['tasks'] = tasks
            context['review_remaining'] = list(dict.fromkeys(t for r in resolutions for t in r['remaining_work']))
            empty = not current.get('items') and not current.get('links') and not current.get('forget')
            if empty and not tasks and not context['review_remaining'] and not context.get('committed_node_refs'):
                reasons = [r['no_change_reason'] for r in resolutions if r.get('no_change_reason')]
                if not reasons:
                    raise MemoryError('reflection_review_empty', 409)
                context['_completion'] = completion(reasons[0], unresolved=(arguments.get('basis') == 'resolve_conflict' or
                    (arguments.get('basis') == 'update_existing' and not support_only)))
            # Already successful decisions are now checkpoints, not repeated model assignments.
            repair_signature = digest([current, tasks, [fingerprint(u, full) for u in full['units']]])
            if tasks and repair_signature == state.get('last_repair'):
                raise MemoryError('reflection_no_evidence_progress', 409)
            state['last_repair'] = repair_signature
        if not full['units'] and not current.get('forget') and not context.get('_completion') and not context.get('review_remaining') and not context.get('committed_node_refs'):
            raise MemoryError('reflection_completion_invalid', 502)
        return current
    finally:
        save_draft()
        if shown:
            engine._record_visible(context, {'disclosures': list({v['fragment_id']: v for v in shown}.values())}, 'reflection_review_pages')
            context['visible_source_refs'] = sorted({v['origin_ref'] for v in shown if v['origin_ref'].startswith('raw:')})
        with engine.observer.span('reflection', 'reviewed draft', inputs={'proposed': arguments}) as event:
            engine.observer.output(event, {'format_version': 2, 'items': current.get('items', []),
                'links': current.get('links', []), 'decisions': all_decisions, 'tasks': state.get('tasks', []),
                'rounds': state['rounds'], 'committed': False, 'approved_units': list(state['checks']),
                'remaining_work': context.get('review_remaining', [])}, kind='memory', title='本组未提交草案与审查进度')
