"""Stage 3: planning. A planner writes an outline (one entry per day: area,
theme, budget share, notes), then a day worker -- the Stage 2 loop, packaged
as a subgraph via common.react_loop -- fills in one day at a time, seeing
only that day's limits and the places already used on earlier days. An
assembler merges the days and computes the total with the calculate_total
tool, so no model ever adds the numbers up itself.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from common.llm import get_llm, usage_from_message
from common.react_loop import run_react_loop
from common.schema import Day, Itinerary, Outline, OutlineDay, TripRequest
from common.tools import ALL_TOOLS, calculate_total, get_weather, search_places
from common.trace import Tracer
from scoring.score import ARRIVAL_BUFFER_MIN, DEPARTURE_BUFFER_MIN

from .prompt import (
    DAY_WORKER_SYSTEM_PROMPT,
    DAY_WORKER_WRITER_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    PLANNER_WRITER_SYSTEM_PROMPT,
    build_day_user_prompt,
    build_planner_user_prompt,
)

PLANNER_TOOLS = [get_weather, search_places]
DAY_WORKER_MAX_STEPS = 15


class PlannerDayDraft(BaseModel):
    date: str
    area: str
    theme: str
    budget_share_inr: float
    notes: str = ""


class PlannerOutlineDraft(BaseModel):
    days: list[PlannerDayDraft]


class Stage3State(TypedDict):
    outline: Optional[dict]
    day_index: int
    completed_days: list[dict]
    used_places: list[str]
    itinerary: Optional[dict]


def compute_day_bounds(trip: TripRequest) -> list[dict]:
    """The deterministic part of the outline: exact available_from/
    available_to per day, from the same buffers the scorer checks. Left to
    code rather than the model, the same way calculate_total is -- exact
    time arithmetic is not what we want an LLM guessing at.
    """
    arrival_date = trip.arrival.date()
    departure_date = trip.departure.date()
    earliest = (trip.arrival + timedelta(minutes=ARRIVAL_BUFFER_MIN)).strftime("%H:%M")
    latest = (trip.departure - timedelta(minutes=DEPARTURE_BUFFER_MIN)).strftime("%H:%M")

    bounds = []
    for d in trip.trip_dates():
        available_from = earliest if d == arrival_date else "08:00"
        available_to = latest if d == departure_date else "22:00"
        bounds.append({"date": d.isoformat(), "available_from": available_from, "available_to": available_to})
    return bounds


def _merge_outline(trip: TripRequest, bounds: list[dict], draft: PlannerOutlineDraft) -> Outline:
    drafts_by_date = {d.date: d for d in draft.days}
    n = len(bounds) or 1
    default_share = round(trip.budget_inr / n, 2)

    days = []
    for b in bounds:
        d = drafts_by_date.get(b["date"])
        if d:
            days.append(
                OutlineDay(
                    date=b["date"],
                    available_from=b["available_from"],
                    available_to=b["available_to"],
                    area=d.area or trip.stay_area,
                    theme=d.theme or "Sightseeing",
                    budget_share_inr=max(d.budget_share_inr, 0),
                    notes=d.notes,
                )
            )
        else:
            days.append(
                OutlineDay(
                    date=b["date"],
                    available_from=b["available_from"],
                    available_to=b["available_to"],
                    area=trip.stay_area,
                    theme="Free time",
                    budget_share_inr=default_share,
                    notes="",
                )
            )

    total_share = sum(day.budget_share_inr for day in days)
    if total_share > trip.budget_inr and total_share > 0:
        scale = trip.budget_inr / total_share
        for day in days:
            day.budget_share_inr = round(day.budget_share_inr * scale, 2)
    return Outline(days=days)


def _run_planner(trip: TripRequest, tracer: Tracer) -> Outline:
    tools_by_name = {t.name: t for t in PLANNER_TOOLS}
    tool_llm = get_llm(temperature=0).bind_tools(PLANNER_TOOLS)
    writer_llm = get_llm(temperature=0).with_structured_output(PlannerOutlineDraft, include_raw=True)

    bounds = compute_day_bounds(trip)
    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=build_planner_user_prompt(trip, [b["date"] for b in bounds])),
    ]

    tracer.stage_marker("Planner may check weather and places before outlining")
    ai_message = tool_llm.invoke(messages)
    tracer.model_usage(usage_from_message(ai_message), node="planner:tools")
    messages.append(ai_message)
    for call in ai_message.tool_calls:
        tool = tools_by_name[call["name"]]
        tracer.action(call["name"], call["args"])
        result = tool.invoke(call["args"])
        tracer.observation(call["name"], result)
        messages.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"], name=call["name"]))

    messages.append(SystemMessage(content=PLANNER_WRITER_SYSTEM_PROMPT))
    result = writer_llm.invoke(messages)
    tracer.model_usage(usage_from_message(result.get("raw")), node="planner:writer")
    draft: PlannerOutlineDraft = result["parsed"]
    return _merge_outline(trip, bounds, draft)


def _run_day_worker(trip: TripRequest, outline_day: OutlineDay, used_places: list[str], tracer: Tracer) -> Day:
    return run_react_loop(
        tracer=tracer,
        system_prompt=DAY_WORKER_SYSTEM_PROMPT,
        user_prompt=build_day_user_prompt(trip, outline_day, used_places),
        tools=ALL_TOOLS,
        output_schema=Day,
        writer_system_prompt=DAY_WORKER_WRITER_SYSTEM_PROMPT,
        max_steps=DAY_WORKER_MAX_STEPS,
        label=outline_day.date,
    )


def build_graph(tracer: Tracer, trip: TripRequest):
    def plan_outline(state: Stage3State) -> dict:
        tracer.stage_marker("Planner writes outline")
        outline = _run_planner(trip, tracer)
        return {
            "outline": outline.model_dump(mode="json"),
            "day_index": 0,
            "completed_days": [],
            "used_places": [],
        }

    def fill_day(state: Stage3State) -> dict:
        outline_days = state["outline"]["days"]
        idx = state["day_index"]
        outline_day = OutlineDay.model_validate(outline_days[idx])
        tracer.stage_marker(f"Day worker fills {outline_day.date} ({idx + 1}/{len(outline_days)})")
        day = _run_day_worker(trip, outline_day, state["used_places"], tracer)

        used = list(state["used_places"])
        for slot in day.slots:
            if slot.kind in ("activity", "meal") and slot.place_name not in used:
                used.append(slot.place_name)

        return {
            "completed_days": state["completed_days"] + [day.model_dump(mode="json")],
            "used_places": used,
            "day_index": idx + 1,
        }

    def route(state: Stage3State) -> str:
        return "fill_day" if state["day_index"] < len(state["outline"]["days"]) else "assemble"

    def assemble(state: Stage3State) -> dict:
        tracer.stage_marker("Assembler merges days and computes the total")
        days = state["completed_days"]
        all_costs = [slot["cost_inr"] for day in days for slot in day["slots"]]
        total = calculate_total.invoke({"amounts": all_costs})["total"]
        itinerary = Itinerary(
            days=[Day.model_validate(d) for d in days],
            total_cost_inr=total,
            assumptions=[
                "Built with a planning outline and one day worker per day; "
                "the total was computed with calculate_total, not by the model."
            ],
        )
        tracer.final_itinerary(itinerary.model_dump(mode="json"))
        return {"itinerary": itinerary.model_dump(mode="json")}

    graph = StateGraph(Stage3State)
    graph.add_node("plan_outline", plan_outline)
    graph.add_node("fill_day", fill_day)
    graph.add_node("assemble", assemble)
    graph.set_entry_point("plan_outline")
    graph.add_edge("plan_outline", "fill_day")
    graph.add_conditional_edges("fill_day", route, {"fill_day": "fill_day", "assemble": "assemble"})
    graph.add_edge("assemble", END)
    return graph.compile()


def run(trip: TripRequest, tracer: Tracer) -> Itinerary:
    app = build_graph(tracer, trip)
    initial_state: Stage3State = {
        "outline": None,
        "day_index": 0,
        "completed_days": [],
        "used_places": [],
        "itinerary": None,
    }
    final_state = app.invoke(initial_state, config={"recursion_limit": 200})
    return Itinerary.model_validate(final_state["itinerary"])
