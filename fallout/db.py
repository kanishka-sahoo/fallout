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


# The image defaults cap result sets at 10k rows and kill queries after 1 s. Both truncate a
# blast radius silently, so lift them on every connect instead of trusting the container args.
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


# Names of the catalogue queries run in the current context, so every tool can report the
# Cypher behind its answer (BUILD.md §6.1 envelope).
_used: ContextVar[list[str] | None] = ContextVar("fallout_queries_used", default=None)


def track_queries() -> list[str]:
    """Start recording query names in this context; returns the (live) list."""
    used: list[str] = []
    _used.set(used)
    return used


@cache
def _text(name: str) -> str:
    return (QUERIES_DIR / f"{name}.cypher").read_text()


def query(name: str) -> str:
    """Text of graph/queries/<name>.cypher, the single source of truth for every query."""
    used = _used.get()
    if used is not None and name not in used:
        used.append(name)
    return _text(name)


def statements(name: str) -> list[str]:
    """A .cypher file holding one statement per line (comments and blanks skipped)."""
    lines = (ln.strip() for ln in query(name).splitlines())
    return [ln for ln in lines if ln and not ln.startswith("//")]


def rows(g: Graph, name: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a catalogue query and return its rows as dicts keyed by column name."""
    res = g.query(query(name), params or {})
    cols = [h[1] if isinstance(h, list | tuple) else h for h in res.header]
    return [dict(zip(cols, r, strict=True)) for r in res.result_set]


def batches(rows: Sequence[Any], size: int = 1000) -> Iterator[Sequence[Any]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]
