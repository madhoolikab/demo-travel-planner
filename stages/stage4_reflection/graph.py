"""Stage 4: reflection. Everything from Stage 3 (planner, day workers,
assembler), plus a reviewer that reads the finished itinerary back and a
reviser that re-runs only the affected day workers, for up to 2 rounds.

The reviewer never imports scoring.score. If it did, review would be
trivial -- it would be handed the answer key instead of having to find
problems the way a careful human editor would.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from common.llm import get_llm, usage_from_message
from common.schema import Day, Itinerary, OutlineDay, TripRequest
from common.tools import calculate_total, get_place_details, get_travel_time
from common.trace import Tracer

# Stage 4 explicitly reuses Stage 3's planner and day worker -- reflection is
# everything Stage 3 does, plus a review/revise loop bolted on afterward.
from stages.stage3_planning.graph import _run_day_worker, _run_planner

from .prompt import REVIEWER_SYSTEM_PROMPT, REVIEWER_WRITER_SYSTEM_PROMPT, build_reviewer_user_prompt

REVIEWER_TOOLS = [get_place_details, get_travel_time, calculate_total]
MAX_ROUNDS = 2


class Problem(BaseModel):
    day: str
    slot: str
    reason: str


class ReviewResult(BaseModel):
    problems: list[Problem]


class Stage4State(TypedDict):
    outline: Optional[dict]
    day_index: int
    completed_days: dict[str, dict]  # date -> Day dict
    itinerary: Optional[dict]
    problems: list[dict]
    round: int


def _used_places_excluding(completed_days: dict[str, dict], exclude_date: Optional[str]) -> list[str]:
    used: list[str] = []
    for date, day in completed_days.items():
        if date == exclude_date:
            continue
        for slot in day["slots"]:
            if slot["kind"] in ("activity", "meal") and slot["place_name"] not in used:
                used.append(slot["place_name"])
    return used


def _run_reviewer(trip: TripRequest, itinerary: Itinerary, tracer: Tracer) -> list[Problem]:
    tools_by_name = {t.name: t for t in REVIEWER_TOOLS}
    tool_llm = get_llm(temperature=0).bind_tools(REVIEWER_TOOLS)
    writer_llm = get_llm(temperature=0).with_structured_output(ReviewResult, include_raw=True)

    messages = [
        SystemMessage(content=REVIEWER_SYSTEM_PROMPT),
        HumanMessage(content=build_reviewer_user_prompt(trip, itinerary)),
    ]
    tracer.stage_marker("Reviewer may check place details, travel times, and the total")
    ai_message = tool_llm.invoke(messages)
    tracer.model_usage(usage_from_message(ai_message), node="reviewer:tools")
    messages.append(ai_message)
    for call in ai_message.tool_calls:
        tool = tools_by_name[call["name"]]
        tracer.action(call["name"], call["args"])
        result = tool.invoke(call["args"])
        tracer.observation(call["name"], result)
        messages.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"], name=call["name"]))

    messages.append(SystemMessage(content=REVIEWER_WRITER_SYSTEM_PROMPT))
    result = writer_llm.invoke(messages)
    tracer.model_usage(usage_from_message(result.get("raw")), node="reviewer:writer")
    review: ReviewResult = result["parsed"]
    if not review.problems:
        tracer.stage_marker("Reviewer found no problems")
    for p in review.problems:
        tracer.stage_marker(f"Problem found: {p.day} {p.slot}: {p.reason}")
    return review.problems


def build_graph(tracer: Tracer, trip: TripRequest):
    def plan_outline(state: Stage4State) -> dict:
        tracer.stage_marker("Planner writes outline")
        outline = _run_planner(trip, tracer)
        return {
            "outline": outline.model_dump(mode="json"),
            "day_index": 0,
            "completed_days": {},
            "round": 0,
            "problems": [],
        }

    def fill_day(state: Stage4State) -> dict:
        outline_days = state["outline"]["days"]
        idx = state["day_index"]
        outline_day = OutlineDay.model_validate(outline_days[idx])
        tracer.stage_marker(f"Day worker fills {outline_day.date} ({idx + 1}/{len(outline_days)})")
        used = _used_places_excluding(state["completed_days"], exclude_date=None)
        day = _run_day_worker(trip, outline_day, used, tracer)
        completed = dict(state["completed_days"])
        completed[outline_day.date] = day.model_dump(mode="json")
        return {"completed_days": completed, "day_index": idx + 1}

    def route_fill(state: Stage4State) -> str:
        return "fill_day" if state["day_index"] < len(state["outline"]["days"]) else "assemble"

    def assemble(state: Stage4State) -> dict:
        tracer.stage_marker("Assembler merges days and computes the total")
        outline_days = state["outline"]["days"]
        ordered_days = [state["completed_days"][d["date"]] for d in outline_days]
        all_costs = [slot["cost_inr"] for day in ordered_days for slot in day["slots"]]
        total = calculate_total.invoke({"amounts": all_costs})["total"]
        itinerary = Itinerary(
            days=[Day.model_validate(d) for d in ordered_days],
            total_cost_inr=total,
            assumptions=[
                "Built with a planning outline, one day worker per day, and "
                f"reviewed for up to {MAX_ROUNDS} rounds before finishing."
            ],
        )
        tracer.final_itinerary(itinerary.model_dump(mode="json"))
        return {"itinerary": itinerary.model_dump(mode="json")}

    def review(state: Stage4State) -> dict:
        after = f"after revision round {state['round']}" if state["round"] else "on the first draft"
        tracer.stage_marker(f"Reviewer checks the itinerary ({after}, {MAX_ROUNDS - state['round']} revision round(s) left)")
        itinerary = Itinerary.model_validate(state["itinerary"])
        problems = _run_reviewer(trip, itinerary, tracer)
        return {"problems": [p.model_dump() for p in problems]}

    def route_review(state: Stage4State) -> str:
        if state["problems"] and state["round"] < MAX_ROUNDS:
            return "revise"
        return "__end__"

    def revise(state: Stage4State) -> dict:
        new_round = state["round"] + 1
        tracer.stage_marker(f"Reviser fixes the affected days (round {new_round})")
        problems_by_day: dict[str, list[dict]] = defaultdict(list)
        for p in state["problems"]:
            problems_by_day[p["day"]].append(p)

        outline_by_date = {d["date"]: OutlineDay.model_validate(d) for d in state["outline"]["days"]}
        completed = dict(state["completed_days"])

        for date, problems in problems_by_day.items():
            outline_day = outline_by_date.get(date)
            if not outline_day:
                # The reviewer named a date outside the trip; nothing to revise.
                continue
            note_addition = "; ".join(f"{p['slot']}: {p['reason']}" for p in problems)
            revised_day = outline_day.model_copy(
                update={
                    "notes": (
                        (outline_day.notes + " | " if outline_day.notes else "")
                        + f"Fix needed from review: {note_addition}"
                    )
                }
            )
            used = _used_places_excluding(completed, exclude_date=date)
            tracer.stage_marker(f"Re-running the day worker for {date} with the review's notes")
            day = _run_day_worker(trip, revised_day, used, tracer)
            completed[date] = day.model_dump(mode="json")

        return {"completed_days": completed, "round": new_round}

    graph = StateGraph(Stage4State)
    graph.add_node("plan_outline", plan_outline)
    graph.add_node("fill_day", fill_day)
    graph.add_node("assemble", assemble)
    graph.add_node("review", review)
    graph.add_node("revise", revise)
    graph.set_entry_point("plan_outline")
    graph.add_edge("plan_outline", "fill_day")
    graph.add_conditional_edges("fill_day", route_fill, {"fill_day": "fill_day", "assemble": "assemble"})
    graph.add_edge("assemble", "review")
    graph.add_conditional_edges("review", route_review, {"revise": "revise", "__end__": END})
    graph.add_edge("revise", "assemble")
    return graph.compile()


def run(trip: TripRequest, tracer: Tracer) -> Itinerary:
    app = build_graph(tracer, trip)
    initial_state: Stage4State = {
        "outline": None,
        "day_index": 0,
        "completed_days": {},
        "itinerary": None,
        "problems": [],
        "round": 0,
    }
    final_state = app.invoke(initial_state, config={"recursion_limit": 300})
    return Itinerary.model_validate(final_state["itinerary"])
