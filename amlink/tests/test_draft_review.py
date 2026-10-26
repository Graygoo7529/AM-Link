import pytest
from amlink.drafts import patch_items, review_payload, check_review
from amlink.errors import MemoryError


def test_patch_keeps_untouched_nodes_and_replacement_is_remove_then_upsert():
    draft = {'items': [{'ref': 'new:a', 'text': 'old'}, {'ref': 'new:b', 'text': 'unchanged'}], 'forget': []}
    value = patch_items(draft, {'reason': 'correct a', 'remove_refs': ['new:a'], 'upsert': [{'ref': 'new:a', 'text': 'new'}]})
    assert {n['ref']: n['text'] for n in value['items']} == {'new:a': 'new', 'new:b': 'unchanged'}
    assert draft['items'][0]['text'] == 'old'


def test_review_requires_all_cited_sources_and_expands_original_positions():
    working = [{'ref': 'raw:a', 'text': 'Maya paid $25, not $50.'}, {'ref': 'raw:b', 'text': 'She bought a chain.'}]
    args = {'items': [{'ref': 'new:chain', 'kind': 'fact', 'text': 'Maya bought a chain for $25.', 'source_refs': ['raw:a', 'raw:b']}]}
    payload = review_payload(args, {}, working)
    output = {'reviews': [{'position': 0, 'action': 'keep', 'text': None, 'detail': 'amount', 'source_positions': [0]}]}
    issues, receipts = check_review(payload, output)
    assert issues[0]['after']['source_refs'] == ['raw:a']
    assert receipts[0]['start'] == 0 and receipts[0]['end'] == len(working[0]['text'])
    output['reviews'][0]['source_positions'].append(1)
    assert check_review(payload, output)[0][0]['after']['source_refs'] == ['raw:a', 'raw:b']
    output['reviews'][0]['source_positions'] = [99]
    with pytest.raises(MemoryError, match='review_invalid'): check_review(payload, output)


def test_review_does_not_load_hidden_sources_from_storage():
    args = {'items': [{'ref': 'new:claim', 'kind': 'fact', 'source_refs': ['raw:hidden'], 'text': 'hidden'}]}
    payload = review_payload(args, {}, [{'ref': 'raw:shown', 'text': 'shown'}])
    assert all(s['source_ref'] != 'raw:hidden' for s in payload['sources'])
    issues, receipts = check_review(payload, {'reviews': [{'position': 0, 'action': 'drop', 'text': None, 'detail': 'No supporting visible source.', 'source_positions': []}]})
    assert issues and not receipts
