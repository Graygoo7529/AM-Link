"""One frozen, explicitly numbered list for tool input and result decoding."""
from copy import deepcopy
from dataclasses import dataclass

from .errors import MemoryError


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
