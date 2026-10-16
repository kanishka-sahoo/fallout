"""Tests the crawl logic that does not need the network: spec classification and spam pruning."""

from ingest.crawl import NON_REGISTRY, NPM_ALIAS, Crawl


def test_npm_alias_parsing() -> None:
    m = NPM_ALIAS.match("npm:wrap-ansi@^7.0.0")
    assert m and (m[1], m[2]) == ("wrap-ansi", "^7.0.0")
    m = NPM_ALIAS.match("npm:@scope/pkg@~1.2")
    assert m and (m[1], m[2]) == ("@scope/pkg", "~1.2")
    m = NPM_ALIAS.match("npm:lodash")
    assert m and (m[1], m[2]) == ("lodash", None)


def test_non_registry_specs() -> None:
    for spec in ["git+https://x/y.git", "github:a/b", "a/b", "file:../x", "https://x/y.tgz", "workspace:*"]:
        assert NON_REGISTRY.match(spec), spec
    for spec in ["^1.2.3", "*", "", ">=1 <2", "latest", "1.x"]:
        assert not NON_REGISTRY.match(spec), spec


def crawl_with(edges: list[tuple[str, str]], missing: dict[str, int], roots: set[str]) -> Crawl:
    c = Crawl(client=None, before="", before_ms=0)  # type: ignore[arg-type]
    keys = {k for e in edges for k in e} | set(missing) | roots
    c.versions = {k: {"key": k} for k in keys}
    c.edges = [{"from": a, "to": b, "requirement": "*", "kind": "prod"} for a, b in edges]
    c.unresolved = [
        {"parent": p, "name": f"gone{i}", "reason": "package_not_found"}
        for p, n in missing.items()
        for i in range(n)
    ]
    c.roots = roots
    return c


def test_spam_prune_removes_clusters_and_orphans() -> None:
    c = crawl_with(
        edges=[
            ("real", "dep"),
            ("spam-a", "spam-b"),  # spam-b has only a few missing deps but depends on spam
            ("spam-a", "dep"),
            ("spam-b", "orphan"),
            *[("spam-b", f"spam-c{i}") for i in range(10)],
        ],
        missing={"spam-a": 40, "spam-b": 2, **{f"spam-c{i}": 12 for i in range(10)}},
        roots={"real", "spam-a"},
    )
    c.prune_spam()
    assert set(c.versions) == {"real", "dep"}  # shared dep survives through the real root
    assert "orphan" not in c.versions  # reachable only through spam
    assert all(u["parent"] in c.versions for u in c.unresolved)


def test_spam_prune_keeps_a_package_with_a_few_missing_deps() -> None:
    c = crawl_with(edges=[("app", f"d{i}") for i in range(30)], missing={"app": 3}, roots={"app"})
    c.prune_spam()
    assert "app" in c.versions and len(c.versions) == 31
