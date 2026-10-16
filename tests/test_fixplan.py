"""BUILD.md §14 fix planner: the single-override case, conflicting ranges -> scoped overrides,
a direct dependency pinned, and edges whose range never admits the bad version left alone.
Uses npm's semver through workers/semver-eval.mjs."""

from fallout.fixplan import apply_changes, best_version, plan_package

DEBUG_SAFE = ["2.6.9", "3.2.7", "4.3.4", "4.3.7", "4.4.0", "4.4.1"]


def req(parent: str, r: str) -> dict[str, str]:
    return {"parent": f"npm:{parent}@1.0.0", "parent_name": parent, "requirement": r}


def test_best_version_is_highest_satisfying_all() -> None:
    assert best_version(DEBUG_SAFE, ["^4.3.1", "^4.1.0"]) == "4.4.1"
    assert best_version(DEBUG_SAFE, ["^4.3.1", "~4.3.0"]) == "4.3.7"
    assert best_version(DEBUG_SAFE, ["^5.0.0"]) is None


def test_single_selector_override_ignores_non_admitting_edges() -> None:
    reqs = [req("eslint", "^4.3.2"), req("@babel/core", "^4.1.0"), req("eslint-plugin-import", "^3.2.7")]
    fix, pin, ov = plan_package("debug", reqs, DEBUG_SAFE, ["4.4.2"], None)
    assert (fix.strategy, fix.version, pin) == ("selector", "4.4.1", None)
    assert ov == {"debug@4.4.2": "4.4.1"}
    assert {r["requirement"] for r in fix.requirements} == {"^4.3.2", "^4.1.0"}  # ^3.2.7 never admits 4.4.2


def test_conflicting_ranges_fall_back_to_scoped() -> None:
    # Both ranges admit the bad 4.4.2 (and 4.x.y prerelease-free), but no safe version fits both.
    reqs = [req("a", ">=4.3.5 <4.4.0 || 4.4.2"), req("b", ">=4.4.1 <4.4.3")]
    fix, _, ov = plan_package("debug", reqs, DEBUG_SAFE, ["4.4.2"], None)
    assert fix.strategy == "scoped"
    assert ov == {"a": {"debug": "4.3.7"}, "b": {"debug": "4.4.1"}}


def test_direct_dependency_is_pinned_not_overridden() -> None:
    reqs = [{"parent": "repo:o/r", "parent_name": "(root)", "requirement": "^4.3.4"}]
    fix, pin, ov = plan_package("debug", reqs, DEBUG_SAFE, ["4.4.2"], ("dependencies", "^4.3.4"))
    assert fix.strategy == "pin"
    assert pin == {"field": "dependencies", "from": "^4.3.4", "to": "4.4.1"}
    assert ov == {}


def test_apply_changes_merges_into_existing_scoped_overrides() -> None:
    manifest = {"dependencies": {"debug": "^4.3.4"}, "overrides": {"eslint": {"debug": "4.3.7"}}}
    changes = {
        "pin": {"debug": {"field": "dependencies", "from": "^4.3.4", "to": "4.4.1"}},
        "overrides": {"error-ex@1.3.3": "1.3.2", "eslint": {"chalk": "4.1.2"}},
    }
    out = apply_changes(manifest, changes)
    assert out["dependencies"]["debug"] == "4.4.1"
    assert out["overrides"] == {"eslint": {"debug": "4.3.7", "chalk": "4.1.2"}, "error-ex@1.3.3": "1.3.2"}
    assert manifest["dependencies"]["debug"] == "^4.3.4"  # input untouched
