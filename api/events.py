"""Structured events from the agent and the API. Each event is one dict. The bus sends it to
all WebSocket subscribers and prints it to stdout in container-log format:

    2026-10-17T14:02:11.482Z fallout-agent  INFO  tool=blast_radius incident=... took_ms=441
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import deque
from datetime import UTC, datetime
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fmt_value(v: Any) -> str:
    s = v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))
    return s if len(s) <= 120 else s[:117] + "..."


def log_line(event: dict[str, Any]) -> str:
    fields = event.get("fields", {})
    if event["kind"] != "tool" and "plan" not in fields:
        fields = {"event": event["kind"], **fields}
    kv = " ".join(f"{k}={fmt_value(v)}" for k, v in fields.items() if v is not None)
    return f"{event['ts']} {event['source']:<13} {event['level']:<5} {kv}"


class EventBus:
    """In-process publish/subscribe. Keeps the last `history` events, so a console that
    connects late can replay the run."""

    def __init__(self, history: int = 2000, echo: bool = True) -> None:
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.history: deque[dict[str, Any]] = deque(maxlen=history)
        self.echo = echo

    def emit(
        self, kind: str, source: str = "fallout-agent", level: str = "INFO", data: Any = None, **fields: Any
    ) -> dict[str, Any]:
        event = {"ts": now_iso(), "kind": kind, "source": source, "level": level, "fields": fields}
        if data is not None:
            event["data"] = data
        event["line"] = log_line(event)
        self.history.append(event)
        if self.echo:
            print(event["line"], file=sys.stdout, flush=True)
        for q in list(self.subscribers):
            q.put_nowait(event)
        return event

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(q)


bus = EventBus()
