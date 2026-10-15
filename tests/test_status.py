"""BUILD.md §14 status machine: one case per status, the override transition, and a scoped
override that does not cover every path."""

import pytest

from fallout.blast import (
    EXPOSED_NO_LOCKFILE,
    LOCKED_MALICIOUS,
    MITIGATED_BY_OVERRIDE,
    NOT_AFFECTED,
    RANGE_ADMITS_LOCK_SAFE,
    OverrideEntry,
    closure_path,
    decide_status,
    override_covers,
)

# eslint@9 and mocha@10 each depend on debug (they are its dependents); parse-json sits two
# hops down, under cosmiconfig.
ADJ = {
    "repo": ["eslint@9", "cosmiconfig@9", "mocha@10"],
    "cosmiconfig@9": ["parse-json@5"],
}
NAMES = {
    "eslint@9": "eslint",
    "cosmiconfig@9": "cosmiconfig",
    "parse-json@5": "parse-json",
    "mocha@10": "mocha",
}
DEBUG_DEPENDENTS = {"eslint@9", "mocha@10"}
BAD_DEBUG = {"4.4.2"}


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"exposed": True, "has_lockfile": True, "locked_affected": ["npm:debug@4.4.2"]}, LOCKED_MALICIOUS),
        ({"exposed": False, "has_lockfile": True, "locked_affected": ["npm:debug@4.4.2"]}, LOCKED_MALICIOUS),
        ({"exposed": False, "has_lockfile": True}, NOT_AFFECTED),
        ({"exposed": True, "has_lockfile": False, "covered": {"debug"}}, MITIGATED_BY_OVERRIDE),
        ({"exposed": True, "has_lockfile": False}, EXPOSED_NO_LOCKFILE),
        ({"exposed": True, "has_lockfile": True}, RANGE_ADMITS_LOCK_SAFE),
    ],
)
def test_one_fixture_per_status(kwargs: dict, status: str) -> None:  # type: ignore[type-arg]
    args = {"locked_affected": [], "reachable": {"debug"}, "covered": set(), **kwargs}
    assert decide_status(**args) == status


def test_range_admits_lock_safe_to_mitigated_by_override() -> None:
    before = override_covers("repo", ADJ, NAMES, DEBUG_DEPENDENTS, [], BAD_DEBUG)
    assert not before
    assert (
        decide_status(exposed=True, has_lockfile=True, locked_affected=[], reachable={"debug"}, covered=set())
        == RANGE_ADMITS_LOCK_SAFE
    )

    fix = [OverrideEntry("debug", None, "4.4.1")]  # global override, applied by the fix PR
    assert override_covers("repo", ADJ, NAMES, DEBUG_DEPENDENTS, fix, BAD_DEBUG)
    status = decide_status(
        exposed=True, has_lockfile=True, locked_affected=[], reachable={"debug"}, covered={"debug"}
    )
    assert status == MITIGATED_BY_OVERRIDE


def test_scoped_override_that_misses_a_path_stays_exposed() -> None:
    scoped = [OverrideEntry("debug", "eslint", "4.3.7")]
    # mocha still reaches debug without passing through eslint
    assert not override_covers("repo", ADJ, NAMES, DEBUG_DEPENDENTS, scoped, BAD_DEBUG)
    both = [*scoped, OverrideEntry("debug", "mocha", "4.3.7")]
    assert override_covers("repo", ADJ, NAMES, DEBUG_DEPENDENTS, both, BAD_DEBUG)


def test_override_to_an_affected_version_does_not_mitigate() -> None:
    assert not override_covers(
        "repo", ADJ, NAMES, DEBUG_DEPENDENTS, [OverrideEntry("debug", None, "4.4.2")], BAD_DEBUG
    )
    assert not override_covers(
        "repo", ADJ, NAMES, DEBUG_DEPENDENTS, [OverrideEntry("debug", None, None)], BAD_DEBUG
    )


def test_closure_path_prefers_shortest_and_respects_blocked() -> None:
    assert closure_path("repo", ADJ, NAMES, {"parse-json@5"}, set()) == [
        "repo",
        "cosmiconfig@9",
        "parse-json@5",
    ]
    assert closure_path("repo", ADJ, NAMES, {"parse-json@5"}, {"cosmiconfig"}) is None
    assert closure_path("repo", ADJ, NAMES, {"repo"}, set()) == ["repo"]  # a direct dependency
