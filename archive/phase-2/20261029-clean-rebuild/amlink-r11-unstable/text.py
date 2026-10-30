from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

FORGET = re.compile(r"\b(forget|erase|delete|remove)\b|忘记|遗忘|删除|撤回|不要再记|别再记", re.I)
CHANGE = re.compile(r"\b(actually|instead|changed|correction|no longer|never|now)\b|改为|其实|不再|从未|现在|更正", re.I)
COMPLEX = re.compile(r"\b(total|both|shared|common|when|before|after|previous|current|how many|which|where|why|percent)\b|多少|共同|之前|之后|当前|以前|哪个|哪里|为什么|比例|一共", re.I)
STOP = set("a an the i you he she it we they my your his her our their is are was were be been of to in on at for and or do does did what which who where when how me can could would should please tell about from with that this have has had".split())


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def terms(text):
    english = [t for t in re.findall(r"[a-z0-9]+", text.casefold()) if t not in STOP]
    chinese = []
    for phrase in re.findall(r"[\u3400-\u9fff]+", text):
        chinese.extend(phrase[i:i+2] for i in range(max(1, len(phrase)-1)))
    return english + chinese


def indexed(text):
    return " ".join(terms(text))


def excerpt(text, limit, query=""):
    if len(text) <= limit:
        return text
    # Bounded contextual excerpt, never pretend the omitted part was inspected.
    words = terms(query)
    positions = [text.casefold().find(w) for w in words]
    hit = min((p for p in positions if p >= 0), default=0)
    start = max(0, hit - limit // 4)
    return ("…" if start else "") + text[start:start+max(1, limit-20)] + "… [片段截断]"

