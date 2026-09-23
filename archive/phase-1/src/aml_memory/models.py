from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    # IDs and message content are opaque protocol values; validation must not
    # normalize away meaningful leading or trailing whitespace.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class MemoryMessage(StrictModel):
    role: Literal["user", "assistant"]
    timestamp: int | None = Field(default=None, ge=0, le=253_402_300_799_999)
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class AddRequest(StrictModel):
    request_id: str = Field(min_length=1)
    messages: list[MemoryMessage] = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)

    @field_validator("request_id", "user_id", "session_id")
    @classmethod
    def reject_blank_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier must not be blank")
        return value


class AddResponse(StrictModel):
    success: Literal[True]
    request_id: str
    user_id: str
    session_id: str


class SearchRequest(StrictModel):
    query: str = Field(min_length=1)
    options: list[str] | None = None
    user_id: str = Field(min_length=1)
    top_k: int = Field(ge=1, le=100)

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value

    @field_validator("user_id")
    @classmethod
    def reject_blank_user_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_id must not be blank")
        return value

    @field_validator("options")
    @classmethod
    def reject_blank_options(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not option.strip() for option in value):
            raise ValueError("options must not contain blank strings")
        return value


class SearchResult(StrictModel):
    id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    score: float | None = None
    created_at: str | None = None


class SearchResponse(StrictModel):
    data: list[SearchResult]
