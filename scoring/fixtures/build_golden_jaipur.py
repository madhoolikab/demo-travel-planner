"""Builds the hand-written 'golden' Jaipur itinerary fixture, and a set of
'bad' variants that each break exactly one of the five checks, by mutating
the golden one. Every price and travel time is pulled from the real data
files (via scoring.score's own lookup helpers) so the fixture can't drift
from the data through arithmetic mistakes.

Run once to (re)generate scoring/fixtures/*.json. These are checked into
git and are what scoring/test_score.py asserts against.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from common.schema import Itinerary, TripRequest  # noqa: E402
from scoring.score import (  # noqa: E402
    _price_for_place_on_date,
    _travel_expected,
    load_city_data,
)

FIXTURES_DIR = Path(__file__).resolve().parent
TRIP = TripRequest.model_validate_json((ROOT / "requests" / "golden_jaipur.json").read_text())
CITY_DATA = load_city_data(TRIP.destination)
GROUP_COUNTS = TRIP.group_counts()
PARTY = TRIP.party_size()
STAY = TRIP.stay_area


def place_price(name: str, date: str) -> float:
    place = next(p for p in CITY_DATA["places"] if p["name"] == name)
    return _price_for_place_on_date(place, date, GROUP_COUNTS)


def restaurant_price(name: str) -> float:
    r = next(r for r in CITY_DATA["restaurants"] if r["name"] == name)
    return r["avg_price_per_person_inr"] * PARTY


def travel(from_name: str, to_name: str, depart: str) -> dict:
    exp = _travel_expected(CITY_DATA, from_name, to_name, depart)
    assert exp, f"no travel data {from_name} -> {to_name}"
    return exp


def add_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m + minutes
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


class DayBuilder:
    """Walks a day forward in time, inserting a correctly-sized travel slot
    for every move (including from/to the stay area), and pulling prices
    straight from the data.
    """

    def __init__(self, date: str):
        self.date = date
        self.clock = None  # set on first move
        self.place = STAY
        self.slots: list[dict] = []

    def _move_to(self, place: str, ready_time: str) -> str:
        """Inserts a travel slot (if needed) from self.place to `place`,
        departing no earlier than ready_time. Returns the arrival time.
        """
        if place == self.place:
            return ready_time
        exp = travel(self.place, place, ready_time)
        start = ready_time
        end = add_minutes(start, exp["minutes"])
        self.slots.append(
            {
                "kind": "travel",
                "place_name": place,
                "start": start,
                "end": end,
                "cost_inr": exp["cost_inr"],
                "note": f"Cab from {self.place}",
            }
        )
        self.place = place
        return end

    def activity(self, place: str, ready_time: str, start: str | None = None) -> str:
        arrival = self._move_to(place, ready_time)
        start = start or arrival
        if start < arrival:
            start = arrival
        info = next(p for p in CITY_DATA["places"] if p["name"] == place)
        # Respect opening time if the model would sensibly wait for it.
        open_time = info["hours"]["open"] if not info.get("closed_dates") or self.date not in info["closed_dates"] else None
        if open_time and start < open_time:
            start = open_time
        end = add_minutes(start, info["duration_minutes"])
        self.slots.append(
            {
                "kind": "activity",
                "place_name": place,
                "start": start,
                "end": end,
                "cost_inr": place_price(place, self.date),
                "note": f"Tickets for {PARTY} travelers",
            }
        )
        return end

    def meal(self, place: str, ready_time: str, duration_min: int, start: str | None = None) -> str:
        arrival = self._move_to(place, ready_time)
        start = start or arrival
        if start < arrival:
            start = arrival
        end = add_minutes(start, duration_min)
        self.slots.append(
            {
                "kind": "meal",
                "place_name": place,
                "start": start,
                "end": end,
                "cost_inr": restaurant_price(place),
                "note": "Meal for the group",
            }
        )
        return end

    def return_to_stay(self, ready_time: str) -> None:
        self._move_to(STAY, ready_time)

    def build(self) -> dict:
        return {"date": self.date, "slots": self.slots}


def build_day1() -> dict:
    # Sun 2027-04-11, arrival 15:00 -> earliest slot 16:00
    d1 = DayBuilder("2027-04-11")
    t = d1.activity("Central Park", ready_time="16:00")
    t = d1.meal("Four Seasons Restaurant", ready_time=t, duration_min=75)
    d1.return_to_stay(t)
    return d1.build()


def build_day2() -> dict:
    # Mon 2027-04-12 (traps: Nahargarh closed, heatwave 12:00-16:00, festival
    # doubles City Palace, Jaigarh unsuitable for a child - all avoided)
    d2 = DayBuilder("2027-04-12")
    t = d2.activity("City Palace", ready_time="09:00")
    t = d2.activity("Albert Hall Museum", ready_time=t)  # indoor, safe inside the heat window
    t = d2.meal("Four Seasons Restaurant", ready_time=t, duration_min=60)
    t = d2.activity("Birla Mandir", ready_time=t)  # indoor, still inside the heat window
    # push the outdoor stop to start at/after 16:00, past the avoid window
    t = max(t, "16:00")
    t = d2.activity("Bapu Bazaar", ready_time=t)
    t = d2.meal("Peacock Rooftop Restaurant", ready_time=t, duration_min=75)
    d2.return_to_stay(t)
    return d2.build()


def build_day3() -> dict:
    # Tue 2027-04-13, departure 18:00 -> latest slot end 16:00
    d3 = DayBuilder("2027-04-13")
    t = d3.activity("Hawa Mahal", ready_time="09:00")
    t = d3.activity("Jantar Mantar", ready_time=t)
    t = d3.meal("Laxmi Misthan Bhandar", ready_time=t, duration_min=60)
    t = d3.activity("Johari Bazaar", ready_time=t)
    d3.return_to_stay(t)
    return d3.build()


def build_golden() -> dict:
    days = [build_day1(), build_day2(), build_day3()]
    total = round(sum(s["cost_inr"] for day in days for s in day["slots"]), 2)
    itinerary = {
        "days": days,
        "total_cost_inr": total,
        "assumptions": ["All costs and travel times taken from the simulated data tools."],
    }
    return itinerary


def check_feasible(itinerary: dict) -> None:
    from scoring.score import score_itinerary

    it = Itinerary.model_validate(itinerary)
    report = score_itinerary(TRIP, it)
    for fid, r in report.results.items():
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {fid}")
        for issue in r.issues:
            print(f"         - {issue}")
    print("total:", itinerary["total_cost_inr"], "/ budget", TRIP.budget_inr)
    assert report.overall_pass, "golden fixture does not pass all checks!"


def to_minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def make_bad_unknowable_facts(golden: dict) -> dict:
    """Corrupts one real slot's cost so it no longer matches the data price.
    Place names, timing, and travel chain are untouched, so nothing else
    should fail.
    """
    v = copy.deepcopy(golden)
    target = v["days"][0]["slots"][1]  # Central Park activity, true price is 0
    assert target["place_name"] == "Central Park"
    old_cost = target["cost_inr"]
    new_cost = old_cost + 500
    target["cost_inr"] = new_cost
    v["total_cost_inr"] = round(v["total_cost_inr"] + (new_cost - old_cost), 2)
    return v


def make_bad_time_window(golden: dict) -> dict:
    """Shifts day 1's first travel+activity earlier, into the 60-minute
    arrival buffer. Same places, same durations, same costs -- only the
    clock moves, so only the time_window check should fail.
    """
    v = copy.deepcopy(golden)
    day1 = v["days"][0]
    travel_slot, activity_slot = day1["slots"][0], day1["slots"][1]
    assert travel_slot["kind"] == "travel" and activity_slot["kind"] == "activity"

    travel_dur = to_minutes(travel_slot["end"]) - to_minutes(travel_slot["start"])
    activity_dur = to_minutes(activity_slot["end"]) - to_minutes(activity_slot["start"])

    travel_slot["start"] = "15:05"
    travel_slot["end"] = add_minutes(travel_slot["start"], travel_dur)
    activity_slot["start"] = travel_slot["end"]
    activity_slot["end"] = add_minutes(activity_slot["start"], activity_dur)
    return v


def make_bad_budget_overshoot() -> dict:
    """Rebuilds day 1 with an extra, correctly-priced and correctly-timed
    evening stop (Chokhi Dhani) added, so the honestly-computed total goes
    over budget without any single slot being individually wrong.
    """
    d1 = DayBuilder("2027-04-11")
    t = d1.activity("Central Park", ready_time="16:00")
    t = d1.meal("Four Seasons Restaurant", ready_time=t, duration_min=75)
    t = d1.activity("Chokhi Dhani", ready_time=t)
    d1.return_to_stay(t)

    d2 = build_day2()
    d3 = build_day3()
    days = [d1.build(), d2, d3]
    total = round(sum(s["cost_inr"] for day in days for s in day["slots"]), 2)
    return {
        "days": days,
        "total_cost_inr": total,
        "assumptions": ["Adds an extra evening at Chokhi Dhani, pushing the correctly-priced total over budget."],
    }


def make_bad_age_group() -> dict:
    """Rebuilds day 2 with Jaigarh Fort (unsuitable for a child) swapped in
    for City Palace, scheduled inside its own hours and outside the heat
    window, with correct travel both ways -- so only age_group should fail.
    """
    d2 = DayBuilder("2027-04-12")
    t = d2.activity("Jaigarh Fort", ready_time="09:00")
    t = d2.activity("Albert Hall Museum", ready_time=t)
    t = d2.meal("Four Seasons Restaurant", ready_time=t, duration_min=60)
    t = d2.activity("Birla Mandir", ready_time=t)
    t = max(t, "16:00")
    t = d2.activity("Bapu Bazaar", ready_time=t)
    t = d2.meal("Peacock Rooftop Restaurant", ready_time=t, duration_min=75)
    d2.return_to_stay(t)

    d1 = build_day1()
    d3 = build_day3()
    days = [d1, d2.build(), d3]
    total = round(sum(s["cost_inr"] for day in days for s in day["slots"]), 2)
    return {
        "days": days,
        "total_cost_inr": total,
        "assumptions": ["Day 2 visits Jaigarh Fort, whose steep climb the data marks unsuitable for a child."],
    }


def make_bad_logistics(golden: dict) -> dict:
    """Adds Nahargarh Fort, closed on 2027-04-12, as an extra day-2 stop
    with no travel slot to reach it. Both issues (closed, missing travel)
    land in the logistics category, so only logistics should fail.
    """
    v = copy.deepcopy(golden)
    nahargarh_price = place_price("Nahargarh Fort", "2027-04-12")
    v["days"][1]["slots"].append(
        {
            "kind": "activity",
            "place_name": "Nahargarh Fort",
            "start": "20:00",
            "end": "21:30",
            "cost_inr": nahargarh_price,
            "note": "Closed on Mondays, scheduled anyway, with no travel slot to reach it",
        }
    )
    v["total_cost_inr"] = round(v["total_cost_inr"] + nahargarh_price, 2)
    return v


def main():
    golden = build_golden()
    print("=== golden ===")
    check_feasible(golden)
    (FIXTURES_DIR / "golden_jaipur_itinerary.json").write_text(json.dumps(golden, indent=2) + "\n")

    variants = {
        "bad_unknowable_facts": make_bad_unknowable_facts(golden),
        "bad_budget_overshoot": make_bad_budget_overshoot(),
        "bad_time_window": make_bad_time_window(golden),
        "bad_age_group": make_bad_age_group(),
        "bad_logistics": make_bad_logistics(golden),
    }
    for name, itinerary in variants.items():
        (FIXTURES_DIR / f"{name}.json").write_text(json.dumps(itinerary, indent=2) + "\n")

    print("\nWrote", 1 + len(variants), "fixtures to", FIXTURES_DIR)


if __name__ == "__main__":
    main()
