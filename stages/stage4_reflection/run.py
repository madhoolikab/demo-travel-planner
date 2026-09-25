"""CLI entrypoint for Stage 4.

Usage:
    python stages/stage4_reflection/run.py [--request golden_jaipur] [--replay]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common.cli import main  # noqa: E402
from stages.stage4_reflection.graph import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(main("stage4_reflection", run))
