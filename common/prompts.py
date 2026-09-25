"""The one piece of prompt text that's identical in every stage: describing
the Trip Request itself. Each stage's own prompt.py only holds what's new
for that stage's pattern, so a diff between two stage folders shows just
the pattern, not a re-typed trip description.
"""
from __future__ import annotations

from common.schema import TripRequest


def build_trip_summary(trip: TripRequest) -> str:
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
