"""Build a source-only release with an explicit allowlist; never include local data."""
from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('__init__', '__main__', 'api', 'config', 'engine', 'errors', 'observation',
           'providers', 'reading', 'schemas', 'store', 'text', 'tool_contract')
FILES = ([f'amlink/{name}.py' for name in MODULES] +
         ['DESIGN.md', 'deploy/README.md', 'deploy/.env.example', 'deploy/requirements.lock',
          'deploy/amlink.service', 'deploy/nginx-location.conf', 'deploy/smoke.py',
          'deploy/verify.py'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'amlink/data/releases')
    args = parser.parse_args()
    version = ast.literal_eval(ast.parse((ROOT / 'amlink/__init__.py').read_text()).body[0].value)
    prefix = 'amlink-' + version
    contents = {name: (ROOT / name).read_bytes() for name in FILES}
    for name in ('LICENSE', 'LICENSE.md'):
        if (ROOT / name).is_file():
            contents[name] = (ROOT / name).read_bytes()
    command = ['git', '-c', f'safe.directory={ROOT.as_posix()}', '-C', str(ROOT)]
    commit = subprocess.check_output(command + ['rev-parse', 'HEAD'], text=True).strip()
    dirty = bool(subprocess.check_output(command + ['status', '--porcelain'], text=True).strip())
    manifest = {'version': version, 'base_commit': commit, 'working_tree_dirty': dirty,
                'python': '3.13', 'database_version': 301, 'index': 'passages-v2',
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())},
                'scope': 'Textual Add/Search runtime; no datasets, databases, research runner or credentials.'}
    contents['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for name, data in sorted(contents.items()):
                info = tarfile.TarInfo(prefix + '/' + name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                archive.addfile(info, io.BytesIO(data))
    data = buffer.getvalue()
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / (prefix + '.tar.gz')
    if target.exists() and target.read_bytes() != data:
        raise SystemExit('Release path already contains different bytes; use another output directory.')
    if not target.exists():
        target.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    target.with_suffix(target.suffix + '.sha256').write_text(digest + '  ' + target.name + '\n', encoding='ascii')
    print(json.dumps({'package': str(target), 'sha256': digest, 'files': len(contents),
                      'base_commit': commit, 'working_tree_dirty': dirty}))


if __name__ == '__main__':
    main()
