"""Sanity checks run on a writer step's structured output, used to trigger
one automatic retry when a model silently drops something it was told to
include.

Observed live, with a real OpenAI call: gpt-4o-mini would sometimes write
only the first day of a 3-day trip and stop (finish_reason "stop", not
"length" -- not a truncation problem, the model just decided it was done),
even with an explicit reminder of every required date in the same prompt.
Prompt wording alone wasn't reliable enough, so the day count is verified
after the fact and, if wrong, the model gets one pointed correction rather
than being trusted blindly.
"""
from __future__ import annotations

from typing import Optional

from common.schema import Day, Itinerary


def itinerary_day_coverage_error(itinerary: Itinerary, expected_dates: list[str]) -> Optional[str]:
    got = [d.date for d in itinerary.days]
    missing = [d for d in expected_dates if d not in got]
    if not missing:
        return None
    return (
        f"Your itinerary is missing {len(missing)} of the {len(expected_dates)} required day(s): "
        f"{', '.join(missing)}. Rewrite the COMPLETE itinerary from scratch, including every one "
        f"of these dates, one entry each: {', '.join(expected_dates)}."
    )


def day_date_error(day: Day, expected_date: str) -> Optional[str]:
    if day.date == expected_date:
        return None
    return f"You wrote the day dated {day.date}, but today is {expected_date}. Rewrite it dated {expected_date}."
