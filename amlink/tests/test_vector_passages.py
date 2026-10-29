from dataclasses import replace
import time

import pytest

from test_core_repairs import make, request
from amlink.errors import MemoryError
from amlink.vector_index import MAX_INPUT_BYTES, slices


@pytest.mark.parametrize('text', ['a paragraph.\n' * 2000, '中文原文🙂，不能丢失。\n' * 2000], ids=['english', 'chinese-emoji'])
def test_utf8_slices_are_lossless_and_bounded(text):
    parts = list(slices(text))
    assert ''.join(p['text'] for p in parts) == text
    assert len(parts) > 1
    assert all(len(p['text'].encode('utf-8')) <= MAX_INPUT_BYTES for p in parts)
    assert all(text[p['start']:p['end']] == p['text'] for p in parts)


def test_late_embedding_failure_rolls_back_whole_add(make):
    engine, provider = make(mode='raw', embedding_enabled=True, embedding_batch=1)
    original, calls = provider.embed, []
    def embed(texts, deadline):
        calls.append(texts)
        if len(calls) == 2:
            raise MemoryError('provider_timeout', 504)
        return original(texts, deadline)
    provider.embed = embed
    with pytest.raises(MemoryError, match='provider_timeout'):
        engine.add(request('long', ['正文🙂' * 3000]))
    assert len(calls) == 2
    assert engine.store.raw('u') == [] and engine.store.nodes('u') == []
    assert engine.store.rows('SELECT * FROM vectors') == []
    assert engine.store.request('u', 'long') is None


def test_vector_tail_is_returned_as_original_range_and_user_isolated(make):
    engine, provider = make(mode='raw', embedding_enabled=True)
    provider.embed = lambda texts, deadline: [[1.0, 0.0] if 'violet' in t or t == 'special color' else [0.0, 1.0] for t in texts]
    text = 'ordinary unrelated material.\n' * 400 + 'The final special hue is violet.'
    engine.add(request('tail', [text]))
    rows = engine._search_refs('u', 'special color', {}, time.monotonic() + 10)
    assert len(rows) == 1  # Many vector slices cannot occupy the candidate list.
    projected = engine._reference(rows[0], 'special color', 'query', 'u')
    assert any('violet' in f['text'] and f['origin_ref'].startswith('raw:') for f in projected['evidence_fragments'])
    assert list(engine.store.vector_rows('other', provider.embedding_fingerprint)) == []
    raw = engine.store.raw('u')[0]['ref']
    engine.store.commit_mutation('u', dict(items=[], links=[], forget=[dict(source_refs=[raw], memory_refs=[], instruction_refs=[])]),
        watermark=1, fingerprint=provider.embedding_fingerprint, vectors={})
    assert not engine.store.rows('SELECT * FROM vectors')
