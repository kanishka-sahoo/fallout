"""fallout-tools: the BUILD.md §6.2 tools over MCP (stdio).

Thin wrappers over fallout/tools.py. Every tool returns the §6.1 envelope
`{result, paths, cypher, timing_ms, summary}`. There is deliberately no `apply_fix` here: a
fix reaches GitHub only through the console's Approve button (api/approval.py), and
tests/test_approval.py asserts this list never grows a GitHub-writing tool.

    uv run python -m mcp_server.server          # stdio; also works from Claude Desktop / Code
"""

from __future__ import annotations

from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer

from fallout import tools

server = MCPServer(
    "fallout-tools",
    instructions=(
        "npm supply-chain incident tools over a FalkorDB graph anchored at time S. Exposure, path, "
        "ranking and fix answers must come only from these tools; cite the path ids they return."
    ),
)


async def _run(name: str, **kwargs: Any) -> dict[str, Any]:
    # The tools block on FalkorDB and spawn Node workers; keep them off the event loop.
    return await anyio.to_thread.run_sync(lambda: tools.TOOLS[name](**kwargs))


@server.tool()
async def ingest_advisory(incident_id: str, advisory_ids: list[str] | None = None) -> dict[str, Any]:
    """Ingest OSV advisories into an incident: creates the malicious/affected Version nodes and
    computes which dependents would resolve to them (CAN_RESOLVE_TO). With no advisory_ids, the
    incident's configured advisory list is used. Write tool."""
    return await _run("ingest_advisory", advisory_ids=advisory_ids, incident_id=incident_id)


@server.tool()
async def blast_radius(incident_id: str, max_hops: int = 16) -> dict[str, Any]:
    """Multi-hop reverse BFS from the incident's affected versions: exposed versions per hop,
    every repo's status and exposure path id, and the top exposed packages by downloads.
    Persists the result; run it before exposure_path / repo_status / plan_fix."""
    return await _run("blast_radius", incident_id=incident_id, max_hops=max_hops)


@server.tool()
async def exposure_path(
    incident_id: str, repo: str | None = None, package: str | None = None
) -> dict[str, Any]:
    """Exact chain target -> ... -> affected version with the semver requirement on every hop.
    Target: a repo (cross-checked with shortestPath, plus one path per affected package it
    reaches), or a package: `name` (its version at S) or `name@version`. Give exactly one."""
    return await _run("exposure_path", incident_id=incident_id, repo=repo, package=package)


@server.tool()
async def repo_status(incident_id: str, repo: str | None = None) -> dict[str, Any]:
    """Lockfile- and override-aware status for one repo (or all): LOCKED_MALICIOUS,
    EXPOSED_NO_LOCKFILE, RANGE_ADMITS_LOCK_SAFE, MITIGATED_BY_OVERRIDE or NOT_AFFECTED."""
    return await _run("repo_status", incident_id=incident_id, repo=repo)


@server.tool()
async def critical_packages(k: int = 10, algorithm: str = "pagerank") -> dict[str, Any]:
    """Ecosystem chokepoint packages by algo.pageRank or algo.betweenness over the package
    dependency projection at S. algorithm: 'pagerank' | 'betweenness'."""
    return await _run("critical_packages", k=k, algorithm=algorithm)


@server.tool()
async def maintainer_reach(k: int = 10) -> dict[str, Any]:
    """npm accounts whose takeover would reach the most packages and weekly downloads
    (concentration risk, not criticism of individuals)."""
    return await _run("maintainer_reach", k=k)


@server.tool()
async def plan_fix(repo: str, incident_id: str) -> dict[str, Any]:
    """Build a minimal remediation plan (npm overrides / pins to the highest safe version at S)
    for one repo and store it as a PENDING plan. Read-only on the repo; returns a plan_id."""
    return await _run("plan_fix", repo=repo, incident_id=incident_id)


@server.tool()
async def request_fix_approval(plan_id: str) -> dict[str, Any]:
    """Ask a human to approve a PENDING plan: marks it AWAITING_APPROVAL and shows an approval
    card in the console. This cannot apply the fix; only the human's Approve click can."""
    return await _run("request_fix_approval", plan_id=plan_id)


@server.tool()
async def recheck_repo(repo: str, incident_id: str, branch: str | None = None) -> dict[str, Any]:
    """Re-parse a repo (or one of its branches, e.g. a fix PR), replace its lockfile and override
    edges, recompute its status and return the before/after diff."""
    return await _run("recheck_repo", repo=repo, incident_id=incident_id, branch=branch)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
