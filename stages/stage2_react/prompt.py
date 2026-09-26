"""Stage 2's prompt. New relative to Stage 1: the model can call tools
repeatedly and must explain itself in one sentence before every call, since
it's now checking things (closures, weather, travel time) rather than just
gathering everything once.
"""
from __future__ import annotations

from common.prompts import build_tool_grounded_writer_prompt, build_trip_summary
from common.schema import TripRequest

REACT_SYSTEM_PROMPT = (
    "You are a travel planner with access to tools for looking up places, "
    "restaurants, weather, and travel times. Work step by step: before "
    "every tool call, write one sentence explaining why you're making it, "
    "then call the tool. Use what you learn to check your plan as you go: "
    "check whether a place is open on the date you want to use it, whether "
    "the weather is a problem before scheduling something outdoors, and -- "
    "for every single move from one place to the next in your plan, "
    "including from the stay area at the start of a day and back at the "
    "end -- call get_travel_time for that specific pair of places and use "
    "its exact minutes and cost for that travel slot. Do not guess or "
    "round a travel time or cost you could have looked up. When you have "
    "checked every place and every move and are ready to write the "
    "itinerary, reply with no further tool calls."
)


def build_user_prompt(trip: TripRequest) -> str:
    return build_trip_summary(trip)


def build_writer_system_prompt(trip: TripRequest) -> str:
    base = build_tool_grounded_writer_prompt([d.isoformat() for d in trip.trip_dates()])
    return (
        f"{base}\n\nFor every travel slot's minutes and cost, use the exact "
        "numbers get_travel_time returned for that pair of places -- do not "
        "estimate or round them yourself."
    )
