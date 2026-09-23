from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_AUTH_SCHEMES = {"none", "token", "bearer", "x-api-key"}
SUPPORTED_ENRICHMENT_MODES = {"sync", "async"}
OFFICIAL_LLM_MODEL = "gpt-4o-mini"


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path = Path("data/aml_memory.db")
    markdown_view_dir: Path | None = Path("data/markdown")
    auth_scheme: str = "none"
    api_key: str = ""
    max_top_k: int = 100
    working_memory_event_limit: int = 40
    working_memory_char_limit: int = 16_000
    maintenance_event_threshold: int = 1
    maintenance_char_threshold: int = 1
    enrichment_mode: str = "sync"
    enrichment_max_attempts: int = 5
    add_deadline_seconds: float = 120.0
    search_deadline_seconds: float = 30.0
    llm_model: str = OFFICIAL_LLM_MODEL
    allow_nonofficial_llm_model: bool = False
    llm_enabled: bool = False
    openai_api_key: str = ""
    openai_base_url: str = "https://api.zhizengzeng.com/v1"
    llm_timeout_seconds: float = 90.0
    llm_max_output_tokens: int = 2500
    llm_max_retries: int = 2
    llm_max_concurrency: int = 16
    embedding_enabled: bool = False
    embedding_model: str = "embedding-3"
    embedding_api_key: str = ""
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    embedding_dimensions: int = 512
    embedding_batch_size: int = 64
    embedding_timeout_seconds: float = 60.0
    embedding_max_retries: int = 2
    embedding_max_concurrency: int = 32

    @classmethod
    def from_env(cls) -> "Settings":
        markdown_value = os.environ.get("AML_MARKDOWN_VIEW_DIR", "data/markdown").strip()
        settings = cls(
            db_path=Path(os.environ.get("AML_DB_PATH", "data/aml_memory.db")),
            markdown_view_dir=Path(markdown_value) if markdown_value else None,
            auth_scheme=os.environ.get("AML_AUTH_SCHEME", "none").strip().lower(),
            api_key=os.environ.get("AML_API_KEY", ""),
            max_top_k=int(os.environ.get("AML_MAX_TOP_K", "100")),
            working_memory_event_limit=int(
                os.environ.get("AML_WORKING_MEMORY_EVENT_LIMIT", "40")
            ),
            working_memory_char_limit=int(
                os.environ.get("AML_WORKING_MEMORY_CHAR_LIMIT", "16000")
            ),
            maintenance_event_threshold=int(
                os.environ.get("AML_MAINTENANCE_EVENT_THRESHOLD", "1")
            ),
            maintenance_char_threshold=int(
                os.environ.get("AML_MAINTENANCE_CHAR_THRESHOLD", "1")
            ),
            enrichment_mode=os.environ.get(
                "AML_ENRICHMENT_MODE", "sync"
            ).strip().lower(),
            enrichment_max_attempts=int(
                os.environ.get("AML_ENRICHMENT_MAX_ATTEMPTS", "5")
            ),
            add_deadline_seconds=float(
                os.environ.get("AML_ADD_DEADLINE_SECONDS", "120")
            ),
            search_deadline_seconds=float(
                os.environ.get("AML_SEARCH_DEADLINE_SECONDS", "30")
            ),
            llm_model=os.environ.get("AML_LLM_MODEL", OFFICIAL_LLM_MODEL).strip(),
            allow_nonofficial_llm_model=_as_bool(
                os.environ.get("AML_ALLOW_NONOFFICIAL_LLM_MODEL"), False
            ),
            llm_enabled=_as_bool(
                os.environ.get(
                    "AML_LLM_ENABLED", os.environ.get("AML_MAINTENANCE_ENABLED")
                ),
                False,
            ),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_base_url=os.environ.get(
                "OPENAI_BASE_URL", "https://api.zhizengzeng.com/v1"
            ).strip(),
            llm_timeout_seconds=float(
                os.environ.get("AML_LLM_TIMEOUT_SECONDS", "90")
            ),
            llm_max_output_tokens=int(
                os.environ.get("AML_LLM_MAX_OUTPUT_TOKENS", "2500")
            ),
            llm_max_retries=int(os.environ.get("AML_LLM_MAX_RETRIES", "2")),
            llm_max_concurrency=int(
                os.environ.get("AML_LLM_MAX_CONCURRENCY", "16")
            ),
            embedding_enabled=_as_bool(
                os.environ.get("AML_EMBEDDING_ENABLED"), False
            ),
            embedding_model=os.environ.get(
                "AML_EMBEDDING_MODEL", "embedding-3"
            ).strip(),
            embedding_api_key=os.environ.get("ZHIPU_API_KEY", ""),
            embedding_base_url=os.environ.get(
                "ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
            ).strip(),
            embedding_dimensions=int(
                os.environ.get("AML_EMBEDDING_DIMENSIONS", "512")
            ),
            embedding_batch_size=int(
                os.environ.get("AML_EMBEDDING_BATCH_SIZE", "64")
            ),
            embedding_timeout_seconds=float(
                os.environ.get("AML_EMBEDDING_TIMEOUT_SECONDS", "60")
            ),
            embedding_max_retries=int(
                os.environ.get("AML_EMBEDDING_MAX_RETRIES", "2")
            ),
            embedding_max_concurrency=int(
                os.environ.get("AML_EMBEDDING_MAX_CONCURRENCY", "32")
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.auth_scheme not in SUPPORTED_AUTH_SCHEMES:
            raise ValueError(
                f"AML_AUTH_SCHEME must be one of {sorted(SUPPORTED_AUTH_SCHEMES)}"
            )
        if self.auth_scheme != "none" and not self.api_key:
            raise ValueError("AML_API_KEY is required when authentication is enabled")
        if not 1 <= self.max_top_k <= 100:
            raise ValueError("AML_MAX_TOP_K must be between 1 and 100")
        if self.working_memory_event_limit < 1:
            raise ValueError("AML_WORKING_MEMORY_EVENT_LIMIT must be positive")
        if self.working_memory_char_limit < 1:
            raise ValueError("AML_WORKING_MEMORY_CHAR_LIMIT must be positive")
        if self.maintenance_event_threshold < 1:
            raise ValueError("AML_MAINTENANCE_EVENT_THRESHOLD must be positive")
        if self.maintenance_char_threshold < 1:
            raise ValueError("AML_MAINTENANCE_CHAR_THRESHOLD must be positive")
        if self.enrichment_mode not in SUPPORTED_ENRICHMENT_MODES:
            raise ValueError(
                "AML_ENRICHMENT_MODE must be one of "
                f"{sorted(SUPPORTED_ENRICHMENT_MODES)}"
            )
        if not 1 <= self.enrichment_max_attempts <= 20:
            raise ValueError("AML_ENRICHMENT_MAX_ATTEMPTS must be between 1 and 20")
        if self.add_deadline_seconds <= 0:
            raise ValueError("AML_ADD_DEADLINE_SECONDS must be positive")
        if self.search_deadline_seconds <= 0:
            raise ValueError("AML_SEARCH_DEADLINE_SECONDS must be positive")
        if self.llm_model != OFFICIAL_LLM_MODEL and not self.allow_nonofficial_llm_model:
            raise ValueError(
                f"AML_LLM_MODEL must be {OFFICIAL_LLM_MODEL!r} unless "
                "AML_ALLOW_NONOFFICIAL_LLM_MODEL=true for local debugging"
            )
        if not self.llm_model:
            raise ValueError("AML_LLM_MODEL must not be blank")
        if self.llm_enabled and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when AML_LLM_ENABLED=true")
        if not self.openai_base_url:
            raise ValueError("OPENAI_BASE_URL must not be blank")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("AML_LLM_TIMEOUT_SECONDS must be positive")
        if not 128 <= self.llm_max_output_tokens <= 8192:
            raise ValueError("AML_LLM_MAX_OUTPUT_TOKENS must be between 128 and 8192")
        if not 0 <= self.llm_max_retries <= 5:
            raise ValueError("AML_LLM_MAX_RETRIES must be between 0 and 5")
        if self.llm_max_concurrency < 1:
            raise ValueError("AML_LLM_MAX_CONCURRENCY must be positive")
        if self.embedding_model != "embedding-3":
            raise ValueError("AML_EMBEDDING_MODEL must be 'embedding-3'")
        if self.embedding_enabled and not self.embedding_api_key:
            raise ValueError(
                "ZHIPU_API_KEY is required when AML_EMBEDDING_ENABLED=true"
            )
        if not self.embedding_base_url:
            raise ValueError("ZHIPU_BASE_URL must not be blank")
        if not 256 <= self.embedding_dimensions <= 2048:
            raise ValueError("AML_EMBEDDING_DIMENSIONS must be between 256 and 2048")
        if not 1 <= self.embedding_batch_size <= 64:
            raise ValueError("AML_EMBEDDING_BATCH_SIZE must be between 1 and 64")
        if self.embedding_timeout_seconds <= 0:
            raise ValueError("AML_EMBEDDING_TIMEOUT_SECONDS must be positive")
        if not 0 <= self.embedding_max_retries <= 5:
            raise ValueError("AML_EMBEDDING_MAX_RETRIES must be between 0 and 5")
        if self.embedding_max_concurrency < 1:
            raise ValueError("AML_EMBEDDING_MAX_CONCURRENCY must be positive")
