"""Shared CLI entrypoint for every stage's run.py, so running any stage
looks and behaves the same: load a trip request, run the stage (or replay a
saved run), print the trace as it happens, then the itinerary, the cost
counters, and the scorecard, and save the run for later --replay or for the
web UI.

Usage from a stage's run.py:
    from common.cli import main
    from .graph import run as run_stage
    if __name__ == "__main__":
        sys.exit(main("stage0_baseline", run_stage))
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.render import render_itinerary, render_trip_request  # noqa: E402
from common.runs import load_latest_run, save_run  # noqa: E402
from common.schema import Itinerary, TripRequest  # noqa: E402
from common.trace import Tracer  # noqa: E402
from scoring.score import print_scorecard, score_itinerary  # noqa: E402

REQUESTS_DIR = ROOT / "requests"
DEFAULT_REQUEST = "golden_jaipur"

StageFn = Callable[[TripRequest, Tracer], Itinerary]


def load_request(name: str) -> TripRequest:
    path = REQUESTS_DIR / f"{name}.json"
    if path.exists():
        return TripRequest.model_validate_json(path.read_text())
    # Bonus exercise: a raw city with no data, e.g. "Goa" -- reuse the golden
    # trip's dates/party/budget/stay area, just swap the destination.
    golden = TripRequest.model_validate_json((REQUESTS_DIR / f"{DEFAULT_REQUEST}.json").read_text())
    return golden.model_copy(update={"destination": name})


def main(stage_name: str, run_stage: StageFn, argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=f"Run {stage_name}")
    parser.add_argument(
        "--request", default=DEFAULT_REQUEST, help="Request name in requests/, or a raw city name"
    )
    parser.add_argument("--replay", action="store_true", help="Print a saved run instead of calling the API")
    args = parser.parse_args(argv)

    trip = load_request(args.request)
    print(render_trip_request(trip))
    print(f"\n=== {stage_name} ===")

    if args.replay:
        saved = load_latest_run(stage_name, args.request)
        if not saved:
            print(f"No saved run for {stage_name} / {args.request}. Run once without --replay first.")
            return 1
        itinerary = Itinerary.model_validate(saved["itinerary"])
        print(f"(replaying a saved run from {saved['saved_at']})")
        summary = saved["summary"]
    else:
        tracer = Tracer(stage=stage_name).start()
        itinerary = run_stage(trip, tracer)
        tracer.stop()
        summary = tracer.summary()

    print(render_itinerary(itinerary))
    print(
        f"\nCost: {summary['model_calls']} model call(s), {summary['tool_calls']} tool call(s), "
        f"{summary['total_tokens']} tokens, {summary['seconds']}s"
    )

    print()
    report = score_itinerary(trip, itinerary)
    print_scorecard(report)

    if not args.replay:
        save_run(
            stage_name,
            args.request,
            trip.model_dump(mode="json"),
            itinerary.model_dump(mode="json"),
            tracer.events,
            summary,
            scorecard=report.as_dict(),
        )
    return 0
