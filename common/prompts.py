"""The one piece of prompt text that's identical in every stage: describing
the Trip Request itself. Each stage's own prompt.py only holds what's new
for that stage's pattern, so a diff between two stage folders shows just
the pattern, not a re-typed trip description.
"""
from __future__ import annotations

from common.schema import TripRequest

# Used by Stage 1 and Stage 2: the final call that turns gathered tool
# results into the whole-trip Itinerary, with no tools attached of its own.
#
# The exact dates are restated here (not just once, back in the first user
# message) because by the time this runs, several tool messages sit between
# it and the original request -- observed live: without this reminder, the
# model would sometimes write only the first day and stop, having lost
# track of "cover every day" over the longer context.
def build_tool_grounded_writer_prompt(dates: list[str]) -> str:
    dates_desc = ", ".join(dates)
    return (
        "Using only what you learned from the tools above, write a day-by-day "
        "itinerary with specific places, times, and costs in INR. Do not invent "
        "facts you were not given by a tool. Include a travel slot for every "
        "move between places, including from the stay area at the start of the "
        "day and back at the end. For a travel slot, place_name is just the "
        "destination you're arriving at (e.g. 'Amber Fort'), never a "
        "description of the route (not 'C-Scheme to Amber Fort') -- say how "
        "you're getting there in the note instead, e.g. 'Cab from the stay "
        "area'. State a total cost and any assumptions you made.\n\n"
        f"Your itinerary must include exactly these {len(dates)} calendar day(s), "
        f"each with its own entry, in order: {dates_desc}."
    )


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
