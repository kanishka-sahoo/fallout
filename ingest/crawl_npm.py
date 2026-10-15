"""Maintainers, publishers, provenance and weekly downloads for the crawled closure
(BUILD.md §5.1, §5.5 step 4).

Per version: `GET registry.npmjs.org/{name}/{version}` -> `_npmUser` (publisher),
`maintainers[]` and `dist.attestations.provenance`. Only usernames are kept, never emails.
Per package: `api.npmjs.org/downloads/point/last-week`, in bulk for unscoped names (<=128 per
call); the API refuses scoped names in bulk, so those go one at a time at lower concurrency.
Download counts are current, not as of S (a stated limitation): weighting and display only.

    uv run python -m ingest.crawl_npm [--concurrency 32] [--downloads-interval 1.5]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from typing import Any

from fallout.settings import RAW_DIR
from ingest.crawl import OUT_DIR as CRAWL_DIR
from ingest.http import CachedClient, RetryableStatus, encode_pkg

REGISTRY_VERSION = "https://registry.npmjs.org/{name}/{version}"
DOWNLOADS = "https://api.npmjs.org/downloads/point/last-week/{names}"
BULK = 128
OUT_DIR = RAW_DIR / "npm"


async def version_meta(client: CachedClient, rec: dict[str, Any]) -> dict[str, Any]:
    doc = await client.get_json(
        REGISTRY_VERSION.format(name=encode_pkg(rec["name"]), version=encode_pkg(rec["version"]))
    )
    if doc is None:
        return {"key": rec["key"], "found": False}
    attestations = (doc.get("dist") or {}).get("attestations") or {}
    return {
        "key": rec["key"],
        "found": True,
        "publisher": (doc.get("_npmUser") or {}).get("name"),
        "maintainers": sorted({m["name"] for m in doc.get("maintainers") or [] if m.get("name")}),
        "has_provenance": bool(attestations.get("provenance")),
    }


async def downloads(client: CachedClient, names: list[str]) -> dict[str, int | None]:
    unscoped = sorted(n for n in names if not n.startswith("@"))
    scoped = sorted(n for n in names if n.startswith("@"))
    out: dict[str, int | None] = {}
    failed: list[str] = []

    async def bulk(chunk: list[str]) -> None:
        try:
            doc = await client.get_json(DOWNLOADS.format(names=",".join(chunk))) or {}
        except RetryableStatus:
            failed.extend(chunk)  # not cached, so a rerun retries only these
            return
        if len(chunk) == 1:  # a single name returns the point object, not a map
            doc = {chunk[0]: doc}
        for n in chunk:
            out[n] = (doc.get(n) or {}).get("downloads")

    async def single(name: str) -> None:
        try:
            doc = await client.get_json(DOWNLOADS.format(names=encode_pkg(name)))
        except RetryableStatus:
            failed.append(name)
            return
        out[name] = (doc or {}).get("downloads")
        if len(out) % 1000 == 0:
            progress = f"{len(out)}/{len(names)} (http hit/miss {client.hits}/{client.misses})"
            print(f"  downloads {progress}", flush=True)

    await asyncio.gather(
        *(bulk(unscoped[i : i + BULK]) for i in range(0, len(unscoped), BULK)),
        *(single(n) for n in scoped),
    )
    if failed:
        print(f"  downloads: {len(failed)} packages still rate-limited; rerun to fill them in", flush=True)
    return out


async def amain(concurrency: int, downloads_concurrency: int, downloads_interval: float) -> None:
    versions = [json.loads(line) for line in (CRAWL_DIR / "versions.jsonl").open()]
    names = sorted({v["name"] for v in versions})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    async with CachedClient(concurrency=concurrency) as reg:
        metas = await asyncio.gather(*(version_meta(reg, v) for v in versions))
        print(f"versions: {len(metas)} (http hit/miss {reg.hits}/{reg.misses}) {time.monotonic() - t0:.0f}s")
    with (OUT_DIR / "version_meta.jsonl").open("w") as f:
        for m in metas:
            f.write(json.dumps(m) + "\n")

    async with CachedClient(concurrency=downloads_concurrency, min_interval=downloads_interval) as dl:
        counts = await downloads(dl, names)
        print(f"downloads: {len(counts)} (http hit/miss {dl.hits}/{dl.misses}) {time.monotonic() - t0:.0f}s")
    with (OUT_DIR / "downloads.jsonl").open("w") as f:
        for n in names:
            f.write(json.dumps({"name": n, "weekly_downloads": counts.get(n)}) + "\n")

    found = [m for m in metas if m["found"]]
    maintainers = Counter(name for m in found for name in m["maintainers"])
    summary = {
        "versions": len(metas),
        "versions_not_found": len(metas) - len(found),
        "versions_with_publisher": sum(1 for m in found if m["publisher"]),
        "versions_with_provenance": sum(1 for m in found if m["has_provenance"]),
        "distinct_maintainers": len(maintainers),
        "packages": len(names),
        "packages_without_downloads": sum(1 for n in names if counts.get(n) is None),
        "elapsed_s": round(time.monotonic() - t0),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--downloads-concurrency", type=int, default=1)
    ap.add_argument(
        "--downloads-interval", type=float, default=1.5, help="seconds between downloads API requests"
    )
    args = ap.parse_args()
    asyncio.run(amain(args.concurrency, args.downloads_concurrency, args.downloads_interval))


if __name__ == "__main__":
    main()
