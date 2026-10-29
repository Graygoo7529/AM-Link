"""Typed candidate connections; choosing a legal shape never proves its meaning."""
from .errors import MemoryError
from .reflection import _relation_kinds_valid


def connection_menu(nodes, proposed_refs):
    by_ref = {n['ref']: n for n in nodes}
    result = []
    for left in by_ref.values():
        for right in by_ref.values():
            if left['ref'] == right['ref'] or (proposed_refs and not ({left['ref'], right['ref']} & set(proposed_refs))):
                continue
            for relation in ('about', 'contains', 'supersedes', 'contradicts', 'same_event_as'):
                if not _relation_kinds_valid(left.get('kind'), right.get('kind'), relation):
                    continue
                if relation in {'contradicts', 'same_event_as'} and left['ref'] > right['ref']:
                    continue
                shared = sorted(set(left.get('source_refs', [])) & set(right.get('source_refs', [])))
                if relation == 'contains' and not shared:
                    continue
                result.append(dict(position=len(result), from_ref=left['ref'], relation=relation,
                    to_ref=right['ref'], shared_sources=shared if relation == 'contains' else [],
                    narrative=f"{left['kind']} {left['ref']} —{relation}→ {right['kind']} {right['ref']}"))
    return result


def resolve_connections(arguments, menu):
    if set(arguments) != {'links'} or not isinstance(arguments['links'], list):
        raise MemoryError('reflection_relation_output_invalid', 502)
    result = []
    for link in arguments['links']:
        if not isinstance(link, dict) or set(link) != {'connection_position', 'source_refs', 'support'}:
            raise MemoryError('reflection_relation_output_invalid', 502)
        position = link['connection_position']
        if type(position) is not int or not 0 <= position < len(menu):
            raise MemoryError('reflection_relation_position_invalid', 502)
        if not isinstance(link['source_refs'], list) or not link['source_refs'] or not isinstance(link['support'], str) or not link['support'].strip():
            raise MemoryError('reflection_relation_output_invalid', 502)
        candidate = menu[position]
        result.append({k: candidate[k] for k in ('from_ref', 'relation', 'to_ref')} |
                      {'source_refs': link['source_refs'], 'support': link['support']})
    return result
