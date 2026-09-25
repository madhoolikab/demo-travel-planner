"""CLI entrypoint for Stage 1.

Usage:
    python stages/stage1_tool_calls/run.py [--request golden_jaipur] [--replay]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common.cli import main  # noqa: E402
from stages.stage1_tool_calls.graph import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(main("stage1_tool_calls", run))
