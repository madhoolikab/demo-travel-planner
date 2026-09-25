"""Stage 4's reviewer prompt. New relative to Stage 3: after the itinerary
is assembled, a reviewer reads the whole thing back and checks it against
the same kind of rules the scoring script checks -- but it must never see
the scoring script itself, or review would be trivial (it would be handed
the answer key).
"""
from __future__ import annotations

from common.render import render_itinerary, render_trip_request
from common.schema import Itinerary, TripRequest

REVIEWER_SYSTEM_PROMPT = (
    "You are reviewing a finished trip itinerary before it is shown to the "
    "traveler. Check it against these rules:\n"
    "- Every place is open at the time it is scheduled.\n"
    "- Every activity is suitable for every traveler in the group -- check "
    "age suitability for each one, especially anything physically "
    "demanding for a child or a senior.\n"
    "- The plan fits between the arrival and departure times.\n"
    "- The stated total is within the Budget.\n"
    "- Every move between places has enough travel time.\n"
    "You have read-only tools to check place details, travel times, and to "
    "re-add up costs -- use them to verify your claims rather than "
    "guessing. List every problem you find, each with the day it's on, "
    "which slot it concerns, and why it's a problem. If you find nothing "
    "wrong, return an empty list of problems."
)

REVIEWER_WRITER_SYSTEM_PROMPT = (
    "Return the list of problems you found, using what you learned above. "
    "Return an empty list if you found none."
)


def build_reviewer_user_prompt(trip: TripRequest, itinerary: Itinerary) -> str:
    return (
        f"{render_trip_request(trip)}\n\n"
        "Here is the finished itinerary to review:\n"
        f"{render_itinerary(itinerary)}"
    )
