"""Opens a fix PR through the GitHub REST API.

This module uses only the Git Data API (blob, tree, commit, ref, pull request). The token is
never written to a git checkout or to `.git/config`. The token is a fine-grained personal access
token for the demo org, with the "contents" and "pull requests" permissions. Only the API process
reads it, from FALLOUT_GH_TOKEN. The MCP server and the sandbox do not get the token.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

from fallout.settings import ROOT, SETTINGS

API = "https://api.github.com"


class RepoNotAllowed(Exception):
    pass


@dataclass
class PullRequest:
    url: str
    number: int
    branch: str
    commit: str


def client() -> httpx.Client:
    load_dotenv(ROOT / ".env")
    token = os.environ.get("FALLOUT_GH_TOKEN")
    if not token:
        raise RuntimeError("FALLOUT_GH_TOKEN is not set")
    return httpx.Client(
        base_url=API,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"fallout ({SETTINGS['contact_email']})",
        },
        timeout=30,
    )


def open_pr(
    full_name: str, branch: str, files: dict[str, str], title: str, body: str, message: str
) -> PullRequest:
    if full_name not in SETTINGS["allowed_repos"]:
        raise RepoNotAllowed(f"{full_name} is not in config.allowed_repos")
    with client() as gh:
        repo = gh.get(f"/repos/{full_name}").raise_for_status().json()
        base = repo["default_branch"]
        head = gh.get(f"/repos/{full_name}/git/ref/heads/{base}").raise_for_status().json()["object"]["sha"]
        base_tree = gh.get(f"/repos/{full_name}/git/commits/{head}").raise_for_status().json()["tree"]["sha"]
        tree = []
        for path, content in files.items():
            blob = gh.post(
                f"/repos/{full_name}/git/blobs", json={"content": content, "encoding": "utf-8"}
            ).raise_for_status()
            tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob.json()["sha"]})
        new_tree = (
            gh.post(f"/repos/{full_name}/git/trees", json={"base_tree": base_tree, "tree": tree})
            .raise_for_status()
            .json()["sha"]
        )
        commit = (
            gh.post(
                f"/repos/{full_name}/git/commits",
                json={"message": message, "tree": new_tree, "parents": [head]},
            )
            .raise_for_status()
            .json()["sha"]
        )
        gh.post(
            f"/repos/{full_name}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit}
        ).raise_for_status()
        pr = (
            gh.post(
                f"/repos/{full_name}/pulls", json={"title": title, "head": branch, "base": base, "body": body}
            )
            .raise_for_status()
            .json()
        )
    return PullRequest(pr["html_url"], pr["number"], branch, commit)


def parse_pr_url(url: str) -> tuple[str, int]:
    """Returns (owner/repo, number) for https://github.com/owner/repo/pull/N."""
    parts = url.removeprefix("https://github.com/").split("/")
    if len(parts) != 4 or parts[2] != "pull" or not parts[3].isdigit():
        raise ValueError(f"not a pull request URL: {url}")
    return f"{parts[0]}/{parts[1]}", int(parts[3])


def close_pr(url: str) -> dict[str, str]:
    """Closes a Fallout PR and deletes its branch. Only repos on the allowlist, only fallout/ branches."""
    full, number = parse_pr_url(url)
    if full not in SETTINGS["allowed_repos"]:
        raise RepoNotAllowed(f"{full} is not in config.allowed_repos")
    with client() as gh:
        pr = gh.get(f"/repos/{full}/pulls/{number}").raise_for_status().json()
        branch = pr["head"]["ref"]
        if not branch.startswith("fallout/"):
            raise RepoNotAllowed(f"{url} is not a Fallout branch ({branch})")
        if pr["state"] == "open":
            gh.patch(f"/repos/{full}/pulls/{number}", json={"state": "closed"}).raise_for_status()
        gone = gh.delete(f"/repos/{full}/git/refs/heads/{branch}")
        if gone.status_code not in (204, 404, 422):  # 404/422: the branch is already gone
            gone.raise_for_status()
    _states.pop(url, None)
    return {"repo": full, "number": str(number), "branch": branch}


_states: dict[str, tuple[float, str]] = {}  # url -> (fetched at, state)


def pr_states(urls: list[str], ttl: float = 30.0) -> dict[str, str]:
    """Returns open, closed or merged for each PR URL. Results are cached for `ttl` seconds."""
    import time

    now = time.monotonic()
    out = {u: s for u, (t, s) in _states.items() if u in urls and now - t < ttl}
    todo = [u for u in urls if u not in out]
    if todo:
        with client() as gh:
            for u in todo:
                try:
                    full, number = parse_pr_url(u)
                    pr = gh.get(f"/repos/{full}/pulls/{number}").raise_for_status().json()
                    state = "merged" if pr.get("merged_at") else pr["state"]
                except (ValueError, httpx.HTTPError):
                    state = "unknown"
                _states[u] = (now, state)
                out[u] = state
    return out
