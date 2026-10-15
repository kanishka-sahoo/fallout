"""Seed package list (BUILD.md §5.1): the top of npm-high-impact, plus every package named in
the replay incident. Repo direct dependencies are added separately by repo_seeds.py.

    uv run python -m ingest.seed --limit 5000
"""

from __future__ import annotations

import argparse
import json
import subprocess

from fallout.node import WORKERS
from fallout.settings import RAW_DIR, load_anchor

SEEDS_PATH = RAW_DIR / "seeds.json"


def high_impact() -> list[str]:
    out = subprocess.run(
        ["node", "--input-type=module", "-e",
         "import { npmHighImpact } from 'npm-high-impact'; console.log(JSON.stringify(npmHighImpact))"],
        cwd=WORKERS, capture_output=True, text=True, check=True,
    )  # fmt: skip
    names: list[str] = json.loads(out.stdout)
    return names


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=5000)
    args = ap.parse_args()

    ranked = high_impact()
    incident = sorted({v["name"] for v in load_anchor()["malicious_versions"]})
    seeds = list(dict.fromkeys([*incident, *ranked[: args.limit]]))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    SEEDS_PATH.write_text(json.dumps({"limit": args.limit, "forced": incident, "seeds": seeds}, indent=1))
    print(f"{len(seeds)} seeds ({len(incident)} forced from the incident) -> {SEEDS_PATH}")


if __name__ == "__main__":
    main()
