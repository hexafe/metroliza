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

# A developer desktop's platform theme or style override (e.g. QT_QPA_PLATFORMTHEME=gtk3
# with a dark GTK theme) changes the default palette and makes colour and geometry
# assertions depend on the host. CI runners set neither, so tests run without them.
for _host_qt_appearance in ("QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE"):
    os.environ.pop(_host_qt_appearance, None)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
