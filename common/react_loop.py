"""The ReAct loop, factored out so more than one stage can run it.

Stage 2 is this loop scoped to the whole trip, writing a full Itinerary.
Stage 3's day worker is this same loop scoped to one day, writing a single
Day. Stage 4's reviser is this same loop again, re-run only for the days a
review flagged. Nothing about the loop mechanics changes between them --
only the tools, the prompts, and the output shape do.
"""
from __future__ import annotations

import json
from typing import Annotated, Callable, Optional, Type, TypedDict, TypeVar

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
    output_validator: Optional[Callable[[T], Optional[str]]] = None,
):
    """A model bound to `tools` gives a one-sentence thought and picks an
    action, the tools run, and it repeats -- observing each result and
    deciding the next step -- until it replies with no more tool calls, or
    `max_steps` is reached. A final call with no tools attached then writes
    `output_schema` from everything gathered in the conversation so far.

    `label` tags trace events (e.g. a day's date) so a caller running this
    loop several times (once per day) can tell the steps apart in the UI.

    `output_validator`, if given, is called on the parsed output; if it
    returns an error string instead of None, the writer gets one retry with
    that message appended, instead of the (possibly wrong) result being
    trusted outright. See common/output_checks.py for why this exists.
    """
    tools_by_name = {t.name: t for t in tools}
    # One action per step is the ReAct pattern itself, not just a technical
    # limit: parallel_tool_calls=False also sidesteps a real failure mode
    # seen live, where a model tried to request several tools in one
    # malformed text blob that never parsed as real tool_calls, silently
    # producing zero tool calls for that step.
    react_llm = get_llm(temperature=0).bind_tools(tools, parallel_tool_calls=False)
    # On the very first step there is nothing gathered yet, so "decide not
    # to call a tool" is never a reasonable choice -- but observed live,
    # gpt-4o-mini would sometimes do exactly that anyway, narrating an
    # entire plan as plain text instead of using any tool. tool_choice=
    # "required" makes that first call structurally impossible to skip;
    # every later step goes back to normal "auto" so the model can still
    # choose to stop the loop once it actually has something to go on.
    react_llm_first_step = get_llm(temperature=0).bind_tools(
        tools, parallel_tool_calls=False, tool_choice="required"
    )
    writer_llm = get_llm(temperature=0).with_structured_output(output_schema, include_raw=True)
    prefix = f"[{label}] " if label else ""

    def think_and_act(state: ReactLoopState) -> dict:
        steps = state.get("steps", 0) + 1
        tracer.stage_marker(f"{prefix}step {steps}: model gives a thought and picks the next action")
        model = react_llm_first_step if steps == 1 else react_llm
        ai_message = model.invoke(state["messages"])
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
        history = state["messages"]
        if getattr(history[-1], "tool_calls", None):
            # The step cap was hit with the model mid-turn, wanting more
            # tool calls that never ran. An assistant message with
            # tool_calls must be immediately followed by a response for
            # each one, or the API rejects the whole request -- so drop
            # that incomplete turn rather than send a malformed history.
            history = history[:-1]
        messages = history + [SystemMessage(content=writer_system_prompt)]
        result = writer_llm.invoke(messages)
        tracer.model_usage(usage_from_message(result.get("raw")), node=f"{label}:writer" if label else "writer")
        parsed: T = result["parsed"]

        if output_validator:
            error = output_validator(parsed)
            if error:
                tracer.stage_marker(f"{prefix}output failed a check, retrying once: {error}")
                retry_messages = messages + [result["raw"], HumanMessage(content=error)]
                retry_result = writer_llm.invoke(retry_messages)
                tracer.model_usage(
                    usage_from_message(retry_result.get("raw")),
                    node=f"{label}:writer_retry" if label else "writer_retry",
                )
                parsed = retry_result["parsed"]

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
    output_validator: Optional[Callable[[T], Optional[str]]] = None,
) -> T:
    app = build_react_loop_graph(
        tracer, tools, output_schema, writer_system_prompt, max_steps, label, output_validator
    )
    initial_state: ReactLoopState = {
        "messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        "output": None,
        "steps": 0,
    }
    final_state = app.invoke(initial_state, config={"recursion_limit": max_steps * 2 + 10})
    return output_schema.model_validate(final_state["output"])
