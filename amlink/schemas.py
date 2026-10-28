from __future__ import annotations

from datetime import date
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import MemoryError

Text = Annotated[str, Field(min_length=1)]
Kind = Literal["episode", "person", "entity", "concept", "event", "fact"]
Relation = Literal["about", "contains", "supersedes", "contradicts", "same_event_as"]
DateText = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


def check_source_time(expression, passages, start=None, end=None):
    """Necessary quotation/year support, not a complete temporal reasoner."""
    if expression is None:
        return
    normalize = lambda text: ' '.join(text.split()).casefold()
    if (not isinstance(expression, str) or not expression.strip()
            or not any(normalize(expression) in normalize(text) for text in passages)):
        raise MemoryError('mutation_time_not_quoted', 409)
    years = {value[:4] for value in (start, end) if isinstance(value, str)}
    if any(not any(re.search(r'(?<!\d)' + re.escape(year) + r'(?!\d)', text) for text in passages)
           for year in years):
        raise MemoryError('mutation_time_precision', 409)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def not_blank(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("blank text is not allowed")
        return value


class Message(StrictModel):
    role: Literal["user", "assistant"]
    content: Text
    timestamp: Annotated[int, Field(ge=0, le=253402300799999)] | None = None


class AddRequest(StrictModel):
    request_id: Text
    user_id: Text
    session_id: Text
    messages: Annotated[list[Message], Field(min_length=1)]


class SearchRequest(StrictModel):
    query: Text
    user_id: Text
    top_k: Annotated[int, Field(ge=1, le=100)]
    options: list[Text] | None = None


class ItemChange(StrictModel):
    ref: Text
    kind: Kind
    text: Annotated[str, Field(min_length=1, max_length=6000)]
    source_refs: Annotated[list[Text], Field(min_length=1, max_length=64)]
    time_expression: str | None = None
    time_start: DateText | None = None
    time_end: DateText | None = None

    @model_validator(mode="after")
    def validate_time(self):
        for value in (self.time_start, self.time_end):
            if value is not None:
                date.fromisoformat(value)
        if self.time_start and self.time_end and self.time_start > self.time_end:
            raise ValueError("time range must be ordered")
        if (self.time_start or self.time_end) and not self.time_expression:
            raise ValueError("normalized time requires original expression")
        return self


class LinkChange(StrictModel):
    from_ref: Text
    to_ref: Text
    relation: Relation
    source_refs: Annotated[list[Text], Field(min_length=1, max_length=64)]


class ForgetChange(StrictModel):
    source_refs: list[Text] = Field(default_factory=list, max_length=64)
    memory_refs: list[Text] = Field(default_factory=list, max_length=64)
    instruction_refs: Annotated[list[Text], Field(min_length=1, max_length=16)]


class Mutation(StrictModel):
    basis: Literal["new_information", "update_existing", "resolve_conflict",
                   "identify_person", "add_relation"] = "new_information"
    inspected_refs: list[Text] = Field(default_factory=list, max_length=64)
    no_prior_match: bool = False
    items: list[ItemChange] = Field(default_factory=list, max_length=128)
    links: list[LinkChange] = Field(default_factory=list, max_length=256)
    forget: list[ForgetChange] = Field(default_factory=list, max_length=16)


class QueryExpansion(StrictModel):
    queries: list[Text] = Field(default_factory=list, max_length=3)


class Selection(StrictModel):
    refs: list[Text] = Field(max_length=100)


class BfsAction(StrictModel):
    action: Literal["inspect", "backlinks", "stop"]
    ref: Text | None = None
    frontier_position: int | None = None
    page_position: int | None = None
    reason: str | None = None


class EvictAction(StrictModel):
    refs: list[Text] = Field(default_factory=list, max_length=64)


class ReflectionAction(StrictModel):
    action: Literal["search", "evict", "mutation", "stop"]
    question: str | None = None
    refs: list[Text] = Field(default_factory=list, max_length=32)
