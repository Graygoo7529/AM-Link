"""Validate the single curated case catalog and escape presentation payloads."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PLACEHOLDER = "__AML_CATALOG_JSON__"


def load_catalog(path: Path = ROOT / "catalog.json") -> dict:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("schemaVersion") != 1:
        raise ValueError("unsupported catalog schemaVersion")
    datasets, cases = catalog["datasets"], catalog["cases"]
    for key, dataset in datasets.items():
        for case_id in dataset["cases"]:
            if case_id not in cases:
                raise ValueError(f"unknown case {case_id} in dataset {key}")
        for link in dataset.get("links", []):
            if urlparse(link["url"]).scheme != "https":
                raise ValueError(f"source link must use HTTPS: {key}")
    for key, case in cases.items():
        doc = (path.parent / case["document"]).resolve()
        if not doc.is_relative_to(path.parent.resolve()) or not doc.is_file():
            raise ValueError(f"missing or external case document: {key}")
        if "data" in case:
            data = case["data"]
            if set(data) != {"dataset", "pack", "record", "task", "turns"} or data["dataset"] not in datasets or key not in datasets[data["dataset"]]["cases"]:
                raise ValueError(f"invalid source binding: {key}")
            pack_path = Path(data["pack"])
            if pack_path.is_absolute() or ".." in pack_path.parts or not data["pack"].startswith("dataset/data/prepared/"):
                raise ValueError(f"invalid case pack path: {key}")
            if not all(isinstance(data[k], str) and data[k] for k in ("record", "task")) or not isinstance(data["turns"], list) or not all(isinstance(t,str) and t for t in data["turns"]) or len(set(data["turns"])) != len(data["turns"]):
                raise ValueError(f"invalid source IDs: {key}")
    default = catalog["defaultState"]
    if default["dataset"] not in datasets or default["case"] not in datasets[default["dataset"]]["cases"]:
        raise ValueError("invalid default selection")
    return catalog


def render_fragment(catalog: dict, template: str) -> str:
    if template.count(PLACEHOLDER) != 1:
        raise ValueError("template must have exactly one catalog placeholder")
    # Escape HTML/script boundaries in future case text, without evaluating it.
    payload = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return template.replace(PLACEHOLDER, payload)


