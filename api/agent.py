"""The agent loop (BUILD.md §6.1): LLM -> MCP call_tool -> result -> LLM, at most 12 tool calls
per turn. Tools come from the fallout-tools MCP server over stdio, so the model's tool
choice is literally MCP tool selection. Every call is emitted as a structured event.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from api.events import EventBus, bus
from fallout.llm import MODEL_CFG, Conversation, OfflineLLM, OpenAILLM, Usage, get_llm
from fallout.settings import ROOT, SETTINGS, load_anchor

PATH_ID = re.compile(r"\bp_[0-9a-f]{10}\b")


def system_prompt() -> str:
    S = load_anchor()["S"]
    repos = ", ".join(SETTINGS["allowed_repos"])
    return f"""You are Fallout, an npm supply-chain incident agent. Your tools query a FalkorDB graph of
the npm ecosystem as it stood at the anchor S = {S}, plus the demo repos ({repos}).
The default incident is {SETTINGS["replay_incident"]} (the 8 Sep 2025 chalk/debug compromise).

Rules (mandatory):
1. Answer exposure, path, ranking and fix questions ONLY from tool results. Never use your own
   knowledge of package versions or dependency trees.
2. Every claim about a package, version or edge cites a path id (p_xxxxxxxxxx) returned by a tool
   in this conversation. Anything no tool returned is reported as unknown.
3. To change a repo: call plan_fix, then request_fix_approval, then tell the user the fix awaits
   approval in the console. You cannot apply fixes or open pull requests.
4. When giving exposure answers, state the anchor S and the exposure definition: a target is
   exposed when the version npm would pick for some requirement on its tree is an affected version.
5. "Replay" an incident means ingest_advisory, then blast_radius. If a tool says the blast
   radius is missing, call blast_radius first.
Be concise: lead with the answer, then the cited path(s) with the requirement on each hop."""


class ToolClient:
    """One long-lived MCP stdio session to mcp_server.server."""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self.client: Client | None = None
        self.tools: list[dict[str, Any]] = []

    async def __aenter__(self) -> ToolClient:
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"],
            cwd=str(ROOT),
            # No GitHub token in the tool server's environment: nothing LLM-visible can write to GitHub.
            env={
                "FALLOUT_GH_TOKEN": "",
                **{
                    k: v
                    for k in ("FALKORDB_HOST", "FALKORDB_PORT", "FALLOUT_GRAPH")
                    if (v := os.environ.get(k))
                },
            },
        )
        self.client = await self._stack.enter_async_context(Client(params))
        listed = await self.client.list_tools()
        self.tools = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description or "",
                "parameters": t.input_schema,
            }
            for t in listed.tools
        ]
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._stack:
            await self._stack.aclose()

    @property
    def names(self) -> list[str]:
        return [t["name"] for t in self.tools]

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        assert self.client is not None
        r = await self.client.call_tool(name, args)
        sc = getattr(r, "structured_content", None) or getattr(r, "structuredContent", None)
        if sc is not None:
            return sc.get("result", sc) if set(sc) == {"result"} and isinstance(sc["result"], dict) else sc
        text = "".join(getattr(c, "text", "") for c in r.content)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "result": {"error": text or "tool returned nothing"},
                "paths": [],
                "cypher": [],
                "timing_ms": 0,
            }


@dataclass
class ToolRecord:
    name: str
    arguments: dict[str, Any]
    envelope: dict[str, Any]
    took_ms: int


@dataclass
class AgentResult:
    text: str
    tool_calls: list[ToolRecord] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    cited_path_ids: list[str] = field(default_factory=list)
    unknown_path_ids: list[str] = field(default_factory=list)
    hit_tool_limit: bool = False
    took_ms: int = 0
    offline: bool = False

    def paths(self) -> dict[str, dict[str, Any]]:
        return {p["id"]: p for t in self.tool_calls for p in t.envelope.get("paths", [])}


def llm_view(envelope: dict[str, Any]) -> str:
    """What the model sees of a tool result: everything but the timing noise."""
    return json.dumps({k: envelope.get(k) for k in ("result", "paths", "cypher")}, separators=(",", ":"))


class Agent:
    def __init__(
        self,
        tools: ToolClient,
        llm: OpenAILLM | OfflineLLM | None = None,
        events: EventBus = bus,
        max_tool_calls: int | None = None,
    ) -> None:
        self.tools = tools
        self.llm = llm or get_llm()
        self.events = events
        self.max_tool_calls = max_tool_calls or MODEL_CFG["max_tool_calls_per_turn"]
        self.conv = Conversation()

    async def ask(
        self,
        message: str,
        session: str = "console",
        schema: dict[str, Any] | None = None,
        instructions: str | None = None,
    ) -> AgentResult:
        """One user turn. `schema` asks for a structured final answer (the eval)."""
        t0 = time.monotonic()
        out = AgentResult(text="", offline=self.llm.offline)
        instructions = instructions or system_prompt()
        pending: list[dict[str, Any]] = [self.llm.user(message)]
        self.events.emit("user", session=session, chars=len(message), data={"message": message})
        while True:
            turn = await anyio.to_thread.run_sync(
                self.llm.respond, self.conv, instructions, pending, self.tools.tools, schema
            )
            out.usage.add(turn.usage)
            if not turn.tool_calls:
                out.text = turn.text
                break
            pending = []
            for call in turn.tool_calls:
                if len(out.tool_calls) >= self.max_tool_calls:
                    out.hit_tool_limit = True
                    pending.append(
                        self.llm.tool_output(call, json.dumps({"error": "tool call limit reached"}))
                    )
                    continue
                c0 = time.monotonic()
                env = await self.tools.call(call.name, call.arguments)
                took = round((time.monotonic() - c0) * 1000)
                out.tool_calls.append(ToolRecord(call.name, call.arguments, env, took))
                level = "WARN" if "error" in (env.get("result") or {}) else "INFO"
                self.events.emit(
                    "tool",
                    level=level,
                    tool=call.name,
                    **(env.get("summary") or {}),
                    took_ms=took,
                    data={"name": call.name, "arguments": call.arguments, "envelope": env},
                )
                if call.name == "request_fix_approval" and level == "INFO":
                    self._approval_card(env["result"])
                pending.append(self.llm.tool_output(call, llm_view(env)))
            if out.hit_tool_limit and not pending:
                break

        known = set(out.paths())
        out.cited_path_ids = sorted(set(PATH_ID.findall(out.text)))
        out.unknown_path_ids = [p for p in out.cited_path_ids if p not in known]
        out.took_ms = round((time.monotonic() - t0) * 1000)
        self.events.emit(
            "answer",
            level="WARN" if out.unknown_path_ids else "INFO",
            tool_calls=len(out.tool_calls),
            cited=len(out.cited_path_ids),
            uncited_ids=out.unknown_path_ids or None,
            tokens_in=out.usage.input_tokens,
            tokens_out=out.usage.output_tokens,
            took_ms=out.took_ms,
            data={"text": out.text, "cited_path_ids": out.cited_path_ids, "offline": out.offline},
        )
        return out

    def _approval_card(self, result: dict[str, Any]) -> None:
        from fallout import fixplan
        from fallout.db import graph

        plan = fixplan.load(graph(), result["plan_id"])
        self.events.emit(
            "approval_request",
            source="fallout-api",
            level="WARN",
            plan=result["plan_id"],
            repo=result["repo"],
            status=result["plan_status"],
            data={"plan": plan},
        )
