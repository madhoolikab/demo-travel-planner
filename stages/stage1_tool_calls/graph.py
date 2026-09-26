"""Stage 1: the model gets all six tools and calls them once, in a single
round, before it writes the itinerary. Graph: a model node that chooses
tool calls, a tool node that runs them, and a second model node with no
tools attached, so it can't ask for more.
"""
from __future__ import annotations

import json
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from common.llm import get_llm, usage_from_message
from common.output_checks import itinerary_day_coverage_error
from common.schema import Itinerary, TripRequest
from common.tools import ALL_TOOLS
from common.trace import Tracer

from .prompt import TOOL_CALLER_SYSTEM_PROMPT, build_user_prompt, build_writer_system_prompt

TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}


class Stage1State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    itinerary: Optional[dict]


def build_graph(tracer: Tracer, trip: TripRequest):
    tool_caller_llm = get_llm(temperature=0).bind_tools(ALL_TOOLS)
    writer_llm = get_llm(temperature=0).with_structured_output(Itinerary, include_raw=True)
    writer_system_prompt = build_writer_system_prompt(trip)
    expected_dates = [d.isoformat() for d in trip.trip_dates()]

    def choose_tools(state: Stage1State) -> dict:
        tracer.stage_marker("Model chooses tool calls")
        ai_message = tool_caller_llm.invoke(state["messages"])
        tracer.model_usage(usage_from_message(ai_message), node="tool_caller")
        return {"messages": [ai_message]}

    def run_tools(state: Stage1State) -> dict:
        tracer.stage_marker("Tools run")
        last = state["messages"][-1]
        results = []
        for call in last.tool_calls:
            tool = TOOLS_BY_NAME[call["name"]]
            tracer.action(call["name"], call["args"])
            result = tool.invoke(call["args"])
            tracer.observation(call["name"], result)
            results.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"], name=call["name"]))
        return {"messages": results}

    def write_itinerary(state: Stage1State) -> dict:
        tracer.stage_marker("Model writes itinerary (no tools attached)")
        messages = state["messages"] + [SystemMessage(content=writer_system_prompt)]
        result = writer_llm.invoke(messages)
        tracer.model_usage(usage_from_message(result.get("raw")), node="writer")
        itinerary: Itinerary = result["parsed"]

        error = itinerary_day_coverage_error(itinerary, expected_dates)
        if error:
            tracer.stage_marker(f"Output failed a check, retrying once: {error}")
            retry_messages = messages + [result["raw"], HumanMessage(content=error)]
            retry_result = writer_llm.invoke(retry_messages)
            tracer.model_usage(usage_from_message(retry_result.get("raw")), node="writer_retry")
            itinerary = retry_result["parsed"]

        tracer.final_itinerary(itinerary.model_dump(mode="json"))
        return {"itinerary": itinerary.model_dump(mode="json")}

    graph = StateGraph(Stage1State)
    graph.add_node("choose_tools", choose_tools)
    graph.add_node("run_tools", run_tools)
    graph.add_node("write_itinerary", write_itinerary)
    graph.set_entry_point("choose_tools")
    graph.add_edge("choose_tools", "run_tools")
    graph.add_edge("run_tools", "write_itinerary")
    graph.add_edge("write_itinerary", END)
    return graph.compile()


def run(trip: TripRequest, tracer: Tracer) -> Itinerary:
    app = build_graph(tracer, trip)
    initial_state: Stage1State = {
        "messages": [
            SystemMessage(content=TOOL_CALLER_SYSTEM_PROMPT),
            HumanMessage(content=build_user_prompt(trip)),
        ],
        "itinerary": None,
    }
    final_state = app.invoke(initial_state)
    return Itinerary.model_validate(final_state["itinerary"])
