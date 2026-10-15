"""Resolve `(name, range)` at S outside the crawl (BUILD.md §5.2).

The crawl already resolved every repo direct dependency and override spec, so those come from
data/raw/crawl/resolutions.jsonl. Anything new (e.g. a fix plan's override) goes through the
same packument synthesis and resolver.mjs, with HTTP served from the crawl's cache.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from functools import cache
from typing import Any

from fallout import node
from fallout.settings import RAW_DIR, load_anchor

RESOLUTIONS = RAW_DIR / "crawl" / "resolutions.jsonl"


@cache
def crawl_resolutions() -> dict[tuple[str, str], str | None]:
    if not RESOLUTIONS.exists():
        return {}
    with RESOLUTIONS.open() as f:
        return {(r["name"], r["range"]): r["version"] for r in map(json.loads, f)}


async def packuments(names: set[str], before: str | None = None) -> dict[str, dict[str, Any] | None]:
    """Packuments as they stood at `before` (default S), built exactly as the crawl builds them."""
    from ingest.crawl import Crawl, epoch_ms  # ingest depends on fallout, not the reverse
    from ingest.http import CachedClient

    before = before or load_anchor()["S"]
    async with CachedClient() as client:
        crawl = Crawl(client, before, epoch_ms(before))
        await asyncio.gather(*(crawl.load_packument(n) for n in names))
    return crawl.packuments


def resolve_at_s(pairs: set[tuple[str, str]]) -> dict[tuple[str, str], str | None]:
    """{(name, range): version at S, or None on ETARGET / unknown package}."""
    known = crawl_resolutions()
    out = {p: known[p] for p in pairs if p in known}
    missing = pairs - out.keys()
    if not missing:
        return out
    S = load_anchor()["S"]
    docs = asyncio.run(packuments({n for n, _ in missing}, S))
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    ids = {}
    for i, (name, rng) in enumerate(sorted(missing)):
        if docs.get(name) is None:
            out[(name, rng)] = None
            continue
        ids[str(i)] = (name, rng)
        groups[name].append({"id": str(i), "range": rng})
    results = node.resolve(({"packument": docs[n], "requests": r} for n, r in groups.items()), S)
    for rid, pair in ids.items():
        out[pair] = results[rid].get("version")
    return out
