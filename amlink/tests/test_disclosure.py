"""Evidence ranges must describe the exact original text seen by the model."""
from amlink.evidence import complementary_passages


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
