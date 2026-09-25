"""The Stage 0 prompt: plain text describing the trip, asking for a
day-by-day itinerary. No tools, no data -- the point is to show what a
confident first attempt looks like without real facts.
"""
from __future__ import annotations

from common.prompts import build_trip_summary
from common.schema import TripRequest

SYSTEM_PROMPT = (
    "You are a travel planner. Given a trip request, produce a day-by-day "
    "itinerary with specific places, times, and costs in INR. Be concrete: "
    "name real places, give a start and end time for every slot, and a cost "
    "in INR for the whole group. Include a travel slot for every move "
    "between places, including from the stay area at the start of the day "
    "and back at the end. State a total cost and any assumptions you made."
)


def build_user_prompt(trip: TripRequest) -> str:
    return build_trip_summary(trip)
