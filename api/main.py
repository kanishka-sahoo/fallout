"""The Fallout API. It provides agent chat over WebSocket or HTTP, the event stream, read
endpoints for the console, and the approval endpoint. The approval endpoint is the only way
to start the fix executor.

    uv run uvicorn api.main:app --port 8000

Console session: POST /api/session with the console key sets an HttpOnly cookie. The key is
FALLOUT_CONSOLE_KEY. If it is not set, the API prints a random key at startup. The approve
endpoint requires the cookie.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
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
from fallout import fixplan, simulate
from fallout.db import graph, query, rows
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
        if rows(graph(), "incident_exists", {"incident": SETTINGS["replay_incident"]}):
            prewarm(SETTINGS["replay_incident"])
        yield


app = FastAPI(title="Fallout", lifespan=lifespan)


class ChatIn(BaseModel):
    message: str
    incident: str | None = None


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


def with_context(message: str, incident: str | None) -> str:
    """Tells the agent which incident the console has selected. The eval calls the agent
    directly, so it never sees this note."""
    if not incident or incident == SETTINGS["replay_incident"]:
        return message
    note = f"[Console: the selected incident is {incident}. Use it as incident_id unless I name another."
    if simulate.is_simulated(incident):
        note += " It is a simulated scenario of a what-if attack."
    return f"{note}]\n{message}"


async def run_chat(message: str, incident: str | None = None) -> dict[str, Any]:
    async with state.lock:  # one conversation, one turn at a time
        return agent_payload(await state.agent.ask(with_context(message, incident)))


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
    return await run_chat(body.message, body.incident)


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
    """Read-only tool calls from the console (replay bar, repo table), through the same MCP server."""
    if name not in {"blast_radius", "repo_status", "exposure_path", "critical_packages", "maintainer_reach"}:
        raise HTTPException(403, "only read-only tools can be called directly")
    args = await request.json() if await request.body() else {}
    env = await state.tools.call(name, args)
    bus.emit("tool", tool=name, via="console", **(env.get("summary") or {}), took_ms=env.get("timing_ms"))
    return env


@app.get("/api/incidents")
def incidents() -> list[dict[str, Any]]:
    return rows(graph(), "incident_list")


@app.get("/api/graph/{incident}")
def incident_graph(incident: str) -> dict[str, Any]:
    """Returns the affected versions (hop 0) and every exposed node with its BFS parent, hop and status."""
    g = graph()
    affected = rows(g, "incident_affected_graph", {"incident": incident})
    exposed = rows(g, "incident_graph", {"incident": incident})
    if not affected:
        raise HTTPException(404, f"incident {incident} is not ingested")
    return {
        "incident": incident,
        "affected": affected,
        "nodes": exposed,
        "anchor": load_anchor()["S"],
    }


# -- simulated incidents (fallout/simulate.py) ----------------------------------------------------


def scenario_error(e: Exception) -> HTTPException:
    return HTTPException(422, str(e))


@app.get("/api/packages")
def package_search(q: str = "") -> list[dict[str, Any]]:
    return simulate.search_packages(q)


@app.get("/api/packages/{name:path}/versions")
async def package_versions(name: str, range: str) -> list[dict[str, Any]]:
    try:
        return await anyio.to_thread.run_sync(lambda: simulate.matching_versions(name, range))
    except simulate.ScenarioError as e:
        raise scenario_error(e) from e


@app.get("/api/packages/{name:path}")
async def package_info(name: str) -> dict[str, Any]:
    try:
        return await anyio.to_thread.run_sync(lambda: simulate.package_info(name))
    except simulate.ScenarioError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/templates/maintainer")
def maintainer_template() -> dict[str, Any]:
    try:
        return simulate.maintainer_packages()
    except simulate.ScenarioError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/api/simulations")
async def run_simulation(request: Request) -> dict[str, Any]:
    """Stores a simulated incident, then computes its blast radius through the MCP tool, so the
    event log shows the same steps as a replay. Progress goes out as `simulate` events."""
    spec = await request.json()

    def emit(kind: str, **fields: Any) -> None:
        anyio.from_thread.run_sync(lambda: bus.emit(kind, source="fallout-api", **fields))

    bus.emit("simulate", source="fallout-api", step="prepare", scenario=spec.get("kind"))
    try:
        made = await anyio.to_thread.run_sync(lambda: simulate.create(spec, emit=emit))
    except simulate.ScenarioError as e:
        bus.emit("simulate", source="fallout-api", level="WARN", step="failed", reason=str(e))
        raise scenario_error(e) from e
    inc = made["incident"]
    bus.emit("simulate", source="fallout-api", step="blast", incident=inc, edges=made["report"]["edges"])
    blast = await state.tools.call("blast_radius", {"incident_id": inc})
    bus.emit("tool", tool="blast_radius", via="console", **(blast.get("summary") or {}))
    if "error" in (blast.get("result") or {}):
        bus.emit(
            "simulate", source="fallout-api", level="ERROR", step="failed", reason=blast["result"]["error"]
        )
        raise HTTPException(500, blast["result"]["error"])
    bus.emit("simulate", source="fallout-api", step="done", incident=inc, title=made["title"])
    prewarm(inc)
    return {**made, "blast": {k: v for k, v in blast["result"].items() if k != "repos"}}


@app.delete("/api/simulations/{incident}")
async def delete_simulation(
    incident: str, fallout_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    """Deletes a scenario. Its PRs are deleted first (closed on GitHub, removed from Fallout),
    which needs a console session."""
    if not simulate.is_simulated(incident):
        raise HTTPException(403, "Only simulated incidents can be deleted.")
    open_prs = await anyio.to_thread.run_sync(lambda: fallout_prs(incident))
    if open_prs:
        require_user(fallout_session)
        for p in open_prs:
            out = await anyio.to_thread.run_sync(close_one, p["pr_url"])
            forget_events(p["pr_url"], out["plan_id"], out["branch"])
    try:
        await anyio.to_thread.run_sync(lambda: simulate.delete(incident))
    except simulate.ScenarioError as e:
        raise HTTPException(403, str(e)) from e
    bus.emit(
        "simulate", source="fallout-api", step="deleted", incident=incident, closed_prs=len(open_prs) or None
    )
    return {"ok": True, "closed_prs": len(open_prs)}


_plans: dict[str, tuple[str, dict[str, Any]]] = {}  # incident -> (plan_key, response plan)
_background: set[asyncio.Task[Any]] = set()


def prewarm(incident: str) -> None:
    """Plans the fixes in the background, so the response plan is ready when the console asks."""

    async def run() -> None:
        try:
            await cached_response(incident)
        except Exception as e:  # noqa: BLE001 - a failed prewarm only means the first request is slow
            bus.emit("response_plan", source="fallout-api", level="WARN", incident=incident, error=str(e))

    task = asyncio.get_running_loop().create_task(run())
    _background.add(task)
    task.add_done_callback(_background.discard)


async def cached_response(incident: str) -> tuple[dict[str, Any], bool]:
    key = await anyio.to_thread.run_sync(lambda: simulate.plan_key(incident))
    hit = _plans.get(incident)
    if hit and hit[0] == key:
        return hit[1], True
    out = await anyio.to_thread.run_sync(lambda: simulate.response_plan(incident))
    _plans[incident] = (key, out)
    return out, False


@app.get("/api/response/{incident}")
async def response_plan(incident: str) -> dict[str, Any]:
    """Fix previews for every repo that needs action, from the same planner as plan_fix. Nothing
    is stored in the graph. The result is cached until the blast radius or a repo status changes."""
    if not rows(graph(), "incident_exists", {"incident": incident}):
        raise HTTPException(404, f"incident {incident} is not ingested")
    t0 = asyncio.get_running_loop().time()
    out, cached = await cached_response(incident)
    took = round((asyncio.get_running_loop().time() - t0) * 1000)
    bus.emit(
        "response_plan",
        source="fallout-api",
        incident=incident,
        needs_action=out["needs_action"],
        cached=cached or None,
        took_ms=took,
    )
    return out


@app.post("/api/replay/{incident}")
async def replay(incident: str) -> dict[str, Any]:
    """Ingests the advisories again and recomputes the blast radius. This goes through the MCP
    tools, so the event log shows the same tool calls that the agent makes."""
    ing = await state.tools.call("ingest_advisory", {"incident_id": incident})
    bus.emit("tool", tool="ingest_advisory", via="console", **(ing.get("summary") or {}))
    blast = await state.tools.call("blast_radius", {"incident_id": incident})
    bus.emit("tool", tool="blast_radius", via="console", **(blast.get("summary") or {}))
    prewarm(incident)
    return {"ingest": ing["result"], "blast": blast["result"]}


@app.get("/api/results")
def results() -> Any:
    path = ROOT / "eval" / "results.json"
    if not path.exists():
        raise HTTPException(404, "no eval results yet. Run python -m eval.run")
    import json

    return json.loads(path.read_text())


@app.get("/api/plans")
def plans(status: str | None = None) -> list[dict[str, Any]]:
    import json

    return [{**p, "body": json.loads(p["body"])} for p in rows(graph(), "plan_list", {"status": status})]


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


def thread_emit(kind: str, **fields: Any) -> None:
    """bus.emit for code that runs in a worker thread. The event queues belong to the event loop."""
    anyio.from_thread.run_sync(lambda: bus.emit(kind, **fields))


def require_user(cookie: str | None) -> str:
    user = session_user(cookie)
    if not user:
        raise HTTPException(401, "console session required")
    return user


async def run_fix(plan_id: str, repo: str, user: str) -> dict[str, Any]:
    """Mints the single-use token and runs the fix executor. Only a console click reaches this."""
    token = approval.mint(plan_id, repo)  # the token goes only to apply_fix
    bus.emit("approved", source="fallout-api", plan=plan_id, approved_by=user, step="apply_fix")
    try:
        out = await anyio.to_thread.run_sync(lambda: apply_fix(plan_id, repo, token, user, emit=thread_emit))
    except FixRejected as e:
        bus.emit("rejected", source="fallout-api", level="ERROR", plan=plan_id, reason=str(e))
        raise HTTPException(403, str(e)) from e
    except Exception as e:
        bus.emit("rejected", source="fallout-api", level="ERROR", plan=plan_id, reason=str(e))
        raise HTTPException(502, f"the fix did not finish: {e}") from e
    bus.emit(
        "applied",
        source="fallout-api",
        plan=plan_id,
        result=out["result"],
        pr=out.get("pr_url"),
        data={k: v for k, v in out.items() if k != "recheck"}
        | {"recheck": out.get("recheck", {}).get("result")},
    )
    return {**out, "plan_id": plan_id}


@app.post("/api/plans/{plan_id}/approve")
async def approve(plan_id: str, fallout_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    user = require_user(fallout_session)
    p = fixplan.load(graph(), plan_id)
    if not p:
        raise HTTPException(404, "no such plan")
    if p["status"] != fixplan.AWAITING_APPROVAL:
        raise HTTPException(409, f"plan is {p['status']}")
    return await run_fix(plan_id, p["repo"], user)


class FixIn(BaseModel):
    incident: str
    repo: str


@app.post("/api/fix")
async def one_click_fix(body: FixIn, fallout_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Create PR in one click: plans the fix, puts it up for approval, and approves it as the
    console user who clicked. The agent has no path to this endpoint."""
    user = require_user(fallout_session)
    full = body.repo.removeprefix("repo:")
    if full not in SETTINGS["allowed_repos"]:
        raise HTTPException(403, f"{full} is not in config.allowed_repos")
    g = graph()
    if not rows(g, "incident_exists", {"incident": body.incident}):
        raise HTTPException(404, f"incident {body.incident} is not ingested")
    key = f"repo:{full}"

    def make_plan() -> str:
        from fallout.tools import checkout_dir

        manifest = json.loads((checkout_dir(full) / "package.json").read_text())
        plan = fixplan.plan_repo(g, body.incident, key, manifest)
        if not plan["fixable"]:
            reasons = "; ".join(p["reason"] for p in plan["packages"] if p.get("reason")) or "nothing to fix"
            raise HTTPException(409, f"no fix for {full}: {reasons}")
        plan_id = fixplan.store(g, plan)
        fixplan.transition(g, plan_id, [fixplan.PENDING], fixplan.AWAITING_APPROVAL)
        return plan_id

    bus.emit("plan", source="fallout-api", repo=full, incident=body.incident, step="plan_fix", via="console")
    plan_id = await anyio.to_thread.run_sync(make_plan)
    return await run_fix(plan_id, key, user)


def fallout_prs(incident: str | None = None) -> list[dict[str, Any]]:
    """Every PR that Fallout opened, newest first, with its live state on GitHub."""
    from api import github_pr

    acts = rows(graph(), "action_list")
    opened = [
        a
        for a in acts
        if a["type"] == "OPEN_PR" and a["pr_url"] and (incident is None or a["incident"] == incident)
    ]
    states = github_pr.pr_states([a["pr_url"] for a in opened])
    return [
        {
            "pr_url": a["pr_url"],
            "number": int(a["pr_url"].rsplit("/", 1)[1]),
            "repo": a["repo"],
            "incident": a["incident"],
            "plan_id": a["plan_id"],
            "created_at": a["created_at"],
            "approved_by": a["approved_by"],
            "state": states[a["pr_url"]],
        }
        for a in opened
    ]


@app.get("/api/prs")
async def list_prs(incident: str | None = None) -> list[dict[str, Any]]:
    return await anyio.to_thread.run_sync(lambda: fallout_prs(incident))


class CloseIn(BaseModel):
    pr_url: str


def close_one(pr_url: str) -> dict[str, Any]:
    """Deletes a Fallout PR as far as anything can: closes it on GitHub, deletes its branch,
    removes its Action and Plan nodes, and reloads the repo from its default branch for every
    incident. GitHub has no API to delete a pull request, so the closed PR stays there."""
    from api import github_pr
    from api.fix_executor import recheck_everywhere

    acts = [a for a in rows(graph(), "action_list") if a["pr_url"] == pr_url]
    if not acts:
        raise HTTPException(404, "Fallout did not open this pull request")
    plan_id = next((a["plan_id"] for a in acts if a["plan_id"]), None)
    try:
        gone = github_pr.close_pr(pr_url)
    except github_pr.RepoNotAllowed as e:
        raise HTTPException(403, str(e)) from e
    graph().query(query("pr_forget"), {"pr_url": pr_url, "plan": plan_id})
    recheck_everywhere(gone["repo"], None)
    return {"ok": True, **gone, "plan_id": plan_id}


def forget_events(*needles: str | None) -> None:
    """Drops every logged event that mentions the PR or its plan, so the Activity log shows no trace."""
    marks = [n for n in needles if n]
    keep = [e for e in bus.history if not any(m in json.dumps(e) for m in marks)]
    bus.history.clear()
    bus.history.extend(keep)


@app.post("/api/prs/close")
async def close_pr(body: CloseIn, fallout_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    require_user(fallout_session)
    try:
        out = await anyio.to_thread.run_sync(lambda: close_one(body.pr_url))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"could not delete the pull request: {e}") from e
    forget_events(body.pr_url, out["plan_id"], out["branch"])
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
                    result = await run_chat(msg["message"], msg.get("incident"))
                    await socket.send_json({"type": "answer", "answer": result})

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(pump)
                tg.start_soon(listen)
        except* WebSocketDisconnect:
            pass  # the console closed the tab
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)


# Serves the built console (web/dist) if it exists. It is mounted last, so /api and /ws take precedence.
_DIST = ROOT / "web" / "dist"
if _DIST.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_DIST, html=True), name="console")
