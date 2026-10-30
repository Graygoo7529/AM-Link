"""Build both conversation and standalone views from one curated catalog."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
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


def find_renderer() -> Path:
    codex_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    candidates = list((codex_root / "plugins/cache/openai-bundled/visualize").glob("*/skills/visualize/scripts/render.py"))
    if not candidates:
        raise ValueError("visualize renderer not found; supply --renderer PATH. Existing index.html still works.")
    return max(candidates, key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.parents[3].name)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", action="store_true", help="also export standalone index.html")
    parser.add_argument("--renderer", type=Path, help="visualize skill scripts/render.py")
    parser.add_argument("--inline-output", type=Path, help="also copy current fragment to a chat-owned visualization path")
    parser.add_argument("--check", action="store_true", help="check catalog and both generated views without writes")
    args = parser.parse_args()
    fragment = render_fragment(load_catalog(), (ROOT / "view.template.html").read_text(encoding="utf-8"))
    output = ROOT / "view.html"
    if args.check:
        if args.web or args.inline_output:
            parser.error("--check cannot be combined with output options")
        if not output.exists() or output.read_text(encoding="utf-8") != fragment:
            raise SystemExit("view.html is stale; run python -m casestudies.build --web")
        webpage = ROOT / "index.html"
        if not webpage.exists() or fragment not in html.unescape(webpage.read_text(encoding="utf-8")):
            raise SystemExit("index.html is stale; run python -m casestudies.build --web")
        print("Catalog, case references, view.html and index.html are consistent.")
        return
    for destination in [output] + ([args.inline_output] if args.inline_output else []):
        if destination.resolve() in {(ROOT / "catalog.json").resolve(), (ROOT / "view.template.html").resolve()}:
            raise ValueError("cannot overwrite visualization sources")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(fragment, encoding="utf-8", newline="\n")
    if args.web:
        renderer = args.renderer or find_renderer()
        subprocess.run([sys.executable, "-X", "utf8", str(renderer), str(output), str(ROOT / "index.html"),
            "--title", "AM-Link 数据集与案例库", "--force"], check=True)
    print(f"{len(load_catalog()['datasets'])} datasets / {len(load_catalog()['cases'])} cases: {output}")


if __name__ == "__main__":
    main()
