"""Native arena factory, isolated SQLite database and standard observations."""
from __future__ import annotations

import sqlite3
import hashlib
from dataclasses import replace
from pathlib import Path

from pydantic import ValidationError

from benchmark.targets import TargetResponse

from . import __version__
from .config import Config
from .engine import Engine
from .errors import MemoryError
from .observation import Observer
from .providers import Providers
from .schemas import AddRequest, SearchRequest
from .store import Store
from .text import dumps


class NativeTarget:
    def __init__(self, config, recorder=None, artifacts=None, *, providers=None):
        self.config = config
        self.observer = Observer(recorder, artifacts)
        if config.mode == "graph" and providers is None and not config.llm_api_key:
            raise ValueError("graph mode requires AML2_LLM_API_KEY")
        if config.embedding_enabled and providers is None and not config.embedding_api_key:
            raise ValueError("embedding requires AML2_EMBEDDING_API_KEY")
        self.providers = providers or Providers(config, self.observer)
        self.model_capture_complete = providers is None
        self.store = Store(config.db_path)
        self.engine = Engine(config, self.store, self.providers, self.observer)
        if artifacts:
            (artifacts.directory / "amlink-method.json").write_text(
                dumps({"version": __version__, "config": config.public(), "retries": 0,
                       "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in sorted(Path(__file__).parent.glob("*.py"))},
                       "embedding_scope": "memory nodes; pending raw uses lexical",
                       "answer": "not part of AM-Link"}) + "\n", encoding="utf-8")

    def set_observation_parent(self, parent):
        self.observer.bind(parent)

    def _call(self, operation, request):
        try:
            schema = AddRequest if operation == "add" else SearchRequest
            result = getattr(self.engine, operation)(schema.model_validate(request))
            return TargetResponse(200, result)
        except ValidationError:
            return TargetResponse(422, error_code="invalid_request")
        except MemoryError as error:
            return TargetResponse(error.status, error_code=error.code)
        except sqlite3.Error:
            return TargetResponse(503, error_code="storage_failure")

    def add(self, request):
        return self._call("add", request)

    def search(self, request):
        return self._call("search", request)

    def close(self):
        self.providers.close()
        self.store.close()


def factory(*, recorder, artifacts):
    config = replace(Config.from_env(), db_path=str(artifacts.directory / "memory.sqlite3"))
    return NativeTarget(config, recorder, artifacts)
