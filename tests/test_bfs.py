"""BUILD.md §14: BFS over a hand-built fixture graph with a golden exposed set, hops, paths and
repo statuses. Runs against a throwaway graph in FalkorDB; skipped when FalkorDB is down.

    debug@4.4.2 (MAL)  <-CRT ^4.3.0-  a  <- c <- d <- e <- r1 (no lockfile)
                       <-CRT ^4.3.0-  r3 (direct; global override to 4.4.1)
                                      c  <- h, r5 (lockfile)
    chalk@5.6.1 (MAL)  <-CRT ^5.0.0-  g  <- h <- r4 (lockfile pins chalk@5.6.1)
    debug@2.6.9 <- b <- f <- r2       (never exposed)
"""

import contextlib
from collections.abc import Iterator

import pytest
from falkordb import Graph

from fallout.blast import Affected, blast_radius, exposure_path
from fallout.db import graph

INCIDENT = "test-incident"

FIXTURE = """
CREATE (i:Incident {id: 'test-incident'}), (adv:Advisory {id: 'MAL-TEST', kind: 'MALICIOUS'}),
       (i)-[:INCLUDES]->(adv),
       (pdebug:Package {name: 'debug'}), (pchalk:Package {name: 'chalk'}),
       (m1:Version {key: 'npm:debug@4.4.2', name: 'debug', version: '4.4.2', is_malicious: true}),
       (m2:Version {key: 'npm:chalk@5.6.1', name: 'chalk', version: '5.6.1', is_malicious: true}),
       (adv)-[:AFFECTS]->(m1), (adv)-[:AFFECTS]->(m2),
       (d441:Version {key: 'npm:debug@4.4.1', name: 'debug', version: '4.4.1'}),
       (d269:Version {key: 'npm:debug@2.6.9', name: 'debug', version: '2.6.9'}),
       (c560:Version {key: 'npm:chalk@5.6.0', name: 'chalk', version: '5.6.0'}),
       (pdebug)-[:HAS_VERSION]->(m1), (pdebug)-[:HAS_VERSION]->(d441), (pdebug)-[:HAS_VERSION]->(d269),
       (pchalk)-[:HAS_VERSION]->(m2), (pchalk)-[:HAS_VERSION]->(c560),
       (a:Version {key: 'npm:a@1', name: 'a'}), (b:Version {key: 'npm:b@1', name: 'b'}),
       (c:Version {key: 'npm:c@1', name: 'c'}), (d:Version {key: 'npm:d@1', name: 'd'}),
       (e:Version {key: 'npm:e@1', name: 'e'}), (f:Version {key: 'npm:f@1', name: 'f'}),
       (g:Version {key: 'npm:g@1', name: 'g'}), (h:Version {key: 'npm:h@1', name: 'h'}),
       (a)-[:DEPENDS_ON {requirement: '^4.3.0'}]->(d441), (b)-[:DEPENDS_ON {requirement: '~2.6.9'}]->(d269),
       (c)-[:DEPENDS_ON {requirement: '^1.0.0'}]->(a), (d)-[:DEPENDS_ON {requirement: '^1.0.0'}]->(c),
       (e)-[:DEPENDS_ON {requirement: '^1.0.0'}]->(d), (f)-[:DEPENDS_ON {requirement: '^1.0.0'}]->(b),
       (g)-[:DEPENDS_ON {requirement: '^5.0.0'}]->(c560),
       (h)-[:DEPENDS_ON {requirement: '^1.0.0'}]->(g), (h)-[:DEPENDS_ON {requirement: '^1.0.0'}]->(c),
       (a)-[:CAN_RESOLVE_TO {incident: 'test-incident', requirement: '^4.3.0'}]->(m1),
       (g)-[:CAN_RESOLVE_TO {incident: 'test-incident', requirement: '^5.0.0'}]->(m2),
       (r1:Repo {key: 'repo:t/r1', has_lockfile: false}), (r2:Repo {key: 'repo:t/r2', has_lockfile: true}),
       (r3:Repo {key: 'repo:t/r3', has_lockfile: true}), (r4:Repo {key: 'repo:t/r4', has_lockfile: true}),
       (r5:Repo {key: 'repo:t/r5', has_lockfile: true}),
       (r1)-[:DIRECT_DEP {requirement: '^1.0.0'}]->(e), (r2)-[:DIRECT_DEP {requirement: '^1.0.0'}]->(f),
       (r3)-[:DIRECT_DEP {requirement: '^4.3.0'}]->(d441),
       (r3)-[:CAN_RESOLVE_TO {incident: 'test-incident', requirement: '^4.3.0'}]->(m1),
       (r3)-[:OVERRIDES {spec: '4.4.1', resolved_version: '4.4.1'}]->(pdebug),
       (r4)-[:DIRECT_DEP {requirement: '^1.0.0'}]->(h), (r4)-[:LOCKS {path: 'node_modules/chalk'}]->(m2),
       (r5)-[:DIRECT_DEP {requirement: '^1.0.0'}]->(c), (r5)-[:LOCKS {path: 'node_modules/debug'}]->(d441)
"""

GOLDEN_HOPS = {
    "npm:a@1": 1,
    "npm:g@1": 1,
    "repo:t/r3": 1,
    "npm:c@1": 2,
    "npm:h@1": 2,
    "npm:d@1": 3,
    "repo:t/r4": 3,
    "repo:t/r5": 3,
    "npm:e@1": 4,
    "repo:t/r1": 5,
}
GOLDEN_STATUS = {
    "repo:t/r1": "EXPOSED_NO_LOCKFILE",
    "repo:t/r2": "NOT_AFFECTED",
    "repo:t/r3": "MITIGATED_BY_OVERRIDE",
    "repo:t/r4": "LOCKED_MALICIOUS",
    "repo:t/r5": "RANGE_ADMITS_LOCK_SAFE",
}


@pytest.fixture(scope="module")
def g() -> Iterator[Graph]:
    try:
        g = graph("fallout_test_bfs")
        g.query("RETURN 1")
    except Exception:
        pytest.skip("FalkorDB not reachable")
    with contextlib.suppress(Exception):  # left over from an interrupted run
        g.delete()
    g.query(FIXTURE)
    yield g
    g.delete()


def test_blast_radius_golden(g: Graph) -> None:
    hops: list[int] = []
    res = blast_radius(INCIDENT, g=g, on_hop=lambda hop, new: hops.append(hop))
    assert hops == [1, 2, 3, 4, 5]
    assert not res.truncated
    exposed = {
        r[0]: r[1]
        for r in g.query(
            "MATCH (:Incident)-[x:EXPOSES]->(n) WHERE x.hop IS NOT NULL RETURN n.key, x.hop"
        ).result_set
    }
    assert exposed == GOLDEN_HOPS
    assert {r["repo"]: r["status"] for r in res.repos} == GOLDEN_STATUS
    stored = g.query("MATCH (:Incident)-[x:EXPOSES]->(r:Repo) RETURN r.key, x.status").result_set
    assert dict(stored) == {k: v for k, v in GOLDEN_STATUS.items() if v != "NOT_AFFECTED"}


def test_exposure_path_follows_parent_pointers(g: Graph) -> None:
    blast_radius(INCIDENT, g=g)
    p = exposure_path(g, INCIDENT, "repo:t/r1", Affected.load(g, INCIDENT))
    assert p is not None
    assert p["nodes"] == ["repo:t/r1", "npm:e@1", "npm:d@1", "npm:c@1", "npm:a@1", "npm:debug@4.4.2"]
    assert [e["type"] for e in p["edges"]] == [
        "DIRECT_DEP",
        "DEPENDS_ON",
        "DEPENDS_ON",
        "DEPENDS_ON",
        "CAN_RESOLVE_TO",
    ]
    assert p["edges"][-1]["requirement"] == "^4.3.0"


def test_paths_by_package_cover_each_affected_package(g: Graph) -> None:
    res = blast_radius(INCIDENT, g=g)
    r4 = next(r for r in res.repos if r["repo"] == "repo:t/r4")
    got = {p["package"]: p["nodes"] for p in r4["paths_by_package"]}
    assert got == {
        "chalk": ["repo:t/r4", "npm:h@1", "npm:g@1", "npm:chalk@5.6.1"],
        "debug": ["repo:t/r4", "npm:h@1", "npm:c@1", "npm:a@1", "npm:debug@4.4.2"],
    }


def test_max_hops_truncates(g: Graph) -> None:
    res = blast_radius(INCIDENT, g=g, max_hops=2)
    assert res.truncated
    assert "repo:t/r1" not in {r["repo"] for r in res.repos if r["hop"] is not None}
