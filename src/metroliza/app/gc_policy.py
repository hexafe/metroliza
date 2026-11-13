"""Run cyclic garbage collection only on the QApplication's GUI thread.

Automatic GC runs in whichever Python thread allocates. Collecting a Qt wrapper
cycle there can free signal callables before Qt processes deferred C++ deletion.
Install before starting GUI workers. Application code must never call gc.collect()
from a worker; gc.disable() cannot prevent explicit third-party collections.
Reference-counted destruction is unchanged. A blocked GUI delays cyclic cleanup.
"""

from __future__ import annotations

import gc
import time
import weakref

INTERVAL_MS = 500
_APP_ATTRIBUTE = "_metroliza_gc_policy"
# Resolved once at installation: later checks run inside timer slots, where an
# import could see a test's stubbed PyQt6 module or fail during shutdown.
_QTHREAD = None


def _require_gui_thread(app) -> None:
    global _QTHREAD
    if _QTHREAD is None:
        from PyQt6.QtCore import QThread

        _QTHREAD = QThread
    if _QTHREAD.currentThread() != app.thread():
        raise RuntimeError("Cyclic GC policy must run on the GUI thread")


class GuiGcPolicy:
    """One application-owned timer; at most one collection per generation per tick."""

    def __init__(self, app) -> None:
        from PyQt6.QtCore import QTimer

        self._app = weakref.ref(app)
        self.previous_enabled = gc.isenabled()
        self.previous_thresholds = gc.get_threshold()
        self.collections = [0, 0, 0]
        self.total_ms = 0.0
        self.max_ms = 0.0
        self.active = True
        self._stopped = False
        self._collecting = False
        self.timer = QTimer(app)
        self.timer.setInterval(INTERVAL_MS)
        self.timer.timeout.connect(self.collect_due)
        gc.disable()
        self.timer.start()

    @property
    def app(self):
        """Resolve the application without keeping its Python wrapper alive."""
        return self._app()

    def collect_due(self, *, force_young: bool = False) -> None:
        """Check fresh counters after each generation; never force a full sweep.

        Tests may force a young sweep after teardown, even below threshold. Older
        generations are still bounded by their promotion thresholds. A threshold
        of zero retains Python's disabled automatic-collection semantics.
        """
        _require_gui_thread(self.app)
        if not self.active or self._stopped or self._collecting:
            return
        self._collecting = True
        try:
            for generation in range(3):
                # Generation 2 deliberately uses the promotion threshold without
                # CPython's long-lived ratio heuristic, so promotion pressure
                # still triggers full sweeps with automatic GC disabled.
                # The measured maximum GUI sweep was 42 ms
                # (STEP2 synthetic CSV qualification; see implementation plan).
                threshold = gc.get_threshold()[generation]
                due = threshold > 0 and gc.get_count()[generation] > threshold
                if not due and not (generation == 0 and force_young):
                    break
                started = time.perf_counter()
                gc.collect(generation)
                elapsed_ms = (time.perf_counter() - started) * 1000
                self.collections[generation] += 1
                self.total_ms += elapsed_ms
                self.max_ms = max(self.max_ms, elapsed_ms)
        finally:
            self._collecting = False

    def stop(self) -> None:
        """Stop GUI collections without allowing automatic GC during teardown."""
        _require_gui_thread(self.app)
        if self._stopped:
            return
        self.timer.stop()
        self.timer.timeout.disconnect(self.collect_due)
        self.timer.deleteLater()
        self._stopped = True

    def uninstall(self, *, application_released: bool = False) -> None:
        """Stop the timer and restore the caller's GC settings on the GUI thread.

        The caller must first stop its workers; enabling automatic GC reintroduces
        collection on allocating threads. The deterministic GUI teardown stops
        the timer first and calls this with application_released only after
        successful native destruction, without further Qt method calls.
        """
        if not application_released:
            _require_gui_thread(self.app)
        if not self.active:
            return
        if not application_released:
            self.stop()
        self.active = False
        delattr(self.app, _APP_ATTRIBUTE)
        gc.set_threshold(*self.previous_thresholds)
        if self.previous_enabled:
            gc.enable()
        else:
            gc.disable()


def install(app) -> GuiGcPolicy:
    """Install once for a real GUI application with a running Qt event loop."""
    existing = getattr(app, _APP_ATTRIBUTE, None)
    if isinstance(existing, GuiGcPolicy):
        # No import here: callers re-check after every test, possibly while a test
        # blocks or stubs PyQt6 imports.
        return existing
    from PyQt6.QtWidgets import QApplication

    if not isinstance(app, QApplication):
        raise TypeError("Cyclic GC policy requires QApplication")
    _require_gui_thread(app)
    policy = GuiGcPolicy(app)
    setattr(app, _APP_ATTRIBUTE, policy)
    return policy
