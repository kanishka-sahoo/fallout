"""FalkorDB connection and the Cypher query catalogue (graph/queries/*.cypher)."""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from functools import cache
from typing import Any

from falkordb import FalkorDB, Graph

from fallout.settings import ROOT

QUERIES_DIR = ROOT / "graph" / "queries"
GRAPH_NAME = os.environ.get("FALLOUT_GRAPH", "fallout")


def graph(name: str = GRAPH_NAME) -> Graph:
    host = os.environ.get("FALKORDB_HOST", "localhost")
    port = int(os.environ.get("FALKORDB_PORT", "6380"))
    return FalkorDB(host=host, port=port).select_graph(name)


@cache
def query(name: str) -> str:
    """Text of graph/queries/<name>.cypher, the single source of truth for every query."""
    return (QUERIES_DIR / f"{name}.cypher").read_text()


def statements(name: str) -> list[str]:
    """A .cypher file holding one statement per line (comments and blanks skipped)."""
    lines = (ln.strip() for ln in query(name).splitlines())
    return [ln for ln in lines if ln and not ln.startswith("//")]


def batches(rows: Sequence[Any], size: int = 1000) -> Iterator[Sequence[Any]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]
