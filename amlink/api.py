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
from .providers import Providers
from .schemas import AddRequest, SearchRequest
from .store import Store
from .observation import Observer


def create_app(*, config=None, store=None, providers=None):
    config = config or Config.from_env()
    if providers is None and (not config.llm_api_key or not config.embedding_api_key):
        raise ValueError('LLM and embedding credentials are required')
    store = store or Store(config.db_path)
    providers = providers or Providers(config)
    engine = Engine(config, store, providers, Observer())

    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = engine
        yield
        providers.close()
        store.close()

    app = FastAPI(title="AM-Link", version="0.3.0-clean", lifespan=lifespan)

    @app.exception_handler(MemoryError)
    async def memory_error(_request: Request, error: MemoryError):
        return JSONResponse(status_code=error.status, content={"detail": {"reason": error.code}})

    @app.exception_handler(sqlite3.Error)
    async def storage_error(_request: Request, _error):
        return JSONResponse(status_code=503, content={"detail": {"reason": "storage_failure"}})

    def authorize(request: Request):
        if config.auth_scheme == "none":
            return
        actual = request.headers.get("x-api-key") if config.auth_scheme == "x-api-key" else request.headers.get("authorization")
        prefix = {"bearer": "Bearer ", "token": "Token ", "x-api-key": ""}[config.auth_scheme]
        if not actual or not hmac.compare_digest(actual.encode(), (prefix + config.api_key).encode()):
            raise MemoryError("unauthorized", 401)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.3.0-clean"}

    @app.post("/v1/memory/add", dependencies=[Depends(authorize)])
    async def add(request: AddRequest):
        return await run_in_threadpool(engine.add, request)

    @app.post("/v1/memory/search", dependencies=[Depends(authorize)])
    async def search(request: SearchRequest):
        return await run_in_threadpool(engine.search, request)

    return app
