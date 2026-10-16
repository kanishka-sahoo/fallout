"""Tests lockfile parsing (v1, v2, v3, nested paths, aliases) and overrides parsing (global, nested)."""

import json
from pathlib import Path

from fallout.repo import Locked, Override, direct_deps, locked_packages, parse_overrides, read_repo

V3 = {
    "lockfileVersion": 3,
    "packages": {
        "": {"name": "app", "dependencies": {"debug": "^4.3.4"}},
        "node_modules/debug": {"version": "4.4.1"},
        "node_modules/a/node_modules/debug": {"version": "2.6.9"},
        "node_modules/@scope/pkg": {"version": "1.0.0"},
        "node_modules/strip-ansi-cjs": {"name": "strip-ansi", "version": "6.0.1"},
        "node_modules/@ws/lib": {"resolved": "packages/lib", "link": True},
        "packages/lib": {"name": "@ws/lib", "version": "0.1.0"},
    },
}

V1 = {
    "lockfileVersion": 1,
    "dependencies": {
        "debug": {"version": "4.4.1"},
        "a": {"version": "1.0.0", "dependencies": {"debug": {"version": "2.6.9"}}},
        "strip-ansi-cjs": {"version": "npm:strip-ansi@6.0.1"},
        "local": {"version": "file:../local"},
    },
}


def test_lockfile_v2_v3_packages_map() -> None:
    got = set(locked_packages(V3))
    assert got == {
        Locked("debug", "4.4.1", "node_modules/debug"),
        Locked("debug", "2.6.9", "node_modules/a/node_modules/debug"),
        Locked("@scope/pkg", "1.0.0", "node_modules/@scope/pkg"),
        Locked("strip-ansi", "6.0.1", "node_modules/strip-ansi-cjs"),
    }
    # v2 has the same `packages` map, and also a v1 `dependencies` section that the parser ignores
    assert set(locked_packages({**V3, "lockfileVersion": 2, "dependencies": V1["dependencies"]})) == got


def test_lockfile_v1_nested_dependencies() -> None:
    assert set(locked_packages(V1)) == {
        Locked("debug", "4.4.1", "node_modules/debug"),
        Locked("a", "1.0.0", "node_modules/a"),
        Locked("debug", "2.6.9", "node_modules/a/node_modules/debug"),
        Locked("strip-ansi", "6.0.1", "node_modules/strip-ansi-cjs"),
    }


def test_global_and_scoped_overrides() -> None:
    pkg = {
        "dependencies": {"chalk": "^5.3.0"},
        "overrides": {
            "debug": "4.3.7",
            "eslint": {"debug": "4.3.6", ".": "9.0.0"},
            "glob@10": {"jackspeak": {"strip-ansi": "7.1.0"}},
            "chalk": "$chalk",
        },
    }
    assert parse_overrides(pkg) == [
        Override("debug", "4.3.7", None),
        Override("eslint", "9.0.0", None),
        Override("debug", "4.3.6", "eslint"),
        Override("strip-ansi", "7.1.0", "jackspeak"),
        Override("chalk", "^5.3.0", None),
    ]


def test_direct_deps_with_workspaces_and_aliases(tmp_path: Path) -> None:
    (tmp_path / "packages" / "lib").mkdir(parents=True)
    root = {
        "name": "root",
        "workspaces": ["packages/*"],
        "devDependencies": {"eslint": "^9.0.0", "debug": "^4.3.0"},
        "overrides": {"eslint": {"debug": "4.3.7"}},
    }
    lib = {
        "name": "@ws/lib",
        "dependencies": {"debug": "^4.3.0", "root": "*", "wrap-ansi-cjs": "npm:wrap-ansi@^7.0.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(root))
    (tmp_path / "packages" / "lib" / "package.json").write_text(json.dumps(lib))

    deps = {(d.name, d.range, d.scope) for d in direct_deps(tmp_path)}
    assert deps == {("eslint", "^9.0.0", "dev"), ("debug", "^4.3.0", "prod"), ("wrap-ansi", "^7.0.0", "prod")}

    snap = read_repo("org/x", tmp_path)
    assert not snap.has_lockfile and snap.lockfile_version is None and snap.locked == []
    assert snap.overrides == [Override("debug", "4.3.7", "eslint")]
