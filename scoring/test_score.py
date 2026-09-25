"""Tests the scoring script itself against hand-written fixtures, before any
stage exists. Per the build spec: one itinerary that should pass all five
checks, and one bad itinerary per failure that breaks exactly that one
check. Run with: python scoring/test_score.py

Regenerate the fixtures (if the data or the checks change) with:
    python scoring/fixtures/build_golden_jaipur.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.schema import Itinerary, TripRequest  # noqa: E402
from scoring.score import FAILURE_IDS, score_itinerary  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
TRIP = TripRequest.model_validate_json((ROOT / "requests" / "golden_jaipur.json").read_text())

BAD_VARIANTS = {
    "bad_unknowable_facts.json": "unknowable_facts",
    "bad_budget_overshoot.json": "budget_overshoot",
    "bad_time_window.json": "time_window",
    "bad_age_group.json": "age_group",
    "bad_logistics.json": "logistics",
}


def load(name: str) -> Itinerary:
    return Itinerary.model_validate_json((FIXTURES_DIR / name).read_text())


def run() -> bool:
    ok = True

    golden = load("golden_jaipur_itinerary.json")
    report = score_itinerary(TRIP, golden)
    if report.overall_pass:
        print("[PASS] golden itinerary passes all five checks")
    else:
        ok = False
        print("[FAIL] golden itinerary should pass everything but didn't:")
        for fid in FAILURE_IDS:
            r = report.results[fid]
            if not r.passed:
                for issue in r.issues:
                    print(f"        {fid}: {issue}")

    for fname, expected_failure in BAD_VARIANTS.items():
        itinerary = load(fname)
        report = score_itinerary(TRIP, itinerary)
        failed = [fid for fid in FAILURE_IDS if not report.results[fid].passed]
        if failed == [expected_failure]:
            print(f"[PASS] {fname} fails only {expected_failure}")
        else:
            ok = False
            print(f"[FAIL] {fname} expected to fail only [{expected_failure}], actually failed {failed}")
            for fid in failed:
                for issue in report.results[fid].issues:
                    print(f"        {fid}: {issue}")

    # A city with no data should come back as a clean "no data" result, not
    # a crash, and every check should fail.
    no_data_trip = TRIP.model_copy(update={"destination": "Goa"})
    report = score_itinerary(no_data_trip, golden)
    if report.no_data and not report.overall_pass:
        print("[PASS] unknown city ('Goa') reports no_data and fails cleanly")
    else:
        ok = False
        print("[FAIL] unknown city did not report no_data as expected")

    return ok


if __name__ == "__main__":
    success = run()
    print()
    print("ALL TESTS PASSED" if success else "SOME TESTS FAILED")
    sys.exit(0 if success else 1)
