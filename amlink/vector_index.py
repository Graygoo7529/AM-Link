"""Lossless bounded vector slices; memory bodies keep their original identity."""
from __future__ import annotations

import math
import re

from .text import digest

# Qwen's byte-level BPE cannot require more ordinary tokens than UTF-8 bytes.
# Leave headroom below v4's 8192-token service limit, including service markers.
MAX_INPUT_BYTES = 6000
INDEX_VERSION = 'utf8-passages-v1'


def slices(text):
    start = 0
    while start < len(text):
        end, size = start, 0
        while end < len(text):
            count = len(text[end].encode('utf-8'))
            if size + count > MAX_INPUT_BYTES:
                break
            size += count
            end += 1
        if end < len(text):
            boundaries = list(re.finditer(r'\n|[.!?。！？](?:\s|$)', text[start:end]))
            useful = [m.end() for m in boundaries if m.end() >= (end - start) // 2]
            if useful:
                end = start + useful[-1]
        yield {'start': start, 'end': end, 'content_digest': digest(text), 'text': text[start:end]}
        start = end


def embed_items(provider, items, deadline, batch_size):
    jobs = [(item['ref'], part) for item in items for part in slices(item['text'])]
    result = {item['ref']: [] for item in items}
    for start in range(0, len(jobs), batch_size):
        batch = jobs[start:start + batch_size]
        vectors = provider.embed([part['text'] for _, part in batch], deadline)
        for (ref, part), vector in zip(batch, vectors, strict=True):
            result[ref].append({k: v for k, v in part.items() if k != 'text'} | {'vector': vector})
    return result


def embed_query(provider, text, deadline, batch_size):
    parts = embed_items(provider, [{'ref': 'query', 'text': text}], deadline, batch_size)['query']
    # Ordinary short queries remain one unchanged vector. Long queries use a
    # normalized length-weighted centroid, without dropping their trailing text.
    values = [sum(p['vector'][i] * (p['end'] - p['start']) for p in parts)
              for i in range(len(parts[0]['vector']))]
    norm = math.sqrt(sum(v * v for v in values))
    if not norm:
        from .errors import MemoryError
        raise MemoryError('embedding_query_zero_norm', 502)
    return [v / norm for v in values]
