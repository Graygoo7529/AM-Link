from __future__ import annotations
import math
import os
from dataclasses import dataclass, fields
from pathlib import Path
from urllib.parse import urlsplit

@dataclass(frozen=True)
class Config:
    db_path: str = 'amlink/data/memory.sqlite3'
    llm_base_url: str = 'https://api.zhizengzeng.com/v1'
    llm_api_key: str = ''
    llm_model: str = 'gpt-4o-mini'
    embedding_base_url: str = 'https://api.zhizengzeng.com/v1'
    embedding_api_key: str = ''
    embedding_model: str = 'text-embedding-v4'
    embedding_dimensions: int = 1024
    embedding_batch: int = 10
    model_timeout: float = 90.0
    request_seconds: float = 1740.0
    model_input_chars: int = 80000
    model_max_tokens: int = 4096
    reflection_batch: int = 16
    reflection_min_adds: int = 2
    reflection_chars: int = 12000
    reflection_max_items: int = 6
    candidate_limit: int = 24
    result_chars: int = 24000
    max_provider_calls: int = 0
    max_provider_input_chars: int = 0
    auth_scheme: str = 'none'
    api_key: str = ''

    def __post_init__(self):
        if self.llm_model != 'gpt-4o-mini' or self.embedding_model != 'text-embedding-v4' or self.embedding_dimensions != 1024:
            raise ValueError('required models: gpt-4o-mini and text-embedding-v4/1024')
        if not 1 <= self.embedding_batch <= 10 or not 1 <= self.candidate_limit <= 24:
            raise ValueError('invalid batch or candidate limit')
        if self.request_seconds >= 1800 or self.model_timeout > self.request_seconds:
            raise ValueError('invalid request deadline')
        for field in fields(self):
            v = getattr(self,field.name)
            if field.name in {'max_provider_calls','max_provider_input_chars'} and v == 0:
                continue
            if type(v) in (int,float) and (not math.isfinite(v) or v <= 0):
                raise ValueError(f'{field.name} must be positive and finite')
        for base in (self.llm_base_url, self.embedding_base_url):
            url=urlsplit(base)
            if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError('invalid provider URL')
        if self.auth_scheme not in {'none','bearer','token','x-api-key'}:
            raise ValueError('invalid authentication scheme')
        if self.auth_scheme != 'none' and not self.api_key:
            raise ValueError('authenticated service requires an API key')

    @classmethod
    def from_env(cls):
        defaults=cls()
        return cls(**{f.name:type(getattr(defaults,f.name))(os.environ['AML3_'+f.name.upper()])
                      for f in fields(cls) if 'AML3_'+f.name.upper() in os.environ})

    def public(self):
        return {f.name:getattr(self,f.name) for f in fields(self) if 'key' not in f.name and f.name != 'db_path'}

def load_env_file(path: Path):
    valid={f.name.upper() for f in fields(Config)}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        name,sep,value=line.strip().partition('=')
        if not sep or not name.startswith(('AML2_','AML3_')) or name[5:] not in valid:
            raise ValueError('unsupported configuration assignment')
        os.environ['AML3_'+name[5:]]=value.strip().strip('"').strip("'")
