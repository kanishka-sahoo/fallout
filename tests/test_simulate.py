"""Simulated incidents: version bumps, naming and scenario validation that needs no graph. Also the
console-session gate on every endpoint that writes to GitHub."""

import pytest

from fallout import simulate


@pytest.mark.parametrize(
    ("version", "kind", "out"),
    [
        ("4.4.1", "patch", "4.4.2"),
        ("4.4.1", "minor", "4.5.0"),
        ("4.4.1", "major", "5.0.0"),
        ("0.9.9", "patch", "0.9.10"),
    ],
)
def test_bump(version: str, kind: simulate.Bump, out: str) -> None:
    assert simulate.bump(version, kind) == out


def test_stable_at_s_drops_prereleases_and_later_versions() -> None:
    doc = {
        "versions": {"1.0.0": {}, "1.1.0": {}, "1.2.0-beta.1": {}, "2.0.0": {}},
        "time": {
            "1.0.0": "2020-01-01T00:00:00.000Z",
            "1.1.0": "2024-01-01T00:00:00.000Z",
            "1.2.0-beta.1": "2024-06-01T00:00:00.000Z",
            "2.0.0": "2030-01-01T00:00:00.000Z",  # after S
        },
    }
    assert simulate.stable_at_s(doc) == ["1.1.0", "1.0.0"]


def test_ids_mark_simulations() -> None:
    assert simulate.is_simulated("sim-20261016-120000-abcd")
    assert not simulate.is_simulated("npm-2025-09-08-chalk-debug")


def test_default_titles() -> None:
    one = [{"name": "lodash", "key": "npm:lodash@4.17.22"}]
    assert simulate.default_title({"kind": "release"}, one) == "Malicious release of lodash@4.17.22"
    many = [{"name": n, "key": f"npm:{n}@1.0.1"} for n in ("a", "b", "c", "d", "e")]
    assert simulate.default_title({"kind": "release"}, many) == "Malicious releases of a, b, c and 2 more"
    assert simulate.default_title({"kind": "versions"}, one) == "Compromised versions of lodash"
    assert simulate.default_title({"kind": "osv", "advisories": ["MAL-1"]}, []) == "Advisory MAL-1"


@pytest.mark.parametrize(
    ("spec", "match"),
    [
        ({"kind": "nope"}, "kind must be"),
        ({"kind": "release", "packages": []}, "at least one package"),
        ({"kind": "osv", "advisories": [" "]}, "at least one OSV"),
        ({"kind": "release", "packages": [{"name": f"p{i}"} for i in range(26)]}, "at most 25"),
    ],
)
def test_rejects_bad_specs(spec: dict, match: str) -> None:
    with pytest.raises(simulate.ScenarioError, match=match):
        simulate.create(spec)


def test_only_simulations_can_be_deleted() -> None:
    with pytest.raises(simulate.ScenarioError, match="Only simulated"):
        simulate.delete("npm-2025-09-08-chalk-debug")


def test_pr_endpoints_need_a_console_session() -> None:
    """Create PR, approve and close PR start with require_user: only a console user writes to GitHub."""
    from fastapi import HTTPException

    from api import main

    with pytest.raises(HTTPException) as e:
        main.require_user(None)
    assert e.value.status_code == 401
    with pytest.raises(HTTPException):
        main.require_user("console.forged")
    assert main.require_user(main.session_value("console")) == "console"


def test_pr_url_parsing() -> None:
    from api.github_pr import parse_pr_url

    assert parse_pr_url("https://github.com/fallout-demo/cli-tool/pull/3") == ("fallout-demo/cli-tool", 3)
    with pytest.raises(ValueError):
        parse_pr_url("https://github.com/fallout-demo/cli-tool/issues/3")
