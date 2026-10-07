"""Build the unified research explorer without running a memory system."""
from __future__ import annotations

import argparse
import copy
import html
import json
import subprocess
import sys
from pathlib import Path

from casestudies.build import find_renderer, load_catalog, render_fragment
from visualization.sources import local_sources
from visualization.traces import attach_observations, read_run

ROOT = Path(__file__).resolve().parent


def build_bundle(local: bool = False, run_specs: list[tuple[Path, str]] | None = None,
    observations: Path | None = None) -> dict:
    catalog = load_catalog()
    profiles = json.loads((ROOT / "profiles.json").read_text(encoding="utf-8"))
    if profiles.get("schema_version") != 1 or set(profiles["datasets"]) != set(catalog["datasets"]):
        raise ValueError("profiles must cover the case catalog datasets")
    for key, profile in profiles["datasets"].items():
        if "fieldsFrom" in profile:
            profile["fields"] = copy.deepcopy(profiles["datasets"][profile["fieldsFrom"]]["fields"])
        for field in profile["fields"]:
            if len(field) != 4 or field[1] not in {"history", "task", "annotations", "auxiliary", "metadata"}:
                raise ValueError(f"invalid field routing in {key}")
    for key, binding in profiles["bindings"].items():
        if key not in catalog["cases"] or key not in catalog["datasets"][binding["dataset"]]["cases"]:
            raise ValueError(f"case binding mismatch: {key}")
    if (run_specs or observations) and not local:
        raise ValueError("raw samples and traces require --local")
    bundle = {"schema_version": 1, "updated": profiles["updated"], "catalog": catalog,
        "profiles": profiles, "scope": "local" if local else "curated",
        "local": local_sources(profiles) if local else {"samples": {}, "stats": {}, "missing": []},
        "runs": [read_run(path, kind) for path, kind in (run_specs or [])]}
    bundle["research"] = json.loads((ROOT / "research.json").read_text(encoding="utf-8"))
    if len({r["run_id"] for r in bundle["runs"]}) != len(bundle["runs"]):
        raise ValueError("duplicate run ID")
    if observations:
        attach_observations(bundle["runs"], observations)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--run", type=Path, action="append", default=[])
    parser.add_argument("--run-kind", choices=("fixture", "experiment"), action="append", default=[])
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--renderer", type=Path)
    parser.add_argument("--inline-output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if len(args.run) != len(args.run_kind):
        parser.error("each --run requires one --run-kind")
    bundle = build_bundle(args.local, list(zip(args.run, args.run_kind)), args.observations)
    fragment = render_fragment(bundle, (ROOT / "view.template.html").read_text(encoding="utf-8"))
    if len(fragment.encode("utf-8")) >= 1_000_000:
        raise ValueError("view exceeds 1 MB; select fewer runs or reduce projection size")
    directory = ROOT / "data/local" if args.local else ROOT
    view, webpage = directory / "view.html", directory / "index.html"
    if args.check:
        if args.web or args.inline_output:
            parser.error("--check cannot write outputs")
        if not view.exists() or view.read_text(encoding="utf-8") != fragment:
            raise SystemExit("view is stale; rebuild")
        if not webpage.exists() or fragment not in html.unescape(webpage.read_text(encoding="utf-8")):
            raise SystemExit("webpage is stale; rebuild with --web")
        print("Profiles, cases and both views are consistent.")
        return
    if args.inline_output:
        dest = args.inline_output.resolve()
        # An inline copy must not overwrite source files or local research artifacts.
        repo = ROOT.parent
        if dest.is_relative_to(repo) and not dest.is_relative_to(ROOT / "data"):
            raise ValueError("inline copy must be outside tracked project sources")
    directory.mkdir(parents=True, exist_ok=True)
    view.write_text(fragment, encoding="utf-8", newline="\n")
    if args.local:
        (directory / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if args.inline_output:
        args.inline_output.parent.mkdir(parents=True, exist_ok=True)
        args.inline_output.write_text(fragment, encoding="utf-8", newline="\n")
    if args.web:
        subprocess.run([sys.executable, "-X", "utf8", str(args.renderer or find_renderer()), str(view),
            str(webpage), "--title", "AM-Link 研究可视化", "--force"], check=True)
    print(f"{view}: {len(bundle['catalog']['datasets'])} datasets, {len(bundle['local']['samples'])} local samples, {len(bundle['runs'])} runs")


if __name__ == "__main__":
    main()
