"""Readable, bounded evidence views. Stored source text is never modified."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re

from .text import excerpt, terms


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
        elif not rendered and room >= 160:
            selected, complete = excerpt(text, room, query), False
        else:
            coverage[source["ref"]] = {"ref": source["ref"], "included": False, "reason": "source_content_budget"}
            continue
        rendered[i] = prefix + selected
        used += len(rendered[i]) + 1
        coverage[source["ref"]] = {"ref": source["ref"], "included": True,
            "complete": complete, "source_chars": len(text), "shown_chars": len(selected),
            "reason": "full_message" if complete else "message_excerpt"}
    return "\n".join(rendered[i] for i in sorted(rendered)), [coverage[s["ref"]] for s in sources]
