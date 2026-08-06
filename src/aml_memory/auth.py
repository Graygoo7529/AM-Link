from __future__ import annotations

import hmac

from fastapi import Request

from .errors import AuthenticationError
from .settings import Settings


class MemorySystemAuthenticator:
    def __init__(self, settings: Settings) -> None:
        self.scheme = settings.auth_scheme
        self.api_key = settings.api_key

    def verify(self, request: Request) -> None:
        if self.scheme == "none":
            return
        provided = self._credential(request)
        if not provided or not hmac.compare_digest(provided, self.api_key):
            raise AuthenticationError("invalid or missing Memory System Key")

    def _credential(self, request: Request) -> str | None:
        if self.scheme == "x-api-key":
            return request.headers.get("X-Api-Key")
        authorization = request.headers.get("Authorization", "")
        expected_scheme = "Bearer" if self.scheme == "bearer" else "Token"
        supplied_scheme, separator, credential = authorization.partition(" ")
        if not separator or supplied_scheme.casefold() != expected_scheme.casefold():
            return None
        return credential.strip() or None
