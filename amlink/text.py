from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime

STOP = set('a an the is are was were to of on in for and or with do did does what when where how who which i you it this that'.split())

def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False)

def digest(value):
    return hashlib.sha256((value if isinstance(value, str) else dumps(value)).encode('utf-8')).hexdigest()

def tokens(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    result = []
    for token in re.findall(r'[\u4e00-\u9fff]+|[^\W_]+', text):
        if '\u4e00' <= token[0] <= '\u9fff':
            result.extend(token)
            result.extend(token[i:i+2] for i in range(len(token)-1))
        elif token not in STOP:
            result.append(token)
    return result

def excerpt(text, limit):
    return text if len(text) <= limit else text[:limit-1] + '…'

def ranges(text, max_chars=1800, max_bytes=5500):
    """Lossless Unicode ranges; prefer paragraph or sentence boundaries."""
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        while len(text[start:end].encode('utf-8')) > max_bytes:
            end -= 1
        if end < len(text):
            boundary = max(text.rfind(mark, start+(end-start)//2, end) for mark in ('\n','. ','。','! ','? '))
            if boundary >= 0:
                end = boundary + 1
        yield start, end
        start = end

def byte_chunks(text, limit=6000):
    return [text[a:b] for a,b in ranges(text, limit, limit)]

def label(text):
    words = re.findall(r'[^\W_]+', text.casefold())[:9]
    return '-'.join(words)[:64] or 'record'

def now():
    return datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00','Z')

def source_time(value):
    return datetime.fromtimestamp(value/1000, UTC).isoformat() if value is not None else 'unknown (do not infer a date)'
