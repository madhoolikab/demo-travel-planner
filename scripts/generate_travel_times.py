"""Generates data/<city>/travel_times.json from a simple coordinate map.

This is a one-time authoring helper, not something the workshop runs live.
It computes a plausible cab time/cost for every pair of places (and the stay
area) from rough area coordinates, then applies hand-picked overrides for the
planted traps (e.g. a specific pair that takes much longer than the formula
would suggest). Run it, review the output, then the JSON file is frozen like
the rest of the city data.

Usage: python scripts/generate_travel_times.py <city>
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Coordinates are arbitrary units, roughly km apart, one point per named
# place/restaurant/stay-area used in that city's itineraries.
CITY_CONFIGS = {
    "jaipur": {
        "stay_area": "C-Scheme",
        "coords": {
            "C-Scheme": (0.0, 0.0),
            "Amber Fort": (11.0, 6.0),
            "City Palace": (2.5, 1.2),
            "Hawa Mahal": (2.7, 1.0),
            "Jantar Mantar": (2.6, 1.1),
            "Nahargarh Fort": (3.0, 5.0),
            "Jaigarh Fort": (10.5, 6.3),
            "Albert Hall Museum": (2.0, -1.0),
            "Birla Mandir": (3.5, -2.5),
            "Jal Mahal": (7.0, 3.5),
            "Chokhi Dhani": (-6.0, -9.0),
            "Panna Meena ka Kund": (10.8, 5.8),
            "Galtaji Temple": (8.0, -3.5),
            "Central Park": (0.3, 0.2),
            "Johari Bazaar": (2.3, 1.3),
            "Bapu Bazaar": (2.0, 1.5),
            "Laxmi Misthan Bhandar": (2.4, 1.2),
            "Peacock Rooftop Restaurant": (2.5, 1.1),
            "Tapri Central": (0.2, -0.2),
            "Four Seasons Restaurant": (0.4, 0.3),
            "Handi Restaurant": (0.6, -0.4),
            "Spice Court": (9.0, 5.0),
            "Rawat Mishthan Bhandar": (-1.0, -1.5),
            "Chokhi Dhani Dining": (-6.0, -9.0),
        },
        "peak_windows": [{"start": "08:00", "end": "10:00"}, {"start": "17:00", "end": "19:00"}],
        "peak_time_multiplier": 1.3,
        "peak_cost_multiplier": 1.1,
        # (place_a, place_b) -> override dict. Applied after the formula, so
        # this is where planted traps live.
        "overrides": {
            ("Amber Fort", "Albert Hall Museum"): {
                "normal_minutes": 75,
                "normal_cost_inr": 480,
                "peak_minutes": 95,
                "peak_cost_inr": 520,
            },
        },
    },
    "bangalore": {
        "stay_area": "Indiranagar",
        "coords": {
            "Indiranagar": (0.0, 0.0),
            "Lalbagh Botanical Garden": (-3.0, -4.0),
            "Cubbon Park": (-1.0, -1.0),
            "Bangalore Palace": (-2.0, 0.0),
            "Vidhana Soudha Viewpoint": (-1.2, -0.8),
            "ISKCON Temple": (-6.0, 1.0),
            "Visvesvaraya Industrial and Technological Museum": (-1.0, -1.2),
            "Bannerghatta Biological Park": (-2.0, -16.0),
            "HAL Aerospace Museum": (6.0, -1.0),
            "Commercial Street": (-1.5, 0.5),
            "UB City Mall": (-1.8, -0.5),
            "Indiranagar 100 Feet Road": (0.2, 0.1),
            "Bangalore Aquarium": (-1.0, -1.0),
            "Ulsoor Lake": (0.5, -0.5),
            "Vidyarthi Bhavan": (-4.0, -5.0),
            "Empire Restaurant": (-1.0, 0.0),
            "Toit Brewpub": (0.1, 0.1),
            "Truffles": (0.15, 0.05),
            "Mavalli Tiffin Room": (-3.0, -3.5),
            "Karavalli": (-2.0, 0.0),
            "Corner House Ice Cream": (0.1, -0.05),
            "Nagarjuna Restaurant": (-1.3, -0.3),
        },
        "peak_windows": [{"start": "17:00", "end": "20:00"}],
        # Bangalore's planted trap: heavy evening traffic roughly doubles travel time.
        "peak_time_multiplier": 2.0,
        "peak_cost_multiplier": 1.3,
        "overrides": {},
    },
    "delhi": {
        "stay_area": "Connaught Place",
        "coords": {
            "Connaught Place": (0.0, 0.0),
            "Red Fort": (4.0, 5.0),
            "Humayun's Tomb": (3.0, -3.0),
            "Qutub Minar": (2.0, -14.0),
            "India Gate": (1.0, -1.0),
            "Lotus Temple": (3.0, -11.0),
            "National Museum": (0.5, -1.2),
            "Akshardham Temple": (9.0, -2.0),
            "Jama Masjid": (4.0, 5.2),
            "Chandni Chowk": (3.8, 5.0),
            "Connaught Place Market": (0.1, 0.1),
            "Lodhi Garden": (2.0, -4.0),
            "Dilli Haat": (1.0, -7.0),
            "National Rail Museum": (-3.0, -3.0),
            "Raj Ghat": (4.5, 4.0),
            "Karim's": (4.0, 5.1),
            "Indian Coffee House": (0.05, 0.05),
            "United Coffee House": (0.05, -0.05),
            "Saravana Bhavan": (0.1, 0.02),
            "Paranthe Wali Gali": (3.8, 5.0),
            "Bukhara": (-3.0, -3.0),
            "Khan Chacha": (1.5, -2.0),
            "Dilli Haat Food Court": (1.0, -7.0),
        },
        "peak_windows": [{"start": "08:00", "end": "10:00"}, {"start": "18:00", "end": "20:00"}],
        "peak_time_multiplier": 1.3,
        "peak_cost_multiplier": 1.1,
        "overrides": {},
    },
}

KM_PER_UNIT = 1.5
AVG_SPEED_KMPH = 25
BASE_OVERHEAD_MIN = 8
BASE_COST_INR = 60
COST_PER_KM_INR = 18


def round_to(value: float, nearest: int) -> int:
    return int(round(value / nearest) * nearest)


def compute_pair(a: tuple[float, float], b: tuple[float, float]) -> tuple[int, int]:
    dist_units = math.dist(a, b)
    dist_km = dist_units * KM_PER_UNIT
    minutes = BASE_OVERHEAD_MIN + (dist_km / AVG_SPEED_KMPH) * 60
    cost = BASE_COST_INR + dist_km * COST_PER_KM_INR
    return round_to(minutes, 5), round_to(cost, 10)


def generate(city: str) -> dict:
    config = CITY_CONFIGS[city]
    coords = config["coords"]
    names = list(coords.keys())
    overrides = {frozenset(k): v for k, v in config["overrides"].items()}

    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a_name, b_name = names[i], names[j]
            normal_minutes, normal_cost = compute_pair(coords[a_name], coords[b_name])
            peak_minutes = round_to(normal_minutes * config["peak_time_multiplier"], 5)
            peak_cost = round_to(normal_cost * config["peak_cost_multiplier"], 10)

            override = overrides.get(frozenset((a_name, b_name)))
            if override:
                normal_minutes = override.get("normal_minutes", normal_minutes)
                normal_cost = override.get("normal_cost_inr", normal_cost)
                peak_minutes = override.get("peak_minutes", peak_minutes)
                peak_cost = override.get("peak_cost_inr", peak_cost)

            pairs.append(
                {
                    "from": a_name,
                    "to": b_name,
                    "normal_minutes": normal_minutes,
                    "normal_cost_inr": normal_cost,
                    "peak_minutes": peak_minutes,
                    "peak_cost_inr": peak_cost,
                }
            )

    return {
        "city": city.title(),
        "peak_windows": config["peak_windows"],
        "pairs": pairs,
    }


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CITY_CONFIGS:
        print(f"Usage: python {sys.argv[0]} <{'|'.join(CITY_CONFIGS)}>")
        sys.exit(1)
    city = sys.argv[1]
    result = generate(city)
    out_path = DATA_DIR / city / "travel_times.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {len(result['pairs'])} pairs to {out_path}")


if __name__ == "__main__":
    main()
