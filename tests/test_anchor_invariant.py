"""BUILD.md §14: no non-malicious Version in the loaded graph is newer than S."""

import pytest

from fallout.db import graph
from fallout.settings import load_anchor


@pytest.fixture(scope="module")
def g():  # type: ignore[no-untyped-def]
    try:
        g = graph()
        g.query("RETURN 1")
    except Exception:
        pytest.skip("FalkorDB not reachable")
    return g


def test_no_version_after_s(g) -> None:  # type: ignore[no-untyped-def]
    s = load_anchor()["S_epoch_ms"]
    rows = g.query(
        "MATCH (v:Version) WHERE v.is_malicious = false AND v.published_at > $s RETURN v.key LIMIT 5",
        {"s": s},
    ).result_set
    assert rows == []
