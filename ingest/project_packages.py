"""Builds the package-level projection for the ecosystem algorithms. It creates
(Package)-[:PKG_DEPENDS_ON]->(Package) where any version of one package depends on any version
of the other. It runs in batches of package names. MERGE makes a second run idempotent.

    uv run python -m ingest.project_packages
"""

from __future__ import annotations

import time

from fallout.db import batches, graph, query


def main() -> None:
    g = graph()
    names = [row[0] for row in g.query("MATCH (p:Package) RETURN p.name ORDER BY p.name").result_set]
    t0 = time.monotonic()
    for chunk in batches(names, 500):
        g.query(query("project_packages"), {"names": list(chunk)})
    edges = g.query("MATCH ()-[e:PKG_DEPENDS_ON]->() RETURN count(e)").result_set[0][0]
    print(f"PKG_DEPENDS_ON: {edges} edges over {len(names)} packages  {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    main()
