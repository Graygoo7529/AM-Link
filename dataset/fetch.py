from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit, urlencode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "raw"
CATALOG_PATH = ROOT / "catalog.json"
CHUNK_SIZE = 1024 * 1024


def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def source_entry(dataset_id: str) -> dict[str, Any]:
    catalog = load_catalog()
    for section in ("datasets", "sources"):
        source = catalog.get(section, {}).get(dataset_id)
        if source is not None:
            return source
    raise ValueError(f"unknown dataset: {dataset_id}")


def _assets(source: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(source.get("assets"), list):
        return source["assets"]
    if source.get("download_url") and source.get("raw_relative_path"):
        return [
            {
                "path": source["raw_relative_path"],
                "url": source["download_url"],
                "format": source.get("format", "json-array"),
                "sha256": source.get("sha256"),
                "size_bytes": source.get("size_bytes"),
            }
        ]
    return []


def fetch(dataset_id: str, *, github_api: bool = False) -> list[Path]:
    source = source_entry(dataset_id)
    assets = _assets(source)
    if not assets:
        raise ValueError(f"dataset {dataset_id} has no fetchable assets")
    paths = []
    for asset in assets:
        target = (DATA_DIR / asset["path"]).resolve()
        if not target.is_relative_to(DATA_DIR.resolve()):
            raise ValueError(f"asset path escapes the raw data directory: {asset['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        expected_hash = asset.get("sha256")
        expected_size = asset.get("size_bytes")
        if target.exists():
            actual_hash = sha256_file(target)
            if expected_hash and actual_hash != expected_hash:
                raise ValueError(f"existing file has unexpected sha256: {target}")
            _validate_format(target, asset.get("format", "json"))
            print(json.dumps({"path": str(target), "sha256": actual_hash, "status": "present"}))
            paths.append(target)
            continue

        partial = target.with_suffix(target.suffix + ".partial")
        digest = hashlib.sha256()
        byte_count = 0
        request = urllib.request.Request(
            asset["url"],
            headers={"User-Agent": "AM-Link-dataset-fetch/2"},
        )
        try:
            if github_api:
                data = _github_asset(asset["url"])
                partial.write_bytes(data)
                digest.update(data)
                byte_count = len(data)
            else:
                with urllib.request.urlopen(request, timeout=60) as response:
                    with partial.open("wb") as output:
                        while chunk := response.read(CHUNK_SIZE):
                            output.write(chunk)
                            digest.update(chunk)
                            byte_count += len(chunk)
            actual_hash = digest.hexdigest()
            if expected_hash and actual_hash != expected_hash:
                raise ValueError(
                    f"download sha256 mismatch: expected {expected_hash}, got {actual_hash}"
                )
            if expected_size is not None and byte_count != expected_size:
                raise ValueError(
                    f"download size mismatch: expected {expected_size}, got {byte_count}"
                )
            if byte_count == 0:
                raise ValueError("downloaded file was empty")
            _validate_format(partial, asset.get("format", "json"))
            partial.replace(target)
            receipt = {
                "source_url": asset["url"],
                "transport": "github-api" if github_api else "direct",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "sha256": actual_hash,
                "bytes": byte_count,
                "source_revision": source.get("revision"),
            }
            target.with_suffix(target.suffix + ".receipt.json").write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
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
        paths.append(target)
    return paths


def _github_asset(url: str) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
        raise ValueError("--github-api only supports raw.githubusercontent.com sources")
    owner, repo, revision, path = parsed.path.lstrip("/").split("/", 3)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{quote(path, safe='/')}?ref={quote(revision, safe='')}"
    headers = {"User-Agent": "AM-Link-dataset-fetch/2", "Accept": "application/vnd.github+json"}
    with urllib.request.urlopen(urllib.request.Request(api_url, headers=headers), timeout=60) as response:
        payload = json.load(response)
    if payload.get("encoding") != "base64":
        blob_url = f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{payload['sha']}"
        with urllib.request.urlopen(urllib.request.Request(blob_url, headers=headers), timeout=60) as response:
            payload = json.load(response)
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        raise ValueError("GitHub API did not return file content")
    data = base64.b64decode("".join(payload["content"].split()), validate=True)
    blob_hash = hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()
    if blob_hash != payload.get("sha"):
        raise ValueError("GitHub blob hash mismatch")
    return data


def fetch_sample(dataset_id: str, *, offset: int, limit: int) -> Path:
    """Keep the original HF row response plus a lossless, untruncated JSONL extract."""
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("sample offset must be non-negative and rows must be between 1 and 100")
    source = source_entry(dataset_id)
    if not source.get("hf_repository"):
        raise ValueError(f"{dataset_id} has no Hugging Face row endpoint")
    query = urlencode({
        "dataset": source["hf_repository"], "config": source["hf_config"],
        "split": source["hf_split"], "offset": offset, "length": limit,
    })
    url = f"https://datasets-server.huggingface.co/rows?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "AM-Link-dataset-fetch/2"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        payload = json.loads(raw)
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("row endpoint returned no rows")
    if payload.get("partial") or any(row.get("truncated_cells") for row in rows):
        raise ValueError("row endpoint truncated source cells; refusing an incomplete history")
    if [row.get("row_idx") for row in rows] != list(range(offset, offset + len(rows))):
        raise ValueError("row endpoint returned unexpected row indices")
    target = ROOT / "data" / "snapshots" / dataset_id / f"{source['hf_split']}-{offset}-{limit}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError(f"sample already exists; inspect or choose another row range: {target}")
    response_path = target.with_suffix(".response.json")
    response_path.write_bytes(raw)
    target.write_text("".join(json.dumps(row["row"], ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    receipt = {
        "source_url": url, "source_kind": "hf-row-api-snapshot", "repository": source["hf_repository"],
        "config": source["hf_config"], "split": source["hf_split"], "offset": offset,
        "requested_rows": limit, "rows": len(rows), "source_total_rows": payload.get("num_rows_total"),
        "source_revision": None, "revision_note": "Row API serves its current cached dataset, not a pinned repository revision.",
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "sha256": sha256_file(target),
        "response_sha256": hashlib.sha256(raw).hexdigest(), "truncated_cells": [],
    }
    target.with_suffix(target.suffix + ".receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(target), **receipt}))
    return target


def _validate_format(path: Path, file_format: str) -> None:
    if file_format == "jsonl":
        with path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if line.strip():
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ValueError(f"invalid JSONL on line {line_number}: {path}") from error
        return
    if file_format in {"json", "json-array", "json-object"}:
        if file_format == "json-array":
            from dataset.prepare import iter_json_array

            for _ in iter_json_array(path):
                pass
            return
        with path.open("r", encoding="utf-8") as source:
            json.load(source)
        return
    if file_format == "csv":
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            if csv.DictReader(source).fieldnames is None:
                raise ValueError(f"CSV is missing a header row: {path}")
        return
    if file_format != "text":
        raise ValueError(f"unsupported asset format: {file_format}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    catalog = load_catalog()
    dataset_ids = tuple(catalog.get("datasets", {})) + tuple(catalog.get("sources", {}))
    parser = argparse.ArgumentParser(description="Download licensed public dataset assets")
    parser.add_argument("dataset", choices=dataset_ids)
    parser.add_argument("--github-api", action="store_true", help="use the equivalent GitHub Contents/Blob API")
    parser.add_argument("--sample-rows", type=int, help="fetch an untruncated HF row snapshot (1-100)")
    parser.add_argument("--offset", type=int, default=0)
    arguments = parser.parse_args()
    try:
        if arguments.sample_rows is not None:
            if arguments.github_api:
                raise ValueError("--github-api and --sample-rows are mutually exclusive")
            fetch_sample(arguments.dataset, offset=arguments.offset, limit=arguments.sample_rows)
        else:
            fetch(arguments.dataset, github_api=arguments.github_api)
    except (OSError, ValueError, urllib.error.URLError, csv.Error) as error:
        print(f"dataset fetch failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
