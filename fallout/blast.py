"""Blast radius, exposure paths and repo status.

uv run python -m fallout.blast [--incident npm-2025-09-08-chalk-debug]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from falkordb import Graph

from fallout.db import batches, graph, query, rows
from fallout.settings import SETTINGS

LOCKED_MALICIOUS = "LOCKED_MALICIOUS"
NOT_AFFECTED = "NOT_AFFECTED"
MITIGATED_BY_OVERRIDE = "MITIGATED_BY_OVERRIDE"
EXPOSED_NO_LOCKFILE = "EXPOSED_NO_LOCKFILE"
RANGE_ADMITS_LOCK_SAFE = "RANGE_ADMITS_LOCK_SAFE"


@dataclass(frozen=True)
class Exposed:
    hop: int
    via: str
    kind: str  # Version | Repo


@dataclass(frozen=True)
class Affected:
    keys: frozenset[str]
    packages: frozenset[str]

    @classmethod
    def load(cls, g: Graph, incident: str) -> Affected:
        rs = rows(g, "affected_keys", {"incident": incident})
        if not rs:
            raise LookupError(f"incident {incident} has no affected versions: run ingest_advisory first")
        return cls(frozenset(r["key"] for r in rs), frozenset(r["name"] for r in rs))


# -- BFS -------------------------------------------------------------------------------------------


def bfs(
    g: Graph,
    incident: str,
    affected: Affected,
    max_hops: int,
    on_hop: Callable[[int, list[tuple[str, Exposed]]], None] | None = None,
) -> tuple[dict[str, Exposed], bool]:
    """Runs a reverse BFS from the affected versions. Returns the first (hop, via) of every
    exposed node, and True if the traversal stopped at `max_hops`."""
    visited: dict[str, Exposed] = {}
    frontier = sorted(affected.keys)
    for hop in range(1, max_hops + 1):
        name = "bfs_hop1" if hop == 1 else "bfs_hopn"
        new: list[tuple[str, Exposed]] = []
        for chunk in batches(frontier, 5000):
            for r in rows(g, name, {"frontier": list(chunk), "incident": incident}):
                if r["node"] in visited or r["node"] in affected.keys:
                    continue
                e = Exposed(hop, r["via"], r["kind"])
                visited[r["node"]] = e
                new.append((r["node"], e))
        if on_hop and new:
            on_hop(hop, new)
        frontier = sorted(k for k, e in new if e.kind == "Version")  # repos are leaf nodes
        if not frontier:
            return visited, False
    return visited, True


def persist(g: Graph, incident: str, visited: dict[str, Exposed]) -> None:
    g.query(query("exposes_clear"), {"incident": incident})
    for kind, q in (("Version", "exposes_version"), ("Repo", "exposes_repo")):
        rs = [{"node": k, "hop": e.hop, "via": e.via} for k, e in visited.items() if e.kind == kind]
        for chunk in batches(rs):
            g.query(query(q), {"incident": incident, "rows": list(chunk)})


# -- paths ---------------------------------------------------------------------------------------


def path_id(nodes: Iterable[str]) -> str:
    return "p_" + hashlib.sha1("|".join(nodes).encode()).hexdigest()[:10]


def exposure_path(
    g: Graph, incident: str, repo: str, affected: Affected, kind: str = "repo"
) -> dict[str, Any] | None:
    """Follows the EXPOSES.via parent pointers from `repo` back to an affected version.
    With kind="version", `repo` is a Version key."""
    nodes, edges = [repo], []
    cur = repo
    while cur not in affected.keys:
        hit = rows(g, f"exposes_lookup_{kind}", {"key": cur, "incident": incident})
        if not hit or hit[0]["via"] is None:
            return None
        nxt = hit[0]["via"]
        e = rows(g, f"path_edge_{kind}", {"from": cur, "to": nxt, "incident": incident})
        edges.append({"type": e[0]["type"], "requirement": e[0]["requirement"]} if e else {"type": None})
        nodes.append(nxt)
        cur, kind = nxt, "version"
    return {"id": path_id(nodes), "nodes": nodes, "edges": edges}


def cross_check_path(g: Graph, incident: str, repo: str, malicious: str) -> dict[str, Any] | None:
    rs = rows(g, "path_cross_check", {"repo": repo, "malicious": malicious})
    if not rs:
        return None
    r = rs[0]
    # shortestPath cannot filter on a property, so reject a path that uses another incident's edges (D3).
    if any(i is not None and i != incident for i in r["incidents"]):
        return None
    return {"id": path_id(r["chain"]), "nodes": r["chain"], "edges": r["requirements"]}


# -- status -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OverrideEntry:
    pkg: str
    parent: str | None
    resolved_version: str | None


def closure_path(
    root: str, adj: dict[str, list[str]], names: dict[str, str], targets: set[str], blocked: set[str | None]
) -> list[str] | None:
    """Returns the shortest path from root to a target through the resolved tree, or None.
    The path does not go through a version of a `blocked` package."""
    prev: dict[str, str | None] = {root: None}
    queue = deque([root])
    while queue:
        n = queue.popleft()
        if n in targets:
            path = [n]
            while (p := prev[path[-1]]) is not None:
                path.append(p)
            return path[::-1]
        for c in adj.get(n, ()):
            if c not in prev and names.get(c) not in blocked:
                prev[c] = n
                queue.append(c)
    return None


def override_covers(
    root: str,
    adj: dict[str, list[str]],
    names: dict[str, str],
    dependents: set[str],
    overrides: list[OverrideEntry],
    bad_versions: set[str],
) -> bool:
    """Returns True if the overrides for one affected package apply on every path to it.

    `dependents` are the nodes whose requirement on the package would pick an affected
    version. A global override to a safe version covers all paths. A nested override covers a
    path only if the path goes through a version of its `parent`, because npm applies a nested
    override anywhere below the parent. The function checks whether the root can still reach a
    dependent without going through a parent that has a safe override.
    """
    safe = [o for o in overrides if o.resolved_version and o.resolved_version not in bad_versions]
    if any(o.parent is None for o in safe):
        return True
    return closure_path(root, adj, names, dependents, {o.parent for o in safe}) is None


def decide_status(
    *, exposed: bool, has_lockfile: bool, locked_affected: list[str], reachable: set[str], covered: set[str]
) -> str:
    """Returns the repo status. The checks run in priority order, and the first match wins."""
    if locked_affected:
        return LOCKED_MALICIOUS
    if not exposed:
        return NOT_AFFECTED
    if reachable and reachable <= covered:
        return MITIGATED_BY_OVERRIDE
    if not has_lockfile:
        return EXPOSED_NO_LOCKFILE
    return RANGE_ADMITS_LOCK_SAFE


@dataclass
class Closure:
    """A repo's transitive dependency tree at S: DIRECT_DEP edges from the repo, then DEPENDS_ON edges."""

    root: str
    adj: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    names: dict[str, str] = field(default_factory=dict)
    requirement: dict[tuple[str, str], str] = field(default_factory=dict)

    @classmethod
    def load(cls, g: Graph, repo: str) -> Closure:
        c = cls(repo)
        frontier = []
        for r in rows(g, "repo_closure_root", {"repo": repo}):
            c.add(repo, r)
            frontier.append(r["node"])
        seen = set(frontier)
        while frontier:
            nxt = []
            for chunk in batches(frontier, 5000):
                for r in rows(g, "repo_closure_step", {"frontier": list(chunk)}):
                    c.add(r["parent"], r)
                    if r["node"] not in seen:
                        seen.add(r["node"])
                        nxt.append(r["node"])
            frontier = nxt
        return c

    def add(self, parent: str, r: dict[str, Any]) -> None:
        self.adj[parent].append(r["node"])
        self.names[r["node"]] = r["name"]
        self.requirement[(parent, r["node"])] = r["requirement"]

    def path(self, nodes: list[str], last: dict[str, Any]) -> dict[str, Any]:
        """Returns a path in the tool format: the dependency tree hops, then the CAN_RESOLVE_TO hop `last`."""
        edges = [
            {
                "type": "DIRECT_DEP" if a == self.root else "DEPENDS_ON",
                "requirement": self.requirement[(a, b)],
            }
            for a, b in zip(nodes, nodes[1:], strict=False)
        ]
        edges.append({"type": "CAN_RESOLVE_TO", "requirement": last["requirement"]})
        full = [*nodes, last["target"]]
        return {"id": path_id(full), "nodes": full, "edges": edges}


def repo_status(g: Graph, incident: str, repo: str, affected: Affected, exposed: bool) -> dict[str, Any]:
    cl = Closure.load(g, repo)
    crt = rows(g, "repo_can_resolve", {"repo": repo, "keys": sorted(cl.names), "incident": incident})
    dependents: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in crt:
        dependents[r["pkg"]][r["dependent"]] = r
    reachable = set(dependents)

    pkgs = sorted(affected.packages)
    lk = rows(g, "repo_locks_for", {"repo": repo, "affected_packages": pkgs})[0]
    locked = [x for x in lk["locked"] if x["key"] is not None]
    locked_affected = sorted({x["key"] for x in locked if x["key"] in affected.keys})

    ovs: dict[str, list[OverrideEntry]] = defaultdict(list)
    for o in rows(g, "repo_overrides_for", {"repo": repo, "affected_packages": pkgs}):
        ovs[o["pkg"]].append(OverrideEntry(o["pkg"], o["parent"], o["resolved_version"]))
    bad: dict[str, set[str]] = defaultdict(set)
    for k in affected.keys:
        name, version = k.removeprefix("npm:").rsplit("@", 1)
        bad[name].add(version)
    covered = {
        p
        for p in reachable
        if p in ovs and override_covers(repo, cl.adj, cl.names, set(dependents[p]), ovs[p], bad[p])
    }

    # Keep one path per affected package. Prefer a path that no override covers, because
    # that path explains why the package is still counted.
    by_package = []
    for p in sorted(reachable):
        blocked: set[str | None] = {o.parent for o in ovs.get(p, []) if o.parent}
        nodes = closure_path(repo, cl.adj, cl.names, set(dependents[p]), blocked)
        nodes = nodes or closure_path(repo, cl.adj, cl.names, set(dependents[p]), set())
        if nodes:
            by_package.append(
                {"package": p, "mitigated": p in covered, **cl.path(nodes, dependents[p][nodes[-1]])}
            )

    status = decide_status(
        exposed=exposed,
        has_lockfile=bool(lk["has_lockfile"]),
        locked_affected=locked_affected,
        reachable=reachable,
        covered=covered,
    )
    return {
        "repo": repo,
        "status": status,
        "affected_packages": sorted(reachable),
        "mitigated_packages": sorted(covered),
        "locked_affected": locked_affected,
        "has_lockfile": bool(lk["has_lockfile"]),
        "closure_size": len(cl.names),
        "paths_by_package": by_package,
    }


# -- full run ------------------------------------------------------------------------------------


@dataclass
class BlastResult:
    incident: str
    hops: list[dict[str, int]]
    exposed_versions: int
    exposed_packages: int
    repos: list[dict[str, Any]]
    top_packages: list[dict[str, Any]]
    truncated: bool
    took_ms: int
    paths: list[dict[str, Any]] = field(default_factory=list)


def blast_radius(
    incident: str,
    max_hops: int = 16,
    on_hop: Callable[[int, list[tuple[str, Exposed]]], None] | None = None,
    g: Graph | None = None,
) -> BlastResult:
    t0 = time.monotonic()
    g = g or graph()
    affected = Affected.load(g, incident)
    visited, truncated = bfs(g, incident, affected, max_hops, on_hop)
    persist(g, incident, visited)
    g.query(
        query("incident_blast_mark"),
        {"incident": incident, "now": int(time.time() * 1000), "exposed": len(visited)},
    )

    per_hop: dict[int, dict[str, int]] = defaultdict(lambda: {"versions": 0, "repos": 0})
    for e in visited.values():
        per_hop[e.hop]["versions" if e.kind == "Version" else "repos"] += 1

    now = int(time.time() * 1000)
    repos, paths = [], []
    for r in rows(g, "repo_keys", {}):
        key = r["key"]
        exposed = key in visited
        st = repo_status(g, incident, key, affected, exposed)
        if exposed or st["status"] != NOT_AFFECTED:
            g.query(
                query("repo_status_write"),
                {"incident": incident, "repo": key, "status": st["status"], "now": now},
            )
        st["hop"] = visited[key].hop if exposed else None
        if exposed:
            p = exposure_path(g, incident, key, affected)
            if p:
                st["path_id"] = p["id"]
                paths.append(p)
        repos.append(st)

    exposed_names = {k.rsplit("@", 1)[0] for k, e in visited.items() if e.kind == "Version"}
    return BlastResult(
        incident=incident,
        hops=[{"hop": h, **c} for h, c in sorted(per_hop.items())],
        exposed_versions=sum(1 for e in visited.values() if e.kind == "Version"),
        exposed_packages=len(exposed_names),
        repos=repos,
        top_packages=rows(g, "top_exposed_packages", {"incident": incident, "k": 10}),
        truncated=truncated,
        took_ms=round((time.monotonic() - t0) * 1000),
        paths=paths,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--incident", default=SETTINGS["replay_incident"])
    ap.add_argument("--max-hops", type=int, default=16)
    args = ap.parse_args()

    def on_hop(hop: int, new: list[tuple[str, Exposed]]) -> None:
        repos = [k for k, e in new if e.kind == "Repo"]
        print(
            f"hop {hop:2d}: +{len(new) - len(repos)} versions, +{len(repos)} repos {repos or ''}", flush=True
        )

    res = blast_radius(args.incident, args.max_hops, on_hop)
    print(json.dumps({k: v for k, v in res.__dict__.items() if k != "paths"}, indent=2))
    for p in res.paths:
        print(f"\n{p['id']}")
        for n, e in zip(p["nodes"], [*p["edges"], None], strict=True):
            print(f"  {n}" + (f"\n    --{e['type']} {e.get('requirement')}-->" if e else ""))


if __name__ == "__main__":
    main()
