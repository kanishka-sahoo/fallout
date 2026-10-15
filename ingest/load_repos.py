"""Load the demo repos into FalkorDB (BUILD.md §5.5 step 6): Repo, DIRECT_DEP (resolved at S),
LOCKS and OVERRIDES. Reads the checkouts that repo_seeds.py cloned.

Fails loudly when a direct dependency resolves to a version the crawl never expanded: an
uncrawled target has no outgoing DEPENDS_ON edges and would silently truncate every path.

    uv run python -m ingest.load_repos [--repo fallout-demo/billing-api]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

from falkordb import Graph

from fallout.db import batches, graph, query
from fallout.repo import RepoSnapshot, read_repo
from fallout.resolve import resolve_at_s
from fallout.settings import SETTINGS
from ingest.crawl import OUT_DIR as CRAWL_DIR
from ingest.crawl import vkey
from ingest.repo_seeds import REPOS_DIR


class UncrawledDependency(RuntimeError):
    pass


@cache
def crawled_keys() -> frozenset[str]:
    with (CRAWL_DIR / "versions.jsonl").open() as f:
        return frozenset(json.loads(line)["key"] for line in f)


def git(repo_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def repo_key(full_name: str) -> str:
    return f"repo:{full_name}"


def write_repo(g: Graph, snap: RepoSnapshot, head_sha: str | None, default_branch: str | None) -> None:
    pairs = {(d.name, d.range) for d in snap.deps} | {(o.name, o.spec) for o in snap.overrides}
    resolved = resolve_at_s(pairs)

    direct, bad = [], []
    for d in snap.deps:
        version = resolved.get((d.name, d.range))
        key = vkey(d.name, version) if version else None
        if key is None or key not in crawled_keys():
            bad.append(f"{d.name}@{d.range} -> {key or 'ETARGET'}")
            continue
        direct.append({"to": key, "requirement": d.range, "scope": d.scope})
    if bad:
        raise UncrawledDependency(
            f"{snap.full_name}: direct deps with no crawl record (rerun repo_seeds + crawl): {bad}"
        )

    key = repo_key(snap.full_name)
    g.query(
        query("repo_upsert"),
        {
            "key": key,
            "full_name": snap.full_name,
            "default_branch": default_branch,
            "head_sha": head_sha,
            "has_lockfile": snap.has_lockfile,
            "lockfile_version": snap.lockfile_version,
        },
    )
    g.query(query("repo_clear"), {"key": key})
    g.query(query("repo_direct_deps"), {"key": key, "rows": direct})
    locks: list[dict[str, Any]] = [
        {"name": lk.name, "version": lk.version, "key": vkey(lk.name, lk.version), "path": lk.path}
        for lk in snap.locked
    ]
    for chunk in batches(locks):
        g.query(query("repo_locks"), {"key": key, "rows": list(chunk)})
    overrides = [
        {
            "name": o.name,
            "spec": o.spec,
            "parent": o.parent,
            "resolved_version": resolved.get((o.name, o.spec)),
        }
        for o in snap.overrides
    ]
    g.query(query("repo_overrides"), {"key": key, "rows": overrides})
    print(
        f"{snap.full_name}: direct={len(direct)} locks={len(locks)} overrides={len(overrides)} "
        f"lockfile={snap.lockfile_version}"
    )


def load_repo(g: Graph, full_name: str, repo_dir: Path | None = None) -> RepoSnapshot:
    repo_dir = repo_dir or REPOS_DIR / full_name
    snap = read_repo(full_name, repo_dir)
    is_git = (repo_dir / ".git").exists()
    write_repo(
        g,
        snap,
        head_sha=git(repo_dir, "rev-parse", "HEAD") if is_git else None,
        default_branch=git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD") if is_git else None,
    )
    return snap


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", action="append", help="full name; default: every allowed repo")
    args = ap.parse_args()
    g = graph()
    for full_name in args.repo or SETTINGS["allowed_repos"]:
        load_repo(g, full_name)


if __name__ == "__main__":
    main()
