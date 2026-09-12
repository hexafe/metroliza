"""Pytest configuration shared across the test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path


expected_qt_platform = os.environ.get("METROLIZA_EXPECT_QT_PLATFORM", "").strip()
if expected_qt_platform:
    if not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = expected_qt_platform
elif os.environ.get("QT_QPA_PLATFORM") not in {"offscreen", "minimal"}:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
