from __future__ import annotations

import hmac
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import Config
from .engine import Engine
from .errors import MemoryError
from .observation import Observer
from .providers import Providers
from .schemas import AddRequest, SearchRequest
from .store import Store

def create_app(*, config=None, store=None, providers=None, observer=None):
    config = config or Config.from_env()
    if config.mode == "graph" and providers is None and not config.llm_api_key:
        raise ValueError("graph mode requires AML2_LLM_API_KEY")
    if config.embedding_enabled and providers is None and not config.embedding_api_key:
        raise ValueError("embedding mode requires AML2_EMBEDDING_API_KEY")
    if config.auth_scheme != "none" and not config.api_key:
        raise ValueError("authentication requires AML2_API_KEY")
    store = store or Store(config.db_path)
    observer = observer or Observer()
    providers = providers or Providers(config, observer)
    engine = Engine(config, store, providers, observer)

    @asynccontextmanager
    async def lifespan(application):
        application.state.config = config
        application.state.engine = engine
        try:
            yield
        finally:
            providers.close()
            store.close()

    app = FastAPI(title="AM-Link phase 2", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(MemoryError)
    async def memory_error(_request: Request, error: MemoryError):
        return JSONResponse(status_code=error.status, content={"detail": {"reason": error.code}})

    @app.exception_handler(sqlite3.Error)
    async def storage_error(_request: Request, _error):
        return JSONResponse(status_code=503, content={"detail": {"reason": "storage_failure"}})

    def authorize(request: Request):
        if config.auth_scheme == "none":
            return
        value = request.headers.get("authorization")
        if config.auth_scheme == "x-api-key":
            value = request.headers.get("x-api-key")
        expected = config.api_key
        if not expected:
            raise MemoryError("authentication_not_configured", 503)
        prefix = {"bearer": "Bearer ", "token": "Token ", "x-api-key": ""}[config.auth_scheme]
        if not value or not hmac.compare_digest(value.encode(), (prefix + expected).encode()):
            raise MemoryError("unauthorized", 401)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/v1/memory/add", dependencies=[Depends(authorize)])
    async def add(request: AddRequest):
        result = await run_in_threadpool(engine.add, request)
        return {"success": True, "request_id": result["request_id"],
                "user_id": result["user_id"], "session_id": result["session_id"]}

    @app.post("/v1/memory/search", dependencies=[Depends(authorize)])
    async def search(request: SearchRequest):
        return await run_in_threadpool(engine.search, request)

    return app
