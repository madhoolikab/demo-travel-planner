"""Stage 1's prompt. Only this file's content is new relative to Stage 0 --
the trip description (build_trip_summary) is shared, so a diff between the
two stages' prompt.py shows just the pattern: the model now has tools, in
one round, before it writes anything.
"""
from __future__ import annotations

from common.prompts import TOOL_GROUNDED_WRITER_SYSTEM_PROMPT, build_trip_summary
from common.schema import TripRequest

TOOL_CALLER_SYSTEM_PROMPT = (
    "You are a travel planner with access to tools for looking up places, "
    "restaurants, weather, and travel times. Before you write anything, call "
    "whatever tools you need to gather real information about this trip -- "
    "you can call several tools at once. You will not get another chance to "
    "call tools after this, so gather everything you think you'll need now."
)

WRITER_SYSTEM_PROMPT = TOOL_GROUNDED_WRITER_SYSTEM_PROMPT


def build_user_prompt(trip: TripRequest) -> str:
    return build_trip_summary(trip)
