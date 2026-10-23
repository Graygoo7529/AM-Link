"""Readable, bounded evidence views. Stored source text is never modified."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re

from .text import excerpt, terms


def _excerpt_with_range(text, limit, query=""):
    """Return a bounded excerpt and the source character range it exposes."""
    if len(text) <= limit:
        return text, [0, len(text)], True
    words = terms(query)
    positions = [text.casefold().find(word) for word in words]
    hit = min((position for position in positions if position >= 0), default=0)
    start = max(0, hit - limit // 4)
    width = max(1, limit - 20)
    selected = text[start:start + width]
    return ("…" if start else "") + selected + "… [片段截断]", [start, start + len(selected)], False


def source_date(timestamp):
    if timestamp is None:
        return None
    # Integer conversion avoids rounding the maximum supported millisecond into
    # year 10000 on platforms using a double precision timestamp.
    seconds, millis = divmod(timestamp, 1000)
    value = datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=millis * 1000)
    return value.isoformat().replace("+00:00", "Z")


def slug(text, limit=36):
    return re.sub(r"[^\w-]+", "-", text, flags=re.UNICODE).strip("-_").lower()[:limit] or "context"


def episode_label(sources):
    speakers = list(dict.fromkeys(match.group(1).strip() for source in sources
        if (match := re.search(r"(?m)^Speaker:\s*([^\n]+)", source["text"]))))
    text = " ".join(re.sub(r"(?m)^Speaker:[^\n]*", "", source["text"]) for source in sources)
    words = [word for word in dict.fromkeys(terms(text)) if word not in {"hey", "hi", "good", "thanks", "yeah", "speaker"}]
    day = source_date(sources[0].get("source_time"))
    return "-".join(([day[:10]] if day else []) + speakers[:2] + words[:4])


def episode_text(sources):
    """Group session/date headers instead of repeating long run IDs on every turn."""
    lines, last = [], None
    for source in sources:
        key = (source["session_id"], source.get("source_time"))
        if key != last:
            lines.append(f"[session={key[0]}][source_time={source_date(key[1]) or 'unknown'}]")
            last = key
        lines.append(f"[{source['role']}][ordinal={source['ordinal']}] {source['text']}")
    return "\n".join(lines)


def source_header(source):
    return (f"[source={source['ref']}][role={source['role']}][ordinal={source['ordinal']}]"
            f"[source_time={source_date(source.get('source_time')) or 'unknown'}]")


def passages(sources, query, limit):
    """Choose complete messages first, preserving local order and date headers.

    This is a display projection, not semantic inference. Coverage records are
    returned even for omitted messages; a long message is explicitly partial.
    """
    keywords = set(terms(query))
    counts = Counter(word for source in sources for word in set(terms(source["text"])))
    ranked = sorted(range(len(sources)), key=lambda i: (
        -sum(1 / counts[word] for word in keywords.intersection(terms(sources[i]["text"]))), i))
    rendered, coverage, used = {}, {}, 0
    for i in ranked:
        source = sources[i]
        prefix = source_header(source) + " "
        text = source["text"]
        room = limit - used - len(prefix) - 1
        if len(prefix) + len(text) + used + 1 <= limit:
            selected, complete = text, True
        elif room >= 160:
            selected, source_range, complete = _excerpt_with_range(text, room, query)
        else:
            coverage[source["ref"]] = {"ref": source["ref"], "included": False, "reason": "source_content_budget"}
            continue
        if complete:
            source_range = [0, len(text)]
        rendered[i] = prefix + selected
        used += len(rendered[i]) + 1
        coverage[source["ref"]] = {"ref": source["ref"], "included": True,
            "complete": complete, "source_chars": len(text), "shown_chars": len(selected),
            "shown_range": source_range,
            "reason": "full_message" if complete else "message_excerpt"}
    return "\n".join(rendered[i] for i in sorted(rendered)), [coverage[s["ref"]] for s in sources]


def complementary_passages(sources, queries, limit, max_fragments=4):
    """Expose a small, non-overlapping set of source/query fragments.

    This is a model-input projection. It never changes stored source text and
    deliberately reports omitted sources so Select can request Inspect later.
    """
    queries = list(dict.fromkeys(str(query).strip() for query in queries if str(query).strip())) or [""]
    pairs = []
    for query in queries:
        query_terms = set(terms(query))
        for index, source in enumerate(sources):
            source_terms = set(terms(source["text"]))
            pairs.append((-(len(query_terms & source_terms)), index, query))
    pairs.sort()
    chosen, used_sources, fragments, used = [], set(), [], 0
    per_fragment = max(100, limit // max(1, max_fragments))
    for _, index, query in pairs:
        source = sources[index]
        if source["ref"] in used_sources or len(fragments) >= max_fragments:
            continue
        header = source_header(source) + f" [query={excerpt(query, 120)}] "
        room = limit - used - len(header) - 1
        if room < 80:
            continue
        size = min(per_fragment, room)
        text, shown_range, complete = _excerpt_with_range(source["text"], size, query)
        rendered = header + text
        fragments.append({"source_ref": source["ref"], "query": excerpt(query, 160),
                          "text": rendered, "complete": complete,
                          "shown_range": shown_range, "source_chars": len(source["text"]),
                          "shown_chars": len(text), "role": source.get("role"),
                          "ordinal": source.get("ordinal"),
                          "source_time": source.get("source_time")})
        chosen.append(source["ref"])
        used_sources.add(source["ref"])
        used += len(rendered) + 1
    coverage = []
    for source in sources:
        match = next((fragment for fragment in fragments if fragment["source_ref"] == source["ref"]), None)
        coverage.append({"ref": source["ref"], "included": bool(match),
                         "complete": bool(match and match["complete"]),
                         "source_chars": len(source["text"]),
                         "shown_chars": match["shown_chars"] if match else 0,
                         "shown_range": match["shown_range"] if match else None,
                         "shown_ranges": [match["shown_range"]] if match else [],
                         "reason": "complementary_fragment" if match else "source_content_budget"})
    return fragments, coverage
