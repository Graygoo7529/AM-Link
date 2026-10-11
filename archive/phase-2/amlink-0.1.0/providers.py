"""One HTTP attempt per model operation. No SDK, retries, or failover."""
from __future__ import annotations

import json
import math
import threading
import time
from urllib.parse import urlsplit

import httpx

from .errors import MemoryError
from .text import digest, dumps


class Providers:
    def __init__(self, config, observer, *, transport=None):
        self.config, self.observer = config, observer
        self.client = httpx.Client(transport=transport or httpx.HTTPTransport(retries=0), follow_redirects=False)
        self.lock = threading.Lock()
        self.calls = self.input_chars = 0
        self.embedding_fingerprint = digest([config.embedding_base_url, config.embedding_model,
                                            config.embedding_dimensions, "narrative-v1"])

    def close(self):
        self.client.close()

    def _post(self, *, base, path, key, body, model, embedding, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MemoryError("request_deadline", 504)
        if not key:
            raise MemoryError("provider_not_configured", 503)
        chars = len(dumps(body))
        if chars > self.config.model_input_chars:
            raise MemoryError("model_input_budget", 413)
        with self.lock:
            if self.calls >= self.config.max_provider_calls or self.input_chars + chars > self.config.max_provider_input_chars:
                raise MemoryError("provider_run_budget", 429)
            self.calls += 1
            self.input_chars += chars
        with self.observer.span("model", "embedding" if embedding else "gpt-4o-mini", inputs=body) as event:
            if event is not None:
                event["model"] = {"provider": urlsplit(base).hostname or "configured",
                    "name": model, "input_tokens": None, "output_tokens": None,
                    "cached_tokens": None, "cost_usd": None,
                    "usage_source": "provider response; pricing not assumed"}
            try:
                response = self.client.post(base.rstrip("/") + path,
                    headers={"Authorization": "Bearer " + key}, json=body,
                    timeout=min(remaining, self.config.model_timeout))
            except httpx.TimeoutException:
                raise MemoryError("provider_timeout", 504) from None
            except httpx.HTTPError:
                raise MemoryError("provider_network", 502) from None
            if response.status_code == 429:
                raise MemoryError("provider_rate_limit", 429)
            if response.status_code != 200:
                raise MemoryError("provider_http_failure", 502)
            try:
                data = response.json()
            except ValueError:
                raise MemoryError("provider_invalid_json", 502) from None
            if not isinstance(data, dict):
                raise MemoryError("provider_invalid_response", 502)
            usage = data.get("usage") or {}
            if event is not None:
                for output, source in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
                    value = usage.get(source)
                    if type(value) is int and value >= 0:
                        event["model"][output] = value
                if embedding:
                    event["model"]["output_tokens"] = 0
                cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                if type(cached) is int and cached >= 0:
                    event["model"]["cached_tokens"] = cached
            if time.monotonic() >= deadline:
                raise MemoryError("request_deadline", 504)
            self.observer.output(event, data, kind="memory", title="模型公开输出及用量")
            return data

    def json(self, purpose, prompt, payload, deadline):
        data = self._post(base=self.config.llm_base_url, path="/chat/completions",
            key=self.config.llm_api_key, model=self.config.llm_model, embedding=False, deadline=deadline,
            body={"model": self.config.llm_model, "temperature": 0,
                  "max_tokens": self.config.model_max_tokens, "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": prompt},
                               {"role": "user", "content": dumps({"purpose": purpose, "data": payload})}]})
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("incomplete model output")
            result = json.loads(choice["message"]["content"])
            if not isinstance(result, dict):
                raise ValueError("expected JSON object")
            return result
        except (KeyError, IndexError, TypeError, ValueError):
            raise MemoryError("model_output_invalid", 502) from None

    def embed(self, texts, deadline):
        if not texts or len(texts) > self.config.embedding_batch:
            raise ValueError("invalid embedding batch size")
        data = self._post(base=self.config.embedding_base_url, path="/embeddings",
            key=self.config.embedding_api_key, model=self.config.embedding_model, embedding=True, deadline=deadline,
            body={"model": self.config.embedding_model, "input": texts,
                  "dimensions": self.config.embedding_dimensions})
        try:
            rows = sorted(data["data"], key=lambda r: r["index"])
            if [r["index"] for r in rows] != list(range(len(texts))):
                raise ValueError("embedding count/order")
            result = []
            for row in rows:
                vector = row["embedding"]
                if len(vector) != self.config.embedding_dimensions or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
                    raise ValueError("embedding dimensions/values")
                norm = math.sqrt(sum(v*v for v in vector))
                if not norm:
                    raise ValueError("zero embedding")
                result.append([v/norm for v in vector])
            return result
        except (KeyError, TypeError, ValueError):
            raise MemoryError("embedding_output_invalid", 502) from None

