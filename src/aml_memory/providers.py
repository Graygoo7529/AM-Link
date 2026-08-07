from __future__ import annotations

import json
import math
import random
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import httpx


RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    pass


class ProviderDeadlineExceeded(ProviderError):
    pass


class JsonModelProvider(Protocol):
    model: str

    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def close(self) -> None: ...


class OpenAICompatibleJsonModel:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_output_tokens: int,
        max_retries: int,
        max_concurrency: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries
        self._timeout_seconds = timeout_seconds
        self._deadline_state = threading.local()
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def generate_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        payload, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
        }
        response = self._post_with_retry(
            "/chat/completions", body, deadline=self._current_deadline()
        )
        try:
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProviderError("model returned an invalid JSON response") from error
        if not isinstance(parsed, dict):
            raise ProviderError("model JSON response must be an object")
        return parsed

    def _post_with_retry(
        self,
        path: str,
        body: dict[str, Any],
        *,
        deadline: float | None,
    ) -> httpx.Response:
        with _capacity_slot(self._semaphore, deadline):
            for attempt in range(self.max_retries + 1):
                try:
                    response = self._client.post(
                        path,
                        json=body,
                        timeout=_request_timeout(self._timeout_seconds, deadline),
                    )
                except httpx.TransportError as error:
                    if attempt >= self.max_retries:
                        raise ProviderError("model provider request failed") from error
                    _backoff(attempt, deadline=deadline)
                    continue
                if response.status_code < 400:
                    return response
                if (
                    response.status_code not in RETRYABLE_STATUS_CODES
                    or attempt >= self.max_retries
                ):
                    raise ProviderError(
                        f"model provider returned HTTP {response.status_code}"
                    )
                _backoff(attempt, deadline=deadline)
        raise ProviderError("model provider retry loop exhausted")

    @contextmanager
    def deadline_scope(self, deadline: float | None) -> Iterator[None]:
        previous = getattr(self._deadline_state, "value", None)
        self._deadline_state.value = deadline
        try:
            yield
        finally:
            self._deadline_state.value = previous

    def _current_deadline(self) -> float | None:
        return getattr(self._deadline_state, "value", None)

    def close(self) -> None:
        self._client.close()


class ZhipuEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int,
        batch_size: int,
        timeout_seconds: float,
        max_retries: int,
        max_concurrency: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._timeout_seconds = timeout_seconds
        self._deadline_state = threading.local()
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        deadline = self._current_deadline()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(
                self._embed_batch(
                    texts[start : start + self.batch_size], deadline=deadline
                )
            )
        return vectors

    def _embed_batch(
        self, texts: list[str], *, deadline: float | None
    ) -> list[list[float]]:
        body = {
            "model": self.model,
            "input": texts,
            "dimensions": self.dimensions,
        }
        with _capacity_slot(self._semaphore, deadline):
            for attempt in range(self.max_retries + 1):
                try:
                    response = self._client.post(
                        "/embeddings",
                        json=body,
                        timeout=_request_timeout(self._timeout_seconds, deadline),
                    )
                except httpx.TransportError as error:
                    if attempt >= self.max_retries:
                        raise ProviderError(
                            "embedding provider request failed"
                        ) from error
                    _backoff(attempt, deadline=deadline)
                    continue
                if response.status_code < 400:
                    break
                if (
                    response.status_code not in RETRYABLE_STATUS_CODES
                    or attempt >= self.max_retries
                ):
                    raise ProviderError(
                        f"embedding provider returned HTTP {response.status_code}"
                    )
                _backoff(attempt, deadline=deadline)
            else:
                raise ProviderError("embedding provider retry loop exhausted")

        try:
            items = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors = [_normalize_vector(item["embedding"]) for item in items]
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderError("embedding provider returned an invalid response") from error
        if len(vectors) != len(texts):
            raise ProviderError("embedding provider returned the wrong vector count")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise ProviderError("embedding provider returned the wrong dimensions")
        return vectors

    @contextmanager
    def deadline_scope(self, deadline: float | None) -> Iterator[None]:
        previous = getattr(self._deadline_state, "value", None)
        self._deadline_state.value = deadline
        try:
            yield
        finally:
            self._deadline_state.value = previous

    def _current_deadline(self) -> float | None:
        return getattr(self._deadline_state, "value", None)

    def close(self) -> None:
        self._client.close()


def _normalize_vector(values: Any) -> list[float]:
    if not isinstance(values, list) or not values:
        raise ValueError("vector must be a non-empty list")
    vector = [float(value) for value in values]
    if any(not math.isfinite(value) for value in vector):
        raise ValueError("vector contains a non-finite value")
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if norm == 0:
        raise ValueError("vector norm must be positive")
    return [value / norm for value in vector]


@contextmanager
def provider_deadline(
    provider: JsonModelProvider | EmbeddingProvider,
    deadline: float | None,
) -> Iterator[None]:
    scope = getattr(provider, "deadline_scope", None)
    if scope is None:
        yield
        return
    with scope(deadline):
        yield


@contextmanager
def _capacity_slot(
    semaphore: threading.BoundedSemaphore, deadline: float | None
) -> Iterator[None]:
    if deadline is None:
        acquired = semaphore.acquire()
    else:
        remaining = deadline - time.monotonic()
        acquired = remaining > 0 and semaphore.acquire(timeout=remaining)
    if not acquired:
        raise ProviderDeadlineExceeded(
            "provider deadline exceeded while waiting for capacity"
        )
    try:
        yield
    finally:
        semaphore.release()


def _request_timeout(configured: float, deadline: float | None) -> float:
    if deadline is None:
        return configured
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProviderDeadlineExceeded("provider deadline exceeded")
    return max(0.001, min(configured, remaining))


def _backoff(attempt: int, *, deadline: float | None) -> None:
    delay = min(0.25 * (2**attempt), 2.0) + random.uniform(0.0, 0.1)
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderDeadlineExceeded("provider deadline exceeded during retry")
        delay = min(delay, remaining)
    time.sleep(delay)
