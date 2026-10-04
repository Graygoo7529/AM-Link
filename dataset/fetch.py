from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "raw"
CATALOG_PATH = ROOT / "catalog.json"
CHUNK_SIZE = 1024 * 1024


def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def fetch(dataset_id: str) -> Path:
    datasets = load_catalog()["datasets"]
    if dataset_id not in datasets:
        raise ValueError(f"unknown dataset: {dataset_id}")

    source = datasets[dataset_id]
    target = DATA_DIR / source["raw_relative_path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    expected_hash = source.get("sha256")
    if target.exists():
        actual_hash = sha256_file(target)
        if expected_hash and actual_hash != expected_hash:
            raise ValueError(f"existing file has unexpected sha256: {target}")
        print(json.dumps({"path": str(target), "sha256": actual_hash, "status": "present"}))
        return target

    partial = target.with_suffix(target.suffix + ".partial")
    digest = hashlib.sha256()
    byte_count = 0
    request = urllib.request.Request(
        source["download_url"],
        headers={"User-Agent": "AM-Link-dataset-fetch/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            with partial.open("wb") as output:
                while chunk := response.read(CHUNK_SIZE):
                    output.write(chunk)
                    digest.update(chunk)
                    byte_count += len(chunk)
        actual_hash = digest.hexdigest()
        if expected_hash and actual_hash != expected_hash:
            partial.unlink(missing_ok=True)
            raise ValueError(
                f"download sha256 mismatch: expected {expected_hash}, got {actual_hash}"
            )
        if byte_count == 0:
            partial.unlink(missing_ok=True)
            raise ValueError("downloaded file was empty")
        with partial.open("r", encoding="utf-8") as downloaded:
            first_character = ""
            while chunk := downloaded.read(4096):
                first_character = next((char for char in chunk if not char.isspace()), "")
                if first_character:
                    break
        if first_character != "[":
            partial.unlink(missing_ok=True)
            raise ValueError("expected a JSON array dataset")
        partial.replace(target)
    except (OSError, urllib.error.URLError):
        partial.unlink(missing_ok=True)
        raise
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    print(
        json.dumps(
            {
                "path": str(target),
                "bytes": byte_count,
                "sha256": actual_hash,
                "source_revision": source.get("revision"),
                "status": "downloaded",
            }
        )
    )
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Download one licensed public dataset")
    parser.add_argument("dataset", choices=load_catalog()["datasets"].keys())
    arguments = parser.parse_args()
    try:
        fetch(arguments.dataset)
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(f"dataset fetch failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
