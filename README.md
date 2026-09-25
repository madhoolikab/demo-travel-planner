# Agentic Trip Planner Workshop

A hands-on workshop repo that teaches four agent design patterns — **tool calls**,
**ReAct**, **planning**, and **reflection** — by building the same trip planner
five times, each stage adding one pattern to the one before it.

All travel data (places, prices, hours, weather, travel times) is simulated and
frozen in `data/`, with traps planted on purpose so each pattern has something
concrete to fix. A scoring script checks every stage's output against the data
so improvement is measurable, not just a vibe.

A web UI (`backend/` + `frontend/`) sits on top so you can run any stage, watch
its live trace (thoughts / tool calls / results), and see the scorecard and cost
counters update — without reading terminal output.

## Build progress

This repo is being built incrementally, committing after each piece:

- [x] Project scaffolding, requirements, env config
- [ ] Trip Request / Itinerary schemas (`common/schema.py`)
- [ ] Simulated data: Jaipur (Golden Trip), Bangalore, Delhi
- [ ] Tools, trace printer, token/call counters (`common/tools.py`, `common/trace.py`)
- [ ] Scoring script + hand-written test itineraries (`scoring/score.py`)
- [ ] Stage 0 — baseline (one plain model call)
- [ ] Stage 1 — tool calls (single round)
- [ ] Stage 2 — ReAct (loop of thought/action/observation)
- [ ] Stage 3 — planning (outline + per-day workers)
- [ ] Stage 4 — reflection (reviewer + reviser loop)
- [ ] Scorecard runner across all stages, multiple runs
- [ ] Backend API (FastAPI) streaming live traces
- [ ] Frontend UI (run stages, watch traces, compare scorecards)

## Project layout

```text
trip-planner-workshop/
  data/               jaipur/ bangalore/ delhi/  -> places, restaurants, weather, travel_times
  requests/           golden_jaipur.json, bangalore.json, delhi.json
  common/
    schema.py         TripRequest and Itinerary
    tools.py           the six simulated tools
    llm.py             model client built from .env
    trace.py           prints thought/action/observation, counts calls + tokens
  stages/
    stage0_baseline/
    stage1_tool_calls/
    stage2_react/
    stage3_planning/
    stage4_reflection/   each has graph.py and run.py
  scoring/
    score.py           checks one itinerary against the data
    run_all.py          runs every stage and prints the scorecard
  backend/             FastAPI app exposing the stages + traces to the UI
  frontend/            web UI: run a stage, watch the trace live, compare stages
  runs/                saved itineraries and traces (for --replay, no API calls)
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in OPENAI_API_KEY
```

## The four patterns, in one line each

| Stage | Pattern | Fixes |
| --- | --- | --- |
| 0 | none (baseline) | — |
| 1 | Tool calls (single round) | Unknowable facts |
| 2 | ReAct (loop + reasoning) | Logistics (closures, weather, travel time) |
| 3 | Planning (outline + day workers) | Budget overshoot, time window |
| 4 | Reflection (reviewer + reviser) | Age-group suitability |

See the full build spec in this repo's history / docs for the complete design
(trip request format, itinerary format, the five failure checks, planted traps
per city, and the workshop schedule).
