"""Global comparison of page-selected contributions, with lossless member maps."""
from .evidence import _excerpt_with_range
from .text import excerpt


def members(card):
    return card.get('members', [card])


def contribution_groups(selected, contributions):
    """Notes navigate; their exact previously selected passages remain evidence."""
    groups, covered, seen = [], set(), set()
    for contribution in contributions:
        cards = contribution['cards']
        identity = tuple(sorted((c['row']['ref'], c['fragment']['fragment_id']) for c in cards))
        if not identity or identity in seen:
            continue
        seen.add(identity)
        covered.update(identity)
        groups.append({'row': cards[0]['row'], 'members': cards, 'note': contribution['evidence']})
    ungrouped = {}
    for card in selected:
        key = (card['row']['ref'], card['fragment']['fragment_id'])
        if key not in covered:
            ungrouped.setdefault(card['row']['ref'], []).append(card)
    groups.extend({'row': cards[0]['row'], 'members': cards, 'note': 'Selected passages without a contribution note.'}
                  for cards in ungrouped.values())
    return groups


def contribution_view(group, query, width):
    cards = group['members']
    refs = list(dict.fromkeys(c['row']['ref'] for c in cards))
    lines = ['PAGE SELECTION NOTE (untrusted, not an answer): ' + excerpt(group['note'], width // 2, query),
             f'Bound to {len(cards)} previously read passages. References: ' + ', '.join(refs),
             'Excerpts below are partial; selecting this card retains every bound original passage.']
    # This is a navigation view, never a new evidence fragment or read receipt.
    for card in cards[:2]:
        value = card['fragment']
        text, (start, end), _ = _excerpt_with_range(value['text'], max(60, width // 4), query)
        lines.append(f"Original {value['origin_ref']} [{value['start']+start}:{value['start']+end}]: {text}")
    return '\n'.join(lines)
