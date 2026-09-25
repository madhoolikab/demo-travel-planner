"""Runs every stage several times on a trip request and prints one scorecard
row per stage, one column per failure, so the room can see the improvement
stage by stage. Also records the cost of each run (model calls, tool calls,
tokens, seconds) so the cost can be discussed next to the benefit.

Plain Python orchestration only -- the actual pass/fail judging is entirely
scoring.score, called fresh for every run.

Usage:
    python scoring/run_all.py [--request golden_jaipur] [--runs 3] [--stages stage0_baseline,stage2_react]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.cli import load_request  # noqa: E402
from common.runs import save_run  # noqa: E402
from common.trace import Tracer  # noqa: E402
from scoring.score import FAILURE_IDS, FAILURE_LABELS, score_itinerary  # noqa: E402

STAGE_ORDER = [
    "stage0_baseline",
    "stage1_tool_calls",
    "stage2_react",
    "stage3_planning",
    "stage4_reflection",
]


def _load_stage_run_fn(stage_name: str):
    module = __import__(f"stages.{stage_name}.graph", fromlist=["run"])
    return module.run


def run_stage_n_times(stage_name: str, request_name: str, n: int) -> dict:
    trip = load_request(request_name)
    run_fn = _load_stage_run_fn(stage_name)

    pass_counts = {fid: 0 for fid in FAILURE_IDS}
    overall_pass_count = 0
    summaries = []

    for i in range(n):
        print(f"  run {i + 1}/{n}...", end=" ", flush=True)
        tracer = Tracer(stage=stage_name, on_event=None).start()
        try:
            itinerary = run_fn(trip, tracer)
        finally:
            tracer.stop()
        summary = tracer.summary()
        summaries.append(summary)

        report = score_itinerary(trip, itinerary)
        for fid in FAILURE_IDS:
            if report.results[fid].passed:
                pass_counts[fid] += 1
        if report.overall_pass:
            overall_pass_count += 1

        save_run(
            f"{stage_name}_run{i + 1}",
            request_name,
            trip.model_dump(mode="json"),
            itinerary.model_dump(mode="json"),
            tracer.events,
            summary,
        )
        print("pass" if report.overall_pass else "fail")

    return {
        "stage": stage_name,
        "runs": n,
        "pass_counts": pass_counts,
        "overall_pass_count": overall_pass_count,
        "avg_model_calls": round(mean(s["model_calls"] for s in summaries), 1),
        "avg_tool_calls": round(mean(s["tool_calls"] for s in summaries), 1),
        "avg_tokens": round(mean(s["total_tokens"] for s in summaries), 0),
        "avg_seconds": round(mean(s["seconds"] for s in summaries), 1),
    }


def print_scorecard(rows: list[dict]) -> None:
    label_w = max(len(FAILURE_LABELS[fid]) for fid in FAILURE_IDS)
    header = f"{'Stage':<20}" + "".join(f"{FAILURE_LABELS[fid]:<{label_w + 3}}" for fid in FAILURE_IDS)
    header += f"{'Overall':<10}{'Calls':<8}{'Tools':<8}{'Tokens':<9}{'Seconds':<8}"
    print(header)
    print("-" * len(header))
    for row in rows:
        n = row["runs"]
        cells = "".join(f"{row['pass_counts'][fid]}/{n}".ljust(label_w + 3) for fid in FAILURE_IDS)
        overall = f"{row['overall_pass_count']}/{n}"
        print(
            f"{row['stage']:<20}{cells}{overall:<10}{row['avg_model_calls']:<8}"
            f"{row['avg_tool_calls']:<8}{row['avg_tokens']:<9}{row['avg_seconds']:<8}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", default="golden_jaipur")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--stages",
        default=",".join(STAGE_ORDER),
        help="Comma-separated stage folder names, default: all five",
    )
    args = parser.parse_args(argv)

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    rows = []
    for stage_name in stages:
        print(f"\n=== {stage_name} on {args.request} ({args.runs} runs) ===")
        rows.append(run_stage_n_times(stage_name, args.request, args.runs))

    print("\n\nScorecard\n")
    print_scorecard(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
