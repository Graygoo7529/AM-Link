"""One frozen, explicitly numbered list for tool input and result decoding."""
from copy import deepcopy
from dataclasses import dataclass

from .errors import MemoryError
from .evidence import fragment


def visible_fragments(projected, working=()):
    """Ranges actually serialized, regardless of their display container."""
    found = {}

    def add(value, owner=None, text=None):
        if not isinstance(value, dict) or not all(k in value for k in
                ("origin_ref", "content_digest", "start", "end", "fragment_id")):
            return
        value = {**value}
        if text is not None:
            value["text"] = text
        if len(value.get("text", "")) != value["end"] - value["start"]:
            return
        if owner:
            value["item_ref"] = owner
        key = value["fragment_id"]
        if key not in found or owner:
            found[key] = value

    for value in projected.get("disclosures", []):
        add(value, value.get("item_ref"))
    for ref, row in projected.get("items", {}).items():
        add(row.get("text_fragment"), ref, row.get("text"))
    for ref, row in projected.get("references", {}).items():
        for value in row.get("evidence_fragments", []):
            add(value, ref)
    for row in projected.get("sources", []):
        add(row.get("text_fragment"), text=row.get("text"))
    for row in working:
        if row.get('text_fragment'):
            add(row['text_fragment'], text=row['text'])
        else:
            add(fragment(row, 0, len(row["text"])))
    return list(found.values())


def range_is_visible(value, shown):
    """Union coverage for a specific version and requested interval."""
    end = value["start"]
    for start, stop in sorted((v["start"], v["end"]) for v in shown
                              if v["origin_ref"] == value["origin_ref"]
                              and v["content_digest"] == value["content_digest"]):
        if stop <= end:
            continue
        if start > end:
            return False
        end = max(end, stop)
        if end >= value["end"]:
            return True
    return end >= value["end"]


def range_receipt(value):
    return {k: v for k, v in value.items() if k in
            {"fragment_id", "origin_ref", "content_digest", "start", "end", "source_chars", "item_ref"}}


@dataclass(frozen=True)
class Choices:
    rows: tuple

    @classmethod
    def freeze(cls, references, allowed=None):
        return cls(tuple({**deepcopy(row), "position": i,
                          "allowed_actions": list((allowed or {}).get(row["ref"], ["inspect", "backlinks"]))}
                         for i, row in enumerate(references)))

    def resolve(self, position, action=None):
        if type(position) is not int or not 0 <= position < len(self.rows):
            raise MemoryError("reference_invalid_position", 502)
        row = self.rows[position]
        if action is not None and action not in row["allowed_actions"]:
            raise MemoryError("reference_action_not_allowed", 502)
        return row["ref"]

    def subset(self, positions):
        if not isinstance(positions, list):
            raise MemoryError("selection_invalid_position", 502)
        try:
            refs = [self.resolve(pos) for pos in positions]
        except MemoryError:
            raise MemoryError("selection_invalid_position", 502) from None
        return list(dict.fromkeys(refs))

    def integer_schema(self, nullable=False):
        schema = {"type": "integer", "enum": list(range(len(self.rows)))}
        if not self.rows:
            return {"type": "null"}
        return {"anyOf": [schema, {"type": "null"}]} if nullable else schema

    def inspect_target_schema(self, position_name):
        # Bind each reference to its own offered page enum. Independent enums
        # allow syntactically valid but nonexistent reference/page pairs.
        alternatives = []
        for row in self.rows:
            if "inspect" not in row["allowed_actions"]:
                continue
            alternatives.append({"type": "object", "properties": {
                position_name: {"type": "integer", "enum": [row["position"]]},
                "page_position": {"anyOf": [{"type": "integer", "enum": [p["position"] for p in row["pages"]]}, {"type": "null"}]}}})
        return {"anyOf": alternatives}
