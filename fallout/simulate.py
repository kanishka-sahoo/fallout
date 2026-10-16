"""Simulated incidents: a what-if compromise, run through the same pipeline as a real advisory.

A scenario is one of three kinds:
- release: an attacker publishes a new version of each package at `published_at`, which can be
  now or in the future. The new version is the next patch, minor or major after the newest stable
  version at S, or a version that the user gives. These versions are MALICIOUS, so exposure uses
  the rule of the chalk/debug replay: npm resolves each requirement with the new version added,
  as of its publish time.
- versions: existing versions that match a semver range are declared compromised. This uses the
  VULN rule: a dependent is exposed if the version resolved at S is in the set.
- osv: real advisory ids from OSV, the same as a configured incident. Use it for an attack that
  is happening now.

Simulated incident ids start with "sim-". Their fixes are previews only: the approve endpoint
refuses them, so a simulation can never open a pull request. The graph is still the snapshot
at S, so a scenario answers "what if this happened to the ecosystem as it stood at S".
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Literal

from fallout import fixplan, node
from fallout.advisory import AdvisoryReport, epoch_ms, fetch, parse_ts, vkey, write_incident
from fallout.blast import EXPOSED_NO_LOCKFILE, LOCKED_MALICIOUS, NOT_AFFECTED, RANGE_ADMITS_LOCK_SAFE
from fallout.db import graph, query, rows
from fallout.resolve import packuments
from fallout.settings import load_anchor

PREFIX = "sim-"
STABLE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
Bump = Literal["patch", "minor", "major"]


class ScenarioError(ValueError):
    """The scenario cannot run as given. The message says what to change."""


def is_simulated(incident: str) -> bool:
    return incident.startswith(PREFIX)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def bump(version: str, kind: Bump) -> str:
    major, minor, patch = (int(x) for x in STABLE.match(version).groups())  # type: ignore[union-attr]
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def stable_at_s(doc: dict[str, Any] | None) -> list[str]:
    """Returns the stable versions published at or before S, newest first."""
    if not doc:
        return []
    cutoff = parse_ts(load_anchor()["S"])
    vs = [
        v
        for v in doc.get("versions", {})
        if STABLE.match(v) and doc.get("time", {}).get(v) and parse_ts(doc["time"][v]) <= cutoff
    ]
    return sorted(vs, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)


# -- lookups for the scenario builder ------------------------------------------------------------


def search_packages(q: str, k: int = 8) -> list[dict[str, Any]]:
    q = q.strip().lower()
    return rows(graph(), "sim_package_search", {"q": q, "k": k}) if q else []


def package_info(name: str) -> dict[str, Any]:
    """Returns what the builder shows for one package: the newest version at S, the versions
    that a release would add, and how many dependents in the graph point at the package."""
    hit = rows(graph(), "sim_package_info", {"name": name})
    if not hit:
        raise ScenarioError(
            f"{name} is not in the graph. Only packages in the snapshot at S can be simulated."
        )
    doc = asyncio.run(packuments({name})).get(name)
    versions = stable_at_s(doc)
    if not versions:
        raise ScenarioError(f"{name} has no stable release at S.")
    latest = versions[0]
    return {
        **hit[0],
        "latest": latest,
        "versions": versions[:40],
        "next": {k: bump(latest, k) for k in ("patch", "minor", "major")},
    }


def maintainer_packages(k: int = 8) -> dict[str, Any]:
    """The packages of the maintainer account with the widest reach, for the takeover template."""
    rs = rows(graph(), "sim_maintainer_packages", {"k": k})
    if not rs:
        raise ScenarioError("no maintainer reach in the graph. Run python -m analysis.algorithms first.")
    return {"maintainer": rs[0]["maintainer"], "reach": rs[0]["reach"], "packages": [r["name"] for r in rs]}


def matching_versions(name: str, range_: str) -> list[dict[str, Any]]:
    doc = asyncio.run(packuments({name})).get(name)
    versions = stable_at_s(doc)
    res = node.semver_eval([{"id": "m", "op": "filter", "range": range_, "versions": versions}])["m"]
    if res.get("result") == "unknown":
        raise ScenarioError(f"{range_!r} is not a semver range.")
    assert doc is not None
    return [{"version": v, "published_iso": doc["time"][v]} for v in res["result"]]


# -- building and running a scenario --------------------------------------------------------------


def release_rows(spec: dict[str, Any], advisory: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Affected rows for the release scenario, and the keys of the invented versions."""
    published = spec.get("published_at") or now_iso()
    try:
        when = parse_ts(published)
    except (ValueError, TypeError) as e:
        raise ScenarioError(f"{published!r} is not a time.") from e
    if when <= parse_ts(load_anchor()["S"]):
        raise ScenarioError(
            "The release time must be after the snapshot time S. Use compromised versions for older releases."
        )
    published = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    out, keys = [], []
    for p in spec["packages"]:
        info = package_info(p["name"])
        version = (
            p.get("version") if p.get("release") == "custom" else info["next"][p.get("release") or "patch"]
        )
        if not version or not re.match(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$", version):
            raise ScenarioError(f"Give {p['name']} a version such as 1.2.3.")
        if version in info["versions"]:
            raise ScenarioError(
                f"{p['name']}@{version} already existed at S. "
                "Choose a new version, or use compromised versions."
            )
        out.append(
            {
                "advisory": advisory,
                "name": p["name"],
                "version": version,
                "key": vkey(p["name"], version),
                "malicious": True,
                "published_at": epoch_ms(published),
                "published_iso": published,
            }
        )
        keys.append(vkey(p["name"], version))
    return out, keys


def versions_rows(spec: dict[str, Any], advisory: str) -> list[dict[str, Any]]:
    out = []
    for p in spec["packages"]:
        hits = matching_versions(p["name"], p.get("range") or "")
        if not hits:
            raise ScenarioError(f"No release of {p['name']} at S matches {p.get('range')!r}.")
        out += [
            {
                "advisory": advisory,
                "name": p["name"],
                "version": h["version"],
                "key": vkey(p["name"], h["version"]),
                "malicious": False,
                "published_at": epoch_ms(h["published_iso"]),
                "published_iso": h["published_iso"],
            }
            for h in hits
        ]
    return out


def default_title(spec: dict[str, Any], affected: list[dict[str, Any]]) -> str:
    kind = spec["kind"]
    if kind == "osv":
        return f"Advisory {', '.join(spec['advisories'][:3])}" + (
            " and more" if len(spec["advisories"]) > 3 else ""
        )
    names = sorted({a["name"] for a in affected})
    head = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    if kind == "release":
        versions = ", ".join(sorted({a["key"].removeprefix("npm:") for a in affected})[:3])
        return f"Malicious release of {versions}" if len(names) <= 3 else f"Malicious releases of {head}"
    return f"Compromised versions of {head}"


def create(spec: dict[str, Any], emit: Any = None) -> dict[str, Any]:
    """Stores a simulated incident and its CAN_RESOLVE_TO edges. The caller then runs blast_radius."""
    emit = emit or (lambda *a, **k: None)
    t0 = time.monotonic()
    kind = spec.get("kind")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    incident = f"{PREFIX}{stamp}-{secrets.token_hex(2)}"
    advisory = f"SIM-{stamp}-{secrets.token_hex(2)}".upper()
    invented: list[str] = []

    if kind in ("release", "versions"):
        if not spec.get("packages"):
            raise ScenarioError("Add at least one package.")
        if len(spec["packages"]) > 25:
            raise ScenarioError("A scenario can have at most 25 packages.")
        if kind == "release":
            affected, invented = release_rows(spec, advisory)
        else:
            affected = versions_rows(spec, advisory)
        advisories = [
            {
                "id": advisory,
                "kind": "MALICIOUS" if kind == "release" else "VULN",
                "summary": spec.get("summary") or "Simulated in the Fallout console",
                "published_at": affected[0]["published_iso"] if kind == "release" else now_iso(),
                "severity": "CRITICAL",
                "url": None,
            }
        ]
    elif kind == "osv":
        ids = [a.strip().upper() for a in spec.get("advisories", []) if a.strip()]
        if not ids:
            raise ScenarioError("Add at least one OSV advisory id, such as MAL-2025-46969.")
        spec = {**spec, "advisories": ids}
        try:
            advisories, affected = asyncio.run(fetch(ids))
        except LookupError as e:
            raise ScenarioError(str(e)) from e
        if not affected:
            raise ScenarioError("These advisories list no npm versions that existed at S.")
    else:
        raise ScenarioError("kind must be release, versions or osv.")

    title = (spec.get("title") or "").strip() or default_title(spec, affected)
    emit("simulate", step="resolve", incident=incident, affected_versions=len(affected))
    g = graph()
    report: AdvisoryReport = write_incident(g, incident, title, advisories, affected, t0)
    scenario = {k: spec.get(k) for k in ("kind", "packages", "advisories", "published_at")}
    scenario["versions"] = sorted({a["key"].removeprefix("npm:") for a in affected})
    g.query(
        query("sim_mark"),
        {
            "incident": incident,
            "scenario": json.dumps(scenario),
            "now": int(time.time() * 1000),
            "keys": invented,
        },
    )
    return {"incident": incident, "title": title, "report": report.__dict__}


def delete(incident: str) -> None:
    if not is_simulated(incident):
        raise ScenarioError("Only simulated incidents can be deleted.")
    g = graph()
    g.query(query("can_resolve_clear"), {"incident": incident})
    g.query(query("exposes_clear"), {"incident": incident})
    g.query(query("sim_delete_plans"), {"incident": incident})
    g.query(query("sim_delete"), {"incident": incident})


# -- response plan ------------------------------------------------------------------------------

NEEDS_ACTION = {LOCKED_MALICIOUS, EXPOSED_NO_LOCKFILE, RANGE_ADMITS_LOCK_SAFE}
PRIORITY = [LOCKED_MALICIOUS, EXPOSED_NO_LOCKFILE, RANGE_ADMITS_LOCK_SAFE]


def plan_key(incident: str) -> str:
    """Changes whenever the blast radius or a repo status changes, so a cached plan is never stale."""
    g = graph()
    inc = rows(g, "incident_exists", {"incident": incident})
    statuses = sorted(
        (r["repo"], r["status"] or "") for r in rows(g, "sim_repo_statuses", {"incident": incident})
    )
    return json.dumps([inc[0]["blast_at"] if inc else None, statuses])


def response_plan(incident: str) -> dict[str, Any]:
    """Builds fix previews for every repo that needs action, with the same planner as plan_fix,
    and merges their overrides into one block that is safe to add to every repo. Nothing is stored."""
    from fallout.tools import checkout_dir

    g = graph()
    statuses = rows(g, "sim_repo_statuses", {"incident": incident})
    statuses.sort(key=lambda r: (PRIORITY.index(r["status"]) if r["status"] in PRIORITY else 9, r["repo"]))

    def plan(r: dict[str, Any]) -> dict[str, Any]:
        if r["status"] not in NEEDS_ACTION:
            return {"repo": r["repo"], "status": r["status"] or NOT_AFFECTED, "plan": None}
        try:
            full = r["repo"].removeprefix("repo:")
            manifest = json.loads((checkout_dir(full) / "package.json").read_text())
            return {
                "repo": r["repo"],
                "status": r["status"],
                "plan": fixplan.plan_repo(g, incident, r["repo"], manifest),
            }
        except Exception as e:  # noqa: BLE001 - one repo's failure must not hide the others
            return {"repo": r["repo"], "status": r["status"], "plan": None, "error": str(e)}

    # Each plan spends most of its time in node subprocesses, so the repos run in parallel.
    with ThreadPoolExecutor(max_workers=6) as pool:
        repos = list(pool.map(plan, statuses))

    merged: dict[str, Any] = {}
    safe: dict[str, str] = {}
    for r in repos:
        if not r["plan"]:
            continue
        for key, val in r["plan"]["changes"]["overrides"].items():
            if isinstance(val, dict):
                merged.setdefault(key, {}).update(val)
            else:
                merged[key] = val
        for f in r["plan"]["packages"]:
            if f.get("version"):
                safe[f["package"]] = f["version"]

    actions: defaultdict[str, int] = defaultdict(int)
    for r in repos:
        if r["status"] in NEEDS_ACTION:
            actions[r["status"]] += 1
    return {
        "incident": incident,
        "simulated": is_simulated(incident),
        "anchor_S": load_anchor()["S"],
        "repos": repos,
        "needs_action": sum(actions.values()),
        "by_status": dict(actions),
        "overrides": merged,
        "safe_versions": safe,
    }
