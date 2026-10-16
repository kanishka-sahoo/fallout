"""Open a fix PR through the GitHub REST API (BUILD.md §6.3 step 4).

Git data API only (blobs -> tree -> commit -> ref -> pull), so the token never touches a git
checkout or `.git/config`. The token is a fine-grained PAT scoped to the demo org (contents +
pull requests) and is read from FALLOUT_GH_TOKEN by the API process only; the MCP server
and the sandbox never receive it.
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
