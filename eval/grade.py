"""Grades one answer against the oracle. This module does not read FalkorDB.

- A cited node `name@version` is hallucinated if it is not in the target's oracle tree, is not
  an affected version of the advisory group, and is not in the registry (packument cache).
- A cited edge (two consecutive hops, from the target root) is hallucinated if the oracle tree
  does not have it. The last hop to an affected version is valid in two cases. For malicious
  advisory groups, the parent has an edge to that package whose spec admits the version. For
  vulnerable advisory groups, npm installed that affected version there.
- A path is valid if it is not empty, every edge exists, and it ends at an affected version.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from typing import Any

from eval.dataset import TREES, slug
from fallout import node


def split(spec: str) -> tuple[str, str] | None:
    spec = spec.strip().removeprefix("npm:")
    at = spec.rfind("@")
    return (spec[:at], spec[at + 1 :]) if at > 0 else None


@cache
def admits(spec: str, version: str) -> bool:
    r = node.semver_eval([{"id": "x", "op": "satisfies", "range": spec, "version": version}])["x"]
    return r.get("result") is True


class Tree:
    def __init__(self, nodes: list[dict[str, Any]]) -> None:
        self.nodes = {
            f"{n['package']}@{n['version']}" for n in nodes if not n.get("root") and n.get("version")
        }
        self.edges: dict[str, list[dict[str, Any]]] = defaultdict(list)  # "pkg@ver" or ROOT -> edges
        for n in nodes:
            src = "ROOT" if n.get("root") else f"{n['package']}@{n['version']}"
            for e in n["edgesOut"]:
                if e.get("type") == "dev" and not n.get("root") and not n.get("workspace"):
                    continue
                self.edges[src].append(e)
            if n.get("workspace") and not n.get("root"):  # workspace links are edges from the root
                self.edges["ROOT"].extend(n["edgesOut"])

    def has_edge(self, src: str, pkg: str, version: str, last_mode: str | None) -> bool:
        for e in self.edges.get(src, []):
            to_pkg = e.get("toPackage") or e["name"]
            if to_pkg != pkg:
                continue
            if e.get("to") == version:
                return True
            if last_mode == "admits":
                spec = e["spec"]
                if spec.startswith("npm:"):
                    spec = spec.split("@", 2)[-1] if spec.count("@") >= 2 else "*"
                if admits(spec, version):
                    return True
        return False


class Grader:
    def __init__(self, dataset: dict[str, Any]) -> None:
        self.units = {u["unit"]: u for u in dataset["units"]}
        self.oracle = {(p["unit"], p["target"]): p for p in dataset["pairs"]}
        self._trees: dict[str, Tree] = {}
        self._registry: dict[str, set[str]] = {}

    def tree(self, target: str) -> Tree:
        if target not in self._trees:
            self._trees[target] = Tree(json.loads((TREES / f"{slug(target)}.json").read_text()))
        return self._trees[target]

    def registry_has(self, name: str, version: str) -> bool:
        if name not in self._registry:
            from fallout.resolve import packuments

            # Use a worker thread, because System C also calls the grader from inside its event loop.
            with ThreadPoolExecutor(1) as ex:
                doc = ex.submit(asyncio.run, packuments({name})).result().get(name) or {}
            self._registry[name] = set(doc.get("versions", {}))
        return version in self._registry[name]

    def grade(self, unit: str, target: str, path: list[str], exposed: bool) -> dict[str, Any]:
        u = self.units[unit]
        tree = self.tree(target)
        hops = [h for h in (split(p) for p in path if not p.startswith("repo:")) if h]
        bad_nodes = [
            f"{n}@{v}"
            for n, v in hops
            if f"{n}@{v}" not in tree.nodes
            and v not in u["affected"].get(n, [])
            and not self.registry_has(n, v)
        ]
        bad_edges = []
        prev = "ROOT"
        for i, (n, v) in enumerate(hops):
            last = i == len(hops) - 1 and v in u["affected"].get(n, [])
            if not tree.has_edge(prev, n, v, u["mode"] if last else None):
                bad_edges.append(f"{prev} -> {n}@{v}")
            prev = f"{n}@{v}"
        ends_affected = bool(hops) and hops[-1][1] in u["affected"].get(hops[-1][0], [])
        return {
            "nodes_cited": len(hops),
            "nodes_hallucinated": len(bad_nodes),
            "edges_cited": len(hops),
            "edges_hallucinated": len(bad_edges),
            "bad_nodes": bad_nodes,
            "bad_edges": bad_edges,
            "path_valid": bool(hops) and not bad_edges and ends_affected,
            "unparsed": len(path) - len(hops),
        }

    def path_cause(self, unit: str, target: str, grade: dict[str, Any]) -> str:
        """Explains why the path in an exposed answer is not a path that npm would install."""
        tree = self.tree(target)
        for e in grade["bad_edges"]:
            src, dst = e.split(" -> ")
            n = (split(dst) or ("", ""))[0]
            if src != "ROOT" and src not in tree.nodes:
                return f"`{src}` is not in npm's tree: an earlier hop resolved differently (limitations 4, 9)"
            for edge in tree.edges.get(src, []):
                if (edge.get("toPackage") or edge["name"]) != n:
                    continue
                if edge.get("type") in ("peer", "peerOptional"):
                    return (
                        f"peer `{n}`: npm installs {edge.get('to')}; the graph resolves the range alone "
                        "(limitation 9)"
                    )
                to = f"{n}@{edge.get('to')}"
                return f"npm installs `{to}` under `{src}` (spec `{edge['spec']}`): override/dedupe"
        return "path does not end at an affected version"

    def cause(self, unit: str, target: str, pred: bool | None, path: list[str] | None = None) -> str:
        """Gives a probable reason why the graph disagrees with npm, for the error analysis in the README."""
        gold = self.oracle[(unit, target)]
        if pred is None:
            return "no answer"
        tree = self.tree(target)
        if pred and not gold["oracle_exposed"]:
            off = [p for p in (path or []) if split(p) and p.removeprefix("npm:") not in tree.nodes]
            if off:
                return (
                    f"graph resolved {off[0]}, npm installs another version (dedupe/peer, limitations 4, 9)"
                )
            if target.startswith("repo:"):
                return "npm applies the repo's overrides while resolving (limitation 10)"
            return "graph path exists in npm's tree but the edge spec does not admit the version"
        hops = gold["oracle_paths"][0] if gold["oracle_paths"] else []
        if any(h.get("type") == "peer" for h in hops):
            return "oracle path goes through a peer dependency (limitation 9)"
        chain = " > ".join(f"{h['name']}@{h['version']}" for h in hops)
        return f"graph misses npm's path {chain} (resolution approximation, limitations 1–3)"
