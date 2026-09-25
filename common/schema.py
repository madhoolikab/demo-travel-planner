"""Fixed data formats shared by every stage: the Trip Request the planner reads,
and the Itinerary it must return. Every stage (0 through 4) uses these same
models, so the scoring script can check every stage the same way, and the UI
can render any stage's output the same way.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AgeGroup = Literal["child", "adult", "senior"]
SlotKind = Literal["activity", "meal", "travel"]


class TripRequest(BaseModel):
    """One trip request. Free text destination; only cities with data in
    data/<city>/ can actually be planned for.
    """

    destination: str = Field(..., description="Free text city name, e.g. Jaipur")
    arrival: datetime = Field(..., description="Date and time the group arrives in the city")
    departure: datetime = Field(..., description="Date and time the group leaves the city")
    budget_inr: int = Field(..., gt=0, description="Total on-ground spend for the whole group in INR")
    traveler_age_groups: list[AgeGroup] = Field(
        ..., min_length=1, description="One entry per traveler"
    )
    stay_area: str = Field(..., description="Neighborhood where the group sleeps")

    @field_validator("departure")
    @classmethod
    def departure_after_arrival(cls, v: datetime, info):
        arrival = info.data.get("arrival")
        if arrival is not None and v <= arrival:
            raise ValueError("departure must be after arrival")
        return v

    def trip_dates(self) -> list[date]:
        """One entry per calendar day from arrival to departure, inclusive."""
        days = []
        d = self.arrival.date()
        while d <= self.departure.date():
            days.append(d)
            d = date.fromordinal(d.toordinal() + 1)
        return days

    def group_counts(self) -> dict[str, int]:
        counts = {"child": 0, "adult": 0, "senior": 0}
        for a in self.traveler_age_groups:
            counts[a] += 1
        return counts

    def party_size(self) -> int:
        return len(self.traveler_age_groups)


class Slot(BaseModel):
    """One time slot in a day: an activity, a meal, or travel between places."""

    kind: SlotKind
    place_name: str = Field(..., description="Must match a name in the city's data exactly")
    start: str = Field(..., description="HH:MM, 24-hour")
    end: str = Field(..., description="HH:MM, 24-hour")
    cost_inr: float = Field(..., ge=0, description="Cost in INR for the whole group")
    note: str = ""

    @field_validator("start", "end")
    @classmethod
    def valid_time(cls, v: str) -> str:
        # Raises if not parseable as HH:MM
        time.fromisoformat(v)
        return v

    def start_minutes(self) -> int:
        h, m = self.start.split(":")
        return int(h) * 60 + int(m)

    def end_minutes(self) -> int:
        h, m = self.end.split(":")
        return int(h) * 60 + int(m)


class Day(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    slots: list[Slot] = Field(default_factory=list)


class Itinerary(BaseModel):
    days: list[Day]
    total_cost_inr: float = Field(..., ge=0)
    assumptions: list[str] = Field(default_factory=list)
