"""Runs a stage in a background thread and exposes its trace as a live
queue of events, so the FastAPI layer can stream them to the browser over
SSE while the (blocking, synchronous) model calls happen underneath.

One run = one RunState, kept in memory for the life of the process. This is
a workshop tool for a handful of people watching one run at a time, not a
production job queue -- deliberately simple.
"""
from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Optional

from common.cli import load_request
from common.runs import save_run
from common.schema import Itinerary
from common.trace import Tracer
from scoring.score import score_itinerary

STAGE_MODULES = {
    "stage0_baseline": "stages.stage0_baseline.graph",
    "stage1_tool_calls": "stages.stage1_tool_calls.graph",
    "stage2_react": "stages.stage2_react.graph",
    "stage3_planning": "stages.stage3_planning.graph",
    "stage4_reflection": "stages.stage4_reflection.graph",
}

DONE_EVENT = {"type": "__done__"}


@dataclass
class RunState:
    run_id: str
    stage: str
    request_name: str
    status: str = "running"  # running | done | error
    queue: "queue.Queue" = field(default_factory=queue.Queue)
    events: list = field(default_factory=list)
    itinerary: Optional[dict] = None
    scorecard: Optional[dict] = None
    summary: Optional[dict] = None
    error: Optional[str] = None


_RUNS: dict[str, RunState] = {}
_LOCK = threading.Lock()


def _get_run_fn(stage: str):
    module = __import__(STAGE_MODULES[stage], fromlist=["run"])
    return module.run


def start_run(stage: str, request_name: str) -> RunState:
    if stage not in STAGE_MODULES:
        raise ValueError(f"Unknown stage: {stage}")
    run_id = uuid.uuid4().hex[:12]
    state = RunState(run_id=run_id, stage=stage, request_name=request_name)
    with _LOCK:
        _RUNS[run_id] = state

    thread = threading.Thread(target=_execute, args=(state,), daemon=True)
    thread.start()
    return state


def _execute(state: RunState) -> None:
    def on_event(event: dict) -> None:
        state.events.append(event)
        state.queue.put(event)

    try:
        trip = load_request(state.request_name)
        tracer = Tracer(stage=state.stage, on_event=on_event).start()
        run_fn = _get_run_fn(state.stage)
        itinerary: Itinerary = run_fn(trip, tracer)
        tracer.stop()
        summary = tracer.summary()

        report = score_itinerary(trip, itinerary)
        state.itinerary = itinerary.model_dump(mode="json")
        state.scorecard = report.as_dict()
        state.summary = summary
        state.status = "done"

        save_run(
            state.stage,
            state.request_name,
            trip.model_dump(mode="json"),
            state.itinerary,
            state.events,
            summary,
        )
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the UI rather than crash the thread silently
        state.status = "error"
        state.error = f"{type(exc).__name__}: {exc}"
    finally:
        state.queue.put(DONE_EVENT)


def get_run(run_id: str) -> Optional[RunState]:
    with _LOCK:
        return _RUNS.get(run_id)
