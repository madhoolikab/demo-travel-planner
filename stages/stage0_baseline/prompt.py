"""The Stage 0 prompt: plain text describing the trip, asking for a
day-by-day itinerary. No tools, no data -- the point is to show what a
confident first attempt looks like without real facts.
"""
from __future__ import annotations

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
    counts = trip.group_counts()
    party = ", ".join(f"{n} {g}" for g, n in counts.items() if n)
    return (
        f"Plan a trip to {trip.destination}.\n"
        f"Arrival: {trip.arrival:%A %d %B %Y, %H:%M}\n"
        f"Departure: {trip.departure:%A %d %B %Y, %H:%M}\n"
        f"Travelers: {party}\n"
        f"Budget for on-ground spend, excluding flights and the stay: ₹{trip.budget_inr:,}\n"
        f"Stay area: {trip.stay_area}\n\n"
        "Return a day-by-day itinerary covering every calendar day from arrival to departure."
    )
