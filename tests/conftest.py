"""Pytest configuration shared across the test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path


if os.environ.get("QT_QPA_PLATFORM") not in {"offscreen", "minimal"}:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
