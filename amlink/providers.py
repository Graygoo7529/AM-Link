"""Shared, observable one-attempt provider boundary."""
from __future__ import annotations
import math
import threading
import time
from urllib.parse import urlsplit
import httpx
from .errors import MemoryError
from .observation import Observer
from .text import dumps
from .tool_contract import parse_tool

class Providers:
    def __init__(self,config,observer=None,*,transport=None):
        self.config=config
        self.observer=observer or Observer()
        self.client=httpx.Client(transport=transport)
        self.lock=threading.Lock()
        self.calls=0
        self.input_chars=0
        self.responses=0
        self.usage={'input_tokens':0,'output_tokens':0,'cached_tokens':0}
        self.embedding_fingerprint=f'{config.embedding_base_url}|text-embedding-v4|1024|passages-v2'

    def close(self):
        self.client.close()

    def _post(self,path,body,deadline,embedding=False):
        cfg=self.config
        key=cfg.embedding_api_key if embedding else cfg.llm_api_key
        base=cfg.embedding_base_url if embedding else cfg.llm_base_url
        if not key:
            raise MemoryError('provider_not_configured',503)
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise MemoryError('request_deadline',504)
        chars=len(dumps(body))
        if chars>cfg.model_input_chars:
            raise MemoryError('model_input_budget',413)
        with self.lock:
            if (cfg.max_provider_calls and self.calls>=cfg.max_provider_calls) or (cfg.max_provider_input_chars and self.input_chars+chars>cfg.max_provider_input_chars):
                raise MemoryError('provider_run_budget',429)
            self.calls+=1
            self.input_chars+=chars
        with self.observer.span('model', 'embedding' if embedding else 'gpt-4o-mini',inputs=body) as event:
            if event is not None:
                event['model']={'provider':urlsplit(base).hostname,'name':body['model'],'input_tokens':None,
                    'output_tokens':None,'cached_tokens':None,'cost_usd':None,'usage_source':'provider reported; price not assumed'}
            try:
                response=self.client.post(base.rstrip('/')+path,json=body,
                    headers={'Authorization':'Bearer '+key},timeout=min(cfg.model_timeout,remaining))
            except httpx.TimeoutException:
                raise MemoryError('provider_timeout',504) from None
            except httpx.HTTPError:
                raise MemoryError('provider_network',502) from None
            if response.status_code!=200:
                raise MemoryError('provider_rate_limit' if response.status_code==429 else 'provider_http_failure',
                                  429 if response.status_code==429 else 502)
            try:
                value=response.json()
            except ValueError:
                raise MemoryError('provider_invalid_json',502) from None
            if not isinstance(value,dict):
                raise MemoryError('provider_invalid_response',502)
            with self.lock:
                self.responses+=1
            usage=value.get('usage') or {}
            for target,origin in [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens')]:
                n=usage.get(origin)
                if embedding and target=='output_tokens':
                    n=0
                if type(n) is int and n>=0:
                    with self.lock:
                        self.usage[target]+=n
                    if event is not None:
                        event['model'][target]=n
            cached=(usage.get('prompt_tokens_details') or {}).get('cached_tokens')
            if type(cached) is int and cached>=0:
                with self.lock:
                    self.usage['cached_tokens']+=cached
                if event is not None:
                    event['model']['cached_tokens']=cached
            self.observer.output(event,value,title='模型实际输出与用量')
            if time.monotonic()>=deadline:
                raise MemoryError('request_deadline',504)
            return value

    def embed(self,texts,deadline):
        if any(not isinstance(t,str) or not t or len(t.encode('utf-8'))>6000 for t in texts):
            raise MemoryError('embedding_input_budget',413)
        vectors=[]
        for start in range(0,len(texts),self.config.embedding_batch):
            batch=texts[start:start+self.config.embedding_batch]
            value=self._post('/embeddings',{'model':self.config.embedding_model,'input':batch,
                             'dimensions':1024},deadline,embedding=True)
            try:
                rows=sorted(value['data'],key=lambda r:r['index'])
                if [r['index'] for r in rows]!=list(range(len(batch))):
                    raise ValueError()
                for row in rows:
                    v=row['embedding']
                    if len(v)!=1024 or any(type(x) not in (int,float) or not math.isfinite(x) for x in v):
                        raise ValueError()
                    norm=math.sqrt(sum(x*x for x in v))
                    if not norm:
                        raise ValueError()
                    vectors.append([x/norm for x in v])
            except (KeyError,TypeError,ValueError):
                raise MemoryError('embedding_output_invalid',502) from None
        return vectors

    def tool(self,name,prompt,content,schema,deadline):
        tool={'name':name,'description':name.replace('_',' '),'parameters':schema,'strict':True}
        body={'model':self.config.llm_model,'temperature':0,'max_completion_tokens':self.config.model_max_tokens,
            'messages':[{'role':'system','content':prompt},{'role':'user','content':content}],
            'tools':[{'type':'function','function':tool}],
            'tool_choice':{'type':'function','function':{'name':name}},'parallel_tool_calls':False}
        value=self._post('/chat/completions',body,deadline)
        return parse_tool(value,[tool]).arguments

def object_schema(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}

def positions_schema(maximum):
    # The tool describes the data shape. The caller validates cardinality, identity
    # and scope against its actual input, without exposing schema limits as content.
    return {'type':'array','items':{'type':'integer'},
            'description':f'Ordered unique offered position numbers from 1 through {maximum}; empty is allowed.'}
