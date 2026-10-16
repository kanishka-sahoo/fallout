"""The tools that the LLM can call, as plain functions over FalkorDB.

mcp_server/server.py makes them available over MCP. The eval and the tests call them directly.
Every tool returns this envelope:

    {"result": ..., "paths": [{id, nodes[], edges[{type, requirement}]}],
     "cypher": [query names under graph/queries/], "timing_ms": int, "summary": {k: v}}

`summary` holds the values that the event log prints (`tool=blast_radius hops=10 ...`).
No tool in this module uses GitHub or can apply a fix. Fixes go through api/approval.py and
api/fix_executor.py only.
"""

from __future__ import annotations

import functools
import json
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fallout import fixplan
from fallout.advisory import ingest_advisory as _ingest
from fallout.advisory import recompute_repo_edges
from fallout.blast import (
    NOT_AFFECTED,
    Affected,
    cross_check_path,
    path_id,
)
from fallout.blast import (
    blast_radius as _blast,
)
from fallout.blast import (
    exposure_path as _exposure_path,
)
from fallout.blast import (
    repo_status as _repo_status,
)
from fallout.db import graph, query, rows, track_queries
from fallout.settings import SETTINGS, load_anchor, load_incident

EXPOSURE_DEFINITION = (
    "A target is exposed when, as of the anchor S, the version npm would pick for some requirement "
    "on its resolved dependency tree is an affected version (malicious versions are injected as "
    "of their publish time)."
)

STATUS_MEANING = {
    "LOCKED_MALICIOUS": "the lockfile pins an affected version: installs from the lockfile get it",
    "EXPOSED_NO_LOCKFILE": "no lockfile, and a requirement on its tree would pick an affected version",
    "RANGE_ADMITS_LOCK_SAFE": (
        "the lockfile pins safe versions, but a requirement would pick an affected version on any "
        "fresh resolve (npm install without the lockfile, `npm update`, a bot PR)"
    ),
    "MITIGATED_BY_OVERRIDE": "every affected package it reaches is covered by an override to a safe version",
    "NOT_AFFECTED": "no requirement on its tree would pick an affected version",
}


class ToolError(Exception):
    """A tool failure that the LLM gets as a message, for example bad input or a missing prerequisite."""


def tool(
    fn: Callable[..., tuple[Any, list[dict[str, Any]], dict[str, Any]]],
) -> Callable[..., dict[str, Any]]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        used = track_queries()
        t0 = time.monotonic()
        try:
            result, paths, summary = fn(*args, **kwargs)
        except (ToolError, LookupError) as e:
            result, paths, summary = {"error": str(e)}, [], {"error": type(e).__name__}
        return {
            "result": result,
            "paths": paths,
            "cypher": list(used),
            "timing_ms": round((time.monotonic() - t0) * 1000),
            "summary": summary,
        }

    return wrapper


def repo_key(repo: str) -> str:
    """Normalizes a repo name. `billing-api`, `fallout-demo/billing-api` and
    `repo:fallout-demo/billing-api` are the same repo."""
    name = repo.strip().removeprefix("repo:")
    if "/" not in name:
        name = f"{SETTINGS['github_org']}/{name}"
    return f"repo:{name}"


def known_repo(g: Any, repo: str) -> str:
    key = repo_key(repo)
    if not rows(g, "repo_exposed", {"repo": key, "incident": ""}):
        known = [r["key"].removeprefix("repo:") for r in rows(g, "repo_keys")]
        raise ToolError(f"unknown repo {repo!r}; known repos: {known}")
    return key


def require_incident(g: Any, incident: str, need_blast: bool = True) -> dict[str, Any]:
    hit = rows(g, "incident_exists", {"incident": incident})
    if not hit:
        raise ToolError(f"incident {incident!r} not ingested: call ingest_advisory first")
    if need_blast and hit[0]["blast_at"] is None:
        raise ToolError(f"no blast radius stored for {incident!r}: call blast_radius first")
    return hit[0]


def anchor() -> dict[str, str]:
    return {"anchor_S": load_anchor()["S"], "exposure_definition": EXPOSURE_DEFINITION}


# -- read tools ----------------------------------------------------------------------------------


@tool
def ingest_advisory(advisory_ids: list[str] | None, incident_id: str, title: str | None = None):
    """Gets OSV advisories, creates the malicious versions and computes CAN_RESOLVE_TO edges."""
    if not advisory_ids:
        try:
            cfg = load_incident(incident_id)
        except FileNotFoundError as e:
            raise ToolError(f"no advisory ids given and no config/incidents/{incident_id}.json") from e
        advisory_ids, title = cfg["advisories"], title or cfg.get("title")
    rep = _ingest(list(advisory_ids), incident_id, title)
    result = {**rep.__dict__, "unknown_specs": rep.unknown_specs[:20], **anchor()}
    return (
        result,
        [],
        {
            "incident": incident_id,
            "advisories": rep.advisories,
            "affected_versions": rep.affected_versions,
            "edges": rep.edges,
        },
    )


@tool
def blast_radius(incident_id: str, max_hops: int = 16):
    """Runs a reverse BFS, one hop at a time, from the affected versions.
    Stores the EXPOSES edges and the repo statuses."""
    g = graph()
    require_incident(g, incident_id, need_blast=False)
    res = _blast(incident_id, max_hops, g=g)
    repos = [
        {
            "repo": r["repo"].removeprefix("repo:"),
            "status": r["status"],
            "hop": r["hop"],
            "path_id": r.get("path_id"),
            "affected_packages": r["affected_packages"],
            "mitigated_packages": r["mitigated_packages"],
            "locked_affected": r["locked_affected"],
        }
        for r in res.repos
    ]
    result = {
        "incident": incident_id,
        "hops": res.hops,
        "exposed_versions": res.exposed_versions,
        "exposed_packages": res.exposed_packages,
        "truncated": res.truncated,
        "repos": repos,
        "top_exposed_packages_by_downloads": res.top_packages,
        **anchor(),
    }
    exposed_repos = sum(1 for r in repos if r["status"] != NOT_AFFECTED)
    return (
        result,
        res.paths,
        {
            "incident": incident_id,
            "hops": len(res.hops),
            "exposed_versions": res.exposed_versions,
            "exposed_repos": exposed_repos,
        },
    )


def split_spec(spec: str) -> tuple[str, str | None]:
    """`debug@4.4.1` -> (debug, 4.4.1); `@scope/x` -> (@scope/x, None)."""
    at = spec.rfind("@")
    return (spec[:at], spec[at + 1 :] or None) if at > 0 else (spec, None)


def package_exposure(g: Any, incident_id: str, package: str, affected: Affected):
    from fallout.resolve import resolve_at_s

    name, version = split_spec(package.strip().removeprefix("npm:"))
    if version is None:
        version = resolve_at_s({(name, "*")}).get((name, "*"))
        if version is None:
            raise ToolError(f"{name} has no version at S")
    key = f"npm:{name}@{version}"
    hit = rows(g, "version_lookup", {"key": key, "incident": incident_id})
    if not hit:
        raise ToolError(f"{name}@{version} is not in the graph (not crawled, or did not exist at S)")
    if key in affected.keys:  # the target itself is an affected version
        path: dict[str, Any] | None = {"id": path_id([key]), "nodes": [key], "edges": []}
    elif hit[0]["hop"] is not None:
        path = _exposure_path(g, incident_id, key, affected, kind="version")
    else:
        path = None
    result = {
        "target": f"{name}@{version}",
        "exposed": path is not None,
        "hop": 0 if key in affected.keys else hit[0]["hop"],
        "path_id": path["id"] if path else None,
        **anchor(),
    }
    return (
        result,
        [path] if path else [],
        {"package": result["target"], "path_len": len(path["edges"]) if path else 0},
    )


@tool
def exposure_path(incident_id: str, repo: str | None = None, package: str | None = None):
    """Returns the path from the target to an affected version, with the requirement on every hop.
    The target is a repo or a package. For a package, `name` means its version at S.
    `name@version` is also valid."""
    if bool(repo) == bool(package):
        raise ToolError("give exactly one of repo or package")
    if package:
        g = graph()
        require_incident(g, incident_id)
        return package_exposure(g, incident_id, package, Affected.load(g, incident_id))
    assert repo is not None
    g = graph()
    require_incident(g, incident_id)
    key = known_repo(g, repo)
    affected = Affected.load(g, incident_id)
    hit = rows(g, "repo_exposed", {"repo": key, "incident": incident_id})[0]
    exposed = hit["hop"] is not None
    st = _repo_status(g, incident_id, key, affected, exposed)
    paths: list[dict[str, Any]] = []
    via = _exposure_path(g, incident_id, key, affected) if exposed else None
    cross = None
    if via:
        paths.append(via)
        cross = cross_check_path(g, incident_id, key, via["nodes"][-1])
        if cross and cross["id"] != via["id"]:
            paths.append(cross)
    per_package = []
    for p in st["paths_by_package"]:
        if all(p["id"] != q["id"] for q in paths):
            paths.append({k: p[k] for k in ("id", "nodes", "edges")})
        per_package.append(
            {
                "package": p["package"],
                "path_id": p["id"],
                "hops": len(p["edges"]),
                "mitigated": p["mitigated"],
            }
        )
    result = {
        "repo": key.removeprefix("repo:"),
        "exposed": exposed,
        "status": st["status"],
        "status_meaning": STATUS_MEANING[st["status"]],
        "hop": hit["hop"],
        "path_id": via["id"] if via else None,
        "shortest_path_check": (
            {"path_id": cross["id"], "same_length": len(cross["nodes"]) == len(via["nodes"])}
            if cross and via
            else None
        ),
        "per_package": per_package,
        **anchor(),
    }
    return (
        result,
        paths,
        {
            "repo": result["repo"],
            "path_len": len(via["edges"]) if via else 0,
            "packages": len(per_package),
        },
    )


@tool
def repo_status(incident_id: str, repo: str | None = None):
    """Returns the status of one repo or of every repo. The status uses the lockfile and the overrides."""
    g = graph()
    require_incident(g, incident_id)
    affected = Affected.load(g, incident_id)
    keys = [known_repo(g, repo)] if repo else [r["key"] for r in rows(g, "repo_keys")]
    out, paths = [], []
    for key in keys:
        hit = rows(g, "repo_exposed", {"repo": key, "incident": incident_id})[0]
        st = _repo_status(g, incident_id, key, affected, hit["hop"] is not None)
        for p in st["paths_by_package"]:
            paths.append({k: p[k] for k in ("id", "nodes", "edges")})
        out.append(
            {
                "repo": key.removeprefix("repo:"),
                "status": st["status"],
                "status_meaning": STATUS_MEANING[st["status"]],
                "has_lockfile": st["has_lockfile"],
                "locked_affected": st["locked_affected"],
                "affected_packages": st["affected_packages"],
                "mitigated_packages": st["mitigated_packages"],
                "path_ids": {p["package"]: p["id"] for p in st["paths_by_package"]},
            }
        )
    counts: dict[str, int] = {}
    for r in out:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"repos": out, **anchor()}, paths, {"repos": len(out), **{k.lower(): v for k, v in counts.items()}}


@tool
def critical_packages(k: int = 10, algorithm: str = "pagerank"):
    """Returns the critical packages by the stored algo.pageRank or algo.betweenness scores."""
    if algorithm not in ("pagerank", "betweenness"):
        raise ToolError("algorithm must be 'pagerank' or 'betweenness'")
    g = graph()
    k = max(1, min(int(k), 100))
    top = rows(g, "critical_packages", {"k": k, "order": algorithm})
    if not top:
        raise ToolError("no centrality scores stored: run `python -m analysis.algorithms`")
    query("algo_pagerank" if algorithm == "pagerank" else "algo_betweenness")  # the query behind the scores
    result = {
        "algorithm": algorithm,
        "projection": "(Package)-[:PKG_DEPENDS_ON]->(Package), resolved at S",
        "packages": top,
    }
    return result, [], {"algorithm": algorithm, "k": k, "top": top[0]["package"]}


@tool
def maintainer_reach(k: int = 10):
    """Returns the npm accounts whose takeover would reach the most packages and downloads."""
    g = graph()
    k = max(1, min(int(k), 100))
    top = rows(g, "maintainer_reach_top", {"k": k})
    if not top:
        raise ToolError("no maintainer reach stored: run `python -m analysis.algorithms`")
    result = {
        "note": "ecosystem concentration risk, not a judgement of any individual",
        "definition": (
            "reach = packages that transitively depend on any package the account maintains "
            "(PKG_DEPENDS_ON at S, own packages included), and their summed weekly downloads"
        ),
        "maintainers": top,
    }
    return result, [], {"k": k, "top_reach": top[0]["reach_packages"]}


# -- plans ---------------------------------------------------------------------------------------


def checkout_dir(full_name: str) -> Path:
    from ingest.repo_seeds import REPOS_DIR

    d = REPOS_DIR / full_name
    if not (d / "package.json").exists():
        raise ToolError(f"no checkout for {full_name}: run `python -m ingest.repo_seeds`")
    return d


@tool
def plan_fix(repo: str, incident_id: str):
    """Makes a minimal override plan for one repo and stores it as a PENDING Plan."""
    g = graph()
    require_incident(g, incident_id)
    key = known_repo(g, repo)
    full = key.removeprefix("repo:")
    manifest = json.loads((checkout_dir(full) / "package.json").read_text())
    body = fixplan.plan_repo(g, incident_id, key, manifest)
    plan_id = fixplan.store(g, body)
    plan = fixplan.load(g, plan_id)
    assert plan is not None
    result = {
        "plan_id": plan_id,
        "plan_status": plan["status"],
        "repo": full,
        "status_before": body["status_before"],
        "fixable": body["fixable"],
        "changes": body["changes"],
        "packages": [
            {k: p[k] for k in ("package", "strategy", "version", "scoped", "reason") if p[k]}
            | {"requirements_on_paths": sorted({r["requirement"] for r in p["requirements"]})}
            for p in body["packages"]
        ],
        "path_ids": {p["package"]: p["id"] for p in body["paths"]},
        "next_step": (
            "call request_fix_approval with this plan_id; a human approves it in the console"
            if plan["status"] == fixplan.PENDING
            else "nothing to apply"
        ),
        **anchor(),
    }
    paths = [{k: p[k] for k in ("id", "nodes", "edges")} for p in body["paths"]]
    return result, paths, {"plan": plan_id, "repo": full, "fixable": body["fixable"]}


@tool
def request_fix_approval(plan_id: str):
    """Sets a plan to AWAITING_APPROVAL, and the console shows the approval card.
    This tool cannot apply the plan."""
    g = graph()
    plan = fixplan.load(g, plan_id)
    if plan is None:
        raise ToolError(f"unknown plan {plan_id!r}")
    if plan["status"] == fixplan.AWAITING_APPROVAL:
        moved = True
    elif plan["status"] != fixplan.PENDING:
        raise ToolError(f"plan {plan_id} is {plan['status']}; only a PENDING plan can request approval")
    else:
        moved = fixplan.transition(g, plan_id, [fixplan.PENDING], fixplan.AWAITING_APPROVAL)
    result = {
        "plan_id": plan_id,
        "plan_status": fixplan.AWAITING_APPROVAL if moved else plan["status"],
        "repo": plan["repo"].removeprefix("repo:"),
        "message": "The fix awaits human approval in the Fallout console. The agent cannot apply it.",
    }
    return result, [], {"plan": plan_id, "repo": result["repo"], "status": result["plan_status"]}


# -- recheck -------------------------------------------------------------------------------------


def fetch_ref(full_name: str, ref: str) -> tuple[Path, str]:
    """Exports `ref` of a public demo repo into a temporary directory. It uses no token, because the
    demo repos are public and the LLM can call this tool. Returns (dir, commit sha)."""
    src = checkout_dir(full_name)
    subprocess.run(["git", "-C", str(src), "fetch", "-q", "origin", ref], check=True, timeout=60)
    sha = subprocess.run(
        ["git", "-C", str(src), "rev-parse", "FETCH_HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    out = Path(tempfile.mkdtemp(prefix="fallout-recheck-"))
    arch = subprocess.run(["git", "-C", str(src), "archive", sha], capture_output=True, check=True).stdout
    tar_path = out / ".archive.tar"
    tar_path.write_bytes(arch)
    with tarfile.open(tar_path) as t:
        t.extractall(out, filter="data")
    tar_path.unlink()
    return out, sha


def snapshot_status(g: Any, incident: str, key: str) -> dict[str, Any]:
    hit = rows(g, "repo_exposed", {"repo": key, "incident": incident})[0]
    return {"status": hit["status"] or NOT_AFFECTED, "hop": hit["hop"]}


@tool
def recheck_repo(repo: str, incident_id: str, branch: str | None = None):
    """Parses a repo (or a PR branch) again, replaces its LOCKS and OVERRIDES edges, recomputes
    its status and returns the status before and after."""
    from ingest.load_repos import load_repo

    g = graph()
    require_incident(g, incident_id)
    key = known_repo(g, repo)
    full = key.removeprefix("repo:")
    affected = Affected.load(g, incident_id)
    hit = rows(g, "repo_exposed", {"repo": key, "incident": incident_id})[0]
    before = _repo_status(g, incident_id, key, affected, hit["hop"] is not None)
    before_edge = snapshot_status(g, incident_id, key)

    if branch:
        repo_dir, sha = fetch_ref(full, branch)
    else:
        repo_dir, sha = checkout_dir(full), None
    load_repo(g, full, repo_dir)
    g.query(query("repo_ref_set"), {"key": key, "ref": branch or "local", "sha": sha})
    recompute_repo_edges(g, incident_id, key)

    src = rows(g, "repo_exposure_source", {"repo": key, "incident": incident_id})[0]
    if src["direct_hits"]:
        hop, via = 1, sorted(src["direct_hits"])[0]
    elif src["deps"]:
        best = min(src["deps"], key=lambda d: (d["hop"], d["via"]))
        hop, via = best["hop"] + 1, best["via"]
    else:
        hop, via = None, None
    after = _repo_status(g, incident_id, key, affected, hop is not None)
    g.query(
        query("repo_exposes_set"),
        {
            "incident": incident_id,
            "repo": key,
            "hop": hop,
            "via": via,
            "status": after["status"],
            "now": int(time.time() * 1000),
        },
    )

    def view(st: dict[str, Any]) -> dict[str, Any]:
        return {k: st[k] for k in ("status", "affected_packages", "mitigated_packages", "locked_affected")}

    result = {
        "repo": full,
        "ref": branch or "local checkout",
        "commit": sha,
        "before": {**view(before), "hop": before_edge["hop"]},
        "after": {**view(after), "hop": hop},
        "changed": before["status"] != after["status"],
        "status_meaning": STATUS_MEANING[after["status"]],
        **anchor(),
    }
    paths = [{k: p[k] for k in ("id", "nodes", "edges")} for p in after["paths_by_package"]]
    return result, paths, {"repo": full, "before": before["status"], "after": after["status"]}


TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    f.__name__: f
    for f in (
        ingest_advisory,
        blast_radius,
        exposure_path,
        repo_status,
        critical_packages,
        maintainer_reach,
        plan_fix,
        request_fix_approval,
        recheck_repo,
    )
}
