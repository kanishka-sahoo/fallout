"""Clone the demo org and turn every manifest into crawl seeds (BUILD.md §5.5 step 2).

Runs before the crawl so no repo direct dependency is left uncrawled. Reads the root and
workspace package.json files: dependencies, devDependencies and overrides specs.

    uv run python -m ingest.repo_seeds
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from fallout.repo import manifests, parse_overrides
from fallout.settings import RAW_DIR, ROOT, SETTINGS

REPOS_DIR = RAW_DIR / "repos"
REPO_SEEDS_PATH = RAW_DIR / "repo_seeds.json"


def git_auth_args() -> list[str]:
    """Pass the token as a one-off header so it is never written to .git/config."""
    load_dotenv(ROOT / ".env")
    token = os.environ["FALLOUT_GH_TOKEN"]
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]


def sync_repo(full_name: str) -> Path:
    dest = REPOS_DIR / full_name
    if (dest / ".git").exists():
        subprocess.run(["git", *git_auth_args(), "-C", str(dest), "pull", "-q", "--ff-only"], check=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{full_name}.git"
        subprocess.run(["git", *git_auth_args(), "clone", "-q", url, str(dest)], check=True)
    return dest


def repo_seed_pairs(repo_dir: Path) -> list[dict[str, str]]:
    paths = manifests(repo_dir)
    docs = [json.loads(p.read_text()) for p in paths]
    internal = {d.get("name") for d in docs}  # workspace packages are not registry deps
    pairs = []
    for d in docs:
        for field, scope in (("dependencies", "prod"), ("devDependencies", "dev")):
            for name, spec in d.get(field, {}).items():
                if name not in internal:
                    pairs.append({"name": name, "range": spec, "source": scope})
        for o in parse_overrides(d):
            pairs.append({"name": o.name, "range": o.spec, "source": "override"})
    return pairs


def main() -> None:
    out = {}
    for full_name in SETTINGS["allowed_repos"]:
        pairs = repo_seed_pairs(sync_repo(full_name))
        out[full_name] = pairs
        print(f"{full_name}: {len(pairs)} seed pairs")
    REPO_SEEDS_PATH.write_text(json.dumps(out, indent=1))
    print(f"-> {REPO_SEEDS_PATH}")


if __name__ == "__main__":
    main()
