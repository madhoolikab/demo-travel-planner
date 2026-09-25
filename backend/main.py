"""FastAPI app behind the web UI: lists stages and trip requests, starts a
stage run, streams its trace live over SSE, and serves the finished
itinerary + scorecard. Also serves the built frontend as static files, so
the whole workshop UI is one process on one port.

Run with:
    uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from backend.run_manager import STAGE_MODULES, get_run, start_run
from common.cli import REQUESTS_DIR, load_request
from common.render import render_trip_request
from common.runs import list_runs, load_latest_run

app = FastAPI(title="Agentic Trip Planner Workshop")

STAGE_META = {
    "stage0_baseline": {
        "order": 0,
        "title": "Stage 0 · Baseline",
        "pattern": "None",
        "one_liner": "One plain model call. No tools, no data.",
        "fixes": [],
    },
    "stage1_tool_calls": {
        "order": 1,
        "title": "Stage 1 · Tool calls",
        "pattern": "Tool calls",
        "one_liner": "The model calls all six tools once, in one round, before writing.",
        "fixes": ["unknowable_facts"],
    },
    "stage2_react": {
        "order": 2,
        "title": "Stage 2 · ReAct",
        "pattern": "ReAct",
        "one_liner": "Thought, action, observation, repeated until the model is ready.",
        "fixes": ["logistics"],
    },
    "stage3_planning": {
        "order": 3,
        "title": "Stage 3 · Planning",
        "pattern": "Planning",
        "one_liner": "An outline first, then one day worker per day.",
        "fixes": ["budget_overshoot", "time_window"],
    },
    "stage4_reflection": {
        "order": 4,
        "title": "Stage 4 · Reflection",
        "pattern": "Reflection",
        "one_liner": "A reviewer checks the finished plan and sends problems back to fix.",
        "fixes": ["age_group"],
    },
}


@app.get("/api/config")
def get_config():
    requests = []
    for path in sorted(REQUESTS_DIR.glob("*.json")):
        trip = load_request(path.stem)
        requests.append(
            {
                "name": path.stem,
                "destination": trip.destination,
                "summary": render_trip_request(trip),
                "trip_request": trip.model_dump(mode="json"),
            }
        )
    stages = [{"name": name, **meta} for name, meta in sorted(STAGE_META.items(), key=lambda kv: kv[1]["order"])]
    return {"requests": requests, "stages": stages}


@app.post("/api/runs")
def create_run(payload: dict):
    stage = payload.get("stage")
    request_name = payload.get("request", "golden_jaipur")
    if stage not in STAGE_MODULES:
        raise HTTPException(400, f"Unknown stage: {stage}")
    state = start_run(stage, request_name)
    return {"run_id": state.run_id, "status": state.status}


@app.get("/api/runs/{run_id}")
def get_run_status(run_id: str):
    state = get_run(run_id)
    if not state:
        raise HTTPException(404, "Run not found")
    return {
        "run_id": state.run_id,
        "stage": state.stage,
        "request": state.request_name,
        "status": state.status,
        "itinerary": state.itinerary,
        "scorecard": state.scorecard,
        "summary": state.summary,
        "error": state.error,
        "events": state.events,
    }


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str):
    state = get_run(run_id)
    if not state:
        raise HTTPException(404, "Run not found")

    async def event_generator():
        loop = asyncio.get_event_loop()
        while True:
            event = await loop.run_in_executor(None, state.queue.get)
            if event.get("type") == "__done__":
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "status": state.status,
                            "itinerary": state.itinerary,
                            "scorecard": state.scorecard,
                            "summary": state.summary,
                            "error": state.error,
                        }
                    ),
                }
                break
            yield {"event": "trace", "data": json.dumps(event)}

    return EventSourceResponse(event_generator())


@app.get("/api/history")
def get_history():
    return {"runs": list_runs()}


@app.get("/api/history/{stage}/{request_name}")
def get_history_run(stage: str, request_name: str):
    saved = load_latest_run(stage, request_name)
    if not saved:
        raise HTTPException(404, "No saved run")
    return saved


# Serve the built frontend as static files. Mounted last (and matched only
# after the /api/* routes above) so the API always takes priority.
_frontend_dir = ROOT / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
