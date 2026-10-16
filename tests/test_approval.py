"""Approval tests. The executor rejects forged, expired, reused and wrong-repo tokens. It refuses a
repo that is not on the allowlist. No tool that the LLM can see can open a PR."""

import asyncio
import subprocess
import sys

import pytest

from api import approval
from api.fix_executor import FixRejected, apply_fix

PLAN, REPO = "pl_test01", "repo:fallout-demo/billing-api"


def test_fresh_token_verifies_once() -> None:
    used = approval.UsedTokens()
    tok = approval.mint(PLAN, REPO)
    approval.verify(tok, PLAN, REPO, used=used)
    with pytest.raises(approval.ApprovalError, match="already used"):
        approval.verify(tok, PLAN, REPO, used=used)


@pytest.mark.parametrize(
    ("token", "plan", "repo", "match"),
    [
        ("9999999999." + "0" * 64, PLAN, REPO, "bad signature"),  # forged
        (None, PLAN, "repo:fallout-demo/cli-tool", "bad signature"),  # issued for another repo
        (None, "pl_other", REPO, "bad signature"),  # issued for another plan
        ("garbage", PLAN, REPO, "malformed"),
    ],
)
def test_rejects_bad_tokens(token: str | None, plan: str, repo: str, match: str) -> None:
    tok = token or approval.mint(PLAN, REPO)
    with pytest.raises(approval.ApprovalError, match=match):
        approval.verify(tok, plan, repo, used=approval.UsedTokens())


def test_rejects_expired_token() -> None:
    tok = approval.mint(PLAN, REPO, now=1_000_000)
    with pytest.raises(approval.ApprovalError, match="expired"):
        approval.verify(tok, PLAN, REPO, now=1_000_000 + approval.TTL_S + 1, used=approval.UsedTokens())


def test_executor_rejects_forged_token_and_foreign_repo() -> None:
    with pytest.raises(FixRejected, match="bad signature"):
        apply_fix(PLAN, REPO, "1." + "0" * 64, "test")
    foreign = "repo:someone-else/project"
    with pytest.raises(FixRejected, match="allowed_repos"):
        apply_fix(PLAN, foreign, approval.mint(PLAN, foreign), "test")


def test_open_pr_refuses_foreign_repo() -> None:
    from api.github_pr import RepoNotAllowed, open_pr

    with pytest.raises(RepoNotAllowed):
        open_pr("someone-else/project", "b", {}, "t", "b", "m")


EXPECTED_TOOLS = {
    "ingest_advisory",
    "blast_radius",
    "exposure_path",
    "repo_status",
    "critical_packages",
    "maintainer_reach",
    "plan_fix",
    "request_fix_approval",
    "recheck_repo",
}


def test_mcp_tool_list_has_no_github_writer() -> None:
    from mcp import Client

    from mcp_server.server import server

    async def names() -> set[str]:
        async with Client(server) as c:
            return {t.name for t in (await c.list_tools()).tools}

    got = asyncio.run(names())
    assert got == EXPECTED_TOOLS
    assert not any("apply" in n or n.split("_")[0] == "pr" or "merge" in n for n in got)


def test_tool_server_never_imports_github_or_executor() -> None:
    code = (
        "import sys, mcp_server.server, fallout.tools;"
        "bad = [m for m in ('api.github_pr', 'api.fix_executor', 'api.approval') if m in sys.modules];"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
