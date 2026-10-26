"""Local draft edits and a source-to-statement review before atomic writing."""
from copy import deepcopy
import re

from .errors import MemoryError
from .projection import visible_fragments
from .text import digest


def patch_items(draft, patch):
    if not isinstance(patch.get('reason'), str) or not patch['reason'].strip():
        raise MemoryError('reflection_patch_invalid', 502)
    upsert, remove = patch.get('upsert'), patch.get('remove_refs')
    if not isinstance(upsert, list) or not isinstance(remove, list):
        raise MemoryError('reflection_patch_invalid', 502)
    result = deepcopy(draft)
    old = {item['ref']: item for item in result.get('items', [])}
    if any(ref not in old for ref in remove) or len(set(remove)) != len(remove):
        raise MemoryError('reflection_patch_unknown_item', 502)
    if any(not isinstance(item, dict) or not isinstance(item.get('ref'), str) for item in upsert):
        raise MemoryError('reflection_patch_invalid', 502)
    if len({item['ref'] for item in upsert}) != len(upsert):
        raise MemoryError('reflection_patch_ambiguous', 502)
    old = {ref: item for ref, item in old.items() if ref not in remove}
    for item in upsert:
        old[item['ref']] = item
    result['items'] = list(old.values())
    if len(old) > 12:
        raise MemoryError('reflection_item_draft_invalid', 502)
    if digest(result) == digest(draft):
        raise MemoryError('reflection_no_draft_progress', 409)
    return result


def review_payload(arguments, projected, working):
    """Only the same source ranges shown to the writing model are reviewable."""
    visible = visible_fragments(projected, working)
    units, sources, index = [], [], {}
    for kind, values in [('item', arguments.get('items', [])), ('relation', arguments.get('links', []))]:
        for value in values:
            positions = []
            for v in visible:
                if not v['origin_ref'].startswith('raw:'):
                    continue
                start = 0
                while start < len(v['text']):
                    end = min(start + 700, len(v['text']))
                    if end < len(v['text']):
                        boundaries = list(re.finditer(r'[.!?。！？]\s|\n', v['text'][start:end]))
                        if boundaries and boundaries[-1].end() > 300:
                            end = start + boundaries[-1].end()
                    key = (v['origin_ref'], v['content_digest'], v['start'] + start, v['start'] + end)
                    if key not in index:
                        index[key] = len(sources)
                        sources.append({'position': len(sources), 'source_ref': v['origin_ref'], 'text': v['text'][start:end],
                            'start': v['start'] + start, 'end': v['start'] + end, 'content_digest': v['content_digest'],
                            'role': v.get('role'), 'source_time': v.get('source_time'), 'session_id': v.get('session_id')})
                    positions.append(index[key])
                    start = end
            units.append({'position': len(units), 'kind': kind, 'proposal': value,
                'source_positions': list(dict.fromkeys(positions))})
    return {'units': units, 'sources': sources, 'endpoints': [
        {'ref': item['ref'], 'kind': item['kind'], 'text': item['text']}
        for item in [*projected.get('items', {}).values(), *arguments.get('items', [])]]}


def check_review(payload, output):
    reviews = output.get('reviews')
    if not isinstance(reviews, list) or len(reviews) != len(payload['units']):
        raise MemoryError('reflection_review_incomplete', 502)
    seen, decisions, receipts = set(), [], []
    units = {u['position']: u for u in payload['units']}
    for review in reviews:
        position = review.get('position')
        if type(position) is not int or position in seen or position not in units:
            raise MemoryError('reflection_review_invalid', 502)
        seen.add(position)
        unit = units[position]
        action = review.get('action')
        decision = {'position': position, 'kind': unit['kind'], 'before': unit['proposal'],
                    'action': action, 'detail': review.get('detail', '')}
        if action == 'drop':
            if not decision['detail']:
                raise MemoryError('reflection_review_invalid', 502)
            decisions.append({**decision, 'after': None})
            continue
        if action not in {'keep', 'revise'} or not review.get('source_positions'):
            raise MemoryError('reflection_review_invalid', 502)
        corrected = deepcopy(unit['proposal'])
        if action == 'revise':
            if unit['kind'] != 'item' or not isinstance(review.get('text'), str) or not review['text'].strip():
                raise MemoryError('reflection_review_invalid', 502)
            corrected['text'] = review['text']
            if review.get('time') is not None:
                if not isinstance(review['time'], dict) or set(review['time']) != {'time_expression', 'time_start', 'time_end'}:
                    raise MemoryError('reflection_review_invalid', 502)
                corrected.update(review['time'])
        supported = set()
        for index in review['source_positions']:
            if type(index) is not int or index not in unit['source_positions']:
                raise MemoryError('reflection_review_invalid', 502)
            source = payload['sources'][index]
            supported.add(source['source_ref'])
            receipts.append({'position': position, 'kind': unit['kind'], 'proposal': unit['proposal'],
                'source_ref': source['source_ref'], 'start': source['start'],
                'end': source['end'], 'quote': source['text'],
                'content_digest': source['content_digest']})
        corrected['source_refs'] = sorted(supported)
        decisions.append({**decision, 'after': corrected})
    return decisions, receipts
