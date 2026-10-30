from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, strict=True)


class Message(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    timestamp: int | None = Field(default=None, ge=0, le=253402300799999)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class AddRequest(StrictModel):
    request_id: str = Field(min_length=1)
    messages: list[Message] = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)

    @field_validator("request_id", "user_id", "session_id")
    @classmethod
    def id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier must not be blank")
        return value


class SearchRequest(StrictModel):
    query: str = Field(min_length=1)
    options: list[str] | None = None
    user_id: str = Field(min_length=1)
    top_k: int = Field(ge=1, le=100)

    @field_validator('options')
    @classmethod
    def nonblank_options(cls, value):
        if value is not None and any(not x.strip() for x in value):
            raise ValueError('options must not contain blank text')
        return value

    @field_validator("query", "user_id")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class SearchResult(StrictModel):
    id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    score: float | None = None
    created_at: str | None = None


class SearchResponse(StrictModel):
    data: list[SearchResult]


class AddResponse(StrictModel):
    success: Literal[True]
    request_id: str
    user_id: str
    session_id: str
