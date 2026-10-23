"""Pure bounded-prefix planning. No model calls, retry or background work."""
import re
from .text import dumps
from .evidence import fragment

UPDATE = re.compile(r"\b(correction|changed\s+(?:my|the|our)|no longer|instead of|update\s+(?:my|the|our))\b|改为|更正|不再|变更为|更新我的", re.I)
EXPLICIT_CHANGE = re.compile(r"\bcorrection\s*:|\b(?:I|we)\s+(?:have\s+)?changed\s+(?:my|our)\b|(?:更正|变更为|改为)", re.I)
FORGET_REQUEST = re.compile(r"\b(?:please\s+)?(?:forget|erase|delete|remove)\s+(?:my|the|that|this|everything|all|what)\b|请.*(?:忘记|删除|遗忘)|不要再记|别再记|删除.*(?:记录|记忆|信息)", re.I)

def plan_prefix(pending, request_end, required, settled, config):
    if required:
        return {"target": required, "trigger": required > settled, "reasons": ["frozen_retry"]}
    rows = [row for row in pending if row["ordinal"] <= request_end]
    target, reasons = 0, []
    for left, right in zip(rows, rows[1:]):
        if left["session_id"] != right["session_id"]:
            target = left["ordinal"]
    if target:
        reasons.append("session_prefix")
    request_ids = {row["request_id"] for row in rows}
    size = sum(len(dumps(row)) for row in rows)
    ordinary = len(request_ids) >= config.reflection_min_adds and (
        len(rows) >= config.reflection_threshold or sum(len(row["text"]) for row in rows) >= config.reflection_chars)
    capacity = len(rows) >= 2 * config.batch_messages or size >= 2 * config.batch_chars
    hints = [{"ref": row["ref"], "cue": match.group(0), "excerpt": row["text"][max(0, match.start()-40):match.end()+100]}
             for row in rows if row["role"] == "user" and (match := UPDATE.search(row["text"]))]
    signal = any(row["role"] == "user" and (EXPLICIT_CHANGE.search(row["text"]) or FORGET_REQUEST.search(row["text"])) for row in rows)
    for hit, reason in ((ordinary, "accumulation"), (capacity, "capacity"), (signal, "explicit_change")):
        if hit:
            target = request_end
            reasons.append(reason)
    return {"target": target, "trigger": target > settled, "reasons": reasons,
            "request_count": len(request_ids), "request_end": request_end,
            "change_hints": hints[:8], "omitted_hint_count": max(0, len(hints)-8)}


def prefix_overview(rows, watermark, limit):
    groups = []
    for row in rows:
        key = (row["session_id"], row["request_id"])
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(row)
    result = {"message_count": len(rows), "through": rows[-1]["ordinal"] if rows else 0,
              "group_count": len(groups), "groups": [], "omitted_groups": 0,
              "meaning": "partial overview, not inspected source text; future batches planning only"}
    for (session, request), values in groups:
        sample = values[:1] + (values[-1:] if len(values) > 1 else [])
        group = {"session": session, "request": request, "count": len(values),
                 "ordinals": [values[0]["ordinal"], values[-1]["ordinal"]],
                 "roles": list(dict.fromkeys(row["role"] for row in values)),
                 "samples": [{**fragment(row, 0, 80), "planning_only": row["ordinal"] > watermark} for row in sample]}
        result["groups"].append(group)
        if len(dumps(result)) > limit:
            result["groups"].pop()
            result["omitted_groups"] += 1
    return result
