"""Builds the eval dataset: advisory groups x targets, labelled by the oracle and by the graph.

1. Each advisory group in eval/advisories.json is ingested as incident `eval-<unit>`, and its
   blast radius is stored. This is the graph data that the System C tools read.
2. Targets: the demo repos, a fixed random sample (seed 42) of seed packages at their version
   at S, and a second stratum from the most-downloaded seeds (DECISIONS D11). The seeds that
   come from the incident (the chalk and duckdb packages) are not included.
3. The oracle (eval/oracle/oracle.mjs) does not read FalkorDB. It builds each target's ideal
   tree once and labels it for every advisory group. The affected versions come directly from
   OSV and the registry (fallout.advisory.fetch), not from the graph. The trees and lockfiles
   are kept for the hallucination check and for System B.
4. The graph label for every pair is also recorded, for the disagreement analysis.

Writes eval/dataset.json.
    uv run python -m eval.dataset [--targets 200] [--top-targets 300] [--jobs 8] [--skip-ingest]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fallout.advisory import fetch, ingest_advisory
from fallout.blast import blast_radius
from fallout.db import graph, rows
from fallout.resolve import crawl_resolutions
from fallout.settings import RAW_DIR, ROOT, SETTINGS, load_anchor
from ingest.repo_seeds import REPOS_DIR

EVAL = ROOT / "eval"
ORACLE = EVAL / "oracle" / "oracle.mjs"
TREES = EVAL / "oracle" / "trees"
LABELS = EVAL / "oracle" / "labels"
UNITS_PATH = EVAL / "advisories.json"
OUT = EVAL / "dataset.json"
SEED = 42


def incident_id(unit: str) -> str:
    return f"eval-{unit}"


def slug(target: str) -> str:
    return target.replace("repo:", "repo__").replace("npm:", "").replace("/", "__").replace("@", "_at_")


def load_units() -> list[dict[str, Any]]:
    return json.loads(UNITS_PATH.read_text())["units"]


def affected_sets(units: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Returns unit -> {mode, affected: {pkg: [versions]}}, from OSV and the registry only."""
    out = {}
    for u in units:
        _, affected = asyncio.run(fetch(u["advisories"], u["kind"]))
        by_pkg: dict[str, list[str]] = {}
        for a in affected:
            by_pkg.setdefault(a["name"], []).append(a["version"])
        out[u["unit"]] = {
            "mode": "admits" if u["kind"] == "MALICIOUS" else "installed",
            "affected": {k: sorted(set(v)) for k, v in sorted(by_pkg.items())},
        }
    return out


def sample_packages(n: int, n_big: int = 0, top: int = 3000) -> dict[str, str]:
    """Returns {target: stratum}. `random`: n seeds, sampled uniformly (seed 42). `top-downloads`:
    n_big more, sampled from the `top` seeds by weekly downloads (seed 43). Uniform samples are
    mostly leaf packages with small trees, so they are almost never exposed. The download rank
    does not depend on any exposure label, so the second stratum adds positive cases without
    a bias toward the graph."""
    seeds_doc = json.loads((RAW_DIR / "seeds.json").read_text())
    forced = set(seeds_doc.get("forced", []))
    at_s = crawl_resolutions()
    g = graph()
    pool = []
    for name in sorted(set(seeds_doc["seeds"]) - forced):
        v = at_s.get((name, "*"))
        if v:
            pool.append(f"npm:{name}@{v}")
    present = set()
    for i in range(0, len(pool), 5000):
        chunk = pool[i : i + 5000]
        res = g.query("UNWIND $k AS k MATCH (v:Version {key: k}) RETURN v.key", {"k": chunk})
        present |= {r[0] for r in res.result_set}
    pool = [p for p in pool if p in present]
    chosen = {t: "random" for t in random.Random(SEED).sample(pool, n)}
    if n_big:
        with (RAW_DIR / "npm" / "downloads.jsonl").open() as f:
            dl = {r["name"]: r["weekly_downloads"] or 0 for r in map(json.loads, f)}
        ranked = sorted(pool, key=lambda t: (-dl.get(t.removeprefix("npm:").rsplit("@", 1)[0], 0), t))[:top]
        rest = [t for t in ranked if t not in chosen]
        chosen |= {t: "top-downloads" for t in random.Random(SEED + 1).sample(rest, min(n_big, len(rest)))}
    return dict(sorted(chosen.items()))


def run_oracle(target: str, units_file: Path, before: str, units_hash: str) -> dict[str, Any]:
    s = slug(target)
    label_path = LABELS / f"{s}.json"
    if label_path.exists():
        cached = json.loads(label_path.read_text())
        if cached.get("units_hash") == units_hash:
            return cached
    tree_out, lock_out = TREES / f"{s}.json", TREES / f"{s}.lock.json"
    with tempfile.TemporaryDirectory(prefix="fallout-oracle-") as tmp:
        cmd = ["node", str(ORACLE), "--before", before, "--units", str(units_file)]
        if target.startswith("repo:"):
            proj = Path(tmp) / "repo"
            shutil.copytree(
                REPOS_DIR / target.removeprefix("repo:"),
                proj,
                ignore=shutil.ignore_patterns(".git", "package-lock.json", "node_modules"),
            )
            cmd += ["--project", str(proj)]
        else:
            cmd += ["--package", target.removeprefix("npm:")]
        t0 = time.monotonic()
        proc = subprocess.run(
            [*cmd, "--tree-out", str(tree_out), "--lock-out", str(lock_out)],
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
    out: dict[str, Any]
    if proc.returncode != 0:
        out = {"target": target, "error": proc.stderr[-1500:], "units_hash": units_hash}
    else:
        out = {
            **json.loads(proc.stdout),
            "units_hash": units_hash,
            "took_ms": round((time.monotonic() - t0) * 1000),
        }
    label_path.write_text(json.dumps(out))
    return out


def graph_labels(targets: list[str], units: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    g = graph()
    out = {}
    for u in units:
        inc = incident_id(u["unit"])
        keys = {r["key"] for r in rows(g, "affected_keys", {"incident": inc})}
        for t in targets:
            if t.startswith("repo:"):
                hit = rows(g, "repo_exposed", {"repo": t, "incident": inc})
                hop = hit[0]["hop"] if hit else None
            else:
                hit = rows(g, "version_lookup", {"key": t, "incident": inc})
                hop = 0 if t in keys else (hit[0]["hop"] if hit else None)
            out[(u["unit"], t)] = {"exposed": hop is not None, "hop": hop}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--targets", type=int, default=200)
    ap.add_argument("--top-targets", type=int, default=300, help="targets from the top 3000 by downloads")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--skip-ingest", action="store_true")
    args = ap.parse_args()
    S = load_anchor()["S"]
    units = load_units()

    ingest_reports = {}
    if not args.skip_ingest:
        for u in units:
            inc = incident_id(u["unit"])
            rep = ingest_advisory(u["advisories"], inc, u["title"], u["kind"])
            res = blast_radius(inc)
            ingest_reports[u["unit"]] = {
                "affected_versions": rep.affected_versions,
                "edges": rep.edges,
                "exposed_versions": res.exposed_versions,
                "hops": len(res.hops),
            }
            print(f"{inc}: {ingest_reports[u['unit']]}", flush=True)

    strata = {f"repo:{r}": "demo-repo" for r in SETTINGS["allowed_repos"]} | sample_packages(
        args.targets, args.top_targets
    )
    targets = list(strata)
    aff = affected_sets(units)
    TREES.mkdir(parents=True, exist_ok=True)
    LABELS.mkdir(parents=True, exist_ok=True)
    units_file = EVAL / "oracle" / "units.json"
    units_file.write_text(json.dumps(aff, indent=1))
    units_hash = hashlib.sha1(units_file.read_bytes()).hexdigest()[:12]

    t0 = time.monotonic()
    with ThreadPoolExecutor(args.jobs) as pool:
        oracle = dict(
            zip(targets, pool.map(lambda t: run_oracle(t, units_file, S, units_hash), targets), strict=True)
        )
    failed = [t for t, o in oracle.items() if "error" in o]
    print(f"oracle: {len(targets)} targets, {len(failed)} failed, {time.monotonic() - t0:.0f}s", flush=True)

    glabels = graph_labels(targets, units)
    pairs = []
    for u in units:
        for t in targets:
            o = oracle[t]
            if "error" in o:
                continue
            ou = o["units"][u["unit"]]
            pairs.append(
                {
                    "unit": u["unit"],
                    "incident": incident_id(u["unit"]),
                    "target": t,
                    "target_kind": "repo" if t.startswith("repo:") else "package",
                    "stratum": strata[t],
                    "oracle_exposed": ou["exposed"],
                    "oracle_paths": ou["paths"],
                    "graph_exposed": glabels[(u["unit"], t)]["exposed"],
                    "graph_hop": glabels[(u["unit"], t)]["hop"],
                }
            )
    doc = {
        "S": S,
        "seed": SEED,
        "units": [{**u, "incident": incident_id(u["unit"]), **aff[u["unit"]]} for u in units],
        "ingest": ingest_reports,
        "targets": strata,
        "oracle_failed": {t: oracle[t]["error"][-300:] for t in failed},
        "pairs": pairs,
    }
    OUT.write_text(json.dumps(doc, indent=1))
    pos = sum(p["oracle_exposed"] for p in pairs)
    agree = sum(p["oracle_exposed"] == p["graph_exposed"] for p in pairs)
    print(f"pairs={len(pairs)} oracle_positive={pos} graph_agrees={agree}/{len(pairs)}")


if __name__ == "__main__":
    main()
