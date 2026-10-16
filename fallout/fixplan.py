"""Minimal remediation plans (BUILD.md §6.3 step 1).

For each affected package P a repo still reaches (unmitigated, or locked at an affected
version), find the requirements on P in the repo's resolved tree that admit an affected
version, and pick the highest version of P published at or before S that is not affected and
satisfies all of them.

- A **selector override** `{"P@<affected>": v}`. Arborist applies a keyed rule only to edges
  whose spec intersects the key (override-set.js `getEdgeRule`), so it rewrites exactly the
  edges that admit the malicious version and leaves e.g. `debug@^3.2.7` alone. One version
  then has to satisfy only the admitting ranges, which avoids most scoped overrides.
- A **direct dependency** on P is pinned to the highest safe version its own range admits.
  The pin does not intersect the selector, so npm's root-override check (EOVERRIDE) never fires.
- When no single version fits the admitting ranges: **scoped overrides** `{parent: {P: v}}`,
  one per parent package, each with the highest safe version its own ranges admit.

Override rules match on the edge *name*, so an aliased edge (`"strip-ansi-cjs":
"npm:strip-ansi@^6"`) is never rewritten; the sandbox verification catches any such miss
before a PR exists.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from falkordb import Graph

from fallout import node
from fallout.blast import Affected, Closure, repo_status
from fallout.db import query, rows
from fallout.resolve import packuments
from fallout.settings import load_anchor

PENDING = "PENDING"
AWAITING_APPROVAL = "AWAITING_APPROVAL"
APPLYING = "APPLYING"
APPLIED = "APPLIED"
FAILED = "FAILED"
NOTHING_TO_FIX = "NOTHING_TO_FIX"


@dataclass
class PackageFix:
    package: str
    strategy: str  # selector | pin | scoped | unresolved
    version: str | None
    requirements: list[dict[str, str]]
    scoped: dict[str, str] = field(default_factory=dict)  # parent package ("(root)" = pin) -> version
    reason: str = ""


def safe_versions(pkg: str, bad: set[str], S: str) -> list[str]:
    """Stable versions of `pkg` published at or before S that are not affected, non-deprecated
    first (deprecated ones only when nothing else exists), highest last."""
    from ingest.anchor import parse_ts

    doc = asyncio.run(packuments({pkg}, S)).get(pkg) or {"versions": {}, "time": {}}
    cutoff = parse_ts(S)
    pool = [
        v
        for v in doc["versions"]
        if v not in bad and "-" not in v and doc["time"].get(v) and parse_ts(doc["time"][v]) <= cutoff
    ]
    live = [v for v in pool if not doc["versions"][v].get("deprecated")]
    return live or pool


def best_version(candidates: list[str], ranges: list[str]) -> str | None:
    """Highest candidate satisfying every range (npm semver), or None."""
    if not candidates:
        return None
    reqs = [
        {"id": f"{i}:{j}", "op": "satisfies", "range": r, "version": v}
        for i, v in enumerate(candidates)
        for j, r in enumerate(ranges)
    ]
    ok = node.semver_eval(reqs)
    fits = [
        v
        for i, v in enumerate(candidates)
        if all(ok[f"{i}:{j}"].get("result") is True for j in range(len(ranges)))
    ]
    if not fits:
        return None
    top = node.semver_eval([{"id": "max", "op": "maxSatisfying", "range": "*", "versions": fits}])
    return top["max"]["result"]


def admits(range_: str, versions: list[str]) -> bool:
    r = node.semver_eval([{"id": "a", "op": "maxSatisfying", "range": range_, "versions": versions}])["a"]
    return r.get("result") not in (None, "unknown")


def manifest_field(manifest: dict[str, Any], pkg: str) -> str | None:
    for f in ("dependencies", "devDependencies", "optionalDependencies"):
        if pkg in manifest.get(f, {}):
            return f
    return None


def plan_package(
    pkg: str,
    reqs: list[dict[str, str]],
    candidates: list[str],
    bad_versions: list[str],
    direct: tuple[str, str] | None,
) -> tuple[PackageFix, dict[str, str] | None, dict[str, Any]]:
    """Decide the fix for one affected package.

    reqs: every requirement on `pkg` in the resolved tree, as {parent, parent_name, requirement};
    the root's own requirement has parent_name "(root)". candidates: safe versions at S.
    direct: (manifest field, spec) when the root manifest depends on `pkg` directly.
    Returns (fix, pin or None, overrides to merge).
    """
    admitting = [r for r in reqs if admits(r["requirement"], bad_versions)]
    fix = PackageFix(pkg, "selector", None, admitting)
    pin = None
    if direct and admits(direct[1], bad_versions):
        pv = best_version(candidates, [direct[1]])
        if pv:
            pin = {"field": direct[0], "from": direct[1], "to": pv}
            fix.scoped["(root)"] = pv
    transitive = [r for r in admitting if r["parent_name"] != "(root)"]
    if not transitive:
        fix.strategy, fix.version = "pin", fix.scoped.get("(root)")
        if fix.version is None:
            fix.strategy, fix.reason = "unresolved", f"no safe {pkg} version at S satisfies the direct range"
        return fix, pin, {}

    v = best_version(candidates, sorted({r["requirement"] for r in transitive}))
    if v:
        fix.version = v
        return fix, pin, {f"{pkg}@{' || '.join(bad_versions)}": v}

    fix.strategy = "scoped"
    overrides: dict[str, Any] = {}
    by_parent: dict[str, list[str]] = defaultdict(list)
    for r in transitive:
        by_parent[r["parent_name"]].append(r["requirement"])
    for parent, ranges in sorted(by_parent.items()):
        pv = best_version(candidates, sorted(set(ranges)))
        if pv is None:
            fix.strategy = "unresolved"
            fix.reason = f"no safe {pkg} version at S satisfies {parent}'s {sorted(set(ranges))}"
            return fix, pin, {}
        overrides[parent] = {pkg: pv}
        fix.scoped[parent] = pv
    return fix, pin, overrides


def plan_repo(g: Graph, incident: str, repo_key: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Build (but do not store) a plan body for one repo."""
    S = load_anchor()["S"]
    affected = Affected.load(g, incident)
    hit = rows(g, "repo_exposed", {"repo": repo_key, "incident": incident})
    exposed = bool(hit and hit[0]["hop"] is not None)
    st = repo_status(g, incident, repo_key, affected, exposed)
    locked_pkgs = {k.removeprefix("npm:").rsplit("@", 1)[0] for k in st["locked_affected"]}
    targets = sorted((set(st["affected_packages"]) - set(st["mitigated_packages"])) | locked_pkgs)

    bad: dict[str, set[str]] = defaultdict(set)
    for k in affected.keys:
        name, version = k.removeprefix("npm:").rsplit("@", 1)
        bad[name].add(version)

    cl = Closure.load(g, repo_key)
    changes: dict[str, Any] = {"pin": {}, "overrides": {}}
    fixes = []
    for pkg in targets:
        reqs = [
            {"parent": parent, "parent_name": cl.names.get(parent, "(root)"), "requirement": req}
            for (parent, child), req in cl.requirement.items()
            if cl.names.get(child) == pkg
        ]
        direct = manifest_field(manifest, pkg)
        fix, pin, overrides = plan_package(
            pkg,
            reqs,
            safe_versions(pkg, bad[pkg], S),
            sorted(bad[pkg]),
            (direct, manifest[direct][pkg]) if direct else None,
        )
        fixes.append(fix)
        if pin:
            changes["pin"][pkg] = pin
        for key, val in overrides.items():
            if isinstance(val, dict):
                changes["overrides"].setdefault(key, {}).update(val)
            else:
                changes["overrides"][key] = val

    paths = [p for p in st["paths_by_package"] if p["package"] in targets]
    return {
        "repo": repo_key,
        "incident": incident,
        "status_before": st["status"],
        "anchor_S": S,
        "packages": [asdict(f) for f in fixes],
        "changes": changes,
        "paths": paths,
        "fixable": bool(fixes) and all(f.strategy != "unresolved" for f in fixes),
    }


def apply_changes(manifest: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """The manifest with the plan's pins and overrides merged in (existing overrides kept
    unless the plan replaces the same key)."""
    out = json.loads(json.dumps(manifest))
    for pkg, pin in changes["pin"].items():
        out[pin["field"]][pkg] = pin["to"]
    ov = out.setdefault("overrides", {})
    for key, val in changes["overrides"].items():
        if isinstance(val, dict) and isinstance(ov.get(key), dict):
            ov[key] = {**ov[key], **val}
        else:
            ov[key] = val
    return out


# -- storage -------------------------------------------------------------------------------------


def store(g: Graph, body: dict[str, Any]) -> str:
    plan_id = "pl_" + secrets.token_hex(3)
    status = PENDING if body["fixable"] else NOTHING_TO_FIX if not body["packages"] else FAILED
    g.query(
        query("plan_upsert"),
        {
            "id": plan_id,
            "repo": body["repo"],
            "incident": body["incident"],
            "status": status,
            "now": int(time.time() * 1000),
            "body": json.dumps(body),
        },
    )
    return plan_id


def load(g: Graph, plan_id: str) -> dict[str, Any] | None:
    hit = rows(g, "plan_get", {"id": plan_id})
    if not hit:
        return None
    p = hit[0]
    return {**p, "body": json.loads(p["body"])}


def transition(g: Graph, plan_id: str, frm: list[str], to: str) -> bool:
    """Compare-and-set on the plan status; False when the plan was not in `frm`."""
    hit = rows(g, "plan_set_status", {"id": plan_id, "from": frm, "to": to, "now": int(time.time() * 1000)})
    return bool(hit)
