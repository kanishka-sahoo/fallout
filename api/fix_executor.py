"""apply_fix is the only code path from a plan to GitHub. The API calls it after a person clicks
Approve. It is not an MCP tool.

    1. Check the token (HMAC, expiry, single use), the repo allowlist, and that the plan
       is still AWAITING_APPROVAL.
    2. In the sandbox, run npm install --package-lock-only --ignore-scripts --before=S.
       The sandbox has no secrets.
    3. Check that no locked version is in the incident's affected set.
    4. Open a PR through the GitHub API. The body has the advisories, the graph paths,
       the rationale and the verification result.
    5. Write an Action node (ON the repo, REMEDIATES the incident), then run recheck_repo
       on the PR branch.
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
from fallout.simulate import is_simulated
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


def advisory_link(a: dict[str, Any]) -> str:
    return f"[{a['id']}]({a['url']})" if a.get("url") else str(a["id"])


def pr_body(plan: dict[str, Any], advisories: list[dict[str, Any]], verification: dict[str, Any]) -> str:
    body = plan["body"]
    out = [
        f"## Fallout: remediation for `{body['incident']}`",
        "",
        *(
            [
                "> **Simulated scenario.** This change blocks versions from a what-if attack that "
                "was modelled in the Fallout console. The overrides apply only if those versions "
                "are ever published.",
                "",
            ]
            if is_simulated(body["incident"])
            else []
        ),
        f"Status before this change: **{body['status_before']}**.",
        "",
        f"Snapshot time S: `{body['anchor_S']}`. The dependency graph and version resolution use the "
        "npm registry as it was at S, one second before the first malicious version was published.",
        "",
        "### Advisories",
        *[f"- {advisory_link(a)}: `{a['package']}@{a['version']}`" for a in advisories],
        "",
        "### Why this repo is exposed",
        "",
        "Each path goes from this repo to an affected version. Each hop shows the edge type and "
        "the version requirement.",
    ]
    for p in body["paths"]:
        out += ["", f"**{p['package']}** (`{p['id']}`)", "", render_path(p)]
    out += ["", "### Change", "", "```json", json.dumps(body["changes"], indent=2), "```", ""]
    out += ["### Rationale", ""]
    for p in body["packages"]:
        reqs = ", ".join(f"`{r}`" for r in sorted({r["requirement"] for r in p["requirements"]}))
        if p["strategy"] == "selector":
            why = (
                f"A version-specific override changes the affected version to `{p['version']}`. "
                f"This is the highest safe version, published at or before S, that satisfies {reqs}."
            )
        elif p["strategy"] == "pin":
            why = (
                f"The direct dependency is pinned to `{p['version']}`. This is the highest safe "
                "version in its range, published at or before S."
            )
        else:
            scoped = ", ".join(f"`{k}` → `{v}`" for k, v in p["scoped"].items())
            why = f"Nested overrides: {scoped}. No single safe version satisfies {reqs}."
        out.append(f"- `{p['package']}`: {why}")
    v = verification
    out += [
        "",
        "### Verification",
        "",
        "The install ran in a sandbox container with no secrets.",
        "",
        f"- Command: `{v['command']}`",
        f"- Exit code {v['exit_code']}, {v['took_ms']} ms, {v['locked_count']} packages locked.",
        f"- Affected versions in the new lockfile: **{len(v['affected_found'])}**"
        + (f" ({', '.join(v['affected_found'])})" if v["affected_found"] else ""),
        f"- Locked versions of the incident's packages: {', '.join(v['checked_versions']) or 'none'}",
    ]
    if v.get("pruned"):
        out.append(f"- Lockfile entries at affected versions, removed before the install: {v['pruned']}")
    out += ["", f"Plan `{plan['id']}` was approved in the Fallout console. Fallout opened this pull request."]
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
                title=(
                    f"fix(deps): block simulated malicious versions of {', '.join(pkgs)} ({incident})"
                    if is_simulated(incident)
                    else f"fix(deps): remove malicious versions of {', '.join(pkgs)} ({incident})"
                ),
                body=pr_body(plan, advisories, v),
                message=f"fix(deps): remediate {incident}\n\nFallout plan {plan_id}, verified in a sandbox.",
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
        recheck_everywhere(full, pr.branch, skip=incident)
        emit(
            "recheck",
            source="fallout-api",
            plan=plan_id,
            repo=full,
            before=recheck["result"].get("before", {}).get("status"),
            after=recheck["result"].get("after", {}).get("status"),
        )
    return out


def recheck_everywhere(full: str, branch: str | None, skip: str | None = None) -> list[str]:
    """Every incident reads the same LOCKS and OVERRIDES edges of a repo. After the repo is loaded
    from another branch, this rechecks it for each incident that holds a status for it.
    `branch=None` loads the default branch from the local checkout."""
    g = graph()
    done = []
    for r in rows(g, "repo_incidents", {"repo": f"repo:{full}"}):
        if r["incident"] != skip:
            recheck_repo(full, r["incident"], branch=branch)
            done.append(r["incident"])
    if branch is None and not done:
        recheck_repo(full, SETTINGS["replay_incident"])  # still reload the checkout
    return done
