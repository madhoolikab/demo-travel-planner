"""Stage 2: ReAct. The model calls tools repeatedly, giving a one-sentence
thought before each call, observing the result, and deciding the next step
-- until it's ready to write the itinerary, or a cap of 15 steps is hit.

This is exactly common.react_loop's loop, scoped to the whole trip. Stage 3
reuses the same loop, scoped to one day at a time.
"""
from __future__ import annotations

from common.output_checks import itinerary_day_coverage_error
from common.react_loop import build_react_loop_graph, run_react_loop
from common.schema import Itinerary, TripRequest
from common.tools import ALL_TOOLS
from common.trace import Tracer

from .prompt import REACT_SYSTEM_PROMPT, build_user_prompt, build_writer_system_prompt

MAX_STEPS = 15


def _day_coverage_validator(trip: TripRequest):
    expected = [d.isoformat() for d in trip.trip_dates()]
    return lambda itinerary: itinerary_day_coverage_error(itinerary, expected)


def build_graph(tracer: Tracer, trip: TripRequest):
    """Exposed for inspection (e.g. printing the graph topology); run()
    below is what stages/stage2_react/run.py actually calls.
    """
    return build_react_loop_graph(
        tracer,
        ALL_TOOLS,
        Itinerary,
        build_writer_system_prompt(trip),
        MAX_STEPS,
        output_validator=_day_coverage_validator(trip),
    )


def run(trip: TripRequest, tracer: Tracer) -> Itinerary:
    return run_react_loop(
        tracer=tracer,
        system_prompt=REACT_SYSTEM_PROMPT,
        user_prompt=build_user_prompt(trip),
        tools=ALL_TOOLS,
        output_schema=Itinerary,
        writer_system_prompt=build_writer_system_prompt(trip),
        max_steps=MAX_STEPS,
        output_validator=_day_coverage_validator(trip),
    )
