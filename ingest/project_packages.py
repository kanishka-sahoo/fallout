"""Package-level projection for the ecosystem algorithms (BUILD.md §5.5 step 7, §7.6):
(Package)-[:PKG_DEPENDS_ON]->(Package) wherever any version of one depends on any version of
the other. Batched by chunks of package names; MERGE keeps re-runs idempotent.

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
