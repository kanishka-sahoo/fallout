"""Resolves `(name, range)` at S outside the crawl.

The crawl already resolved every direct dependency and override spec of the repos. Those
results come from data/raw/crawl/resolutions.jsonl. A new pair (for example, a fix plan's
override) goes through the same packument construction and resolver.mjs. HTTP responses come
from the crawl's cache.
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
    """Returns the packuments as they were at `before` (default S), built in the same way as in the crawl."""
    # ingest imports fallout, so fallout imports ingest only inside functions
    from ingest.crawl import Crawl, epoch_ms
    from ingest.http import CachedClient

    before = before or load_anchor()["S"]
    async with CachedClient() as client:
        crawl = Crawl(client, before, epoch_ms(before))
        await asyncio.gather(*(crawl.load_packument(n) for n in names))
    return crawl.packuments


def resolve_at_s(pairs: set[tuple[str, str]]) -> dict[tuple[str, str], str | None]:
    """Returns {(name, range): version at S}. The version is None for ETARGET or an unknown package."""
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
