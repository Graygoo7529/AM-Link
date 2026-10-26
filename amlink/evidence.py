"""Readable, bounded evidence views. Stored source text is never modified."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math
import re

from .text import digest, excerpt, terms


def _excerpt_with_range(text, limit, query="", weights=None):
    """Return a bounded excerpt and the source character range it exposes."""
    if len(text) <= limit:
        return text, [0, len(text)], True
    width = max(1, limit - 20)
    keywords = set(terms(query))
    counts = Counter(terms(text))
    weights = weights or {word: 1 / (1 + math.log1p(counts[word])) for word in keywords}
    # Rank windows, not the first occurrence of any query word. Match offsets
    # come from the original string: casefold() changes Unicode codepoint counts.
    starts, occurrences = {0}, {}
    for word in sorted(keywords):
        hits = [m.start() for m in re.finditer(re.escape(word), text, re.IGNORECASE)]
        if len(hits) > 128:
            hits = [hits[i * (len(hits) - 1) // 127] for i in range(128)]
        occurrences[word] = hits
        starts.update(max(0, min(len(text) - width, hit - width // 4)) for hit in hits)
    def score(offset):
        matched = keywords.intersection(terms(text[offset:offset + width]))
        weight = sum(weights.get(word, 0) for word in matched)
        # Ties must leave room after the meaningful hit for its qualifier/date,
        # instead of selecting the earliest window that barely reaches the hit.
        distance = sum(weights.get(word, 0) * min(
            (abs(pos - offset - width / 3) for pos in occurrences[word]
             if offset <= pos < offset + width), default=width) for word in matched)
        return -weight, distance, offset
    start = min(starts, key=score)
    selected = text[start:start + width]
    return ("…" if start else "") + selected + "… [片段截断]", [start, start + len(selected)], False


def fragment(source, start, end, *, query=""):
    """Immutable half-open Python codepoint range; labels never enter text."""
    text = source["text"]
    start, end = max(0, start), min(len(text), end)
    version = digest(text)
    return {"fragment_id": digest([source["ref"], version, start, end]),
            "origin_ref": source["ref"], "source_ref": source["ref"],
            "content_digest": version, "start": start, "end": end,
            "text": text[start:end], "shown_range": [start, end],
            "source_chars": len(text), "shown_chars": end - start,
            "complete": start == 0 and end == len(text), "query": query,
            "origin_kind": "raw" if source["ref"].startswith("raw:") else "item",
            **{k: source[k] for k in ("role", "ordinal", "session_id", "source_time") if k in source}}


def shrink_fragment(value, limit):
    """Shrink a range itself, never re-excerpt a rendered header or ellipsis."""
    if len(value["text"]) <= limit:
        return dict(value)
    end = value["start"] + max(0, limit)
    return {**value, "end": end, "text": value["text"][:limit],
            "fragment_id": digest([value["origin_ref"], value["content_digest"], value["start"], end]),
            "shown_range": [value["start"], end], "shown_chars": max(0, limit), "complete": False}


def render_fragment(value):
    label = (f"[{value['origin_ref']} {value['start']}:{value['end']}/{value['source_chars']}]"
             f"[source_time={source_date(value.get('source_time')) or 'unknown'}]")
    if value.get("role"):
        label += f"[role={value['role']}][ordinal={value.get('ordinal', '?')}]"
    return label + " " + value["text"]


def ranges_complete(values, length):
    end = 0
    for start, stop in sorted((v["start"], v["end"]) for v in values):
        if start > end:
            return False
        end = max(end, stop)
    return end >= length


def pages(source, width=1800):
    return [fragment(source, start, start + width) for start in range(0, len(source["text"]), width)]


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
    return (f"[source={source['ref']}][role={source.get('role', 'derived')}][ordinal={source.get('ordinal', 'unknown')}]"
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
    # Common scene words ("year", "project") should not dominate a rarer
    # information need. Weight only supplied query terms; no inferred answer,
    # amount, person or timestamp is introduced here.
    counts = Counter(word for source in sources for word in terms(source["text"]))
    weights = {word: 1 / (1 + math.log1p(counts[word])) for query in queries for word in terms(query)}
    source_words = [terms(source["text"]) for source in sources]
    average_words = sum(map(len, source_words)) / max(1, len(sources))
    ranked = []
    for query in queries:
        query_terms = set(terms(query))
        pairs = []
        for index, source in enumerate(sources):
            source_terms = set(source_words[index])
            length_norm = 0.25 + 0.75 * len(source_words[index]) / max(1, average_words)
            pairs.append((-sum(weights[word] for word in query_terms & source_terms) / length_norm, index, query))
        ranked.append(sorted(pairs))
    # One proposal per query before taking a second from the same query.
    pairs = [group[i] for i in range(len(sources)) for group in ranked if i < len(group)]
    fragments, used = [], 0
    per_fragment = max(100, limit // max(1, max_fragments))
    for _, index, query in pairs:
        source = sources[index]
        if len(fragments) >= max_fragments:
            continue
        header = source_header(source) + f" [query={excerpt(query, 120)}] "
        room = limit - used - len(header) - 1
        if room < 80:
            continue
        # Keep a short message whole if it fits one half of the total budget.
        # Otherwise several arbitrary cuts can omit the qualifier or amount at
        # its end even when there was enough space for the complete assertion.
        short_complete = len(source["text"]) + len(header) + 1 <= limit // 2
        size = min(len(source["text"]) if short_complete else per_fragment, room)
        _, shown_range, _ = _excerpt_with_range(source["text"], size, query, weights)
        start, end = shown_range
        overlapping = [f for f in fragments if f["origin_ref"] == source["ref"]
                       and f["start"] <= end and start <= f["end"]]
        if overlapping:
            start = min(start, *(f["start"] for f in overlapping))
            end = max(end, *(f["end"] for f in overlapping))
            if any(f["start"] <= start and end <= f["end"] for f in overlapping):
                continue
        value = fragment(source, start, end, query=excerpt(query, 160))
        new_used = used - sum(len(render_fragment(f)) + 1 for f in overlapping) + len(render_fragment(value)) + 1
        if new_used > limit:
            continue
        fragments = [f for f in fragments if f not in overlapping] + [value]
        used = new_used
    coverage = []
    for source in sources:
        matches = [f for f in fragments if f["source_ref"] == source["ref"]]
        coverage.append({"ref": source["ref"], "included": bool(matches),
                         "complete": ranges_complete(matches, len(source["text"])),
                         "source_chars": len(source["text"]),
                         "shown_chars": sum(f["shown_chars"] for f in matches),
                         "shown_range": matches[0]["shown_range"] if matches else None,
                         "shown_ranges": [f["shown_range"] for f in matches],
                         "reason": "complementary_fragment" if matches else "source_content_budget"})
    return fragments, coverage
