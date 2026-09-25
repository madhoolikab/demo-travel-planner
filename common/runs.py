"""Saves and loads itinerary + trace runs under runs/. Backs the optional
--replay flag (print a saved run without calling the API) and lets the web
UI list and re-show past runs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def _slug(*parts: str) -> str:
    return "_".join(p.strip().lower().replace(" ", "-") for p in parts)


def save_run(
    stage: str, request_name: str, trip: dict, itinerary: dict, events: list, summary: dict
) -> Path:
    RUNS_DIR.mkdir(exist_ok=True)
    payload = {
        "stage": stage,
        "request_name": request_name,
        "trip_request": trip,
        "itinerary": itinerary,
        "events": events,
        "summary": summary,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    slug = _slug(stage, request_name)
    (RUNS_DIR / f"{slug}_latest.json").write_text(json.dumps(payload, indent=2))
    stamped = RUNS_DIR / f"{slug}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    stamped.write_text(json.dumps(payload, indent=2))
    return stamped


def load_latest_run(stage: str, request_name: str) -> Optional[dict]:
    slug = _slug(stage, request_name)
    path = RUNS_DIR / f"{slug}_latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def list_runs() -> list[dict]:
    RUNS_DIR.mkdir(exist_ok=True)
    out = []
    for path in sorted(RUNS_DIR.glob("*_latest.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        out.append(
            {
                "stage": data.get("stage"),
                "request_name": data.get("request_name"),
                "saved_at": data.get("saved_at"),
                "summary": data.get("summary"),
            }
        )
    return out
