"""Loads the crawl into FalkorDB in UNWIND batches of 1,000. The order is: indexes,
Package/Version/HAS_VERSION, DEPENDS_ON, then the npm metadata from crawl_npm.py (Maintainer,
MAINTAINS, PUBLISHED, and the downloads, maintainer count and provenance of each package).

A package's maintainers and provenance come from its newest version in the graph. That version
approximates the version that was `latest` at S. Every step uses MERGE, so it is safe to run again.

    uv run python -m ingest.load_graph [--reset] [--only-npm]
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
from ingest.crawl_npm import OUT_DIR as NPM_DIR


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        return [json.loads(line) for line in f]


def npm_rows() -> dict[str, list[dict[str, Any]]]:
    versions = {v["key"]: v for v in read_jsonl(OUT_DIR / "versions.jsonl")}
    metas = {m["key"]: m for m in read_jsonl(NPM_DIR / "version_meta.jsonl") if m["found"]}
    downloads = {d["name"]: d["weekly_downloads"] for d in read_jsonl(NPM_DIR / "downloads.jsonl")}

    newest: dict[str, dict[str, Any]] = {}
    for v in versions.values():
        cur = newest.get(v["name"])
        if cur is None or (v["published_at"] or 0) > (cur["published_at"] or 0):
            newest[v["name"]] = v

    packages, maintains = [], []
    for name, v in newest.items():
        meta = metas.get(v["key"], {})
        maintainers = meta.get("maintainers", [])
        packages.append(
            {
                "name": name,
                "weekly_downloads": downloads.get(name),
                "maintainer_count": len(maintainers),
                "has_provenance": bool(meta.get("has_provenance")),
            }
        )
        maintains += [{"maintainer": m, "package": name} for m in maintainers]
    published = [{"maintainer": m["publisher"], "key": k} for k, m in metas.items() if m.get("publisher")]
    return {"load_package_props": packages, "load_maintains": maintains, "load_published": published}


def load(g: Any, name: str, rows: list[dict[str, Any]], t0: float) -> None:
    for chunk in batches(rows):
        g.query(query(name), {"rows": list(chunk)})
    print(f"{name}: {len(rows)} rows  {time.monotonic() - t0:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="delete the graph first")
    ap.add_argument("--only-npm", action="store_true", help="skip versions and edges; load npm metadata")
    args = ap.parse_args()

    g = graph()
    if args.reset:
        with contextlib.suppress(Exception):  # the graph does not exist yet
            g.delete()
        g = graph()
    for stmt in statements("schema_indexes"):
        try:
            g.query(stmt)
        except Exception as e:  # the index exists from an earlier run
            if "already indexed" not in str(e):
                raise

    t0 = time.monotonic()
    if not args.only_npm:
        for name, file in (("load_versions", "versions.jsonl"), ("load_depends_on", "edges.jsonl")):
            load(g, name, read_jsonl(OUT_DIR / file), t0)
    for name, rows in npm_rows().items():
        load(g, name, rows, t0)
    g.query(query("maintainer_package_count"))

    counts = g.query(
        "MATCH (p:Package) WITH count(p) AS packages "
        "MATCH (v:Version) WITH packages, count(v) AS versions "
        "MATCH ()-[e:DEPENDS_ON]->() WITH packages, versions, count(e) AS edges "
        "MATCH (m:Maintainer) RETURN packages, versions, edges, count(m)"
    ).result_set[0]
    print(f"graph: packages={counts[0]} versions={counts[1]} depends_on={counts[2]} maintainers={counts[3]}")


if __name__ == "__main__":
    main()
