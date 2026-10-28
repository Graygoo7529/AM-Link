"""Encode test decisions in the current provider-facing review protocol."""


def review_output(payload, output):
    result = {'remaining_work': output.get('remaining_work', []),
              'no_change_reason': output.get('no_change_reason') or (
                  output.get('reason') if output.get('resolution') == 'episode_only' else None)}
    units = {u['position']: u for u in payload['units']}
    for review in output['reviews']:
        unit = units[review['position']]
        value = {key: review[key] for key in ('action', 'detail')}
        value['evidence_positions'] = review['source_positions']
        if unit['kind'] == 'item':
            value.pop('action')
            value.update(text=review.get('text'), **{key: (review.get('time') or {}).get(key)
                for key in ('time_expression', 'time_start', 'time_end')})
            if review['action'] == 'keep':
                value.update({key: unit['proposal'].get(key) for key in ('text', 'time_expression', 'time_start', 'time_end')})
        else:
            if unit['proposal'].get('relation') == 'supersedes':
                value['replacement_quote'] = review.get('replacement_quote')
        result[f"u{review['position']}"] = value
    return result
