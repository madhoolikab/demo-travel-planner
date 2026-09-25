"""Renders an Itinerary and a TripRequest as readable text for the terminal.
Every stage's CLI runner uses this, and the web UI shows the same
underlying data, just as HTML instead of text.
"""
from __future__ import annotations

from common.schema import Itinerary, TripRequest


def render_trip_request(trip: TripRequest) -> str:
    counts = trip.group_counts()
    party_bits = ", ".join(f"{n} {g}" for g, n in counts.items() if n)
    return (
        f"{trip.destination} | {trip.arrival:%a %d %b %Y, %H:%M} -> "
        f"{trip.departure:%a %d %b %Y, %H:%M} | Budget ₹{trip.budget_inr:,} | "
        f"{party_bits} | staying in {trip.stay_area}"
    )


def render_itinerary(itinerary: Itinerary) -> str:
    lines = []
    for day in itinerary.days:
        lines.append(f"\n{day.date}")
        for slot in sorted(day.slots, key=lambda s: s.start_minutes()):
            cost = f"₹{slot.cost_inr:g}" if slot.cost_inr else "free"
            lines.append(
                f"  {slot.start}-{slot.end}  [{slot.kind:8s}] {slot.place_name:30s} {cost:>8s}  {slot.note}"
            )
    lines.append(f"\nTotal: ₹{itinerary.total_cost_inr:g}")
    if itinerary.assumptions:
        lines.append("Assumptions:")
        for a in itinerary.assumptions:
            lines.append(f"  - {a}")
    return "\n".join(lines)
