"""Stage 0: one call to the model, no tools, no graph. This is the
baseline every later stage is compared against. It's called graph.py to
keep the same module shape as stages 1-4, even though there is no LangGraph
graph here -- the build spec is explicit that Stage 0 has none.
"""
from __future__ import annotations

from common.llm import get_llm
from common.schema import Itinerary, TripRequest
from common.trace import Tracer

from .prompt import SYSTEM_PROMPT, build_user_prompt


def run(trip: TripRequest, tracer: Tracer) -> Itinerary:
    llm = get_llm(temperature=0).with_structured_output(Itinerary, include_raw=True)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(trip)},
    ]
    tracer.stage_marker("Calling the model with no tools and no data")
    result = llm.invoke(messages)

    raw = result.get("raw")
    usage = getattr(raw, "usage_metadata", None) if raw is not None else None
    tracer.model_usage(_normalize_usage(usage), node="baseline")

    itinerary: Itinerary = result["parsed"]
    tracer.final_itinerary(itinerary.model_dump(mode="json"))
    return itinerary


def _normalize_usage(usage) -> dict:
    if not usage:
        return {}
    return {
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
    }
