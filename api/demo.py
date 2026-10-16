"""BUILD.md §10 demo script, headless, through the real API (in-process TestClient, so the
lifespan starts the MCP server exactly as uvicorn would).

    uv run python -m api.demo [--repo billing-api] [--no-approve]
    uv run python -m api.demo --reset

Step 5 clicks Approve: it opens a real PR in the demo org and rechecks the PR branch, which
leaves the graph showing that branch. `--reset` reloads every repo from its local checkout
of the default branch and recomputes the repo edges and statuses.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from fastapi.testclient import TestClient

from fallout.settings import SETTINGS


def say(step: str, text: str) -> None:
    print(f"\n=== {step}\n{text}", flush=True)


def reset() -> None:
    from fallout import tools
    from fallout.advisory import recompute_repo_edges
    from fallout.db import graph, query
    from ingest.load_repos import load_repo

    g = graph()
    inc = SETTINGS["replay_incident"]
    for full in SETTINGS["allowed_repos"]:
        load_repo(g, full)
        g.query(query("repo_ref_set"), {"key": f"repo:{full}", "ref": "local", "sha": None})
        recompute_repo_edges(g, inc, f"repo:{full}")
    env = tools.blast_radius(inc)
    print(json.dumps({r["repo"]: r["status"] for r in env["result"]["repos"]}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="billing-api")
    ap.add_argument("--no-approve", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    if args.reset:
        reset()
        return

    os.environ.setdefault("FALLOUT_CONSOLE_KEY", f"demo-{os.getpid()}")
    from api.main import app

    t0 = time.monotonic()
    with TestClient(app) as c:

        def chat(msg: str) -> dict[str, Any]:
            r = c.post("/api/chat", json={"message": msg}).raise_for_status().json()
            calls = ", ".join(t["name"] for t in r["tool_calls"])
            say(msg, f"[tools: {calls}] [cited: {r['cited_path_ids']}]\n{r['text']}")
            if r["unknown_path_ids"]:
                sys.exit(f"answer cites path ids no tool returned: {r['unknown_path_ids']}")
            return r

        chat("Ingest the chalk/debug advisories and replay the incident.")
        chat(f"Why is {args.repo} affected?")
        chat("Triage: what is the status of every repo?")
        fix = chat(f"Fix {args.repo}.")
        req = next((t for t in fix["tool_calls"] if t["name"] == "request_fix_approval"), None)
        if req is None:
            sys.exit("the agent did not request approval")
        plan_id = req["arguments"]["plan_id"]
        plan = c.get(f"/api/plans/{plan_id}").json()
        say("approval card", f"{plan_id} {plan['status']} {json.dumps(plan['body']['changes'])}")

        # Without the console session nothing can approve.
        assert c.post(f"/api/plans/{plan_id}/approve").status_code == 401

        if not args.no_approve:
            c.post("/api/session", json={"key": os.environ["FALLOUT_CONSOLE_KEY"], "user": "kanishka"})
            out = c.post(f"/api/plans/{plan_id}/approve")
            if out.status_code != 200:
                sys.exit(f"approve failed: {out.status_code} {out.text}")
            res = out.json()
            v = res["verification"]
            rc = (res.get("recheck") or {}).get("result", {})
            say(
                "approved -> apply_fix",
                f"verification ok={v['ok']} affected_found={v['affected_found']} ({v['took_ms']} ms)\n"
                f"PR: {res['pr_url']}\n"
                f"recheck: {rc.get('before', {}).get('status')} -> {rc.get('after', {}).get('status')}\n"
                f"action: {res['action_id']}",
            )
            if rc.get("after", {}).get("status") != "MITIGATED_BY_OVERRIDE":
                sys.exit("status did not flip to MITIGATED_BY_OVERRIDE")

        chat("Zoom out: which packages are the ecosystem's critical chokepoints by pagerank?")
        chat("Which maintainers have the largest reach?")
    say("done", f"{time.monotonic() - t0:.1f}s end to end")


if __name__ == "__main__":
    main()
