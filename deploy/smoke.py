"""Exercise the real HTTP API with synthetic text; no model or HTTP retries."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--user-id', default='deployment-smoke-' + uuid.uuid4().hex)
    parser.add_argument('--verify-only', action='store_true', help='Read the same synthetic user after a restart.')
    args = parser.parse_args()
    if args.env_file:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from amlink.config import load_env_file
        load_env_file(args.env_file)
    url = urlsplit(args.base_url)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('base URL must contain no credentials, query, or fragment')
    scheme, key = os.environ.get('AML3_AUTH_SCHEME'), os.environ.get('AML3_API_KEY')
    if scheme not in {'bearer', 'token', 'x-api-key'} or not key:
        raise ValueError('configure authenticated AML3_AUTH_SCHEME and AML3_API_KEY')
    header = {'x-api-key': key} if scheme == 'x-api-key' else {'Authorization': ('Bearer ' if scheme == 'bearer' else 'Token ') + key}

    def call(path, value=None, *, authenticated=True, expected=200):
        body = json.dumps(value).encode() if value is not None else None
        headers = {'Content-Type': 'application/json', **(header if authenticated else {})}
        request = Request(args.base_url.rstrip('/') + path, data=body, headers=headers)
        try:
            with urlopen(request, timeout=1800) as response:
                status, result = response.status, response.read()
        except HTTPError as error:
            status, result = error.code, error.read()
        if status != expected:
            raise RuntimeError(f'{path}: expected {expected}, received {status}')
        return json.loads(result)

    health = call('/health', authenticated=False)
    query = {'user_id': args.user_id, 'query': 'What is the current quota for the synthetic Cedar project?', 'top_k': 5}
    call('/v1/memory/search', query, authenticated=False, expected=401)
    call('/v1/memory/search', query | {'top_k': 0}, expected=422)
    if not args.verify_only:
        add = {'request_id': 'first', 'user_id': args.user_id, 'session_id': 'synthetic',
               'messages': [{'role': 'user', 'content': 'The synthetic Cedar project quota is 1000 calls per day.', 'timestamp': 1780272000000}]}
        # Four concurrent copies are one logical Add, not retries after failure.
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: call('/v1/memory/add', add), range(4)))
        expected = {'success': True, **{name: add[name] for name in ('request_id', 'user_id', 'session_id')}}
        if any(value != expected for value in values):
            raise RuntimeError('Add receipt does not match the request')
        update = add | {'request_id': 'update', 'messages': [{'role': 'user', 'content': 'Correction: the synthetic Cedar project quota is now 1200 calls per day.', 'timestamp': 1780358400000}]}
        call('/v1/memory/add', update)
        call('/v1/memory/add', add | {'messages': update['messages']}, expected=422)
    result = call('/v1/memory/search', query)
    rows = result.get('data')
    if not isinstance(rows, list) or len(rows) > 5 or any(not row.get('id') or not row.get('content') for row in rows):
        raise RuntimeError('invalid Search result')
    if not any('1200' in row['content'] for row in rows):
        raise RuntimeError('current quota original is missing from Search')
    isolated = call('/v1/memory/search', query | {'user_id': args.user_id + '-empty'})
    if isolated != {'data': []}:
        raise RuntimeError('empty user returned memory')
    print(json.dumps({'ok': True, 'version': health.get('version'), 'user_id': args.user_id,
                      'verify_only': args.verify_only, 'returned': len(rows),
                      'checks': ['auth', 'request_schema', 'evidence', 'user_isolation'] +
                      ([] if args.verify_only else ['concurrent_idempotency', 'conflicting_replay'])}))


if __name__ == '__main__':
    main()
