"""CLI entrypoint for Stage 0.

Usage:
    python stages/stage0_baseline/run.py [--request golden_jaipur] [--replay]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common.cli import main  # noqa: E402
from stages.stage0_baseline.graph import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(main("stage0_baseline", run))
