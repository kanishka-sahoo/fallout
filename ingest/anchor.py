"""Computes the snapshot time S and writes config/anchor.json.

S is the earliest registry publish time of the replay incident's malicious versions, minus
one second. The affected versions come from OSV. The publish times come from the `time` map
in the npm registry, which keeps entries for versions that npm removed later. No value in
this file is entered by hand.

    uv run python -m ingest.anchor [--incident npm-2025-09-08-chalk-debug]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fallout.settings import ANCHOR_PATH, SETTINGS, load_incident
from ingest.http import CachedClient, encode_pkg

OSV_VULN = "https://api.osv.dev/v1/vulns/{id}"
REGISTRY = "https://registry.npmjs.org/{name}"


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso_ms(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def affected_versions(client: CachedClient, advisory_id: str) -> list[dict[str, Any]]:
    vuln = await client.get_json(OSV_VULN.format(id=advisory_id))
    if vuln is None:
        raise LookupError(f"OSV has no record for {advisory_id}")
    out = []
    for aff in vuln.get("affected", []):
        pkg = aff.get("package", {})
        if pkg.get("ecosystem") != "npm":
            continue
        for version in aff.get("versions", []):
            out.append({"advisory": advisory_id, "name": pkg["name"], "version": version})
    if not out:
        raise LookupError(f"{advisory_id} lists no concrete npm versions")
    return out


async def publish_time(client: CachedClient, name: str, version: str) -> datetime:
    doc = await client.get_json(REGISTRY.format(name=encode_pkg(name)))
    ts = (doc or {}).get("time", {}).get(version)
    if ts is None:
        raise LookupError(f"registry has no publish time for {name}@{version}")
    return parse_ts(ts)


async def compute(incident_id: str) -> dict[str, Any]:
    incident = load_incident(incident_id)
    async with CachedClient() as client:
        per_adv = await asyncio.gather(*(affected_versions(client, a) for a in incident["advisories"]))
        versions = [v for vs in per_adv for v in vs]
        times = await asyncio.gather(*(publish_time(client, v["name"], v["version"]) for v in versions))

    for v, t in zip(versions, times, strict=True):
        v["published_at"] = iso_ms(t)
    versions.sort(key=lambda v: v["published_at"])
    first = versions[0]
    s = parse_ts(first["published_at"]) - timedelta(seconds=1)
    return {
        "incident": incident_id,
        "S": iso_ms(s),
        "S_epoch_ms": int(s.timestamp() * 1000),
        "derived_from": (
            f"{first['name']}@{first['version']} published {first['published_at']} "
            "(npm registry time) minus 1s"
        ),
        "computed_at": iso_ms(datetime.now(UTC)),
        "malicious_versions": versions,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--incident", default=SETTINGS["replay_incident"])
    args = ap.parse_args()
    anchor = asyncio.run(compute(args.incident))
    ANCHOR_PATH.write_text(json.dumps(anchor, indent=2) + "\n")
    print(f"S = {anchor['S']}  ({anchor['derived_from']})")
    print(f"{len(anchor['malicious_versions'])} malicious versions -> {ANCHOR_PATH}")


if __name__ == "__main__":
    main()
