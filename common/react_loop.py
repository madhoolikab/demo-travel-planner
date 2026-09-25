"""The ReAct loop, factored out so more than one stage can run it.

Stage 2 is this loop scoped to the whole trip, writing a full Itinerary.
Stage 3's day worker is this same loop scoped to one day, writing a single
Day. Stage 4's reviser is this same loop again, re-run only for the days a
review flagged. Nothing about the loop mechanics changes between them --
only the tools, the prompts, and the output shape do.
"""
from __future__ import annotations

import json
from typing import Annotated, Optional, Type, TypedDict, TypeVar

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from common.llm import get_llm, usage_from_message
from common.trace import Tracer

T = TypeVar("T", bound=BaseModel)


class ReactLoopState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    output: Optional[dict]
    steps: int


def build_react_loop_graph(
    tracer: Tracer,
    tools: list,
    output_schema: Type[T],
    writer_system_prompt: str,
    max_steps: int = 15,
    label: str = "",
):
    """A model bound to `tools` gives a one-sentence thought and picks an
    action, the tools run, and it repeats -- observing each result and
    deciding the next step -- until it replies with no more tool calls, or
    `max_steps` is reached. A final call with no tools attached then writes
    `output_schema` from everything gathered in the conversation so far.

    `label` tags trace events (e.g. a day's date) so a caller running this
    loop several times (once per day) can tell the steps apart in the UI.
    """
    tools_by_name = {t.name: t for t in tools}
    react_llm = get_llm(temperature=0).bind_tools(tools)
    writer_llm = get_llm(temperature=0).with_structured_output(output_schema, include_raw=True)
    prefix = f"[{label}] " if label else ""

    def think_and_act(state: ReactLoopState) -> dict:
        steps = state.get("steps", 0) + 1
        tracer.stage_marker(f"{prefix}step {steps}: model gives a thought and picks the next action")
        ai_message = react_llm.invoke(state["messages"])
        tracer.model_usage(usage_from_message(ai_message), node=f"{label}:react" if label else "react")
        if isinstance(ai_message.content, str) and ai_message.content.strip():
            tracer.thought(ai_message.content.strip(), day=label or None)
        return {"messages": [ai_message], "steps": steps}

    def run_tools(state: ReactLoopState) -> dict:
        last = state["messages"][-1]
        results = []
        for call in last.tool_calls:
            tool = tools_by_name[call["name"]]
            tracer.action(call["name"], call["args"], day=label or None)
            result = tool.invoke(call["args"])
            tracer.observation(call["name"], result, day=label or None)
            results.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"], name=call["name"]))
        return {"messages": results}

    def write_output(state: ReactLoopState) -> dict:
        tracer.stage_marker(f"{prefix}writing the final output (loop ended)")
        messages = state["messages"] + [SystemMessage(content=writer_system_prompt)]
        result = writer_llm.invoke(messages)
        tracer.model_usage(usage_from_message(result.get("raw")), node=f"{label}:writer" if label else "writer")
        parsed: T = result["parsed"]
        return {"output": parsed.model_dump(mode="json")}

    def route(state: ReactLoopState) -> str:
        last = state["messages"][-1]
        wants_tools = bool(getattr(last, "tool_calls", None))
        if wants_tools and state["steps"] >= max_steps:
            tracer.stage_marker(f"{prefix}loop cap ({max_steps} steps) reached, stopping")
            return "write_output"
        return "run_tools" if wants_tools else "write_output"

    graph = StateGraph(ReactLoopState)
    graph.add_node("think_and_act", think_and_act)
    graph.add_node("run_tools", run_tools)
    graph.add_node("write_output", write_output)
    graph.set_entry_point("think_and_act")
    graph.add_conditional_edges(
        "think_and_act", route, {"run_tools": "run_tools", "write_output": "write_output"}
    )
    graph.add_edge("run_tools", "think_and_act")
    graph.add_edge("write_output", END)
    return graph.compile()


def run_react_loop(
    tracer: Tracer,
    system_prompt: str,
    user_prompt: str,
    tools: list,
    output_schema: Type[T],
    writer_system_prompt: str,
    max_steps: int = 15,
    label: str = "",
) -> T:
    app = build_react_loop_graph(tracer, tools, output_schema, writer_system_prompt, max_steps, label)
    initial_state: ReactLoopState = {
        "messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        "output": None,
        "steps": 0,
    }
    final_state = app.invoke(initial_state, config={"recursion_limit": max_steps * 2 + 10})
    return output_schema.model_validate(final_state["output"])
