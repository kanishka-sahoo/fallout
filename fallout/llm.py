"""One LLM interface for the agent (api/agent.py) and the eval systems (eval/run.py).

`OpenAILLM` calls the OpenAI Responses API with the model in config/model.json. `OfflineLLM` is a
scripted planner. It selects tools by keyword and calls the same tools, with no model. It lets
the demo and the integration run without OPENAI_API_KEY. Every answer it writes has an offline
label, and the eval does not accept it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from fallout.settings import CONFIG_DIR, ROOT, SETTINGS

MODEL_CFG: dict[str, Any] = json.loads((CONFIG_DIR / "model.json").read_text())


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def add(self, other: Usage) -> None:
        for k in self.__dataclass_fields__:
            setattr(self, k, getattr(self, k) + getattr(other, k))

    def cost_usd(self) -> float | None:
        p = MODEL_CFG["price_usd_per_mtok"]
        if p["input"] is None or p["output"] is None:
            return None
        cached = p["cached_input"] if p["cached_input"] is not None else p["input"]
        fresh = self.input_tokens - self.cached_input_tokens
        return (
            fresh * p["input"] + self.cached_input_tokens * cached + self.output_tokens * p["output"]
        ) / 1e6


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    response_id: str | None = None
    raw: Any = None


@dataclass
class Conversation:
    """Provider state between turns. OpenAI uses the previous response id. OfflineLLM uses the transcript."""

    previous_response_id: str | None = None
    transcript: list[dict[str, Any]] = field(default_factory=list)


class OpenAILLM:
    name = "openai"
    offline = False

    def __init__(self, model: str | None = None, reasoning_effort: str | None = None) -> None:
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model or MODEL_CFG["model"]
        self.effort = reasoning_effort or MODEL_CFG["reasoning_effort"]

    def respond(
        self,
        conv: Conversation,
        instructions: str,
        new_input: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> Turn:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": new_input,
            "reasoning": {"effort": self.effort},
            "max_output_tokens": MODEL_CFG["max_output_tokens"],
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["parallel_tool_calls"] = False
        if schema:
            kwargs["text"] = {
                "format": {"type": "json_schema", "name": "answer", "schema": schema, "strict": True}
            }
        if conv.previous_response_id:
            kwargs["previous_response_id"] = conv.previous_response_id
        r = self.client.responses.create(**kwargs)
        conv.previous_response_id = r.id
        calls = [
            ToolCall(item.call_id, item.name, json.loads(item.arguments or "{}"))
            for item in r.output
            if item.type == "function_call"
        ]
        u = r.usage
        usage = Usage(
            input_tokens=u.input_tokens if u else 0,
            cached_input_tokens=(u.input_tokens_details.cached_tokens if u and u.input_tokens_details else 0),
            output_tokens=u.output_tokens if u else 0,
            reasoning_tokens=(
                u.output_tokens_details.reasoning_tokens if u and u.output_tokens_details else 0
            ),
        )
        return Turn(r.output_text or "", calls, usage, r.id, r)

    @staticmethod
    def tool_output(call: ToolCall, output: str) -> dict[str, Any]:
        return {"type": "function_call_output", "call_id": call.id, "output": output}

    @staticmethod
    def user(text: str) -> dict[str, Any]:
        return {"role": "user", "content": text}


# -- offline ---------------------------------------------------------------------------------------

OFFLINE_TAG = "[offline mode: scripted planner, no LLM]"


def _repo_in(text: str) -> str | None:
    names = [r.split("/", 1)[1] for r in SETTINGS["allowed_repos"]]
    for n in sorted(names, key=len, reverse=True):
        if n in text:
            return n
    return None


def _render(name: str, env: dict[str, Any]) -> str:
    r = env["result"]
    if "error" in r:
        return f"`{name}` failed: {r['error']}"
    if name == "blast_radius":
        hit = [x for x in r["repos"] if x["status"] != "NOT_AFFECTED"]
        lines = [
            f"As of S = {r['anchor_S']}, {r['exposed_versions']} versions across {r['exposed_packages']} "
            f"packages are exposed, over {len(r['hops'])} hops.",
            *(
                f"- {x['repo']}: {x['status']}"
                + (f" (hop {x['hop']}, path {x['path_id']})" if x["path_id"] else "")
                for x in hit
            ),
        ]
        return "\n".join(lines)
    if name == "exposure_path":
        lines = [f"{r['repo']} is {r['status']}: {r['status_meaning']}."]
        for p in r["per_package"]:
            path = next(q for q in env["paths"] if q["id"] == p["path_id"])
            hops = " -> ".join(
                f"{n.removeprefix('npm:')}" + (f" [{e['requirement']}]" if e else "")
                for n, e in zip(path["nodes"], [None, *path["edges"]], strict=True)
            )
            lines.append(f"- {p['package']} ({p['path_id']}): {hops}")
        return "\n".join(lines)
    if name == "repo_status":
        return "\n".join(f"- {x['repo']}: {x['status']} ({x['status_meaning']})" for x in r["repos"])
    if name == "plan_fix":
        return f"Plan {r['plan_id']} for {r['repo']} ({r['plan_status']}): {json.dumps(r['changes'])}"
    if name == "request_fix_approval":
        return r["message"]
    if name == "critical_packages":
        return "\n".join(
            f"- {p['package']} ({r['algorithm']}={p[r['algorithm']]:.4g})" for p in r["packages"]
        )
    if name == "maintainer_reach":
        return "\n".join(
            f"- {m['maintainer']}: reaches {m['reach_packages']} packages" for m in r["maintainers"]
        )
    if name == "recheck_repo":
        return f"{r['repo']} @ {r['ref']}: {r['before']['status']} -> {r['after']['status']}"
    return json.dumps(r)[:500]


class OfflineLLM:
    """Selects a fixed tool sequence from keywords in the message, then formats the results."""

    name = "offline"
    offline = True

    def __init__(self, incident: str | None = None) -> None:
        self.incident = incident or SETTINGS["replay_incident"]

    def plan(self, text: str) -> list[tuple[str, dict[str, Any]]]:
        t = text.lower()
        repo = _repo_in(t)
        inc = self.incident
        if re.search(r"\b(fix|remediate|patch)\b", t) and repo:
            return [("plan_fix", {"repo": repo, "incident_id": inc}), ("request_fix_approval", {})]
        if "recheck" in t and repo:
            return [("recheck_repo", {"repo": repo, "incident_id": inc})]
        if ("why" in t or "path" in t) and repo:
            return [("exposure_path", {"repo": repo, "incident_id": inc})]
        if "maintainer" in t:
            return [("maintainer_reach", {"k": 10})]
        if any(w in t for w in ("critical", "chokepoint", "pagerank", "betweenness")):
            algo = "betweenness" if "betweenness" in t else "pagerank"
            return [("critical_packages", {"k": 10, "algorithm": algo})]
        if "status" in t or "triage" in t:
            return [("repo_status", {"incident_id": inc, **({"repo": repo} if repo else {})})]
        if "ingest" in t:
            return [("ingest_advisory", {"incident_id": inc}), ("blast_radius", {"incident_id": inc})]
        return [("blast_radius", {"incident_id": inc})]

    def respond(
        self,
        conv: Conversation,
        instructions: str,
        new_input: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> Turn:
        if schema:
            raise RuntimeError("OfflineLLM cannot answer eval questions; set OPENAI_API_KEY")
        conv.transcript.extend(new_input)
        last_user = max(i for i, m in enumerate(conv.transcript) if m.get("role") == "user")
        steps = self.plan(conv.transcript[last_user]["content"])
        done = [m for m in conv.transcript[last_user:] if m.get("type") == "function_call_output"]
        if len(done) < len(steps):
            name, args = steps[len(done)]
            if name == "request_fix_approval":
                plan = json.loads(done[-1]["output"])["result"]
                if not plan.get("plan_id") or plan.get("plan_status") != "PENDING":
                    return self._final(conv, done, steps)
                args = {"plan_id": plan["plan_id"]}
            return Turn("", [ToolCall(f"call_{len(done)}", name, args)], Usage())
        return self._final(conv, done, steps)

    def _final(self, conv: Conversation, done: list[dict[str, Any]], steps: list[tuple[str, Any]]) -> Turn:
        parts = [OFFLINE_TAG]
        for (name, _), out in zip(steps, done, strict=False):
            parts.append(_render(name, json.loads(out["output"])))
        parts.append(
            f"Exposure definition: as of S, npm would pick an affected version. Incident {self.incident}."
        )
        text = "\n\n".join(parts)
        conv.transcript.append({"role": "assistant", "content": text})
        return Turn(text, [], Usage())

    @staticmethod
    def tool_output(call: ToolCall, output: str) -> dict[str, Any]:
        return {"type": "function_call_output", "call_id": call.id, "output": output}

    @staticmethod
    def user(text: str) -> dict[str, Any]:
        return {"role": "user", "content": text}


def get_llm(allow_offline: bool = True) -> OpenAILLM | OfflineLLM:
    load_dotenv(ROOT / ".env")
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAILLM()
    if not allow_offline:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OfflineLLM()
