"""Fallout API (BUILD.md §2, §6): agent chat over WebSocket or HTTP, the event stream, read
endpoints for the console, and the approval endpoint that is the only way to the fix executor.

    uv run uvicorn api.main:app --port 8000

Console session: POST /api/session with the console key (FALLOUT_CONSOLE_KEY; a random key is
printed at startup when unset) sets an HttpOnly cookie. Approve requires that cookie.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

import anyio
from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from api import approval
from api.agent import Agent, ToolClient
from api.events import bus
from api.fix_executor import FixRejected, apply_fix
from fallout import fixplan
from fallout.db import graph, rows
from fallout.settings import ROOT, SETTINGS, load_anchor

load_dotenv(ROOT / ".env")
CONSOLE_KEY = os.environ.get("FALLOUT_CONSOLE_KEY") or secrets.token_urlsafe(12)
SESSION_SECRET = secrets.token_bytes(32)
COOKIE = "fallout_session"


def session_value(user: str) -> str:
    sig = hmac.new(SESSION_SECRET, user.encode(), hashlib.sha256).hexdigest()
    return f"{user}.{sig}"


def session_user(cookie: str | None) -> str | None:
    if not cookie or "." not in cookie:
        return None
    user, _ = cookie.rsplit(".", 1)
    return user if hmac.compare_digest(cookie, session_value(user)) else None


class State:
    tools: ToolClient
    agent: Agent
    lock: asyncio.Lock


state = State()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not os.environ.get("FALLOUT_CONSOLE_KEY"):
        print(f"fallout-api: console key for this run: {CONSOLE_KEY}", flush=True)
    async with ToolClient() as tc:
        state.tools, state.agent, state.lock = tc, Agent(tc), asyncio.Lock()
        bus.emit("startup", source="fallout-api", tools=len(tc.tools), llm=state.agent.llm.name)
        yield


app = FastAPI(title="Fallout", lifespan=lifespan)


class ChatIn(BaseModel):
    message: str


class SessionIn(BaseModel):
    key: str
    user: str = "console"


def agent_payload(r: Any) -> dict[str, Any]:
    return {
        "text": r.text,
        "tool_calls": [
            {"name": t.name, "arguments": t.arguments, "took_ms": t.took_ms} for t in r.tool_calls
        ],
        "cited_path_ids": r.cited_path_ids,
        "unknown_path_ids": r.unknown_path_ids,
        "paths": r.paths(),
        "usage": r.usage.__dict__,
        "took_ms": r.took_ms,
        "offline": r.offline,
    }


async def run_chat(message: str) -> dict[str, Any]:
    async with state.lock:  # one conversation, one turn at a time
        return agent_payload(await state.agent.ask(message))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "llm": state.agent.llm.name, "tools": state.tools.names, "anchor": load_anchor()["S"]}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "anchor": load_anchor(),
        "incident": SETTINGS["replay_incident"],
        "repos": SETTINGS["allowed_repos"],
        "llm": state.agent.llm.name,
    }


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict[str, Any]:
    return await run_chat(body.message)


@app.post("/api/reset")
async def reset() -> dict[str, bool]:
    async with state.lock:
        state.agent = Agent(state.tools)
    return {"ok": True}


@app.get("/api/events")
def events() -> list[dict[str, Any]]:
    return list(bus.history)


@app.post("/api/tools/{name}")
async def call_tool(name: str, request: Request) -> dict[str, Any]:
    """Direct, read-only tool calls for the console (replay bar, repo table). Same MCP server."""
    if name not in {"blast_radius", "repo_status", "exposure_path", "critical_packages", "maintainer_reach"}:
        raise HTTPException(403, "only read tools are callable directly")
    args = await request.json() if await request.body() else {}
    env = await state.tools.call(name, args)
    bus.emit("tool", tool=name, via="console", **(env.get("summary") or {}), took_ms=env.get("timing_ms"))
    return env


@app.get("/api/plans")
def plans(status: str | None = None) -> list[dict[str, Any]]:
    return [
        {**p, "body": None} | {"summary": p["body"][:2000]}
        for p in rows(graph(), "plan_list", {"status": status})
    ]


@app.get("/api/plans/{plan_id}")
def plan(plan_id: str) -> dict[str, Any]:
    p = fixplan.load(graph(), plan_id)
    if not p:
        raise HTTPException(404, "no such plan")
    return p


@app.get("/api/actions")
def actions() -> list[dict[str, Any]]:
    return rows(graph(), "action_list")


@app.post("/api/session")
def session(body: SessionIn) -> Any:
    from fastapi.responses import JSONResponse

    if not hmac.compare_digest(body.key, CONSOLE_KEY):
        raise HTTPException(401, "bad console key")
    resp = JSONResponse({"ok": True, "user": body.user})
    resp.set_cookie(COOKIE, session_value(body.user), httponly=True, samesite="strict", max_age=8 * 3600)
    return resp


@app.post("/api/plans/{plan_id}/approve")
async def approve(plan_id: str, fallout_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    user = session_user(fallout_session)
    if not user:
        raise HTTPException(401, "console session required")
    p = fixplan.load(graph(), plan_id)
    if not p:
        raise HTTPException(404, "no such plan")
    if p["status"] != fixplan.AWAITING_APPROVAL:
        raise HTTPException(409, f"plan is {p['status']}")
    token = approval.mint(plan_id, p["repo"])  # never leaves this function except into apply_fix
    bus.emit("approved", source="fallout-api", plan=plan_id, approved_by=user, step="apply_fix")
    try:
        out = await anyio.to_thread.run_sync(
            lambda: apply_fix(plan_id, p["repo"], token, user, emit=bus.emit)
        )
    except FixRejected as e:
        bus.emit("rejected", source="fallout-api", level="ERROR", plan=plan_id, reason=str(e))
        raise HTTPException(403, str(e)) from e
    bus.emit(
        "applied",
        source="fallout-api",
        plan=plan_id,
        result=out["result"],
        pr=out.get("pr_url"),
        data={k: v for k, v in out.items() if k != "recheck"}
        | {"recheck": out.get("recheck", {}).get("result")},
    )
    return out


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    q = bus.subscribe()
    try:
        await socket.send_json({"type": "history", "events": list(bus.history)})

        async def pump() -> None:
            while True:
                await socket.send_json({"type": "event", "event": await q.get()})

        async def listen() -> None:
            while True:
                msg = await socket.receive_json()
                if msg.get("type") == "chat":
                    result = await run_chat(msg["message"])
                    await socket.send_json({"type": "answer", "answer": result})

        async with anyio.create_task_group() as tg:
            tg.start_soon(pump)
            tg.start_soon(listen)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)
