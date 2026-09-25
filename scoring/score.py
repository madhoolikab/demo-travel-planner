"""Checks one Itinerary against the simulated data for its Trip Request.

Plain Python, no model calls, ever. Used identically for every stage (Stage
4's reviewer must never import this — it's the independent judge). Five
failure checks, each returning pass/fail plus a list of the specific broken
checks so the scorecard can say exactly what's wrong, e.g. "a named fort is
closed on Monday at 10:00".
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, time as time_cls, timedelta
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from common.schema import Day, Itinerary, Slot, TripRequest  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Defaults that can be changed in one place, per the build spec.
ARRIVAL_BUFFER_MIN = 60
DEPARTURE_BUFFER_MIN = 120
PRICE_TOLERANCE = 0.10  # 10%

FAILURE_IDS = ["unknowable_facts", "budget_overshoot", "time_window", "age_group", "logistics"]

FAILURE_LABELS = {
    "unknowable_facts": "Unknowable facts",
    "budget_overshoot": "Budget overshoot",
    "time_window": "Time window",
    "age_group": "Age group",
    "logistics": "Logistics",
}


@dataclass
class CheckResult:
    failure: str
    passed: bool
    issues: list[str] = field(default_factory=list)


@dataclass
class ScoreReport:
    destination: str
    results: dict[str, CheckResult]
    no_data: bool = False

    @property
    def overall_pass(self) -> bool:
        return all(r.passed for r in self.results.values())

    def as_dict(self) -> dict:
        return {
            "destination": self.destination,
            "no_data": self.no_data,
            "overall_pass": self.overall_pass,
            "failures": {
                fid: {"label": FAILURE_LABELS[fid], "passed": r.passed, "issues": r.issues}
                for fid, r in self.results.items()
            },
        }


# ---------------------------------------------------------------------------
# Data loading (independent of common/tools.py on purpose: the scorer must
# stay a plain, standalone judge)
# ---------------------------------------------------------------------------


def load_city_data(city: str) -> Optional[dict]:
    folder = DATA_DIR / city.strip().lower()
    if not folder.exists():
        return None
    return {
        "places": json.loads((folder / "places.json").read_text())["places"],
        "restaurants": json.loads((folder / "restaurants.json").read_text())["restaurants"],
        "weather": {
            d["date"]: d for d in json.loads((folder / "weather.json").read_text())["days"]
        },
        "travel": json.loads((folder / "travel_times.json").read_text()),
    }


def _place_by_name(city_data: dict, name: str) -> Optional[dict]:
    return next((p for p in city_data["places"] if p["name"] == name), None)


def _restaurant_by_name(city_data: dict, name: str) -> Optional[dict]:
    return next((r for r in city_data["restaurants"] if r["name"] == name), None)


def _travel_pair(city_data: dict, a: str, b: str) -> Optional[dict]:
    return next(
        (p for p in city_data["travel"]["pairs"] if {p["from"], p["to"]} == {a, b}), None
    )


def _minutes(hhmm: str) -> int:
    t = time_cls.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


def _is_peak(city_data: dict, hhmm: str) -> bool:
    t = _minutes(hhmm)
    return any(
        _minutes(w["start"]) <= t < _minutes(w["end"])
        for w in city_data["travel"].get("peak_windows", [])
    )


def _overlaps(s1: int, e1: int, s2: int, e2: int) -> bool:
    return s1 < e2 and s2 < e1


def _within_tolerance(actual: float, expected: float, tol: float = PRICE_TOLERANCE) -> bool:
    if expected == 0:
        return abs(actual) <= 1  # allow trivial rounding around free entries
    return abs(actual - expected) <= tol * expected


def _price_for_place_on_date(place: dict, date: str, group_counts: dict[str, int]) -> float:
    override = place.get("date_overrides", {}).get(date, {})
    multiplier = override.get("ticket_multiplier", 1.0)
    return sum(
        place["base_price_inr"][group] * multiplier * count for group, count in group_counts.items()
    )


def _travel_expected(city_data: dict, from_name: str, to_name: str, depart_hhmm: str) -> Optional[dict]:
    pair = _travel_pair(city_data, from_name, to_name)
    if not pair:
        return None
    peak = _is_peak(city_data, depart_hhmm)
    return {
        "minutes": pair["peak_minutes"] if peak else pair["normal_minutes"],
        "cost_inr": pair["peak_cost_inr"] if peak else pair["normal_cost_inr"],
    }


# ---------------------------------------------------------------------------
# Shared per-day analysis: resolves each slot against the data once, so the
# unknowable-facts and logistics checks don't duplicate the place/travel
# lookups.
# ---------------------------------------------------------------------------


@dataclass
class SlotInfo:
    slot: Slot
    prev_place: str
    is_move: bool
    place_record: Optional[dict] = None
    restaurant_record: Optional[dict] = None
    travel_expected: Optional[dict] = None
    missing_travel: bool = False


def _analyze_day(city_data: dict, stay_area: str, day: Day) -> tuple[list[SlotInfo], str]:
    slots_sorted = sorted(day.slots, key=lambda s: s.start_minutes())
    infos: list[SlotInfo] = []
    current = stay_area
    for slot in slots_sorted:
        is_move = slot.place_name != current
        info = SlotInfo(slot=slot, prev_place=current, is_move=is_move)
        if slot.kind == "activity":
            info.place_record = _place_by_name(city_data, slot.place_name)
            # An unknown place is unknowable_facts' concern, not logistics';
            # only flag a missing travel slot for a move between known places.
            info.missing_travel = is_move and info.place_record is not None
        elif slot.kind == "meal":
            info.restaurant_record = _restaurant_by_name(city_data, slot.place_name)
            info.missing_travel = is_move and info.restaurant_record is not None
        elif slot.kind == "travel":
            info.travel_expected = _travel_expected(city_data, current, slot.place_name, slot.start)
            current = slot.place_name
        infos.append(info)
    return infos, current


def _name_known(city_data: dict, stay_area: str, name: str) -> bool:
    if name == stay_area:
        return True
    return _place_by_name(city_data, name) is not None or _restaurant_by_name(city_data, name) is not None


# ---------------------------------------------------------------------------
# The five checks
# ---------------------------------------------------------------------------


def check_unknowable_facts(trip: TripRequest, itinerary: Itinerary, city_data: dict) -> CheckResult:
    issues: list[str] = []
    group_counts = trip.group_counts()
    party = trip.party_size()

    for day in itinerary.days:
        infos, _ = _analyze_day(city_data, trip.stay_area, day)
        for info in infos:
            slot = info.slot
            if slot.kind == "activity":
                if not info.place_record:
                    issues.append(f"{day.date} {slot.start} '{slot.place_name}' is not a place in the data")
                    continue
                expected = _price_for_place_on_date(info.place_record, day.date, group_counts)
                if not _within_tolerance(slot.cost_inr, expected):
                    issues.append(
                        f"{day.date} {slot.start} {slot.place_name}: cost ₹{slot.cost_inr:g} "
                        f"is not within 10% of the data price ₹{expected:g}"
                    )
            elif slot.kind == "meal":
                if not info.restaurant_record:
                    issues.append(f"{day.date} {slot.start} '{slot.place_name}' is not a restaurant in the data")
                    continue
                expected = info.restaurant_record["avg_price_per_person_inr"] * party
                if not _within_tolerance(slot.cost_inr, expected):
                    issues.append(
                        f"{day.date} {slot.start} {slot.place_name}: cost ₹{slot.cost_inr:g} "
                        f"is not within 10% of the data price ₹{expected:g}"
                    )
            elif slot.kind == "travel":
                if not _name_known(city_data, trip.stay_area, slot.place_name):
                    issues.append(f"{day.date} {slot.start} '{slot.place_name}' is not a place in the data")
                    continue
                if info.travel_expected is None:
                    issues.append(
                        f"{day.date} {slot.start} no travel data between "
                        f"'{info.prev_place}' and '{slot.place_name}'"
                    )
                    continue
                expected = info.travel_expected["cost_inr"]
                if not _within_tolerance(slot.cost_inr, expected):
                    issues.append(
                        f"{day.date} {slot.start} travel to {slot.place_name}: cost ₹{slot.cost_inr:g} "
                        f"is not within 10% of the data price ₹{expected:g}"
                    )

    return CheckResult("unknowable_facts", len(issues) == 0, issues)


def check_budget_overshoot(trip: TripRequest, itinerary: Itinerary, city_data: dict) -> CheckResult:
    issues: list[str] = []
    computed_total = sum(slot.cost_inr for day in itinerary.days for slot in day.slots)
    if abs(computed_total - itinerary.total_cost_inr) > 1:
        issues.append(
            f"stated total ₹{itinerary.total_cost_inr:g} does not match the sum of slot costs "
            f"₹{computed_total:g}"
        )
    if itinerary.total_cost_inr > trip.budget_inr:
        issues.append(
            f"total ₹{itinerary.total_cost_inr:g} exceeds the budget ₹{trip.budget_inr:g}"
        )
    return CheckResult("budget_overshoot", len(issues) == 0, issues)


def check_time_window(trip: TripRequest, itinerary: Itinerary, city_data: dict) -> CheckResult:
    issues: list[str] = []
    arrival_date = trip.arrival.date().isoformat()
    departure_date = trip.departure.date().isoformat()
    earliest_allowed = trip.arrival + timedelta(minutes=ARRIVAL_BUFFER_MIN)
    latest_allowed = trip.departure - timedelta(minutes=DEPARTURE_BUFFER_MIN)

    for day in itinerary.days:
        for slot in day.slots:
            day_date = date_cls.fromisoformat(day.date)
            if day.date == arrival_date:
                start_dt = datetime.combine(day_date, time_cls.fromisoformat(slot.start))
                if start_dt < earliest_allowed:
                    issues.append(
                        f"{day.date} {slot.place_name} starts at {slot.start}, earlier than "
                        f"{ARRIVAL_BUFFER_MIN} minutes after arrival ({earliest_allowed.strftime('%H:%M')})"
                    )
            if day.date == departure_date:
                end_dt = datetime.combine(day_date, time_cls.fromisoformat(slot.end))
                if end_dt > latest_allowed:
                    issues.append(
                        f"{day.date} {slot.place_name} ends at {slot.end}, later than "
                        f"{DEPARTURE_BUFFER_MIN} minutes before departure ({latest_allowed.strftime('%H:%M')})"
                    )
    return CheckResult("time_window", len(issues) == 0, issues)


def check_age_group(trip: TripRequest, itinerary: Itinerary, city_data: dict) -> CheckResult:
    issues: list[str] = []
    traveler_groups = set(trip.traveler_age_groups)
    for day in itinerary.days:
        for slot in day.slots:
            if slot.kind != "activity":
                continue
            place = _place_by_name(city_data, slot.place_name)
            if not place:
                continue  # unknowable_facts already reports this
            missing = traveler_groups - set(place["suitable_age_groups"])
            if missing:
                issues.append(
                    f"{day.date} {slot.place_name} is not suitable for: {', '.join(sorted(missing))}"
                )
    return CheckResult("age_group", len(issues) == 0, issues)


def check_logistics(trip: TripRequest, itinerary: Itinerary, city_data: dict) -> CheckResult:
    issues: list[str] = []
    for day in itinerary.days:
        infos, final_place = _analyze_day(city_data, trip.stay_area, day)
        for info in infos:
            slot = info.slot

            if slot.kind == "activity" and info.place_record:
                place = info.place_record
                if day.date in place.get("closed_dates", []):
                    issues.append(f"{day.date} {slot.place_name} is closed on this date but is scheduled at {slot.start}")
                else:
                    open_m, close_m = _minutes(place["hours"]["open"]), _minutes(place["hours"]["close"])
                    if slot.start_minutes() < open_m or slot.end_minutes() > close_m:
                        issues.append(
                            f"{day.date} {slot.place_name} is scheduled {slot.start}-{slot.end}, "
                            f"outside its hours {place['hours']['open']}-{place['hours']['close']}"
                        )
                if place["indoor_outdoor"] == "outdoor":
                    weather = city_data["weather"].get(day.date)
                    for w in (weather or {}).get("avoid_outdoor_windows", []):
                        if _overlaps(slot.start_minutes(), slot.end_minutes(), _minutes(w["start"]), _minutes(w["end"])):
                            issues.append(
                                f"{day.date} {slot.place_name} at {slot.start}-{slot.end} falls in the "
                                f"outdoor-avoid window {w['start']}-{w['end']} ({w.get('reason', 'bad weather')})"
                            )

            if slot.kind == "meal" and info.restaurant_record:
                r = info.restaurant_record
                open_m, close_m = _minutes(r["hours"]["open"]), _minutes(r["hours"]["close"])
                if slot.start_minutes() < open_m or slot.end_minutes() > close_m:
                    issues.append(
                        f"{day.date} {slot.place_name} is scheduled {slot.start}-{slot.end}, "
                        f"outside its hours {r['hours']['open']}-{r['hours']['close']}"
                    )

            if info.missing_travel:
                issues.append(
                    f"{day.date} {slot.start} moves from '{info.prev_place}' to "
                    f"'{slot.place_name}' with no travel slot"
                )

            if slot.kind == "travel":
                # Unknown places are unknowable_facts' concern; only flag
                # missing travel data here when both ends are known places.
                both_known = _name_known(city_data, trip.stay_area, info.prev_place) and _name_known(
                    city_data, trip.stay_area, slot.place_name
                )
                if info.travel_expected is None and both_known:
                    issues.append(
                        f"{day.date} {slot.start} no travel time data from "
                        f"'{info.prev_place}' to '{slot.place_name}'"
                    )
                elif info.travel_expected is not None:
                    actual = slot.end_minutes() - slot.start_minutes()
                    needed = info.travel_expected["minutes"]
                    if actual < needed:
                        issues.append(
                            f"{day.date} travel {info.prev_place} -> {slot.place_name} is only "
                            f"{actual} min, needs at least {needed} min"
                        )

        if final_place != trip.stay_area and _name_known(city_data, trip.stay_area, final_place):
            issues.append(
                f"{day.date} no travel slot back to the stay area ({trip.stay_area}) "
                f"from '{final_place}' at the end of the day"
            )
    return CheckResult("logistics", len(issues) == 0, issues)


CHECKS = {
    "unknowable_facts": check_unknowable_facts,
    "budget_overshoot": check_budget_overshoot,
    "time_window": check_time_window,
    "age_group": check_age_group,
    "logistics": check_logistics,
}


def score_itinerary(trip: TripRequest, itinerary: Itinerary) -> ScoreReport:
    city_data = load_city_data(trip.destination)
    if not city_data:
        results = {
            fid: CheckResult(fid, False, [f"No data available for '{trip.destination}'"])
            for fid in FAILURE_IDS
        }
        return ScoreReport(trip.destination, results, no_data=True)

    results = {fid: fn(trip, itinerary, city_data) for fid, fn in CHECKS.items()}
    return ScoreReport(trip.destination, results)


def print_scorecard(report: ScoreReport) -> None:
    print(f"Scorecard for {report.destination}")
    for fid in FAILURE_IDS:
        r = report.results[fid]
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {FAILURE_LABELS[fid]}")
        for issue in r.issues:
            print(f"         - {issue}")
    print(f"  Overall: {'PASS' if report.overall_pass else 'FAIL'}")


def score_files(itinerary_path: str, trip_request_path: str) -> ScoreReport:
    itinerary = Itinerary.model_validate_json(Path(itinerary_path).read_text())
    trip = TripRequest.model_validate_json(Path(trip_request_path).read_text())
    return score_itinerary(trip, itinerary)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <itinerary.json> <trip_request.json>")
        sys.exit(1)
    report = score_files(sys.argv[1], sys.argv[2])
    print_scorecard(report)
    sys.exit(0 if report.overall_pass else 1)
