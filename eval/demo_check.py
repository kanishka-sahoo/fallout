"""Demo-repo check: compares the graph's exposure of each demo repo with the oracle.

For each demo repo, the oracle builds npm's ideal tree at S from the manifests only. The
lockfile is not used, because exposure is about the versions that the ranges let npm pick. The
oracle reports every edge to an affected package that admits an affected version. For the
replay, this rule gives the same result as D1, because each malicious release was tagged
`latest` and was the newest version. The check compares:
  - whether the repo is exposed,
  - the set of affected packages that the repo reaches (for the graph, without the packages
    that an override mitigates, because arborist applies overrides when it builds the tree),
  - each graph path (every intermediate name@version must be in the oracle tree),
  - for each affected package, the length of the shortestPath cross-check and of the path,
  - the overlap between the graph's transitive dependency tree and the oracle tree.
Writes eval/demo_check.json. Run `fallout.blast` for the incident first.

    uv run python -m eval.demo_check
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fallout.blast import Affected, Closure, blast_radius, cross_check_path
from fallout.db import graph
from fallout.settings import ROOT, SETTINGS, load_anchor
from ingest.repo_seeds import REPOS_DIR

ORACLE = ROOT / "eval" / "oracle" / "oracle.mjs"
TREES = ROOT / "eval" / "oracle" / "trees"
OUT = ROOT / "eval" / "demo_check.json"


def run_oracle(full_name: str, affected: dict[str, list[str]], before: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="fallout-demo-") as tmp:
        proj = Path(tmp) / "repo"
        shutil.copytree(
            REPOS_DIR / full_name,
            proj,
            ignore=shutil.ignore_patterns(".git", "package-lock.json", "node_modules"),
        )
        aff = Path(tmp) / "affected.json"
        aff.write_text(json.dumps(affected))
        tree_out = TREES / f"{full_name.replace('/', '__')}.json"
        TREES.mkdir(parents=True, exist_ok=True)
        cmd = ["node", str(ORACLE), "--before", before, "--affected", str(aff), "--project", str(proj)]
        proc = subprocess.run(
            [*cmd, "--tree-out", str(tree_out)], capture_output=True, text=True, check=False
        )
        if proc.returncode != 0:
            raise RuntimeError(f"oracle failed on {full_name}: {proc.stderr[-2000:]}")
        out = json.loads(proc.stdout)
        nodes = json.loads(tree_out.read_text())
        out["tree"] = {f"npm:{n['package']}@{n['version']}" for n in nodes if not n["workspace"]}
        return out


def main() -> None:
    anchor = load_anchor()
    incident = SETTINGS["replay_incident"]
    affected: dict[str, list[str]] = {}
    for v in anchor["malicious_versions"]:
        affected.setdefault(v["name"], []).append(v["version"])

    g = graph()
    res = blast_radius(incident, g=g)
    aff = Affected.load(g, incident)
    report, ok = [], True
    for st in res.repos:
        full_name = st["repo"].removeprefix("repo:")
        oracle = run_oracle(full_name, affected, anchor["S"])
        oracle_pkgs = sorted({p[-1]["name"] for p in oracle["paths"]})
        graph_exposed = st["hop"] is not None

        bad_hops = []
        for p in st["paths_by_package"]:
            bad_hops += [n for n in p["nodes"][1:-1] if n not in oracle["tree"]]

        cross = []
        for p in st["paths_by_package"]:
            cp = cross_check_path(g, incident, st["repo"], p["nodes"][-1])
            cross.append(
                {"package": p["package"], "path": len(p["nodes"]) - 1, "sp": cp and len(cp["nodes"]) - 1}
            )
        cross_ok = all(c["path"] == c["sp"] for c in cross)
        graph_pkgs = sorted(set(st["affected_packages"]) - set(st["mitigated_packages"]))

        closure = set(Closure.load(g, st["repo"]).names)
        tree = oracle["tree"] - {k for k in oracle["tree"] if k in aff.keys}
        agree = {
            "graph_only": len(closure - tree),
            "oracle_only": len(tree - closure),
            "both": len(closure & tree),
            "jaccard": round(len(closure & tree) / max(1, len(closure | tree)), 3),
            "graph_only_keys": sorted(closure - tree),
            "oracle_only_keys": sorted(tree - closure),
        }
        match = graph_exposed == oracle["exposed"] and graph_pkgs == oracle_pkgs and not bad_hops and cross_ok
        ok &= match
        report.append(
            {
                "repo": full_name,
                "status": st["status"],
                "graph_exposed": graph_exposed,
                "oracle_exposed": oracle["exposed"],
                "graph_packages": graph_pkgs,
                "graph_mitigated_packages": st["mitigated_packages"],
                "oracle_packages": oracle_pkgs,
                "path_hops_missing_from_oracle_tree": bad_hops,
                "bfs_hop": st["hop"],
                "shortest_path_cross_check": cross,
                "unknown_specs": len(oracle["unknown_specs"]),
                "closure_vs_oracle_tree": agree,
                "oracle_reference_paths": [
                    " > ".join(f"{h['name']}@{h['version']}" for h in p) for p in oracle["paths"][:3]
                ],
                "match": match,
            }
        )
        print(
            f"{'OK  ' if match else 'DIFF'} {full_name:32s} {st['status']:24s} "
            f"graph={graph_pkgs} oracle={oracle_pkgs} hop={st['hop']} "
            f"sp_agrees={cross_ok} tree_jaccard={agree['jaccard']}"
        )
    OUT.write_text(
        json.dumps({"incident": incident, "S": anchor["S"], "all_match": ok, "repos": report}, indent=2)
    )
    print(f"-> {OUT}  all_match={ok}")


if __name__ == "__main__":
    main()
