from __future__ import annotations

import os
import math
from dataclasses import dataclass, fields
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    db_path: str = "amlink/data/memory.sqlite3"
    mode: str = "graph"
    reflection_threshold: int = 8
    reflection_chars: int = 6000
    batch_chars: int = 18000
    batch_messages: int = 32
    max_batches: int = 8
    max_request_chars: int = 64000
    max_request_messages: int = 128
    old_candidates: int = 24
    seed_count: int = 8
    candidate_limit: int = 64
    max_hops: int = 3
    max_nodes: int = 32
    max_neighbors: int = 8
    preview_chars: int = 1200
    result_chars: int = 7000
    context_chars: int = 24000
    model_input_chars: int = 80000
    request_seconds: float = 240.0
    model_timeout: float = 60.0
    model_max_tokens: int = 5000
    search_model: bool = True
    llm_base_url: str = "https://api.zhizengzeng.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embedding_enabled: bool = False
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    embedding_api_key: str = ""
    embedding_model: str = "embedding-3"
    embedding_dimensions: int = 512
    embedding_batch: int = 32
    auth_scheme: str = "none"
    api_key: str = ""
    max_provider_calls: int = 10000
    max_provider_input_chars: int = 50000000

    def __post_init__(self):
        if self.mode not in {"raw", "graph"} or self.llm_model != "gpt-4o-mini":
            raise ValueError("mode must be raw/graph; generative model must be gpt-4o-mini")
        if self.auth_scheme not in {"none", "bearer", "token", "x-api-key"}:
            raise ValueError("unsupported authentication scheme")
        for address in (self.llm_base_url, self.embedding_base_url):
            parsed = urlsplit(address)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("provider URL must be a clean HTTP(S) base without credentials/query")
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) in (int, float) and not math.isfinite(value):
                raise ValueError(f"{field.name} must be finite")
            if type(value) in (int, float) and value <= 0 and field.name != "max_hops":
                raise ValueError(f"{field.name} must be positive")
        if not 0 <= self.max_hops <= 8 or self.embedding_batch > 64:
            raise ValueError("invalid graph depth or embedding batch")
        if self.model_timeout > self.request_seconds:
            raise ValueError("model timeout must fit request deadline")

    @classmethod
    def from_env(cls):
        defaults = cls()
        values = {}
        for field in fields(cls):
            name = "AML2_" + field.name.upper()
            if name not in os.environ:
                continue
            raw, default = os.environ[name], getattr(defaults, field.name)
            if isinstance(default, bool):
                if raw.lower() not in {"true", "false", "1", "0"}:
                    raise ValueError(f"{name} must be true/false")
                values[field.name] = raw.lower() in {"true", "1"}
            else:
                values[field.name] = type(default)(raw)
        return cls(**values)

    def public(self):
        # No secret-bearing settings or local filesystem paths in run artifacts.
        return {f.name: getattr(self, f.name) for f in fields(self)
                if "key" not in f.name and f.name != "db_path"}


def load_env_file(path: Path):
    """Explicit opt-in, AML2_* only; never prints values or discovers old keys."""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not name.startswith("AML2_"):
            raise ValueError("environment file must contain AML2_* assignments")
        os.environ[name] = value.strip().strip('"').strip("'")
