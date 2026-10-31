"""Verify an extracted release's file hashes and installed dependency versions."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    problems = []
    for name, expected in manifest['files'].items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            problems.append('file mismatch: ' + name)
    for line in (root / 'deploy/requirements.lock').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        requirement, _, marker = line.partition(';')
        if marker and 'win32' in marker and sys.platform != 'win32':
            continue
        name, version = requirement.strip().split('==')
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = 'missing'
        if installed != version:
            problems.append('dependency mismatch: ' + name)
    if sys.version_info[:2] != (3, 13):
        problems.append('release validation requires Python 3.13')
    print(json.dumps({'version': manifest['version'], 'files': len(manifest['files']),
                      'ok': not problems, 'problems': problems}))
    return bool(problems)


if __name__ == '__main__':
    raise SystemExit(main())
