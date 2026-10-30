from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TargetResponse:
    status_code: int | None
    body: Any = None
    error_type: str | None = None
    error_code: str | None = None
    raw_body: Any = None


class HttpTarget:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        auth_scheme: str,
        api_key: str | None,
    ) -> None:
        if not 0 < timeout <= 1800:
            raise ValueError("timeout must be between 0 and 1800 seconds")
        self.base_url = base_url
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json"}
        if auth_scheme == "none":
            if api_key:
                raise ValueError("api key must be absent when auth scheme is none")
        elif not api_key:
            raise ValueError("api key is required for authenticated targets")
        elif auth_scheme in {"token", "bearer"}:
            scheme = "Token" if auth_scheme == "token" else "Bearer"
            self.headers["Authorization"] = f"{scheme} {api_key}"
        elif auth_scheme == "x-api-key":
            self.headers["X-API-Key"] = api_key
        else:
            raise ValueError(f"unsupported auth scheme: {auth_scheme}")

    def _post(self, path: str, payload: dict[str, Any]) -> TargetResponse:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=self.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status_code = response.status
        except urllib.error.HTTPError as response:
            try:
                error_body = json.loads(response.read(65536).decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                error_body = None
            return TargetResponse(
                status_code=response.code,
                error_code=f"HTTP_{response.code}",
                raw_body=error_body,
            )
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            kind = "timeout" if isinstance(error, (TimeoutError, socket.timeout)) else "network_error"
            return TargetResponse(status_code=None, error_type=kind)

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return TargetResponse(
                status_code=status_code,
                error_type="invalid_json_response",
            )
        return TargetResponse(status_code=status_code, body=parsed, raw_body=parsed)


class AmlApiTarget(HttpTarget):
    """Calls the competition participant Add/Search interface directly."""

    def add(self, request: dict[str, Any]) -> TargetResponse:
        return self._post("/v1/memory/add", request)

    def search(self, request: dict[str, Any]) -> TargetResponse:
        return self._post("/v1/memory/search", request)


class Mem0OssTarget(HttpTarget):
    """Adapts official AML operations to the Mem0 open-source REST API."""

    def add(self, request: dict[str, Any]) -> TargetResponse:
        payload = {
            "messages": [
                {"role": message["role"], "content": message["content"]}
                for message in request["messages"]
            ],
            "user_id": request["user_id"],
            "run_id": request["session_id"],
        }
        response = self._post("/memories", payload)
        if response.error_type or not response.status_code or not 200 <= response.status_code < 300:
            return response
        response_body = response.raw_body
        results = response_body.get("results") if isinstance(response_body, dict) else None
        if not isinstance(results, list) or not results or any(
            not isinstance(result, dict)
            or not isinstance(result.get("id"), str)
            or not result["id"]
            or not isinstance(result.get("event"), str)
            or not result["event"]
            for result in results
        ):
            return TargetResponse(
                status_code=response.status_code,
                error_type="invalid_mem0_add_response",
                raw_body=response_body,
            )
        normalized = {
            "success": True,
            "request_id": request["request_id"],
            "user_id": request["user_id"],
            "session_id": request["session_id"],
        }
        return TargetResponse(
            status_code=response.status_code,
            body=normalized,
            raw_body=response_body,
        )

    def search(self, request: dict[str, Any]) -> TargetResponse:
        response = self._post(
            "/search",
            {
                "query": request["query"],
                "user_id": request["user_id"],
                "top_k": request["top_k"],
                "explain": True,
            },
        )
        if response.error_type or not response.status_code or not 200 <= response.status_code < 300:
            return response
        raw = response.raw_body
        if not isinstance(raw, dict):
            return TargetResponse(
                status_code=response.status_code,
                error_type="invalid_mem0_search_response",
            )
        results = raw.get("results", raw.get("memories"))
        if not isinstance(results, list):
            return TargetResponse(
                status_code=response.status_code,
                error_type="invalid_mem0_search_response",
            )
        normalized_results = []
        for result in results:
            if not isinstance(result, dict):
                return TargetResponse(
                    status_code=response.status_code,
                    error_type="invalid_mem0_search_response",
                )
            memory_id = result.get("id")
            content = result.get("memory", result.get("content"))
            if not isinstance(memory_id, str) or not isinstance(content, str):
                return TargetResponse(
                    status_code=response.status_code,
                    error_type="invalid_mem0_search_response",
                )
            candidate = {"id": memory_id, "content": content}
            score = result.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                candidate["score"] = float(score)
            created_at = result.get("created_at")
            if isinstance(created_at, str):
                candidate["created_at"] = created_at
            candidate["target_metadata"] = {
                field: result[field]
                for field in ("score_details", "categories", "metadata", "run_id")
                if field in result
            }
            normalized_results.append(candidate)
        return TargetResponse(
            status_code=response.status_code,
            body={"data": normalized_results},
            raw_body=raw,
        )


class Mem0LibraryTarget:
    """Adapts the published Mem0 Python package to the arena Add/Search contract."""

    def __init__(self, memory: Any) -> None:
        self.memory = memory

    def add(self, request: dict[str, Any]) -> TargetResponse:
        messages = [
            {"role": message["role"], "content": message["content"]}
            for message in request["messages"]
        ]
        try:
            raw = self.memory.add(
                messages,
                user_id=request["user_id"],
                run_id=request["session_id"],
            )
        except Exception as error:
            return TargetResponse(None, error_type=f"mem0_library_error:{type(error).__name__}")
        results = raw.get("results") if isinstance(raw, dict) else None
        if not isinstance(results, list) or not results or any(
            not isinstance(result, dict)
            or not isinstance(result.get("id"), str)
            or not result["id"]
            or not isinstance(result.get("event"), str)
            or not result["event"]
            for result in results
        ):
            return TargetResponse(None, error_type="invalid_mem0_add_response", raw_body=raw)
        return TargetResponse(
            200,
            body={
                "success": True,
                "request_id": request["request_id"],
                "user_id": request["user_id"],
                "session_id": request["session_id"],
            },
            raw_body=raw,
        )

    def search(self, request: dict[str, Any]) -> TargetResponse:
        try:
            raw = self.memory.search(
                request["query"],
                top_k=request["top_k"],
                filters={"user_id": request["user_id"]},
                explain=True,
            )
        except Exception as error:
            return TargetResponse(None, error_type=f"mem0_library_error:{type(error).__name__}")
        results = raw.get("results") if isinstance(raw, dict) else None
        if not isinstance(results, list):
            return TargetResponse(None, error_type="invalid_mem0_search_response", raw_body=raw)
        normalized = []
        for result in results:
            if not isinstance(result, dict):
                return TargetResponse(None, error_type="invalid_mem0_search_response", raw_body=raw)
            memory_id = result.get("id")
            content = result.get("memory", result.get("content"))
            if not isinstance(memory_id, str) or not memory_id or not isinstance(content, str) or not content:
                return TargetResponse(None, error_type="invalid_mem0_search_response", raw_body=raw)
            candidate = {"id": memory_id, "content": content}
            score = result.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                candidate["score"] = float(score)
            created_at = result.get("created_at")
            if isinstance(created_at, str):
                candidate["created_at"] = created_at
            candidate["target_metadata"] = {
                field: result[field]
                for field in ("score_details", "categories", "metadata", "run_id")
                if field in result
            }
            normalized.append(candidate)
        return TargetResponse(200, body={"data": normalized}, raw_body=raw)
