"""Repo paths and static configuration shared by every stage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
RAW_DIR = DATA_DIR / "raw"
ANCHOR_PATH = CONFIG_DIR / "anchor.json"

SETTINGS: dict[str, Any] = json.loads((CONFIG_DIR / "settings.json").read_text())


def load_incident(incident_id: str) -> dict[str, Any]:
    return json.loads((CONFIG_DIR / "incidents" / f"{incident_id}.json").read_text())


def load_anchor() -> dict[str, Any]:
    if not ANCHOR_PATH.exists():
        raise FileNotFoundError("config/anchor.json missing: run `python -m ingest.anchor` first")
    return json.loads(ANCHOR_PATH.read_text())
