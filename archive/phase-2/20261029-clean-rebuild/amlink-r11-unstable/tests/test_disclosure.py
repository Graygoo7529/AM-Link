"""Evidence ranges must describe the exact original text seen by the model."""
from amlink.evidence import complementary_passages
from amlink.evidence import render_fragment


def test_one_source_keeps_distant_branch_hits():
    text = 'Orchid festival is in May. ' + 'unrelated context. ' * 220 + 'Sapphire ticket costs 72.'
    source = dict(ref='raw:one', text=text, role='user', ordinal=1, session_id='s', source_time=None)
    fragments, coverage = complementary_passages([source], ['Orchid', 'Sapphire'], 1800, 4)
    shown = '\n'.join(f['text'] for f in fragments)
    assert 'Orchid' in shown and 'Sapphire' in shown
    assert len(coverage[0]['shown_ranges']) == 2
    for fragment in fragments:
        start, end = fragment['shown_range']
        assert fragment['text'] == text[start:end]


def test_unicode_ranges_are_original_codepoints():
    text = 'Straße ' * 70 + 'Sapphire is here.'
    source = dict(ref='raw:unicode', text=text, role='user', ordinal=1, session_id='s', source_time=None)
    fragments, _ = complementary_passages([source], ['Sapphire'], 350, 1)
    assert 'Sapphire' in fragments[0]['text']
    start, end = fragments[0]['shown_range']
    assert fragments[0]['text'] == text[start:end]


def test_dense_window_preserves_late_negation_and_distinct_query_terms():
    text = ('Museum public update. ' * 80 +
            'Correction: museum north entrance is NOT wheelchair accessible until Friday. ' +
            'General schedule. ' * 40)
    source = dict(ref='raw:access', text=text, role='user', ordinal=1, session_id='s')
    values, _ = complementary_passages([source], ['museum wheelchair entrance'], 500, 1)
    assert 'NOT wheelchair accessible until Friday' in values[0]['text']
    assert sum(len(render_fragment(v)) + 1 for v in values) <= 500


def test_short_assertions_compete_with_long_repeated_topic_advice():
    sources = [dict(ref='raw:advice', text='The bicycle needs regular maintenance. ' * 90),
               dict(ref='raw:cost', text='I paid 87 for bicycle repairs yesterday. The quote of 99 was cancelled.'),
               dict(ref='raw:time', text='The bicycle repairs were completed on Friday, two days after booking.')]
    values, _ = complementary_passages(sources, ['bicycle repairs'], 700, 3)
    shown = ' '.join(v['text'] for v in values)
    assert '87' in shown and '99 was cancelled' in shown and 'Friday' in shown
    assert sum(len(render_fragment(v)) + 1 for v in values) <= 700
