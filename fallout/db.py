"""FalkorDB connection and the Cypher query catalogue (graph/queries/*.cypher)."""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextvars import ContextVar
from functools import cache
from typing import Any

from falkordb import FalkorDB, Graph

from fallout.settings import ROOT

QUERIES_DIR = ROOT / "graph" / "queries"
GRAPH_NAME = os.environ.get("FALLOUT_GRAPH", "fallout")


# The image defaults limit result sets to 10k rows and stop queries after 1 s. Both limits cut a
# blast radius short without an error. So every connection removes the limits, and the code
# does not rely on the container arguments.
SERVER_CONFIG = {"RESULTSET_SIZE": -1, "TIMEOUT": 0, "TIMEOUT_DEFAULT": 0, "TIMEOUT_MAX": 0}


@cache
def _db(host: str, port: int) -> FalkorDB:
    db = FalkorDB(host=host, port=port)
    for k, v in SERVER_CONFIG.items():
        db.config_set(k, v)
    return db


def graph(name: str = GRAPH_NAME) -> Graph:
    host = os.environ.get("FALKORDB_HOST", "localhost")
    port = int(os.environ.get("FALKORDB_PORT", "6380"))
    return _db(host, port).select_graph(name)


# Names of the catalogue queries that ran in the current context. Every tool reports them in
# the `cypher` field of its envelope.
_used: ContextVar[list[str] | None] = ContextVar("fallout_queries_used", default=None)


def track_queries() -> list[str]:
    """Starts to record query names in this context. Returns the list, which continues to update."""
    used: list[str] = []
    _used.set(used)
    return used


@cache
def _text(name: str) -> str:
    return (QUERIES_DIR / f"{name}.cypher").read_text()


def query(name: str) -> str:
    """Returns the text of graph/queries/<name>.cypher. All queries come from these files."""
    used = _used.get()
    if used is not None and name not in used:
        used.append(name)
    return _text(name)


def statements(name: str) -> list[str]:
    """Returns the statements of a one-statement-per-line .cypher file, without comments and blank lines."""
    lines = (ln.strip() for ln in query(name).splitlines())
    return [ln for ln in lines if ln and not ln.startswith("//")]


def rows(g: Graph, name: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Runs a catalogue query and returns its rows as dicts keyed by column name."""
    res = g.query(query(name), params or {})
    cols = [h[1] if isinstance(h, list | tuple) else h for h in res.header]
    return [dict(zip(cols, r, strict=True)) for r in res.result_set]


def batches(rows: Sequence[Any], size: int = 1000) -> Iterator[Sequence[Any]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]
