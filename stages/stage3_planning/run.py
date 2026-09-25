"""CLI entrypoint for Stage 3.

Usage:
    python stages/stage3_planning/run.py [--request golden_jaipur] [--replay]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common.cli import main  # noqa: E402
from stages.stage3_planning.graph import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(main("stage3_planning", run))
