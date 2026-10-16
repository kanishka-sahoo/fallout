"""Aggregate concentration-of-risk findings for the write-up (BUILD.md §7.7, docs/blog.md).

Numbers only, never a ranking of people: how few accounts reach how much of the graph, and how
many central packages rest on a single maintainer without provenance.

    uv run python -m analysis.ecosystem_report      # writes analysis/ecosystem_report.json
"""

from __future__ import annotations

import json
from collections import defaultdict

from analysis.algorithms import reverse_reach
from fallout.db import graph, rows
from fallout.settings import ROOT, SETTINGS

OUT = ROOT / "analysis" / "ecosystem_report.json"


def main() -> None:
    g = graph()
    dependents: dict[str, list[str]] = defaultdict(list)
    for r in rows(g, "pkg_edges"):
        dependents[r["dependency"]].append(r["dependent"])
    pkgs = g.query(
        "MATCH (p:Package) "
        "RETURN p.name, p.pagerank, p.maintainer_count, p.has_provenance, p.weekly_downloads"
    ).result_set
    total = len(pkgs)
    ranked = sorted((p for p in pkgs if p[1] is not None), key=lambda p: -p[1])

    central = {}
    for k in (100, 1000):
        top = ranked[:k]
        single = [p for p in top if p[2] == 1]
        central[f"top_{k}_by_pagerank"] = {
            "single_maintainer": len(single),
            "without_provenance": sum(1 for p in top if not p[3]),
            "single_maintainer_and_no_provenance": sum(1 for p in single if not p[3]),
        }

    cands = rows(g, "maintainer_candidates", {"k": 300})
    reach = {c["maintainer"]: reverse_reach(c["packages"], dependents) for c in cands}

    # Greedy cover: how many accounts, taken over, reach a given share of the graph's packages.
    covered: set[str] = set()
    curve: list[float] = []
    remaining = dict(reach)
    while remaining and len(curve) < 60:
        best = max(remaining, key=lambda m: len(remaining[m] - covered))
        gain = remaining.pop(best) - covered
        if not gain:
            break
        covered |= gain
        curve.append(len(covered) / total)
    thresholds = {
        f"{int(t * 100)}%": next((i + 1 for i, c in enumerate(curve) if c >= t), None)
        for t in (0.25, 0.4, 0.5)
    }

    single_account = sorted((len(s) / total for s in reach.values()), reverse=True)
    exposed = g.query(
        "MATCH (:Incident {id: $i})-[x:EXPOSES]->(v:Version) RETURN count(v)",
        {"i": SETTINGS["replay_incident"]},
    ).result_set[0][0]
    versions = g.query("MATCH (v:Version) WHERE NOT v.is_malicious RETURN count(v)").result_set[0][0]

    report = {
        "packages": total,
        "versions": versions,
        "replay_exposed_versions": exposed,
        "replay_exposed_share": exposed / versions,
        "central_packages": central,
        "accounts_scored": len(reach),
        "largest_single_account_reach_share": single_account[0],
        "accounts_reaching_over_25pct_alone": sum(1 for s in single_account if s > 0.25),
        "greedy_accounts_to_reach": thresholds,
        "greedy_cover_after_10_accounts": curve[9] if len(curve) >= 10 else None,
        "greedy_curve": curve[:30],
    }
    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "greedy_curve"}, indent=1))


if __name__ == "__main__":
    main()
