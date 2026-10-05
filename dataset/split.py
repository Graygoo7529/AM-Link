from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from pathlib import Path

from dataset.pack import load_pack, validate_pack, write_pack


def split_pack(pack: dict, *, holdout_fraction: float, seed: int) -> dict[str, dict]:
    """Keep records sharing an explicit group/persona/history together."""
    validate_pack(pack)
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout-fraction must be between 0 and 1")
    groups = sorted({str(r.get("group_id", r["id"])) for r in pack["records"]})
    if len(groups) < 2:
        raise ValueError("at least two independent groups are required for a split")
    random.Random(seed).shuffle(groups)
    count = min(len(groups) - 1, max(1, round(len(groups) * holdout_fraction)))
    holdout = set(groups[:count])
    parent_hash = hashlib.sha256(json.dumps(pack, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result = {}
    for name in ("dev", "holdout"):
        child = copy.deepcopy(pack)
        child["records"] = [r for r in child["records"] if (str(r.get("group_id", r["id"])) in holdout) == (name == "holdout")]
        child["preparation"]["selection"] = {
            "parent_selection": pack["preparation"]["selection"], "parent_pack_sha256": parent_hash,
            "split": name, "seed": seed, "holdout_fraction": holdout_fraction,
            "group_key": "group_id, falling back to record.id",
            "record_ids": [r["id"] for r in child["records"]],
        }
        result[name] = child
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a dataset pack by independent source groups")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--holdout-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    packs = split_pack(load_pack(args.input), holdout_fraction=args.holdout_fraction, seed=args.seed)
    if any((args.output_dir / f"{name}.json").exists() for name in packs):
        parser.error("split output files already exist")
    for name, pack in packs.items():
        write_pack(args.output_dir / f"{name}.json", pack)
    print(json.dumps({name: len(pack["records"]) for name, pack in packs.items()}))


if __name__ == "__main__":
    main()
