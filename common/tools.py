"""The six tools every stage from Stage 1 onward can call. Each one reads a
fixed data file under data/<city>/ and returns the same answer on every run.

The tool names, docstrings, and parameters are written the way a real travel
service's API would be documented. The model never sees anything else about
how these are implemented, and it never learns that the data is simulated.
"""
from __future__ import annotations

import json
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NO_DATA_MESSAGE = "No data available for that city."
KNOWN_CITIES = {"jaipur", "bangalore", "delhi"}


def _normalize_city(city: str) -> Optional[str]:
    key = city.strip().lower()
    return key if key in KNOWN_CITIES else None


@lru_cache(maxsize=None)
def _load_city_file(city_key: str, filename: str) -> Optional[dict]:
    path = DATA_DIR / city_key / filename
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _all_city_keys() -> list[str]:
    return sorted(KNOWN_CITIES)


def _minutes(hhmm: str) -> int:
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


def _find_place(place_name: str) -> tuple[Optional[str], Optional[dict]]:
    """Searches every city's places for an exact (case-insensitive) name
    match. Returns (city_key, place_dict) or (None, None).
    """
    target = place_name.strip().lower()
    for city_key in _all_city_keys():
        data = _load_city_file(city_key, "places.json")
        if not data:
            continue
        for place in data["places"]:
            if place["name"].strip().lower() == target:
                return city_key, place
    return None, None


def _find_travel_pair(from_place: str, to_place: str) -> tuple[Optional[str], Optional[dict]]:
    a, b = from_place.strip().lower(), to_place.strip().lower()
    for city_key in _all_city_keys():
        data = _load_city_file(city_key, "travel_times.json")
        if not data:
            continue
        for pair in data["pairs"]:
            names = {pair["from"].strip().lower(), pair["to"].strip().lower()}
            if names == {a, b}:
                return city_key, pair
    return None, None


def _is_peak(depart_time: str, peak_windows: list[dict]) -> bool:
    t = _minutes(depart_time)
    for window in peak_windows:
        if _minutes(window["start"]) <= t < _minutes(window["end"]):
            return True
    return False


# ---------------------------------------------------------------------------
# The six tools
# ---------------------------------------------------------------------------


@tool
def search_places(city: str, category: Optional[str] = None) -> dict:
    """Search for sights, attractions, and things to do in a city. Returns a
    list of places with their name, category, neighborhood, and typical
    adult ticket price. Does not include opening hours or age suitability;
    use get_place_details for that.

    Args:
        city: City name, e.g. "Jaipur".
        category: Optional category filter, e.g. "fort", "museum", "park",
            "temple", "market". Case-insensitive exact match.
    """
    city_key = _normalize_city(city)
    if not city_key:
        return {"message": NO_DATA_MESSAGE}
    data = _load_city_file(city_key, "places.json")
    if not data:
        return {"message": NO_DATA_MESSAGE}

    results = []
    for place in data["places"]:
        if category and place["category"].strip().lower() != category.strip().lower():
            continue
        results.append(
            {
                "name": place["name"],
                "category": place["category"],
                "area": place["area"],
                "typical_adult_price_inr": place["base_price_inr"]["adult"],
            }
        )
    return {"city": data["city"], "places": results}


@tool
def get_place_details(place_name: str, date: str) -> dict:
    """Get live details for one specific place on one specific date: whether
    it's open, its hours that day, ticket prices for child/adult/senior, how
    much time to plan for a visit, whether it's mostly indoor or outdoor, and
    which traveler age groups it's suitable for.

    Args:
        place_name: Exact place name, e.g. "Amber Fort".
        date: Date in YYYY-MM-DD format.
    """
    city_key, place = _find_place(place_name)
    if not place:
        return {"message": f"No data available for a place named '{place_name}'."}

    is_open = date not in place.get("closed_dates", [])
    override = place.get("date_overrides", {}).get(date, {})
    multiplier = override.get("ticket_multiplier", 1.0)
    prices = {
        group: round(price * multiplier)
        for group, price in place["base_price_inr"].items()
    }

    return {
        "name": place["name"],
        "date": date,
        "is_open": is_open,
        "hours": place["hours"] if is_open else None,
        "ticket_price_inr": prices,
        "time_needed_minutes": place["duration_minutes"],
        "indoor_or_outdoor": place["indoor_outdoor"],
        "suitable_age_groups": place["suitable_age_groups"],
    }


@tool
def search_restaurants(
    city: str, area: Optional[str] = None, max_price_per_person: Optional[float] = None
) -> dict:
    """Search for restaurants in a city, optionally filtered by neighborhood
    and by a maximum average price per person. Returns name, area, cuisine,
    average price per person, and opening hours.

    Args:
        city: City name, e.g. "Jaipur".
        area: Optional neighborhood filter, case-insensitive exact match.
        max_price_per_person: Optional maximum average price per person in INR.
    """
    city_key = _normalize_city(city)
    if not city_key:
        return {"message": NO_DATA_MESSAGE}
    data = _load_city_file(city_key, "restaurants.json")
    if not data:
        return {"message": NO_DATA_MESSAGE}

    results = []
    for r in data["restaurants"]:
        if area and r["area"].strip().lower() != area.strip().lower():
            continue
        if max_price_per_person is not None and r["avg_price_per_person_inr"] > max_price_per_person:
            continue
        results.append(r)
    return {"city": data["city"], "restaurants": results}


@tool
def get_weather(city: str, date: str) -> dict:
    """Get the weather forecast for a city on a specific date: condition,
    high temperature in Celsius, chance of rain, air quality, and any time
    windows to avoid being outdoors.

    Args:
        city: City name, e.g. "Jaipur".
        date: Date in YYYY-MM-DD format.
    """
    city_key = _normalize_city(city)
    if not city_key:
        return {"message": NO_DATA_MESSAGE}
    data = _load_city_file(city_key, "weather.json")
    if not data:
        return {"message": NO_DATA_MESSAGE}

    for day in data["days"]:
        if day["date"] == date:
            return day
    return {"message": f"No forecast available for {date}."}


@tool
def get_travel_time(from_place: str, to_place: str, depart_time: str) -> dict:
    """Get the estimated cab travel time and fare between two named places,
    departing at a specific time of day. Travel time and fare depend on
    traffic at that time of day.

    Args:
        from_place: Exact starting place name, e.g. "C-Scheme" or "Amber Fort".
        to_place: Exact destination place name.
        depart_time: Departure time, HH:MM 24-hour.
    """
    city_key, pair = _find_travel_pair(from_place, to_place)
    if not pair:
        return {
            "message": f"No travel time data available between '{from_place}' and '{to_place}'."
        }
    data = _load_city_file(city_key, "travel_times.json")
    peak = _is_peak(depart_time, data.get("peak_windows", []))
    minutes = pair["peak_minutes"] if peak else pair["normal_minutes"]
    cost = pair["peak_cost_inr"] if peak else pair["normal_cost_inr"]
    return {
        "from": from_place,
        "to": to_place,
        "depart_time": depart_time,
        "minutes": minutes,
        "cab_cost_inr": cost,
    }


@tool
def calculate_total(amounts: list[float]) -> dict:
    """Add up a list of amounts and return the sum. Use this instead of
    adding numbers yourself, especially for running totals across a
    multi-day plan.

    Args:
        amounts: List of numbers to sum.
    """
    return {"total": round(sum(amounts), 2)}


ALL_TOOLS = [
    search_places,
    get_place_details,
    search_restaurants,
    get_weather,
    get_travel_time,
    calculate_total,
]
