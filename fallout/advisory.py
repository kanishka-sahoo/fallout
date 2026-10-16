"""Ingests OSV advisories into an incident and computes CAN_RESOLVE_TO edges.

Exposure rule (docs/DECISIONS.md D1): a dependent is exposed if the version that npm *would
pick* for its requirement is affected. A range that only admits an affected version is not enough.
- MALICIOUS (`MAL-`): take the package's packument at S and add its malicious versions with
  their real publish times. npm-pick-manifest then resolves the requirement as of the last
  malicious publish. Each malicious release was the newest version, so for the chalk/debug
  replay this gives the same result as "the range admits it".
- VULN: the version resolved at S (the DEPENDS_ON or DIRECT_DEP target) is in the affected set.
There is one edge per dependent per affected package. It points to the version that npm would pick.

    uv run python -m fallout.advisory [--incident npm-2025-09-08-chalk-debug]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fallout import node
from fallout.db import batches, graph, query
from fallout.db import rows as rows_of
from fallout.repo import split_alias
from fallout.resolve import packuments
from fallout.settings import CONFIG_DIR, SETTINGS, load_anchor

OSV_VULN = "https://api.osv.dev/v1/vulns/{id}"


def vkey(name: str, version: str) -> str:
    return f"npm:{name}@{version}"


def parse_ts(ts: str) -> Any:
    from ingest.anchor import parse_ts as _parse

    return _parse(ts)


def epoch_ms(ts: str) -> int:
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


MALWARE = re.compile(r"\b(malware|malicious)\b", re.I)


def advisory_kind(advisory_id: str, doc: dict[str, Any]) -> str:
    """Classifies an advisory. MAL- records are MALICIOUS. GHSA records for embedded malware
    (ua-parser-js, rc, coa, event-stream) are also MALICIOUS. All others are VULN."""
    if advisory_id.startswith("MAL-"):
        return "MALICIOUS"
    return "MALICIOUS" if MALWARE.search(doc.get("summary") or "") else "VULN"


def osv_range(events: list[dict[str, str]]) -> str | None:
    """Converts OSV SEMVER or ECOSYSTEM events to one npm semver range (`||` of `>=a <b` or `>=a <=c`)."""
    parts, lo = [], None
    for e in events:
        if "introduced" in e:
            lo = "0.0.0" if e["introduced"] in ("0", "") else e["introduced"]
        elif lo is not None and ("fixed" in e or "last_affected" in e):
            hi = f"<{e['fixed']}" if "fixed" in e else f"<={e['last_affected']}"
            parts.append(f">={lo} {hi}")
            lo = None
    if lo is not None:
        parts.append(f">={lo}")
    return " || ".join(parts) or None


async def affected_from_osv(client: Any, advisory_id: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns the affected npm versions. It uses OSV's `versions` list if there is one. If not, it
    matches the OSV ranges against the registry packument with npm semver. Most GHSA records
    have only ranges."""
    from ingest.anchor import REGISTRY
    from ingest.http import encode_pkg

    out, expand = [], []
    for aff in doc.get("affected", []):
        pkg = aff.get("package", {})
        if pkg.get("ecosystem") != "npm":
            continue
        listed = aff.get("versions", [])
        out += [{"advisory": advisory_id, "name": pkg["name"], "version": v} for v in listed]
        if not listed:
            for r in aff.get("ranges", []):
                if r.get("type") in ("SEMVER", "ECOSYSTEM") and (rng := osv_range(r.get("events", []))):
                    expand.append((pkg["name"], rng))
    if expand:
        docs = await asyncio.gather(
            *(client.get_json(REGISTRY.format(name=encode_pkg(n))) for n, _ in expand)
        )
        reqs = [
            {"id": str(i), "op": "filter", "range": rng, "versions": list((d or {}).get("versions", {}))}
            for i, ((_, rng), d) in enumerate(zip(expand, docs, strict=True))
        ]
        res = node.semver_eval(reqs)
        for i, (name, _) in enumerate(expand):
            vs = res[str(i)].get("result")
            if isinstance(vs, list):
                out += [{"advisory": advisory_id, "name": name, "version": v} for v in vs]
    if not out:
        raise LookupError(f"{advisory_id} lists no concrete npm versions")
    return out


async def fetch(
    advisory_ids: list[str], kind: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Converts OSV records to (advisory rows, affected version rows with registry publish times).

    Malicious versions keep their registry publish time. If the registry no longer lists a
    version (for example, it was unpublished years ago), the advisory's OSV publish time is used.
    Vulnerable versions published after S did not exist at S, so they are dropped. `kind`
    replaces the per-record classification (GHSA-mh6f-8j2x-4483 is malware, but its summary
    does not say so).
    """
    from ingest.anchor import iso_ms, publish_time
    from ingest.http import CachedClient

    S = epoch_ms(load_anchor()["S"])
    async with CachedClient() as client:
        docs = [
            d or {}
            for d in await asyncio.gather(*(client.get_json(OSV_VULN.format(id=a)) for a in advisory_ids))
        ]
        for aid, d in zip(advisory_ids, docs, strict=True):
            if not d:
                raise LookupError(f"OSV has no record for {aid}")
        per_adv = await asyncio.gather(
            *(affected_from_osv(client, a, d) for a, d in zip(advisory_ids, docs, strict=True))
        )
        affected = [v for vs in per_adv for v in vs]

        async def when(v: dict[str, Any]) -> str | None:
            try:
                return iso_ms(await publish_time(client, v["name"], v["version"]))
            except LookupError:
                return None

        times = await asyncio.gather(*(when(v) for v in affected))

    advisories = []
    kinds = {}
    for aid, doc in zip(advisory_ids, docs, strict=True):
        kinds[aid] = kind or advisory_kind(aid, doc)
        severity = (doc.get("database_specific") or {}).get("severity")
        advisories.append(
            {
                "id": aid,
                "kind": kinds[aid],
                "summary": doc.get("summary") or (doc.get("details") or "")[:300],
                "published_at": doc.get("published"),
                "severity": severity,
                "url": f"https://osv.dev/vulnerability/{aid}",
            }
        )
    published: dict[str, str | None] = {str(a["id"]): a["published_at"] for a in advisories}
    rows = []
    for v, t in zip(affected, times, strict=True):
        malicious = kinds[v["advisory"]] == "MALICIOUS"
        if malicious and t is None and (pub := published[v["advisory"]]):
            t = iso_ms(parse_ts(pub))
        if not malicious and (t is None or epoch_ms(t) > S):
            continue
        rows.append(
            {
                "advisory": v["advisory"],
                "name": v["name"],
                "version": v["version"],
                "key": vkey(v["name"], v["version"]),
                "malicious": malicious,
                "published_at": epoch_ms(t) if t else None,
                "published_iso": t,
            }
        )
    return advisories, rows


def would_pick_malicious(
    candidates: list[dict[str, Any]], malicious: dict[str, list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Resolves each candidate (dependent, requirement) on a package with malicious versions.
    The malicious versions are added to the packument, and resolution uses the time of the
    last malicious publish."""
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
    for pkg, reqs in groups.items():  # one resolver run per package, because `before` is different for each
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


def resolve_edges(
    candidates: list[dict[str, Any]], affected: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Converts candidate (dependent, requirement) edges to CAN_RESOLVE_TO edges with rule D1."""
    malicious: dict[str, list[dict[str, Any]]] = defaultdict(list)
    vuln: dict[str, set[str]] = defaultdict(set)
    for a in affected:
        if a["malicious"] and a["published_iso"]:
            malicious[a["name"]].append(a)
        elif not a["malicious"]:
            vuln[a["name"]].add(a["version"])

    mal_candidates = [c for c in candidates if c["pkg"] in malicious]
    edges, unknown = would_pick_malicious(mal_candidates, malicious) if mal_candidates else ([], [])
    edges += [
        {**c, "to": vkey(c["pkg"], c["at_s"])} for c in candidates if c["at_s"] in vuln.get(c["pkg"], ())
    ]
    return edges, unknown


def write_edges(g: Any, incident_id: str, edges: list[dict[str, Any]]) -> None:
    for kind, q in (("Version", "can_resolve_version"), ("Repo", "can_resolve_repo")):
        rows = [
            {"dependent": e["dependent"], "to": e["to"], "requirement": e["requirement"]}
            for e in edges
            if e["kind"] == kind
        ]
        for chunk in batches(rows):
            g.query(query(q), {"incident": incident_id, "rows": list(chunk)})


def iso_from_ms(ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def recompute_repo_edges(g: Any, incident_id: str, repo_key: str) -> list[dict[str, Any]]:
    """Recomputes CAN_RESOLVE_TO for one repo's direct requirements after its manifest changes
    (recheck_repo). Version-level edges do not depend on the repo, so they do not change."""
    affected = [
        {**a, "published_iso": iso_from_ms(a["published_at"]) if a["published_at"] else None}
        for a in rows_of(g, "affected_rows", {"incident": incident_id})
    ]
    packages = sorted({a["name"] for a in affected})
    candidates = rows_of(g, "repo_candidate_edges", {"repo": repo_key, "packages": packages})
    edges, _ = resolve_edges(candidates, affected)
    g.query(query("can_resolve_clear_repo"), {"repo": repo_key, "incident": incident_id})
    write_edges(g, incident_id, edges)
    return edges


def ingest_advisory(
    advisory_ids: list[str], incident_id: str, title: str | None = None, kind: str | None = None
) -> AdvisoryReport:
    t0 = time.monotonic()
    advisories, affected = asyncio.run(fetch(advisory_ids, kind))
    return write_incident(graph(), incident_id, title, advisories, affected, t0)


def write_incident(
    g: Any,
    incident_id: str,
    title: str | None,
    advisories: list[dict[str, Any]],
    affected: list[dict[str, Any]],
    t0: float | None = None,
) -> AdvisoryReport:
    """Stores an incident with its advisories and affected versions, then computes its
    CAN_RESOLVE_TO edges. Simulated incidents (fallout/simulate.py) use it too."""
    t0 = t0 or time.monotonic()
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
    edges, unknown = resolve_edges(candidates, affected)

    g.query(query("can_resolve_clear"), {"incident": incident_id})
    write_edges(g, incident_id, edges)

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
