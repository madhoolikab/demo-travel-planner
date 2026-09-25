"""Stage 2: ReAct. Same nodes as Stage 1, plus a conditional edge from the
tool node back to the model node, so the model can check something,
observe the result, and act again -- repeating thought/action/observation
until it replies with no more tool calls, or a cap of 15 steps is hit.
"""
from __future__ import annotations

import json
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.messages import ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from common.llm import get_llm, usage_from_message
from common.schema import Itinerary, TripRequest
from common.tools import ALL_TOOLS
from common.trace import Tracer

from .prompt import REACT_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT, build_user_prompt

TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
MAX_STEPS = 15


class Stage2State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    itinerary: Optional[dict]
    steps: int


def build_graph(tracer: Tracer):
    react_llm = get_llm(temperature=0).bind_tools(ALL_TOOLS)
    writer_llm = get_llm(temperature=0).with_structured_output(Itinerary, include_raw=True)

    def think_and_act(state: Stage2State) -> dict:
        steps = state.get("steps", 0) + 1
        tracer.stage_marker(f"Step {steps}: model gives a thought and picks the next action")
        ai_message = react_llm.invoke(state["messages"])
        tracer.model_usage(usage_from_message(ai_message), node="react")
        if isinstance(ai_message.content, str) and ai_message.content.strip():
            tracer.thought(ai_message.content.strip())
        return {"messages": [ai_message], "steps": steps}

    def run_tools(state: Stage2State) -> dict:
        last = state["messages"][-1]
        results = []
        for call in last.tool_calls:
            tool = TOOLS_BY_NAME[call["name"]]
            tracer.action(call["name"], call["args"])
            result = tool.invoke(call["args"])
            tracer.observation(call["name"], result)
            results.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"], name=call["name"]))
        return {"messages": results}

    def write_itinerary(state: Stage2State) -> dict:
        tracer.stage_marker("Model writes itinerary (loop ended)")
        messages = state["messages"] + [SystemMessage(content=WRITER_SYSTEM_PROMPT)]
        result = writer_llm.invoke(messages)
        tracer.model_usage(usage_from_message(result.get("raw")), node="writer")
        itinerary: Itinerary = result["parsed"]
        tracer.final_itinerary(itinerary.model_dump(mode="json"))
        return {"itinerary": itinerary.model_dump(mode="json")}

    def route(state: Stage2State) -> str:
        last = state["messages"][-1]
        wants_tools = bool(getattr(last, "tool_calls", None))
        if wants_tools and state["steps"] >= MAX_STEPS:
            tracer.stage_marker(f"Loop cap ({MAX_STEPS} steps) reached, stopping")
            return "write_itinerary"
        return "run_tools" if wants_tools else "write_itinerary"

    graph = StateGraph(Stage2State)
    graph.add_node("think_and_act", think_and_act)
    graph.add_node("run_tools", run_tools)
    graph.add_node("write_itinerary", write_itinerary)
    graph.set_entry_point("think_and_act")
    graph.add_conditional_edges(
        "think_and_act", route, {"run_tools": "run_tools", "write_itinerary": "write_itinerary"}
    )
    graph.add_edge("run_tools", "think_and_act")
    graph.add_edge("write_itinerary", END)
    return graph.compile()


def run(trip: TripRequest, tracer: Tracer) -> Itinerary:
    app = build_graph(tracer)
    initial_state: Stage2State = {
        "messages": [
            SystemMessage(content=REACT_SYSTEM_PROMPT),
            HumanMessage(content=build_user_prompt(trip)),
        ],
        "itinerary": None,
        "steps": 0,
    }
    # Each ReAct step is two supersteps (think_and_act, run_tools); leave
    # headroom above MAX_STEPS * 2 for the final write_itinerary step.
    final_state = app.invoke(initial_state, config={"recursion_limit": MAX_STEPS * 2 + 10})
    return Itinerary.model_validate(final_state["itinerary"])
