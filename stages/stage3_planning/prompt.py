"""Stage 3's prompts: one for the planner (writes the outline), one for the
day worker (fills in a single day, scoped by that day's entry in the
outline). New relative to Stage 2: instead of one big trip-wide prompt,
each day worker gets a narrow slice -- its own hours, area, budget, and
what's already been used.
"""
from __future__ import annotations

from common.prompts import build_trip_summary
from common.schema import OutlineDay, TripRequest

PLANNER_SYSTEM_PROMPT = (
    "You are planning the outline for a multi-day trip, before any single "
    "day is filled in. For each calendar day, decide: which part of the "
    "city to focus on (to limit travel that day), a short theme, that "
    "day's share of the total budget, and any notes that matter for "
    "filling the day in later -- for example, a hot afternoon, so indoor "
    "stops should be planned then. You may call get_weather and "
    "search_places to inform these choices. Do not decide exact times or "
    "specific places yet -- that happens separately, one day at a time. "
    "Every day's budget share must add up to no more than the total "
    "Budget."
)

PLANNER_WRITER_SYSTEM_PROMPT = (
    "Using what you've learned, write the outline: one entry per calendar "
    "day listed above, each with an area, a theme, a budget share in INR, "
    "and notes."
)

DAY_WORKER_SYSTEM_PROMPT = (
    "You are filling in a single day of a multi-day trip. You have tools "
    "to look up places, restaurants, weather, and travel times. Work step "
    "by step: before every tool call, write one sentence explaining why "
    "you're making it, then call the tool. Stay inside today's time "
    "window, focus area, and budget. When you have what you need, reply "
    "with no further tool calls."
)

DAY_WORKER_WRITER_SYSTEM_PROMPT = (
    "Using only what you learned from the tools above, write today as a "
    "list of time slots (activities, meals, and travel), each with a "
    "start and end time and a cost in INR for the whole group. Do not "
    "invent facts you were not given by a tool. Stay within today's time "
    "window and budget share. Include a travel slot for every move, "
    "including from the stay area at the start of the day and back at "
    "the end."
)


def build_planner_user_prompt(trip: TripRequest, day_dates: list[str]) -> str:
    dates_desc = "\n".join(f"- {d}" for d in day_dates)
    return f"{build_trip_summary(trip)}\n\nDays to plan for:\n{dates_desc}"


def build_day_user_prompt(trip: TripRequest, day: OutlineDay, used_places: list[str]) -> str:
    counts = trip.group_counts()
    party = ", ".join(f"{n} {g}" for g, n in counts.items() if n)
    used = ", ".join(used_places) if used_places else "none yet"
    return (
        f"Destination: {trip.destination}\n"
        f"Date: {day.date}\n"
        f"Travelers: {party}\n"
        f"Stay area (start and end today's plan here): {trip.stay_area}\n"
        f"Plan only between {day.available_from} and {day.available_to} today.\n"
        f"Focus area: {day.area}\n"
        f"Theme: {day.theme}\n"
        f"Budget for today: ₹{day.budget_share_inr:g}\n"
        f"Notes: {day.notes or 'none'}\n"
        f"Places already used on earlier days -- avoid repeating them: {used}"
    )
