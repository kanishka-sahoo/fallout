"""Parse a repo checkout: manifests, lockfile and overrides (BUILD.md §4.2, §5.5 step 6).

Pure functions over files on disk, so load_repos.py, recheck_repo and the tests share them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NPM_ALIAS = re.compile(r"^npm:((?:@[^/@]+/)?[^@]+)(?:@(.*))?$")


@dataclass(frozen=True)
class Dep:
    name: str  # the registry package actually installed (alias target for `npm:` specs)
    range: str
    scope: str  # prod | dev


@dataclass(frozen=True)
class Locked:
    name: str
    version: str
    path: str


@dataclass(frozen=True)
class Override:
    name: str
    spec: str
    parent: str | None  # None = global; otherwise the package the override is scoped under


def split_alias(name: str, spec: str) -> tuple[str, str]:
    """`"wrap-ansi-cjs": "npm:wrap-ansi@^7"` installs wrap-ansi at ^7."""
    m = NPM_ALIAS.match(spec.strip())
    return (m[1], m[2] or "*") if m else (name, spec)


def strip_selector(key: str) -> str:
    """Override keys may carry a version selector: `debug@4` -> `debug`, `@a/b@1` -> `@a/b`."""
    at = key.rfind("@")
    return key[:at] if at > 0 else key


def manifests(repo_dir: Path) -> list[Path]:
    """Root package.json plus each workspace package.json (glob patterns only)."""
    root = repo_dir / "package.json"
    if not root.exists():
        return []
    found = [root]
    workspaces = json.loads(root.read_text()).get("workspaces", [])
    if isinstance(workspaces, dict):  # yarn-style {"packages": [...]}
        workspaces = workspaces.get("packages", [])
    for pattern in workspaces:
        found += sorted(p / "package.json" for p in repo_dir.glob(pattern) if (p / "package.json").exists())
    return found


def direct_deps(repo_dir: Path) -> list[Dep]:
    """dependencies + devDependencies of the root and every workspace, minus workspace packages.

    One entry per (name, range); `prod` wins when the same pair is both prod and dev.
    """
    docs = [json.loads(p.read_text()) for p in manifests(repo_dir)]
    internal = {d.get("name") for d in docs}
    out: dict[tuple[str, str], str] = {}
    for d in docs:
        for field, scope in (("dependencies", "prod"), ("devDependencies", "dev")):
            for name, spec in d.get(field, {}).items():
                if name in internal:
                    continue
                key = split_alias(name, spec)
                if out.get(key) != "prod":
                    out[key] = scope
    return [Dep(n, r, s) for (n, r), s in out.items()]


def parse_overrides(pkg: dict[str, Any]) -> list[Override]:
    """npm `overrides` -> flat entries. Nested objects scope an override under their key; the
    nearest enclosing key is recorded as `parent`. `"."` overrides the scoping package itself,
    and `$name` references the root dependency's spec."""
    root_specs = {**pkg.get("devDependencies", {}), **pkg.get("dependencies", {})}

    def spec_of(s: str) -> str:
        return root_specs.get(s[1:], s) if s.startswith("$") else s

    out: list[Override] = []

    def walk(tree: dict[str, Any], parent: str | None) -> None:
        for key, val in tree.items():
            name = strip_selector(key)
            if isinstance(val, str):
                out.append(Override(name, spec_of(val), parent))
                continue
            for child, child_val in val.items():
                if child == "." and isinstance(child_val, str):
                    out.append(Override(name, spec_of(child_val), parent))
            walk({k: v for k, v in val.items() if k != "."}, name)

    walk(pkg.get("overrides", {}), None)
    return out


def locked_packages(lock: dict[str, Any]) -> list[Locked]:
    """Every installed registry package in a v1, v2 or v3 package-lock.json."""
    if "packages" in lock:  # v2 / v3
        out = []
        for path, entry in lock["packages"].items():
            if "node_modules/" not in path or entry.get("link") or "version" not in entry:
                continue
            name = entry.get("name") or path.rsplit("node_modules/", 1)[1]
            out.append(Locked(name, entry["version"], path))
        return out

    out = []

    def walk(deps: dict[str, Any], prefix: str) -> None:  # v1: nested `dependencies`
        for name, entry in deps.items():
            path = f"{prefix}node_modules/{name}"
            version = entry.get("version", "")
            real, ver = split_alias(name, version)
            if real != name:  # "npm:string-width@4.2.3"
                version = ver
            if version and not version.startswith(("file:", "git", "http", "link:")):
                out.append(Locked(real, version, path))
            walk(entry.get("dependencies", {}), path + "/")

    walk(lock.get("dependencies", {}), "")
    return out


@dataclass
class RepoSnapshot:
    full_name: str
    deps: list[Dep]
    overrides: list[Override]
    has_lockfile: bool
    lockfile_version: int | None
    locked: list[Locked]


def read_repo(full_name: str, repo_dir: Path) -> RepoSnapshot:
    root = json.loads((repo_dir / "package.json").read_text())
    lock_path = repo_dir / "package-lock.json"
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else None
    return RepoSnapshot(
        full_name=full_name,
        deps=direct_deps(repo_dir),
        overrides=parse_overrides(root),  # npm reads overrides from the root manifest only
        has_lockfile=lock is not None,
        lockfile_version=lock.get("lockfileVersion", 1) if lock else None,
        locked=locked_packages(lock) if lock else [],
    )
