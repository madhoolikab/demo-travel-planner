"""Stage 2's prompt. New relative to Stage 1: the model can call tools
repeatedly and must explain itself in one sentence before every call, since
it's now checking things (closures, weather, travel time) rather than just
gathering everything once.
"""
from __future__ import annotations

from common.prompts import TOOL_GROUNDED_WRITER_SYSTEM_PROMPT, build_trip_summary
from common.schema import TripRequest

REACT_SYSTEM_PROMPT = (
    "You are a travel planner with access to tools for looking up places, "
    "restaurants, weather, and travel times. Work step by step: before "
    "every tool call, write one sentence explaining why you're making it, "
    "then call the tool. Use what you learn to check your plan as you go "
    "-- for example, check whether a place is open on the date you want to "
    "use it, whether the weather is a problem before scheduling something "
    "outdoors, and how long it actually takes to get between two places. "
    "When you have everything you need and are ready to write the "
    "itinerary, reply with no further tool calls."
)

WRITER_SYSTEM_PROMPT = TOOL_GROUNDED_WRITER_SYSTEM_PROMPT


def build_user_prompt(trip: TripRequest) -> str:
    return build_trip_summary(trip)
