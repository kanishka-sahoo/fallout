"""Eval runner (BUILD.md §8): score the systems on the sampled pairs against the oracle.

Systems (same model, same question, same answer schema `{exposed, path}`):
  A  LLM only, no tools
  B  LLM + the target's package-lock.json in context (repo: its own lockfile; package: the
     lockfile the oracle's arborist tree produces at S), compacted, then truncated
     deterministically to the context budget
  C  Fallout: the agent with the MCP tools over FalkorDB
  G  diagnostic, no LLM: the graph tools' own answer (exposure_path), so the graph's error is
     separated from the agent's. Runs without an API key.

Grading never touches FalkorDB: labels, trees and lockfiles come from the oracle, versions
from the registry cache.

    uv run python -m eval.run [--systems A,B,C,G] [--limit N] [--jobs 6]

Writes eval/runs/<run_id>/ (config, every prompt and answer), eval/results.{json,md,png}.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv

from eval.dataset import EVAL, TREES, slug
from eval.dataset import OUT as DATASET_PATH
from eval.grade import Grader
from eval.sample import OUT as SAMPLE_PATH
from fallout.llm import MODEL_CFG, Conversation, Usage
from fallout.settings import ROOT, load_anchor
from ingest.repo_seeds import REPOS_DIR

RUNS = EVAL / "runs"
RESULTS_JSON, RESULTS_MD, RESULTS_PNG = EVAL / "results.json", EVAL / "results.md", EVAL / "results.png"
LOCK_BUDGET_CHARS = 240_000  # ~60k tokens of lockfile, well inside the model's window

ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "exposed": {"type": "boolean"},
        "path": {
            "type": "array",
            "items": {"type": "string"},
            "description": "name@version hops from the target's first dependency (for a package "
            "target: the target itself) down to the affected version; empty when not exposed",
        },
    },
    "required": ["exposed", "path"],
}

SYSTEMS = {
    "A": "LLM only",
    "B": "LLM + lockfile in context",
    "C": "Fallout (graph agent, MCP tools)",
    "G": "Graph tools, no LLM (diagnostic)",
}


def describe_unit(unit: dict[str, Any]) -> str:
    lines = [f"{unit['title']} — advisories: {', '.join(unit['advisories'])} ({unit['kind'].lower()})."]
    for pkg, vs in unit["affected"].items():
        lines.append(f"  affected {pkg}: {', '.join(vs)}")
    return "\n".join(lines)


def question(unit: dict[str, Any], target: str, S: str) -> str:
    kind = "repository" if target.startswith("repo:") else "npm package"
    name = target.removeprefix("repo:").removeprefix("npm:")
    rule = (
        "a requirement on its resolved dependency tree admits (would let npm pick) one of the "
        "affected versions; the malicious versions are treated as published"
        if unit["kind"] == "MALICIOUS"
        else "its resolved dependency tree (as npm would install it at S, ignoring any lockfile "
        "for packages) contains one of the affected versions"
    )
    return (
        f"Anchor time S = {S}. Is the {kind} `{name}` exposed to this advisory set as of S?\n"
        f"{describe_unit(unit)}\n"
        f"Exposed means: {rule}. Dev dependencies of dependencies do not count.\n"
        "Answer with JSON {exposed, path}. `path` lists name@version hops from the target's first "
        "dependency (for a package target, start with the target itself) to the affected version."
    )


def compact_lock(lock: dict[str, Any]) -> str:
    """Keep what resolution needs (path, version, dependency ranges); drop integrity noise."""
    keep = ("version", "dependencies", "optionalDependencies", "peerDependencies", "dev", "optional", "peer")
    pkgs = lock.get("packages") or {}
    if pkgs:
        slim = {path: {k: e[k] for k in keep if k in e} for path, e in pkgs.items()}
        return json.dumps(
            {"lockfileVersion": lock.get("lockfileVersion"), "packages": slim}, separators=(",", ":")
        )
    return json.dumps(lock, separators=(",", ":"))


def lockfile_for(target: str) -> tuple[str, bool]:
    if target.startswith("repo:"):
        p = REPOS_DIR / target.removeprefix("repo:") / "package-lock.json"
        if not p.exists():
            return "(this repository has no package-lock.json; its package.json follows)\n" + (
                REPOS_DIR / target.removeprefix("repo:") / "package.json"
            ).read_text(), False
    else:
        p = TREES / f"{slug(target)}.lock.json"
    text = compact_lock(json.loads(p.read_text()))
    if len(text) <= LOCK_BUDGET_CHARS:
        return text, False
    return text[:LOCK_BUDGET_CHARS] + "\n…[truncated]", True


def normalize_path(target: str, path: list[str]) -> list[str]:
    """One path convention for every system: hops start below a repo, and at the target itself
    for a package target (models often drop that first hop; the convention is not the skill)."""
    hops = [h.removeprefix("npm:") for h in path if not h.startswith("repo:")]
    if target.startswith("npm:") and hops and hops[0] != target.removeprefix("npm:"):
        hops.insert(0, target.removeprefix("npm:"))
    return hops


def parse_answer(text: str) -> dict[str, Any] | None:
    try:
        a = json.loads(text)
        return {"exposed": bool(a["exposed"]), "path": [str(x) for x in a.get("path", [])]}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


# -- systems ---------------------------------------------------------------------------------------


def run_llm_only(item: dict[str, Any], with_lock: bool) -> dict[str, Any]:
    from fallout.llm import OpenAILLM

    llm = OpenAILLM()
    instructions = (
        "You are evaluating npm supply-chain exposure. Use only the information given and your "
        "own knowledge. Return the JSON answer."
    )
    prompt, truncated = item["question"], False
    if with_lock:
        lock, truncated = lockfile_for(item["target"])
        prompt += f"\n\nThe target's package-lock.json (compacted):\n{lock}"
    t0 = time.monotonic()
    turn = llm.respond(Conversation(), instructions, [llm.user(prompt)], None, ANSWER_SCHEMA)
    return {
        "prompt": prompt if not with_lock else item["question"] + f"\n\n[lockfile: {len(prompt)} chars]",
        "raw": turn.text,
        "answer": parse_answer(turn.text),
        "usage": turn.usage.__dict__,
        "latency_ms": round((time.monotonic() - t0) * 1000),
        "truncated": truncated,
        "tool_calls": [],
    }


async def run_agent(items: list[dict[str, Any]], jobs: int, sink: Any) -> None:
    from api.agent import Agent, ToolClient, system_prompt
    from api.events import EventBus
    from fallout.llm import OpenAILLM

    sem = asyncio.Semaphore(jobs)
    quiet = EventBus(echo=False)
    async with ToolClient() as tc:

        async def one(item: dict[str, Any]) -> None:
            async with sem:
                agent = Agent(tc, OpenAILLM(), events=quiet)
                instr = (
                    system_prompt()
                    + "\n\nEval mode: the advisory set is already ingested as incident "
                    + f"`{item['incident']}`; "
                    "its blast radius is stored. Use exposure_path (repo=... or package=name@version) and "
                    "answer with the JSON schema. Copy the path from a tool path's nodes as name@version: "
                    "drop a leading repo:… node, but keep a package target itself as the first hop. "
                    "For a repo, prefer a per_package path with mitigated=false."
                )
                t0 = time.monotonic()
                rec: dict[str, Any]
                try:
                    r = await agent.ask(
                        item["question"], session="eval", schema=ANSWER_SCHEMA, instructions=instr
                    )
                    rec = {
                        "raw": r.text,
                        "answer": parse_answer(r.text),
                        "usage": r.usage.__dict__,
                        "tool_calls": [{"name": t.name, "arguments": t.arguments} for t in r.tool_calls],
                        "hit_tool_limit": r.hit_tool_limit,
                    }
                except Exception as e:  # recorded, scored as no answer
                    rec = {
                        "raw": f"ERROR {type(e).__name__}: {e}",
                        "answer": None,
                        "usage": Usage().__dict__,
                        "tool_calls": [],
                    }
                rec["latency_ms"] = round((time.monotonic() - t0) * 1000)
                rec["prompt"] = item["question"]
                sink(item, rec)

        await asyncio.gather(*(one(i) for i in items))


def run_graph(item: dict[str, Any]) -> dict[str, Any]:
    from fallout import tools

    t0 = time.monotonic()
    t = item["target"]
    kw = {"repo": t.removeprefix("repo:")} if t.startswith("repo:") else {"package": t.removeprefix("npm:")}
    env = tools.exposure_path(incident_id=item["incident"], **kw)
    res = env["result"]
    path: list[str] = []
    if res.get("exposed") and env["paths"]:
        # Prefer a per-package path no override mitigates: that is the route npm still takes.
        live = [p["path_id"] for p in res.get("per_package", []) if not p["mitigated"]]
        by_id = {p["id"]: p for p in env["paths"]}
        chosen = by_id[live[0]] if live and live[0] in by_id else env["paths"][0]
        path = [n.removeprefix("npm:") for n in chosen["nodes"] if not n.startswith("repo:")]
    return {
        "prompt": None,
        "raw": json.dumps(res)[:2000],
        "answer": {"exposed": bool(res.get("exposed")), "path": path} if "error" not in res else None,
        "usage": Usage().__dict__,
        "latency_ms": round((time.monotonic() - t0) * 1000),
        "tool_calls": [{"name": "exposure_path", "arguments": kw}],
    }


# -- metrics ---------------------------------------------------------------------------------------


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(1 for r in records if r["pred"] is True and r["gold"])
    fp = sum(1 for r in records if r["pred"] is True and not r["gold"])
    fn = sum(1 for r in records if r["pred"] is not True and r["gold"])
    tn = sum(1 for r in records if r["pred"] is False and not r["gold"])
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * prec * rec / (prec + rec)
        if prec and rec
        else 0.0
        if prec is not None and rec is not None
        else None
    )
    cited = [r for r in records if r["grade"]["nodes_cited"]]
    nodes = sum(r["grade"]["nodes_cited"] for r in records)
    bad_nodes = sum(r["grade"]["nodes_hallucinated"] for r in records)
    edges = sum(r["grade"]["edges_cited"] for r in records)
    bad_edges = sum(r["grade"]["edges_hallucinated"] for r in records)
    paths = [r for r in records if r["pred"] is True and r["grade"]["nodes_cited"]]
    usage = Usage()
    for r in records:
        usage.add(Usage(**r["usage"]))
    lat = [r["latency_ms"] for r in records]
    cost = usage.cost_usd()
    return {
        "n": len(records),
        "answered": sum(1 for r in records if r["pred"] is not None),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "accuracy": (tp + tn) / len(records) if records else None,
        "hallucinated_node_rate": bad_nodes / nodes if nodes else None,
        "hallucinated_edge_rate": bad_edges / edges if edges else None,
        "answers_with_hallucination": (
            sum(1 for r in cited if r["grade"]["nodes_hallucinated"] or r["grade"]["edges_hallucinated"])
            / len(cited)
            if cited
            else None
        ),
        "path_validity": sum(1 for r in paths if r["grade"]["path_valid"]) / len(paths) if paths else None,
        "paths_cited": len(paths),
        "latency_p50_ms": pct(lat, 0.5),
        "latency_p95_ms": pct(lat, 0.95),
        "tokens_in_per_q": usage.input_tokens / len(records) if records else None,
        "tokens_out_per_q": usage.output_tokens / len(records) if records else None,
        "cost_usd_per_q": cost / len(records) if cost is not None and records else None,
        "truncated_rate": (sum(1 for r in records if r.get("truncated")) / len(records)) if records else None,
    }


def fmt(v: Any, kind: str = "f") -> str:
    if v is None:
        return "—"
    if kind == "%":
        return f"{v:.1%}"
    if kind == "ms":
        return f"{v / 1000:.1f}s" if v >= 1000 else f"{v:.0f}ms"
    if kind == "$":
        return f"${v:.4f}"
    if kind == "int":
        return f"{v:,.0f}"
    return f"{v:.3f}"


def write_results(
    run_id: str, cfg: dict[str, Any], by_sys: dict[str, list[dict[str, Any]]], data: dict[str, Any]
) -> None:
    summary = {s: summarize(rs) for s, rs in by_sys.items()}
    per_unit = {
        s: {u: summarize([r for r in rs if r["unit"] == u]) for u in sorted({r["unit"] for r in rs})}
        for s, rs in by_sys.items()
    }
    disagreements = [
        {k: r[k] for k in ("unit", "target", "gold", "pred", "path", "cause")}
        for r in by_sys.get("G", []) + by_sys.get("C", [])
        if r["pred"] != r["gold"]
    ]
    RESULTS_JSON.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "config": cfg,
                "summary": summary,
                "per_unit": per_unit,
                "disagreements": disagreements,
            },
            indent=1,
        )
    )

    ran = [s for s in SYSTEMS if s in by_sys]
    L = [
        "# Eval results",
        "",
        f"Generated by `eval/run.py`, run `{run_id}`. Anchor S = `{cfg['S']}`. "
        f"{cfg['n_pairs']} sampled (advisory unit, target) pairs over {cfg['n_units']} units, "
        f"{cfg['positives']} positive by the oracle. Model: `{cfg['model']}` (reasoning effort "
        f"`{cfg['reasoning_effort']}`).",
        "",
        "Ground truth: npm's arborist `buildIdealTree` at S (eval/oracle/oracle.mjs); hallucinations are "
        "checked against the oracle tree and the registry cache, never against FalkorDB.",
        "",
        "| System | Precision | Recall | F1 | Hallucinated nodes | Hallucinated edges | Path validity "
        "| p50 | p95 | tokens in/q | cost/q |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in ran:
        m = summary[s]
        L.append(
            f"| {s}. {SYSTEMS[s]} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} | "
            f"{fmt(m['hallucinated_node_rate'], '%')} | {fmt(m['hallucinated_edge_rate'], '%')} | "
            f"{fmt(m['path_validity'], '%')} | {fmt(m['latency_p50_ms'], 'ms')} | "
            f"{fmt(m['latency_p95_ms'], 'ms')} | "
            f"{fmt(m['tokens_in_per_q'], 'int')} | {fmt(m['cost_usd_per_q'], '$')} |"
        )
    for s in SYSTEMS:
        if s not in by_sys:
            L.append(f"| {s}. {SYSTEMS[s]} | not run: {cfg['skipped'].get(s, 'not requested')} |||||||||| ")
    if "B" in summary:
        L += [
            "",
            f"System B lockfile truncation rate: {fmt(summary['B']['truncated_rate'], '%')} "
            f"(budget {LOCK_BUDGET_CHARS:,} chars after compaction).",
        ]
    L += [
        "",
        "## Per advisory unit (F1)",
        "",
        "| Unit | " + " | ".join(ran) + " | positives |",
        "|---|" + "---|" * (len(ran) + 1),
    ]
    for u in sorted({r["unit"] for rs in by_sys.values() for r in rs}):
        pos = next(iter(per_unit.values()))[u]["tp"] + next(iter(per_unit.values()))[u]["fn"]
        L.append(f"| {u} | " + " | ".join(fmt(per_unit[s][u]["f1"]) for s in ran) + f" | {pos} |")
    L += ["", "## Disagreements with the oracle (G and C)", ""]
    if not disagreements:
        L.append("None.")
    else:
        L += ["| System | Unit | Target | Oracle | Answer | Likely cause |", "|---|---|---|---|---|---|"]
        for s in ("G", "C"):
            for r in by_sys.get(s, []):
                if r["pred"] != r["gold"]:
                    L.append(
                        f"| {s} | {r['unit']} | `{r['target']}` | {r['gold']} | {r['pred']} | {r['cause']} |"
                    )
    bad_paths = [
        r for s in ("G", "C") for r in by_sys.get(s, []) if r["pred"] and not r["grade"]["path_valid"]
    ]
    L += ["", "## Exposed answers whose path is not npm's (G and C)", ""]
    if not bad_paths:
        L.append("None.")
    else:
        L += [
            "| System | Unit | Target | Edges not in the oracle tree | Likely cause |",
            "|---|---|---|---|---|",
        ]
        for r in bad_paths:
            edges = (
                "; ".join(f"`{e}`" for e in r["grade"]["bad_edges"][:3])
                or "(does not end at an affected version)"
            )
            L.append(f"| {r['system']} | {r['unit']} | `{r['target']}` | {edges} | {r['path_cause']} |")
    L += [
        "",
        "Dataset: `eval/dataset.json`, sample: `eval/sample.json`, every prompt and answer: "
        f"`eval/runs/{run_id}/`.",
    ]
    RESULTS_MD.write_text("\n".join(L) + "\n")
    chart(summary, ran)


def chart(summary: dict[str, Any], ran: list[str]) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    metrics = [
        ("precision", "Precision"),
        ("recall", "Recall"),
        ("f1", "F1"),
        ("path_validity", "Path validity"),
    ]
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    w = 0.8 / max(1, len(ran))
    colors = {"A": "#9aa5b1", "B": "#5b7083", "C": "#e4572e", "G": "#f2a541"}
    for i, s in enumerate(ran):
        vals = [summary[s][k] or 0 for k, _ in metrics]
        xs = [j + i * w for j in range(len(metrics))]
        ax.bar(xs, vals, w, label=f"{s}. {SYSTEMS[s]}", color=colors[s])
    ax.set_xticks([j + w * (len(ran) - 1) / 2 for j in range(len(metrics))], [m for _, m in metrics])
    ax.set_ylim(0, 1.05)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=7, loc="lower right")
    ax.set_title("Exposure vs the npm oracle (sampled pairs)", fontsize=10)
    fig.tight_layout()
    fig.savefig(RESULTS_PNG)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systems", default="A,B,C,G")
    ap.add_argument("--limit", type=int, default=0, help="first N sampled pairs only (smoke runs)")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--regrade", metavar="RUN_ID", help="rescore a logged run without calling any model")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")

    data = json.loads(DATASET_PATH.read_text())
    sample = json.loads(SAMPLE_PATH.read_text())["pairs"]
    if args.limit:
        sample = sample[: args.limit]
    units = {u["unit"]: u for u in data["units"]}
    gold = {(p["unit"], p["target"]): p for p in data["pairs"]}
    S = load_anchor()["S"]
    items = [
        {
            **p,
            "incident": units[p["unit"]]["incident"],
            "question": question(units[p["unit"]], p["target"], S),
        }
        for p in sample
    ]

    want = [s.strip() for s in args.systems.split(",") if s.strip()]
    skipped = {}
    if not os.environ.get("OPENAI_API_KEY"):
        for s in ("A", "B", "C"):
            if s in want:
                want.remove(s)
                skipped[s] = "OPENAI_API_KEY not set"

    old: list[dict[str, Any]] = []
    if args.regrade:
        run_id, run_dir = args.regrade, RUNS / args.regrade
        old = [json.loads(line) for line in (run_dir / "answers.jsonl").read_text().splitlines()]
        want = [s for s in SYSTEMS if any(o["system"] == s for o in old)]
    else:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = RUNS / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "S": S,
        "n_pairs": len(items),
        "n_units": len({i["unit"] for i in items}),
        "positives": sum(gold[(i["unit"], i["target"])]["oracle_exposed"] for i in items),
        "systems": want,
        "skipped": skipped,
        "model": MODEL_CFG["model"],
        "reasoning_effort": MODEL_CFG["reasoning_effort"],
        "answer_schema": ANSWER_SCHEMA,
        "lock_budget_chars": LOCK_BUDGET_CHARS,
        "seed": data["seed"],
        "note": "temperature is not settable on this reasoning model (DECISIONS D6); prompts logged verbatim",
    }
    if args.regrade:
        cfg = {
            **json.loads((run_dir / "config.json").read_text()),
            "regraded_at": datetime.now(UTC).isoformat(),
        }
    (run_dir / "config.json").write_text(json.dumps(cfg, indent=1))

    grader = Grader(data)
    by_sys: dict[str, list[dict[str, Any]]] = defaultdict(list)
    log = (run_dir / "answers.jsonl").open("w" if args.regrade else "a")

    def record(system: str, item: dict[str, Any], rec: dict[str, Any]) -> None:
        g = gold[(item["unit"], item["target"])]
        a = rec["answer"]
        raw_path = a["path"] if a else None
        if a:
            a = {**a, "path": normalize_path(item["target"], a["path"])}
        grade = grader.grade(item["unit"], item["target"], a["path"] if a else [], bool(a and a["exposed"]))
        row = {
            "system": system,
            "unit": item["unit"],
            "target": item["target"],
            "gold": g["oracle_exposed"],
            "pred": a["exposed"] if a else None,
            "path": a["path"] if a else None,
            "raw_path": raw_path,
            "grade": grade,
            "cause": (
                grader.cause(
                    item["unit"], item["target"], a["exposed"] if a else None, a["path"] if a else None
                )
                if system in "CG"
                else None
            ),
            **{k: rec.get(k) for k in ("usage", "latency_ms", "truncated")},
        }
        row["path_cause"] = (
            grader.path_cause(item["unit"], item["target"], grade)
            if row["pred"] and not grade["path_valid"]
            else None
        )
        by_sys[system].append(row)
        log.write(
            json.dumps(
                {
                    **row,
                    "prompt": rec.get("prompt"),
                    "raw": rec.get("raw"),
                    "tool_calls": rec.get("tool_calls"),
                }
            )
            + "\n"
        )
        log.flush()

    t0 = time.monotonic()
    for o in old:  # --regrade: replay the logged answers through the current grader
        ans = (
            {"exposed": o["pred"], "path": o.get("raw_path") or o["path"] or []}
            if o["pred"] is not None
            else None
        )
        rec = {k: o.get(k) for k in ("usage", "latency_ms", "truncated", "prompt", "raw", "tool_calls")}
        record(o["system"], {"unit": o["unit"], "target": o["target"]}, {**rec, "answer": ans})
    for s in [] if old else want:
        ts = time.monotonic()
        if s in ("A", "B"):
            with ThreadPoolExecutor(args.jobs) as pool:
                for item, rec in zip(
                    items, pool.map(lambda i, s=s: run_llm_only(i, s == "B"), items), strict=True
                ):
                    record(s, item, rec)
        elif s == "C":
            asyncio.run(run_agent(items, args.jobs, lambda item, rec: record("C", item, rec)))
        elif s == "G":
            for item in items:
                record("G", item, run_graph(item))
        m = summarize(by_sys[s])
        print(
            f"{s}: n={m['n']} P={fmt(m['precision'])} R={fmt(m['recall'])} F1={fmt(m['f1'])} "
            f"path_valid={fmt(m['path_validity'], '%')} halluc_nodes={fmt(m['hallucinated_node_rate'], '%')} "
            f"{time.monotonic() - ts:.0f}s",
            flush=True,
        )
    log.close()
    write_results(run_id, cfg, by_sys, data)
    print(f"wrote {RESULTS_MD.relative_to(ROOT)} ({time.monotonic() - t0:.0f}s)")
    if skipped:
        print(f"skipped: {skipped}")


if __name__ == "__main__":
    main()
