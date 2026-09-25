"""Shared trace printing and cost counters, used identically by every stage.

A Tracer records one event per thing that happens (a model call, a thought,
a tool call, a tool result, a stage change, the final itinerary) so that:
  - the terminal / notebook can print a readable step-by-step log, and
  - the backend API can stream the exact same events to the web UI live,
    by passing an `on_event` callback.

Nothing here is stage-specific; stage 0 uses it as much as stage 4.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

Event = dict[str, Any]
EventSink = Callable[[Event], None]


@dataclass
class Tracer:
    stage: str
    on_event: Optional[EventSink] = None
    events: list[Event] = field(default_factory=list)

    model_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    _started_at: Optional[float] = None
    _ended_at: Optional[float] = None

    def start(self) -> "Tracer":
        self._started_at = time.perf_counter()
        self._emit("run_start", {"stage": self.stage})
        return self

    def stop(self) -> "Tracer":
        self._ended_at = time.perf_counter()
        self._emit("run_end", self.summary())
        return self

    @property
    def seconds(self) -> float:
        end = self._ended_at or time.perf_counter()
        start = self._started_at or end
        return round(end - start, 2)

    def summary(self) -> dict:
        return {
            "stage": self.stage,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "seconds": self.seconds,
        }

    # -- event helpers, one per kind of thing worth showing in the room -----

    def thought(self, text: str, day: Optional[str] = None) -> None:
        self._emit("thought", {"text": text, "day": day})
        print(f"  thought: {text}")

    def action(self, tool_name: str, args: dict, day: Optional[str] = None) -> None:
        self.tool_calls += 1
        self._emit("action", {"tool": tool_name, "args": args, "day": day})
        print(f"  action:  {tool_name}({_fmt_args(args)})")

    def observation(self, tool_name: str, result: Any, day: Optional[str] = None) -> None:
        self._emit("observation", {"tool": tool_name, "result": result, "day": day})
        print(f"  observation: {_truncate(result)}")

    def model_usage(self, usage: Optional[dict], node: Optional[str] = None) -> None:
        self.model_calls += 1
        prompt = (usage or {}).get("prompt_tokens", 0) or (usage or {}).get("input_tokens", 0) or 0
        completion = (
            (usage or {}).get("completion_tokens", 0) or (usage or {}).get("output_tokens", 0) or 0
        )
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self._emit(
            "model_call",
            {"node": node, "prompt_tokens": prompt, "completion_tokens": completion},
        )
        print(f"  model call ({node or '-'}): +{prompt + completion} tokens")

    def stage_marker(self, label: str, **payload) -> None:
        self._emit("marker", {"label": label, **payload})
        print(f"-- {label} --")

    def final_itinerary(self, itinerary: dict) -> None:
        self._emit("itinerary", {"itinerary": itinerary})

    def error(self, message: str) -> None:
        self._emit("error", {"message": message})
        print(f"  error: {message}")

    def _emit(self, type_: str, payload: dict) -> None:
        event = {"type": type_, "t": round(time.perf_counter() - (self._started_at or 0), 3), **payload}
        self.events.append(event)
        if self.on_event:
            self.on_event(event)


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def _truncate(value: Any, limit: int = 300) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."
