"""Order Qt destruction on GUI before CPython's module finalization.

No exit policy is changed. Incomplete workers, refused closes or failed cleanup
leave the application alive rather than deleting an unsafe QObject hierarchy.
"""

from __future__ import annotations

import gc
import sys
import time

from metroliza.app.startup_profile import record_event

MAX_DELETE_PASSES = 8
DEFAULT_DEADLINE_S = 5.0  # detached_threads' existing total exit-wait ceiling
_ACTIVE_ATTRIBUTE = "_metroliza_qt_teardown_active"


def _event(name: str, **counts: int) -> None:
    try:
        record_event(name, **counts)
    except BaseException:
        pass


def _stop_workers(deadline: float, *, detached_wait_spent: bool = False) -> bool:
    # Do not import optional services (or create pools) during shutdown.
    charts = sys.modules.get("metroliza.charts.chart_render_service")
    detached = sys.modules.get("metroliza.ui.detached_threads")
    charts_stopped = charts is None or charts.shutdown(deadline=deadline)
    detached_stopped = True
    if detached is not None:
        remaining_ms = min(detached.QUIT_WAIT_TOTAL_MS, max(0, int((deadline - time.monotonic()) * 1000)))
        if detached_wait_spent:
            remaining_ms = 0
        # Do not feed wait(0) to a still-running QThread (Qt 6.6.1); nor
        # grant another wait after the aboutToQuit hook spent its exit budget.
        detached_stopped = not (remaining_ms == 0 and detached.running_threads())
        if detached_stopped:
            detached_stopped = detached.shutdown(total_timeout_ms=remaining_ms)
    return bool(charts_stopped and detached_stopped)


def _flush(app, core, event) -> None:
    core.sendPostedEvents(None, event.Type.DeferredDelete)
    app.processEvents()


def _close_widgets(app, sip, core, event, deadline: float) -> bool:
    attempted = {}
    for _ in range(MAX_DELETE_PASSES):
        widgets = app.topLevelWidgets()
        for widget in widgets:
            if sip.isdeleted(widget) or id(widget) in attempted:
                continue
            # A close handler may already spend its own bounded worker wait.
            # Never repeat that wait on later drain turns. Retain the wrapper
            # locally so a new widget cannot reuse an attempted identity.
            attempted[id(widget)] = widget
            # A refused close can mean a worker still owns the window.
            if widget.close() and not sip.isdeleted(widget):
                widget.deleteLater()
        _flush(app, core, event)
        if not app.topLevelWidgets():
            return True
        if time.monotonic() >= deadline:
            break
    return False


def _live_widgets(widget_type, sip) -> int:
    return sum(isinstance(obj, widget_type) and not sip.isdeleted(obj) for obj in gc.get_objects())


def shutdown_qt(app=None, *, deadline_s: float = DEFAULT_DEADLINE_S) -> bool:
    """Best-effort GUI-only teardown; return whether the application was released.

    The deadline bounds existing worker waits and the number of event-drain turns,
    not arbitrary user close handlers or Python finalizers. Chart joins share
    this deadline. Off-thread calls are quiet no-ops, including GC.
    Repeated/reentrant calls never touch an already deleted native application.
    """
    try:
        widgets = sys.modules.get("PyQt6.QtWidgets")
        if widgets is None:
            return True
        from PyQt6 import sip
        from PyQt6.QtCore import QCoreApplication, QEvent, QThread

        if app is None:
            app = widgets.QApplication.instance()
        if app is None or sip.isdeleted(app):
            return True
        if QThread.currentThread() != app.thread():
            _event("qt_teardown_off_thread")
            return False
        if getattr(app, _ACTIVE_ATTRIBUTE, False):
            return False
        setattr(app, _ACTIVE_ATTRIBUTE, True)
        try:
            return _shutdown_gui(app, widgets.QWidget, sip, QCoreApplication, QEvent, deadline_s)
        finally:
            setattr(app, _ACTIVE_ATTRIBUTE, False)
    except BaseException:
        _event("qt_teardown_incomplete")
        return False


def _shutdown_gui(app, widget_type, sip, core, event, deadline_s: float) -> bool:
    deadline = time.monotonic() + min(DEFAULT_DEADLINE_S, max(0.0, deadline_s))
    stopped = _stop_workers(deadline, detached_wait_spent=getattr(app, "_metroliza_detached_exit_wait_spent", False))
    _event("qt_teardown_workers", stopped=int(stopped))
    if not stopped:
        return False
    closed = _close_widgets(app, sip, core, event, deadline)
    _event("qt_teardown_widgets", complete=int(closed))
    if not closed:
        return False
    policy = getattr(app, "_metroliza_gc_policy", None)
    if policy is not None:
        policy.uninstall()
    collected = gc.collect()
    _event("qt_teardown_gc", collected=collected)
    _flush(app, core, event)
    # Finalizers/events can create widgets: recheck immediately before release.
    remaining = _live_widgets(widget_type, sip)
    if remaining or app.topLevelWidgets():
        _event("qt_teardown_retained", widgets=remaining)
        return False
    # PyQt6 6.6.1's QApplication destructor runs qtwidgets_cleanup_qobjects;
    # QCoreApplication's destructor runs cleanup_qobjects. SIP invalidates the
    # retained Python wrappers. Dropping local references cannot ensure this:
    # diagnostics, module state and callers may still hold the application.
    sip.delete(app)
    released = sip.isdeleted(app)
    _event("qt_teardown_application", released=int(released))
    return released
