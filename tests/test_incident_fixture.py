"""The replay incident's affected versions, as sourced from OSV, equal BUILD.md §5.3."""

from fallout.settings import load_anchor

SPEC_5_3 = {
    # Batch 1, Sep 8 2025
    "debug@4.4.2", "chalk@5.6.1", "ansi-styles@6.2.2", "ansi-regex@6.2.1", "strip-ansi@7.1.1",
    "supports-color@10.2.1", "wrap-ansi@9.0.1", "slice-ansi@7.1.1", "color@5.0.1",
    "color-convert@3.1.1", "color-name@2.0.1", "color-string@2.1.1", "has-ansi@6.0.1",
    "is-arrayish@0.3.3", "error-ex@1.3.3", "simple-swizzle@0.2.3", "chalk-template@1.1.1",
    "supports-hyperlinks@4.1.1", "backslash@0.2.1",
    # Batch 2, Sep 9 2025
    "duckdb@1.3.3", "@duckdb/node-api@1.3.3", "@duckdb/node-bindings@1.3.3",
    "@duckdb/duckdb-wasm@1.29.2", "proto-tinker-wc@0.1.87",
}  # fmt: skip


def test_affected_versions_match_spec() -> None:
    anchor = load_anchor()
    got = {f"{v['name']}@{v['version']}" for v in anchor["malicious_versions"]}
    assert got == SPEC_5_3


def test_anchor_is_one_second_before_first_malicious_publish() -> None:
    anchor = load_anchor()
    first = min(anchor["malicious_versions"], key=lambda v: v["published_at"])
    from ingest.anchor import parse_ts

    delta = parse_ts(first["published_at"]) - parse_ts(anchor["S"])
    assert delta.total_seconds() == 1.0
    assert all(v["published_at"] > anchor["S"] for v in anchor["malicious_versions"])
