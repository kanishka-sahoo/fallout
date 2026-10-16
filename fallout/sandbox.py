"""Lockfile sandbox and verification.

The checkout is copied into a temporary directory without `.git`, and the plan's manifest
replaces package.json. An ephemeral `fallout-sandbox` container (workers/sandbox/Dockerfile)
then runs `npm install --package-lock-only --ignore-scripts --before=<S>` in it as the
unprivileged `node` user. The container gets no other mounts and no environment variables, so
no token can get into the install. The new lockfile is parsed with the same code as
load_repos and checked against the incident's affected set.

Lockfile entries at an affected version are removed before the install. If a locked node
still satisfies an edge, npm keeps it and does not apply the overrides to it. The
LOCKED_MALICIOUS fixture showed this: the hoisted `debug@4.4.2` stayed after
`"debug@4.4.2": "4.4.1"` was added. Removing the entries makes npm resolve those nodes again.
Only v2 and v3 lockfiles are pruned.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fallout.repo import locked_packages

IMAGE = os.environ.get("FALLOUT_SANDBOX_IMAGE", "fallout-sandbox")
DOCKERFILE_DIR = Path(__file__).resolve().parent.parent / "workers" / "sandbox"


@dataclass
class Verification:
    ok: bool
    command: str
    exit_code: int
    took_ms: int
    locked_count: int
    affected_found: list[str]
    checked_versions: list[str]
    stderr_tail: str
    pruned: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def ensure_image() -> None:
    probe = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    if probe.returncode != 0:
        subprocess.run(["docker", "build", "-q", "-t", IMAGE, str(DOCKERFILE_DIR)], check=True)


def prune_lock(work: Path, affected: set[tuple[str, str]]) -> list[str]:
    path = work / "package-lock.json"
    if not path.exists():
        return []
    lock = json.loads(path.read_text())
    pkgs = lock.get("packages")
    if not pkgs:
        return []
    drop = [
        loc
        for loc, e in pkgs.items()
        if "node_modules/" in loc
        and (e.get("name") or loc.rsplit("node_modules/", 1)[1], e.get("version")) in affected
    ]
    for loc in drop:
        del pkgs[loc]
    path.write_text(json.dumps(lock, indent=2) + "\n")
    return drop


def regenerate(
    checkout: Path, manifest: dict[str, Any], before: str, affected: set[tuple[str, str]]
) -> tuple[Path, Verification | None, str, list[str]]:
    """Copies `checkout`, writes `manifest`, removes affected lock entries and runs the install
    in the sandbox. The returned Verification is set only if npm failed."""
    ensure_image()
    # With compose, the API uses the host's Docker daemon. The bind-mounted directory must be
    # a path that the host can also see, so FALLOUT_SANDBOX_TMP is mounted at the same path in both.
    work = Path(tempfile.mkdtemp(prefix="fallout-sandbox-", dir=os.environ.get("FALLOUT_SANDBOX_TMP")))
    shutil.copytree(checkout, work, ignore=shutil.ignore_patterns(".git", "node_modules"), dirs_exist_ok=True)
    (work / "package.json").write_text(json.dumps(manifest, indent=2) + "\n")
    pruned = prune_lock(work, affected)
    os.chmod(work, 0o777)  # the `node` user in the container writes the lockfile
    for p in work.rglob("*"):
        os.chmod(p, 0o777 if p.is_dir() else 0o666)
    cmd = [
        "docker", "run", "--rm", "--network", "bridge", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--memory", "768m",
        "-v", f"{work}:/work", IMAGE, f"--before={before}",
    ]  # fmt: skip
    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
    took = round((time.monotonic() - t0) * 1000)
    shown = f"npm install --package-lock-only --ignore-scripts --before={before}"
    if proc.returncode != 0 or not (work / "package-lock.json").exists():
        failed = Verification(False, shown, proc.returncode, took, 0, [], [], proc.stderr[-2000:], pruned)
        return work, failed, shown, pruned
    return work, None, shown, pruned


def verify(
    work: Path,
    affected: set[tuple[str, str]],
    command: str,
    took_ms: int = 0,
    pruned: list[str] | None = None,
) -> Verification:
    """Checks that no locked (name, version) is in the incident's affected set."""
    lock = json.loads((work / "package-lock.json").read_text())
    locked = locked_packages(lock)
    found = sorted({f"{lk.name}@{lk.version}" for lk in locked if (lk.name, lk.version) in affected})
    names = {n for n, _ in affected}
    checked = sorted({f"{lk.name}@{lk.version}" for lk in locked if lk.name in names})
    return Verification(not found, command, 0, took_ms, len(locked), found, checked, "", pruned or [])


def run(
    checkout: Path, manifest: dict[str, Any], before: str, affected: set[tuple[str, str]]
) -> tuple[Path, Verification]:
    t0 = time.monotonic()
    work, failed, cmd, pruned = regenerate(checkout, manifest, before, affected)
    if failed:
        return work, failed
    return work, verify(work, affected, cmd, round((time.monotonic() - t0) * 1000), pruned)
