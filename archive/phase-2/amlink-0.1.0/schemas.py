from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1)]
Kind = Literal["episode", "person", "entity", "concept", "event", "fact"]
Relation = Literal["about", "contains", "supersedes", "contradicts", "same_event_as"]
DateText = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Calendar date YYYY-MM-DD only; no time or timezone. Omit if unknown.")]


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
    # new:<label> is a batch-local ref; memory:<id> updates a navigation page.
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
            raise ValueError("time range must be ordered and preserve original expression")
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
    items: list[ItemChange] = Field(default_factory=list, max_length=128)
    links: list[LinkChange] = Field(default_factory=list, max_length=256)
    forget: list[ForgetChange] = Field(default_factory=list, max_length=16)


class QueryPlan(StrictModel):
    queries: list[Text] = Field(default_factory=list, max_length=3)
    history: bool = False


class Selection(StrictModel):
    refs: list[Text] = Field(max_length=100)
