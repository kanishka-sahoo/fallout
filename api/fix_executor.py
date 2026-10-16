"""apply_fix: the only path from a plan to GitHub (BUILD.md §6.3). Called by the API right
after a human clicks Approve; never exposed as an MCP tool.

    verify token (HMAC, expiry, single use) + allowlist + plan still AWAITING_APPROVAL
    -> sandbox: npm install --package-lock-only --ignore-scripts --before=S (no secrets)
    -> verify: no locked version is in the incident's affected set
    -> PR through the GitHub API, body = advisory + graph paths + rationale + verification
    -> Action node (ON repo, REMEDIATES incident) -> recheck_repo on the PR branch
"""

from __future__ import annotations

import json
import secrets
import shutil
import time
from collections.abc import Callable
from typing import Any

from api import approval
from api.github_pr import open_pr
from fallout import fixplan, sandbox
from fallout.blast import Affected
from fallout.db import graph, query, rows
from fallout.settings import SETTINGS, load_anchor
from fallout.tools import checkout_dir, recheck_repo

Emit = Callable[..., Any]


class FixRejected(Exception):
    pass


def _noop(*_: Any, **__: Any) -> None:
    return None


def render_path(p: dict[str, Any]) -> str:
    lines = [f"`{p['nodes'][0].removeprefix('repo:')}`"]
    for node, edge in zip(p["nodes"][1:], p["edges"], strict=True):
        name = node.removeprefix("npm:")
        lines.append(f"  → `{name}` &nbsp;(*{edge['type']}* `{edge.get('requirement')}`)")
    return "<br>\n".join(lines)


def pr_body(plan: dict[str, Any], advisories: list[dict[str, Any]], verification: dict[str, Any]) -> str:
    body = plan["body"]
    out = [
        f"## Fallout: remediate `{body['incident']}`",
        "",
        f"Status before: **{body['status_before']}**. Anchor S = `{body['anchor_S']}` "
        "(npm graph and resolution as of just before the first malicious publish).",
        "",
        "### Advisories",
        *[f"- [{a['id']}]({a['url']}): `{a['package']}@{a['version']}`" for a in advisories],
        "",
        "### Why this repo is exposed (graph paths, requirement on every hop)",
    ]
    for p in body["paths"]:
        out += ["", f"**{p['package']}** (`{p['id']}`)", "", render_path(p)]
    out += ["", "### Change", "", "```json", json.dumps(body["changes"], indent=2), "```", ""]
    for p in body["packages"]:
        reqs = ", ".join(f"`{r}`" for r in sorted({r["requirement"] for r in p["requirements"]}))
        if p["strategy"] == "selector":
            why = (
                f"override every edge whose range admits the affected version with `{p['version']}`, "
                f"the highest safe version published ≤ S that satisfies {reqs}"
            )
        elif p["strategy"] == "pin":
            why = f"pin the direct dependency to `{p['version']}` (highest safe version ≤ S in its range)"
        else:
            scoped = ", ".join(f"`{k}` → `{v}`" for k, v in p["scoped"].items())
            why = f"scoped overrides {scoped} (no single safe version satisfies {reqs})"
        out.append(f"- `{p['package']}`: {why}")
    v = verification
    out += [
        "",
        "### Verification (sandbox, no secrets mounted)",
        "",
        f"`{v['command']}` → exit {v['exit_code']} in {v['took_ms']} ms; "
        f"{v['locked_count']} packages locked.",
        f"Affected versions in the new lockfile: **{len(v['affected_found'])}**"
        + (f" ({', '.join(v['affected_found'])})" if v["affected_found"] else ""),
        f"Locked versions of the incident's packages: {', '.join(v['checked_versions']) or 'none'}",
    ]
    if v.get("pruned"):
        out.append(f"Lockfile entries at affected versions removed before the install: {v['pruned']}")
    out += ["", f"Plan `{plan['id']}`, approved in the Fallout console. Opened by Fallout."]
    return "\n".join(out)


def apply_fix(plan_id: str, repo: str, token: str, approved_by: str, emit: Emit = _noop) -> dict[str, Any]:
    g = graph()
    try:
        approval.verify(token, plan_id, repo)
    except approval.ApprovalError as e:
        raise FixRejected(str(e)) from e
    full = repo.removeprefix("repo:")
    if full not in SETTINGS["allowed_repos"]:
        raise FixRejected(f"{full} is not in config.allowed_repos")
    plan = fixplan.load(g, plan_id)
    if plan is None or plan["repo"] != repo:
        raise FixRejected("plan not found for this repo")
    if not fixplan.transition(g, plan_id, [fixplan.AWAITING_APPROVAL], fixplan.APPLYING):
        raise FixRejected(f"plan is {plan['status']}, not AWAITING_APPROVAL")

    incident, S = plan["incident"], load_anchor()["S"]
    affected = Affected.load(g, incident)
    bad = {tuple(k.removeprefix("npm:").rsplit("@", 1)) for k in affected.keys}
    checkout = checkout_dir(full)
    manifest = json.loads((checkout / "package.json").read_text())
    new_manifest = fixplan.apply_changes(manifest, plan["body"]["changes"])

    emit("sandbox", source="fallout-api", plan=plan_id, repo=full, step="npm install --package-lock-only")
    work, ver = sandbox.run(checkout, new_manifest, S, bad)  # type: ignore[arg-type]
    v = ver.as_dict()
    emit(
        "verify",
        source="fallout-api",
        level="INFO" if ver.ok else "ERROR",
        plan=plan_id,
        repo=full,
        ok=ver.ok,
        affected_found=len(ver.affected_found),
        locked=ver.locked_count,
        took_ms=ver.took_ms,
    )
    action_id = "act_" + secrets.token_hex(4)
    now = int(time.time() * 1000)
    pr = None
    try:
        if not ver.ok:
            fixplan.transition(g, plan_id, [fixplan.APPLYING], fixplan.FAILED)
            result = "VERIFICATION_FAILED"
        else:
            pkgs = [p["package"] for p in plan["body"]["packages"]]
            advisories = rows(g, "incident_advisories", {"incident": incident, "packages": pkgs})
            files = {
                "package.json": json.dumps(new_manifest, indent=2) + "\n",
                "package-lock.json": (work / "package-lock.json").read_text(),
            }
            branch = f"fallout/{incident[:40]}-{plan_id}"
            pr = open_pr(
                full,
                branch,
                files,
                title=f"fix(deps): override {', '.join(pkgs)} away from {incident} malicious versions",
                body=pr_body(plan, advisories, v),
                message=f"fix(deps): remediate {incident}\n\nFallout plan {plan_id}; verified in sandbox.",
            )
            emit("pr", source="fallout-api", plan=plan_id, repo=full, pr=pr.url)
            result = "PR_OPENED"
    except Exception:
        fixplan.transition(g, plan_id, [fixplan.APPLYING], fixplan.FAILED)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)

    g.query(
        query("action_create"),
        {
            "id": action_id,
            "repo": repo,
            "incident": incident,
            "type": "OPEN_PR",
            "now": now,
            "approved_by": approved_by,
            "plan_id": plan_id,
            "pr_url": pr.url if pr else None,
            "verification": json.dumps(v),
            "result": result,
        },
    )
    out: dict[str, Any] = {
        "action_id": action_id,
        "result": result,
        "verification": v,
        "pr_url": pr and pr.url,
    }
    if pr:
        fixplan.transition(g, plan_id, [fixplan.APPLYING], fixplan.APPLIED)
        recheck = recheck_repo(full, incident, branch=pr.branch)
        out["recheck"] = recheck
        emit(
            "recheck",
            source="fallout-api",
            plan=plan_id,
            repo=full,
            before=recheck["result"].get("before", {}).get("status"),
            after=recheck["result"].get("after", {}).get("status"),
        )
    return out
