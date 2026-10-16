"""Ecosystem algorithms (BUILD.md §5.5 step 8, §7.6, §7.7): PageRank and betweenness over the
PKG_DEPENDS_ON projection, then maintainer reach. All written back as node properties so the
MCP tools only read them.

Maintainer reach: take the top `--maintainers` accounts by summed PageRank over the packages
they maintain, and reverse-BFS PKG_DEPENDS_ON from all of them at once. `reach_packages` counts
every package the takeover reaches, the maintainer's own packages included; `reach_downloads`
sums their weekly downloads. The BFS runs in memory over the 80k-edge projection: one graph
read instead of 300 frontier walks.

    uv run python -m analysis.algorithms [--skip-reach] [--maintainers 300]
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict, deque
from collections.abc import Iterable

from falkordb import Graph

from fallout.db import batches, graph, query, rows


def reverse_reach(start: Iterable[str], dependents: dict[str, list[str]]) -> set[str]:
    """Every package that transitively depends on any of `start`, plus `start` itself."""
    seen = set(start)
    queue = deque(seen)
    while queue:
        for d in dependents.get(queue.popleft(), ()):
            if d not in seen:
                seen.add(d)
                queue.append(d)
    return seen


def run_centrality(g: Graph) -> dict[str, float]:
    took = {}
    for name in ("algo_pagerank", "algo_betweenness"):
        t0 = time.monotonic()
        g.query(query(name))
        took[name] = round(time.monotonic() - t0, 2)
    return took


def maintainer_reach(g: Graph, k: int) -> list[dict[str, object]]:
    dependents: dict[str, list[str]] = defaultdict(list)
    for r in rows(g, "pkg_edges"):
        dependents[r["dependency"]].append(r["dependent"])
    downloads = {r["name"]: r["downloads"] for r in rows(g, "package_downloads")}

    out = []
    for c in rows(g, "maintainer_candidates", {"k": k}):
        reached = reverse_reach(c["packages"], dependents)
        out.append(
            {
                "maintainer": c["maintainer"],
                "pagerank": c["pr"],
                "reach_packages": len(reached),
                "reach_downloads": sum(downloads.get(p, 0) for p in reached),
            }
        )
    for chunk in batches(out):
        g.query(query("maintainer_reach_write"), {"rows": list(chunk)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maintainers", type=int, default=300)
    ap.add_argument("--skip-reach", action="store_true")
    args = ap.parse_args()
    g = graph()
    print("centrality:", run_centrality(g))
    for order in ("pagerank", "betweenness"):
        top = rows(g, "critical_packages", {"k": 5, "order": order})
        print(f"top by {order}:", [r["package"] for r in top])
    if args.skip_reach:
        return
    t0 = time.monotonic()
    reach = maintainer_reach(g, args.maintainers)
    top = sorted(reach, key=lambda r: -int(r["reach_packages"]))[:5]  # type: ignore[call-overload]
    print(f"maintainer reach: {len(reach)} accounts in {time.monotonic() - t0:.1f}s")
    print(json.dumps(top, indent=2))


if __name__ == "__main__":
    main()
