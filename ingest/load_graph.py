"""Load the crawl into FalkorDB (BUILD.md §5.5 step 5): indexes, Package/Version/HAS_VERSION,
then DEPENDS_ON, in UNWIND batches of 1,000. Maintainers and downloads are layered on by
crawl_npm.py's loader once that stage exists.

    uv run python -m ingest.load_graph [--reset]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import time
from pathlib import Path
from typing import Any

from fallout.db import batches, graph, query, statements
from ingest.crawl import OUT_DIR


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        return [json.loads(line) for line in f]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="delete the graph first")
    args = ap.parse_args()

    g = graph()
    if args.reset:
        with contextlib.suppress(Exception):  # graph did not exist yet
            g.delete()
        g = graph()
    for stmt in statements("schema_indexes"):
        try:
            g.query(stmt)
        except Exception as e:  # index already exists on re-runs
            if "already indexed" not in str(e):
                raise

    t0 = time.monotonic()
    for name, file in (("load_versions", "versions.jsonl"), ("load_depends_on", "edges.jsonl")):
        rows = read_jsonl(OUT_DIR / file)
        for chunk in batches(rows):
            g.query(query(name), {"rows": list(chunk)})
        print(f"{name}: {len(rows)} rows  {time.monotonic() - t0:.0f}s", flush=True)

    counts = g.query(
        "MATCH (p:Package) WITH count(p) AS packages "
        "MATCH (v:Version) WITH packages, count(v) AS versions "
        "MATCH ()-[e:DEPENDS_ON]->() RETURN packages, versions, count(e)"
    ).result_set[0]
    print(f"graph: packages={counts[0]} versions={counts[1]} depends_on={counts[2]}")


if __name__ == "__main__":
    main()
