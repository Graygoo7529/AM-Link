"""One HTTP attempt per model operation. No SDK, retries, or failover."""
from __future__ import annotations

import math
import threading
import time
from dataclasses import replace
from urllib.parse import urlsplit

import httpx

from .errors import MemoryError
from .text import digest, dumps
from .narrative import render
from .tool_contract import parse_tool, ToolResult
from .vector_index import MAX_INPUT_BYTES, INDEX_VERSION


def tool_body(config, purpose, prompt, payload, tools):
    """One serialization for preflight and HTTP, preserving task-first order.

    Storage hashes use sorted keys; the model reads the explicitly composed
    question/decision before its material, so model input must not sort keys.
    """
    contract = ('\nTOOL DELIVERY: Return exactly one tool call. Include every required property, even when its value is null, false or []. '
                'Send only argument properties; schema keywords such as maxItems/type/required are NOT output fields.\n')
    contract += '\n'.join(tool['name'] + ' top-level argument fields: ' +
                          ', '.join(tool['parameters'].get('properties', {})) for tool in tools)
    if purpose == 'reflection':
        contract += ('\nEach proposed item must include ref, kind, text, source_refs, time_expression, time_start and time_end. '
                     'Unknown time fields are explicit null. Always include no_prior_match in reflection_items; do not omit false. '
                     'Each reflection_relations link must include connection_position, source_refs and support. '
                     'In support explain what the cited original says about THIS connection; do not omit this field.')
    return {"model": config.llm_model, "temperature": 0,
            "max_completion_tokens": min(config.model_max_tokens, 1024) if purpose in {"bfs", "query_expansion"} else config.model_max_tokens,
            "parallel_tool_calls": False,
            "tools": [{"type": "function", "function": tool} for tool in tools],
            "tool_choice": {"type": "function", "function": {"name": tools[0]["name"]}} if len(tools) == 1 else "required",
            "messages": [{"role": "system", "content": prompt + contract},
                         {"role": "user", "content": render(purpose, payload)}]}


class Providers:
    def __init__(self, config, observer, *, transport=None):
        self.config, self.observer = config, observer
        self.client = httpx.Client(transport=transport or httpx.HTTPTransport(retries=0), follow_redirects=False)
        self.lock = threading.Lock()
        self.calls = self.input_chars = 0
        self.embedding_fingerprint = digest([config.embedding_base_url, config.embedding_model,
                                            config.embedding_dimensions, "narrative-v1", INDEX_VERSION])

    def close(self):
        self.client.close()

    def _post(self, *, base, path, key, body, model, embedding, deadline, parser=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MemoryError("request_deadline", 504)
        if not key:
            raise MemoryError("provider_not_configured", 503)
        chars = len(dumps(body))
        if chars > self.config.model_input_chars:
            with self.observer.span("context", "model input budget", inputs={
                    "chars": chars, "limit": self.config.model_input_chars, "provider_called": False}):
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
            self.observer.output(event, {"format_version": 1, "request_id": response.headers.get("x-request-id"),
                "response_id": data.get("id"), "max_completion_tokens": body.get("max_completion_tokens"),
                "schema_fingerprint": digest(body.get("tools", []))}, kind="context", title="模型交互协议")
            result = parser(data) if parser is not None else data
            return replace(result, request_id=response.headers.get('x-request-id')) if isinstance(result, ToolResult) else result

    def _parse_embedding(self, data, expected):
        try:
            rows = sorted(data["data"], key=lambda r: r["index"])
            if [r["index"] for r in rows] != list(range(expected)):
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

    def tool(self, purpose, prompt, payload, tools, deadline):
        """One attempt; validate the actual offered schema before domain interpretation."""
        return self._post(base=self.config.llm_base_url, path="/chat/completions",
            key=self.config.llm_api_key, model=self.config.llm_model, embedding=False, deadline=deadline,
            body=tool_body(self.config, purpose, prompt, payload, tools),
            parser=lambda data: parse_tool(data, tools))

    def embed(self, texts, deadline):
        if not texts or len(texts) > self.config.embedding_batch:
            raise ValueError("invalid embedding batch size")
        if any(not text or len(text.encode('utf-8')) > MAX_INPUT_BYTES for text in texts):
            raise MemoryError('embedding_input_budget', 413)
        return self._post(base=self.config.embedding_base_url, path="/embeddings",
            key=self.config.embedding_api_key, model=self.config.embedding_model, embedding=True, deadline=deadline,
            body={"model": self.config.embedding_model, "input": texts,
                  "dimensions": self.config.embedding_dimensions},
            parser=lambda data: self._parse_embedding(data, len(texts)))
