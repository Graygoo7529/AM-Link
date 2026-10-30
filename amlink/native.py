from __future__ import annotations

import sqlite3
from dataclasses import replace

from benchmark.targets import TargetResponse
from pydantic import ValidationError

from .config import Config
from .engine import Engine
from .errors import MemoryError
from .observation import Observer
from .providers import Providers
from .schemas import AddRequest, SearchRequest
from .store import Store
from . import __version__
from .text import dumps,digest
from pathlib import Path


class NativeTarget:
    def __init__(self, config, recorder=None, artifacts=None, *, providers=None):
        self.config = config
        self.observer = Observer(recorder, artifacts)
        if providers is None and (not config.llm_api_key or not config.embedding_api_key):
            raise ValueError('LLM and embedding credentials are required; there is one default method')
        self.providers = providers or Providers(config, self.observer)
        self.model_capture_complete = providers is None
        self.model_configuration = {
            "llm": config.llm_model,
            "embedding": config.embedding_model,
            "embedding_dimensions": config.embedding_dimensions,
            "internal_retries": 0,
        }
        self.adapter_notes = [
            "atomic episode and complete indexes; bounded navigation-note organization",
            "Search returns exact inspected originals; no raw fallback, no internal retry",
        ]
        self.store = Store(config.db_path)
        self.engine = Engine(config, self.store, self.providers, self.observer)
        if artifacts:
            (artifacts.directory / 'amlink-method.json').write_text(dumps({
                'version':__version__,'config':config.public(),'internal_retries':0,
                'sources':{p.name:p.read_text(encoding='utf-8') for p in Path(__file__).parent.glob('*.py')}
            }),encoding='utf-8')

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

    def set_observation_parent(self, parent):
        self.observer.bind(parent)

    def close(self):
        self.providers.close()
        self.store.close()


def factory(*, recorder, artifacts):
    config = replace(Config.from_env(), db_path=str(artifacts.directory / "memory.sqlite3"))
    return NativeTarget(config, recorder, artifacts)
