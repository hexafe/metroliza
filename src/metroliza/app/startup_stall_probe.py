"""Opt-in GUI-thread stall probe for startup measurements (STEP2 instrumentation).

``METROLIZA_STARTUP_STALL_PROBE=1`` installs a 5 ms QTimer right after QApplication creation. A
timer cannot fire while the GUI thread is busy, so the gap between two ticks is the longest time
the event loop could not process input, paint or animate (for example during the main-window
import and construction, or each feature-warmup import). The summary is written to the startup
profile as ``gui_stall_summary``. It measures only; it changes nothing the user sees.
"""

from __future__ import annotations

import os
import time

from metroliza.app.startup_profile import record_event

STALL_PROBE_ENV = "METROLIZA_STARTUP_STALL_PROBE"
TICK_MS = 5
THRESHOLDS_MS = (50, 100, 250, 500, 1000)

_PROBE = None


class StallProbe:
    def __init__(self, app) -> None:
        from PyQt6.QtCore import QTimer

        self._last = time.perf_counter()
        self.max_gap_ms = 0.0
        self.max_gap_at_ms = 0.0
        self.started = self._last
        self.counts = {threshold: 0 for threshold in THRESHOLDS_MS}
        self.blocked_ms = 0.0
        self._timer = QTimer(app)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        gap_ms = (now - self._last) * 1000.0
        self._last = now
        excess = gap_ms - TICK_MS
        if excess > 20:
            self.blocked_ms += excess
        for threshold in THRESHOLDS_MS:
            if gap_ms >= threshold:
                self.counts[threshold] += 1
        if gap_ms > self.max_gap_ms:
            self.max_gap_ms = gap_ms
            self.max_gap_at_ms = (now - self.started) * 1000.0

    def summary(self, phase: str) -> dict[str, float]:
        self._tick()
        fields = {
            "phase": phase,
            "max_gap_ms": round(self.max_gap_ms, 1),
            "max_gap_at_ms": round(self.max_gap_at_ms, 1),
            "blocked_ms": round(self.blocked_ms, 1),
            "elapsed_probe_ms": round((time.perf_counter() - self.started) * 1000.0, 1),
        }
        fields.update({f"gaps_ge_{threshold}ms": count for threshold, count in self.counts.items()})
        return fields


def install_if_requested(app) -> None:
    global _PROBE
    if _PROBE is not None or os.getenv(STALL_PROBE_ENV) != "1":
        return
    try:
        _PROBE = StallProbe(app)
        record_event("gui_stall_probe_installed")
    except Exception as exc:  # pragma: no cover - measurement aid only.
        record_event("gui_stall_probe_failed", error_type=type(exc).__name__)


def record_summary(phase: str) -> None:
    if _PROBE is not None:
        record_event("gui_stall_summary", **_PROBE.summary(phase))
