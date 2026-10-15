"""Time-anchored dependency closure (BUILD.md §5.2).

Breadth-first from the seeds and repo direct deps. Each level:
  1. fetch the version list of every package in the frontier (deps.dev, once per package),
  2. synthesize a packument limited to versions published at or before S,
  3. resolve every new (name, range) pair in one resolver.mjs batch (npm-pick-manifest, before=S),
  4. fetch `:requirements` for each newly discovered version and enqueue its dependencies.

Every HTTP response is cached on disk, so re-running after a crash, or with a larger
--limit, only pays for what is new. Outputs go to data/raw/crawl/*.jsonl.

    uv run python -m ingest.crawl [--limit N] [--concurrency 32]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fallout import node
from fallout.settings import RAW_DIR, load_anchor
from ingest.http import CachedClient, encode_pkg
from ingest.repo_seeds import REPO_SEEDS_PATH
from ingest.seed import SEEDS_PATH

DEPS_PKG = "https://api.deps.dev/v3/systems/npm/packages/{name}"
DEPS_REQS = "https://api.deps.dev/v3/systems/npm/packages/{name}/versions/{version}:requirements"
OUT_DIR = RAW_DIR / "crawl"

NPM_ALIAS = re.compile(r"^npm:((?:@[^/@]+/)?[^@]+)(?:@(.*))?$")
NON_REGISTRY = re.compile(
    r"^(npm:|git\+|git:|github:|gitlab:|bitbucket:|https?:|file:|link:|workspace:)|^[^@\s]+/[^@\s]+$"
)


def vkey(name: str, version: str) -> str:
    return f"npm:{name}@{version}"


def epoch_ms(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


@dataclass(frozen=True)
class Want:
    """A dependency to resolve: `parent` (a Version key, or None for a seed) needs `name@range`."""

    parent: str | None
    name: str
    range: str
    kind: str


@dataclass
class Crawl:
    client: CachedClient
    before: str
    before_ms: int
    packuments: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    resolutions: dict[tuple[str, str], str | None] = field(default_factory=dict)
    versions: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    roots: set[str] = field(default_factory=set)
    pruned: dict[str, int] = field(default_factory=dict)
    spam: set[str] = field(default_factory=set)

    # -- step 1-2: version lists -> packuments at S --------------------------------------------
    async def load_packument(self, name: str) -> None:
        doc = await self.client.get_json(DEPS_PKG.format(name=encode_pkg(name)))
        if doc is None:
            self.packuments[name] = None
            return
        versions: dict[str, Any] = {}
        times: dict[str, str] = {}
        for v in doc.get("versions", []):
            ver = v["versionKey"]["version"]
            published = v.get("publishedAt")
            if published and epoch_ms(published) > self.before_ms:
                continue
            versions[ver] = {"name": name, "version": ver}
            if v.get("isDeprecated"):
                versions[ver]["deprecated"] = v.get("deprecatedReason") or True
            if published:
                times[ver] = published
        self.packuments[name] = {"name": name, "versions": versions, "time": times}

    # -- step 4: requirements of a resolved version ---------------------------------------------
    async def children(self, key: str) -> list[Want]:
        rec = self.versions[key]
        doc = await self.client.get_json(
            DEPS_REQS.format(name=encode_pkg(rec["name"]), version=encode_pkg(rec["version"]))
        )
        if doc is None:
            self.unresolved.append({"parent": key, "reason": "requirements_not_found"})
            return []
        deps = doc.get("npm", {}).get("dependencies", {})
        bundled = set(deps.get("bundleDependencies") or [])
        optional_peers = {m["name"] for m in deps.get("peerDependencyMetadata", []) if m.get("optional")}
        out: dict[str, Want] = {}
        for kind, entries in (
            ("peer", deps.get("peerDependencies", [])),
            ("prod", deps.get("dependencies", [])),
            ("optional", deps.get("optionalDependencies", [])),
        ):
            for d in entries:
                if kind == "peer" and d["name"] in optional_peers:
                    continue
                out[d["name"]] = Want(key, d["name"], d.get("requirement", ""), kind)
        wants = []
        for w in out.values():
            if w.name in bundled:
                self.unresolved.append({**w.__dict__, "reason": "bundled"})
            else:
                wants.append(w)
        return wants

    # -- one BFS level ---------------------------------------------------------------------------
    async def step(self, frontier: list[Want]) -> list[Want]:
        registry = []
        for w in frontier:
            alias = NPM_ALIAS.match(w.range.strip())
            if alias:  # `"wrap-ansi-cjs": "npm:wrap-ansi@^7"` installs the real wrap-ansi
                w = Want(w.parent, alias[1], alias[2] or "*", w.kind)
            if NON_REGISTRY.match(w.range.strip()):
                self.unresolved.append({**w.__dict__, "reason": "non_registry_spec"})
            else:
                registry.append(w)

        missing = {w.name for w in registry} - self.packuments.keys()
        await asyncio.gather(*(self.load_packument(n) for n in missing))

        pending = {(w.name, w.range) for w in registry} - self.resolutions.keys()
        groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        ids: dict[str, tuple[str, str]] = {}
        for i, (name, rng) in enumerate(sorted(pending)):
            if self.packuments.get(name) is None:
                self.resolutions[(name, rng)] = None
                continue
            ids[str(i)] = (name, rng)
            groups[name].append({"id": str(i), "range": rng})
        if groups:
            results = node.resolve(
                ({"packument": self.packuments[n], "requests": reqs} for n, reqs in groups.items()),
                self.before,
            )
            for rid, (name, rng) in ids.items():
                self.resolutions[(name, rng)] = results[rid].get("version")

        new_keys = []
        for w in registry:
            version = self.resolutions[(w.name, w.range)]
            if version is None:
                reason = "package_not_found" if self.packuments.get(w.name) is None else "ETARGET"
                self.unresolved.append({**w.__dict__, "reason": reason})
                continue
            key = vkey(w.name, version)
            if key not in self.versions:
                pk = self.packuments[w.name] or {}
                published = pk.get("time", {}).get(version)
                self.versions[key] = {
                    "key": key,
                    "name": w.name,
                    "version": version,
                    "published_at": epoch_ms(published) if published else None,
                    "deprecated": "deprecated" in pk.get("versions", {}).get(version, {}),
                }
                new_keys.append(key)
            if w.parent is None:
                self.roots.add(key)
            else:
                self.edges.append({"from": w.parent, "to": key, "requirement": w.range, "kind": w.kind})

        nested = await asyncio.gather(*(self.children(k) for k in new_keys))
        return [w for ws in nested for w in ws]

    async def run(self, seeds: list[Want]) -> None:
        frontier, level, t0 = seeds, 0, time.monotonic()
        while frontier:
            frontier = await self.step(frontier)
            level += 1
            print(
                f"level {level:2d}  versions={len(self.versions):7d}  packages={len(self.packuments):6d}  "
                f"edges={len(self.edges):8d}  next={len(frontier):7d}  "
                f"http hit/miss={self.client.hits}/{self.client.misses}  {time.monotonic() - t0:6.0f}s",
                flush=True,
            )

    def prune_spam(self, min_missing: int = 10, min_ratio: float = 0.2) -> None:
        """Drop registry-spam clusters (e.g. tea.xyz token farming) that npm removed after S.

        A version is spam when at least `min_missing` of its dependencies, and at least
        `min_ratio` of them, name packages that no longer exist or are themselves spam. Spam
        versions are removed, then only what is still reachable from the seed and repo roots
        is kept. Real packages
        do not depend on these clusters, but left in they would distort PageRank.
        """
        missing: Counter[str] = Counter()
        for u in self.unresolved:
            if u["reason"] == "package_not_found" and u.get("parent"):
                missing[u["parent"]] += 1
        out_edges: dict[str, list[str]] = defaultdict(list)
        for e in self.edges:
            out_edges[e["from"]].append(e["to"])

        # Spam depends on spam: iterate until no new version qualifies.
        spam: set[str] = set()
        while True:
            found = set()
            for k in self.versions.keys() - spam:
                bad = missing[k] + sum(1 for t in out_edges[k] if t in spam)
                total = missing[k] + len(out_edges[k])
                if bad >= min_missing and bad / total >= min_ratio:
                    found.add(k)
            if not found:
                break
            spam |= found
        keep = set()
        stack = [k for k in self.roots if k not in spam]
        while stack:
            k = stack.pop()
            if k in keep:
                continue
            keep.add(k)
            stack.extend(t for t in out_edges[k] if t not in spam and t not in keep)

        before = len(self.versions)
        self.versions = {k: v for k, v in self.versions.items() if k in keep}
        self.edges = [e for e in self.edges if e["from"] in keep and e["to"] in keep]
        self.unresolved = [u for u in self.unresolved if u.get("parent") is None or u["parent"] in keep]
        self.pruned = {"spam_versions": len(spam), "versions_removed": before - len(self.versions)}
        self.spam = spam

    def write(self) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        def dump(name: str, rows: Any) -> None:
            with (OUT_DIR / name).open("w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")

        dump("versions.jsonl", self.versions.values())
        dump("edges.jsonl", self.edges)
        dump("unresolved.jsonl", self.unresolved)
        (OUT_DIR / "spam.txt").write_text("".join(f"{k}\n" for k in sorted(self.spam)))
        dump(
            "resolutions.jsonl",
            ({"name": n, "range": r, "version": v} for (n, r), v in self.resolutions.items()),
        )
        reasons = Counter(u["reason"] for u in self.unresolved)
        summary = {
            "S": self.before,
            "versions": len(self.versions),
            "packages": sum(1 for p in self.packuments.values() if p is not None),
            "edges": len(self.edges),
            "unresolved": dict(reasons),
            "pruned": self.pruned,
            "http_requests": self.client.misses + self.client.hits,
        }
        (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))


def load_seeds(limit: int | None) -> list[Want]:
    seed_doc = json.loads(SEEDS_PATH.read_text())
    names = seed_doc["seeds"]
    if limit is not None:
        forced = set(seed_doc["forced"])
        names = [n for i, n in enumerate(names) if n in forced or i < limit + len(forced)]
    wants = [Want(None, n, "*", "seed") for n in names]
    for pairs in json.loads(REPO_SEEDS_PATH.read_text()).values():
        wants += [Want(None, p["name"], p["range"], "repo") for p in pairs]
    return wants


async def amain(limit: int | None, concurrency: int) -> None:
    anchor = load_anchor()
    async with CachedClient(concurrency=concurrency) as client:
        crawl = Crawl(client, anchor["S"], anchor["S_epoch_ms"])
        await crawl.run(load_seeds(limit))
        crawl.prune_spam()
        crawl.write()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="use only the first N seeds")
    ap.add_argument("--concurrency", type=int, default=32)
    args = ap.parse_args()
    asyncio.run(amain(args.limit, args.concurrency))


if __name__ == "__main__":
    main()
