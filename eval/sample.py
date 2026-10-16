"""Takes a stratified sample of (advisory group, target) pairs.

The sample has about 300 pairs. Positive pairs (by oracle label) are over-sampled to about 40%.
Every advisory group is included, and every demo repo is paired with the replay advisory group.
The seed is fixed. Writes eval/sample.json.

    uv run python -m eval.sample [--n 300] [--pos-share 0.4]
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict

from eval.dataset import EVAL, SEED
from eval.dataset import OUT as DATASET

OUT = EVAL / "sample.json"


def stratify(pairs: list[dict], n: int, pos_share: float, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    key = lambda p: (p["unit"], p["target"])  # noqa: E731
    chosen: dict[tuple[str, str], dict] = {}
    for p in pairs:  # always include the replay against every demo repo
        if p["unit"] == "chalk-debug" and p["target_kind"] == "repo":
            chosen[key(p)] = p

    by_unit: dict[str, dict[bool, list[dict]]] = defaultdict(lambda: {True: [], False: []})
    for p in sorted(pairs, key=key):
        by_unit[p["unit"]][p["oracle_exposed"]].append(p)
    units = sorted(by_unit)
    n_pos = round(n * pos_share)
    per_unit_pos = max(1, n_pos // len(units))
    per_unit_neg = max(1, (n - n_pos) // len(units))
    for u in units:
        for label, quota in ((True, per_unit_pos), (False, per_unit_neg)):
            pool = [p for p in by_unit[u][label] if key(p) not in chosen]
            for p in rng.sample(pool, min(quota, len(pool))):
                chosen[key(p)] = p

    # Add remaining pairs until there are n. Keep the positive share while positive pairs remain.
    rest: dict[bool, list[dict]] = {True: [], False: []}
    for p in sorted(pairs, key=key):
        if key(p) not in chosen:
            rest[p["oracle_exposed"]].append(p)
    rng.shuffle(rest[True])
    rng.shuffle(rest[False])
    while len(chosen) < n and (rest[True] or rest[False]):
        pos_now = sum(p["oracle_exposed"] for p in chosen.values())
        want_pos = pos_now < pos_share * (len(chosen) + 1)
        src = rest[True] if (want_pos and rest[True]) or not rest[False] else rest[False]
        p = src.pop()
        chosen[key(p)] = p
    return sorted(chosen.values(), key=key)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--pos-share", type=float, default=0.4)
    args = ap.parse_args()
    data = json.loads(DATASET.read_text())
    sample = stratify(data["pairs"], args.n, args.pos_share)
    per_unit: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for p in sample:
        per_unit[p["unit"]][0 if p["oracle_exposed"] else 1] += 1
    OUT.write_text(
        json.dumps(
            {
                "seed": SEED,
                "n": len(sample),
                "positives": sum(p["oracle_exposed"] for p in sample),
                "per_unit": {u: {"pos": c[0], "neg": c[1]} for u, c in sorted(per_unit.items())},
                "pairs": [{"unit": p["unit"], "target": p["target"]} for p in sample],
            },
            indent=1,
        )
    )
    pos = sum(p["oracle_exposed"] for p in sample)
    print(f"sample: {len(sample)} pairs, {pos} positive ({pos / len(sample):.0%})")
    for u, c in sorted(per_unit.items()):
        print(f"  {u:24s} pos={c[0]:3d} neg={c[1]:3d}")


if __name__ == "__main__":
    main()
