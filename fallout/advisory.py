"""Ingest OSV advisories into an incident and compute CAN_RESOLVE_TO (BUILD.md §5.3, §7.1–7.2).

Exposure rule (docs/DECISIONS.md D1): a dependent is exposed when the version npm *would pick*
for its requirement is affected, not merely when the range admits one.
- MALICIOUS (`MAL-`): the package's packument at S, plus its malicious versions injected with
  their real publish times, resolved by npm-pick-manifest as of the last malicious publish.
  Each malicious release was the newest, so for the chalk/debug replay this agrees with
  "range admits".
- VULN: the version resolved at S (the DEPENDS_ON / DIRECT_DEP target) is in the affected set.
One edge per dependent per affected package, pointing at the version npm would pick.

    uv run python -m fallout.advisory [--incident npm-2025-09-08-chalk-debug]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fallout import node
from fallout.db import batches, graph, query
from fallout.repo import split_alias
from fallout.resolve import packuments
from fallout.settings import CONFIG_DIR, SETTINGS

OSV_VULN = "https://api.osv.dev/v1/vulns/{id}"


def vkey(name: str, version: str) -> str:
    return f"npm:{name}@{version}"


def epoch_ms(ts: str) -> int:
    from ingest.anchor import parse_ts

    return int(parse_ts(ts).timestamp() * 1000)


@dataclass
class AdvisoryReport:
    incident: str
    advisories: int
    affected_versions: int
    candidates: int
    edges: int
    by_package: dict[str, int] = field(default_factory=dict)
    unknown_specs: list[dict[str, str]] = field(default_factory=list)
    took_ms: int = 0


async def fetch(advisory_ids: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """OSV records -> (advisory rows, affected version rows with registry publish times)."""
    from ingest.anchor import affected_versions, iso_ms, publish_time
    from ingest.http import CachedClient

    async with CachedClient() as client:
        docs = await asyncio.gather(*(client.get_json(OSV_VULN.format(id=a)) for a in advisory_ids))
        per_adv = await asyncio.gather(*(affected_versions(client, a) for a in advisory_ids))
        affected = [v for vs in per_adv for v in vs]

        async def when(v: dict[str, Any]) -> str | None:
            try:
                return iso_ms(await publish_time(client, v["name"], v["version"]))
            except LookupError:
                return None

        times = await asyncio.gather(*(when(v) for v in affected))

    advisories = []
    for aid, doc in zip(advisory_ids, docs, strict=True):
        doc = doc or {}
        severity = (doc.get("database_specific") or {}).get("severity")
        advisories.append(
            {
                "id": aid,
                "kind": "MALICIOUS" if aid.startswith("MAL-") else "VULN",
                "summary": doc.get("summary") or (doc.get("details") or "")[:300],
                "published_at": doc.get("published"),
                "severity": severity,
                "url": f"https://osv.dev/vulnerability/{aid}",
            }
        )
    rows = []
    for v, t in zip(affected, times, strict=True):
        rows.append(
            {
                "advisory": v["advisory"],
                "name": v["name"],
                "version": v["version"],
                "key": vkey(v["name"], v["version"]),
                "malicious": v["advisory"].startswith("MAL-"),
                "published_at": epoch_ms(t) if t else None,
                "published_iso": t,
            }
        )
    return advisories, rows


def would_pick_malicious(
    candidates: list[dict[str, Any]], malicious: dict[str, list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """For each candidate (dependent, requirement) into a package with malicious versions,
    resolve as of the last malicious publish with those versions injected."""
    docs = asyncio.run(packuments(set(malicious)))
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    befores: dict[str, str] = {}
    for pkg, mal in malicious.items():
        doc = docs[pkg] = docs.get(pkg) or {"name": pkg, "versions": {}, "time": {}}
        for m in mal:
            doc["versions"][m["version"]] = {"name": pkg, "version": m["version"]}
            doc["time"][m["version"]] = m["published_iso"]
        befores[pkg] = max(m["published_iso"] for m in mal)
    ranges = sorted({(c["pkg"], split_alias(c["pkg"], c["requirement"])[1]) for c in candidates})
    ids = {str(i): pr for i, pr in enumerate(ranges)}
    for i, (pkg, rng) in ids.items():
        groups[pkg].append({"id": i, "range": rng})

    picked: dict[tuple[str, str], dict[str, Any]] = {}
    for pkg, reqs in groups.items():  # one resolver run per package: `before` differs
        results = node.resolve([{"packument": docs[pkg], "requests": reqs}], befores[pkg])
        for r in reqs:
            picked[ids[r["id"]]] = results[r["id"]]

    bad = {(pkg, m["version"]) for pkg, mal in malicious.items() for m in mal}
    edges, unknown = [], []
    for c in candidates:
        rng = split_alias(c["pkg"], c["requirement"])[1]
        res = picked[(c["pkg"], rng)]
        if "version" not in res:
            unknown.append(
                {"dependent": c["dependent"], "requirement": c["requirement"], "error": res["error"]}
            )
        elif (c["pkg"], res["version"]) in bad:
            edges.append({**c, "to": vkey(c["pkg"], res["version"])})
    return edges, unknown


def ingest_advisory(advisory_ids: list[str], incident_id: str, title: str | None = None) -> AdvisoryReport:
    t0 = time.monotonic()
    g = graph()
    advisories, affected = asyncio.run(fetch(advisory_ids))
    started = min((a["published_iso"] for a in affected if a["published_iso"]), default=None)
    g.query(
        query("incident_upsert"),
        {
            "id": incident_id,
            "title": title or incident_id,
            "started_at": epoch_ms(started) if started else None,
        },
    )
    g.query(query("advisory_upsert"), {"incident": incident_id, "rows": advisories})
    g.query(query("affected_upsert"), {"rows": affected})

    packages = sorted({a["name"] for a in affected})
    cols = ["pkg", "dependent", "kind", "requirement", "at_s"]
    candidates = [
        dict(zip(cols, row, strict=True))
        for row in g.query(query("candidate_edges"), {"packages": packages}).result_set
    ]

    malicious: dict[str, list[dict[str, Any]]] = defaultdict(list)
    vuln: dict[str, set[str]] = defaultdict(set)
    for a in affected:
        if a["malicious"] and a["published_iso"]:
            malicious[a["name"]].append(a)
        elif not a["malicious"]:
            vuln[a["name"]].add(a["version"])

    edges, unknown = would_pick_malicious([c for c in candidates if c["pkg"] in malicious], malicious)
    edges += [
        {**c, "to": vkey(c["pkg"], c["at_s"])} for c in candidates if c["at_s"] in vuln.get(c["pkg"], ())
    ]

    g.query(query("can_resolve_clear"), {"incident": incident_id})
    for kind, q in (("Version", "can_resolve_version"), ("Repo", "can_resolve_repo")):
        rows = [{"dependent": e["dependent"], "to": e["to"], "requirement": e["requirement"]} for e in edges]
        rows = [r for r, e in zip(rows, edges, strict=True) if e["kind"] == kind]
        for chunk in batches(rows):
            g.query(query(q), {"incident": incident_id, "rows": list(chunk)})

    by_package: dict[str, int] = defaultdict(int)
    for e in edges:
        by_package[e["pkg"]] += 1
    return AdvisoryReport(
        incident=incident_id,
        advisories=len(advisories),
        affected_versions=len(affected),
        candidates=len(candidates),
        edges=len(edges),
        by_package=dict(sorted(by_package.items(), key=lambda kv: -kv[1])),
        unknown_specs=unknown,
        took_ms=round((time.monotonic() - t0) * 1000),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--incident", default=SETTINGS["replay_incident"])
    args = ap.parse_args()
    cfg = json.loads((CONFIG_DIR / "incidents" / f"{args.incident}.json").read_text())
    report = ingest_advisory(cfg["advisories"], args.incident, cfg.get("title"))
    print(json.dumps(report.__dict__, indent=2))


if __name__ == "__main__":
    main()
