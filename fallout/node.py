"""JSONL bridge to the Node workers (resolver.mjs, semver-eval.mjs).

One Node process per batch, not per item: send thousands of lines, read the same number back.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from typing import Any

from fallout.settings import ROOT

WORKERS = ROOT / "workers"


def run_jsonl(script: str, lines: Iterable[dict[str, Any]], *args: str) -> list[dict[str, Any]]:
    payload = "".join(json.dumps(line) + "\n" for line in lines)
    proc = subprocess.run(
        ["node", str(WORKERS / script), *args],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{script} failed: {proc.stderr.strip()}")
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def resolve(groups: Iterable[dict[str, Any]], before: str) -> dict[str, dict[str, Any]]:
    """groups: [{"packument": {...}, "requests": [{"id", "range"}]}] -> {id: {version} | {error}}."""
    return {r["id"]: r for r in run_jsonl("resolver.mjs", groups, "--before", before)}


def semver_eval(requests: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in run_jsonl("semver-eval.mjs", requests)}
