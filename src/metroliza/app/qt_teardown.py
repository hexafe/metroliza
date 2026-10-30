"""Order Qt destruction on GUI before CPython's module finalization.

No exit policy is changed. Incomplete workers, visible windows or failed cleanup
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
APPLICATION_RELEASED = False


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


def _delete_hidden_widgets(app, sip, core, event, deadline: float) -> bool:
    attempted = {}
    for _ in range(MAX_DELETE_PASSES):
        widgets = app.topLevelWidgets()
        if any(not sip.isdeleted(widget) and widget.isVisible() for widget in widgets):
            return False
        for widget in widgets:
            if sip.isdeleted(widget) or id(widget) in attempted:
                continue
            # Keep identities alive across drain turns. Never send a close event:
            # product close handlers have already run, or must remain untouched.
            attempted[id(widget)] = widget
            widget.deleteLater()
        _flush(app, core, event)
        if not app.topLevelWidgets():
            return True
        if time.monotonic() >= deadline:
            break
    return False


def _live_qobjects(widget_type, object_type, thread_type, sip, app_thread) -> dict[str, int]:
    counts = dict(widgets=0, running_threads=0, foreign_objects=0)
    # The GUI thread's own QThread always reports isRunning(); only other
    # running threads make release unsafe. SIP keeps one wrapper per native
    # object and app_thread is held for the scan, so identity is exact.
    for obj in gc.get_objects():
        kind = type(obj)
        if not issubclass(kind, object_type) or sip.isdeleted(obj):
            continue
        counts["widgets"] += int(issubclass(kind, widget_type))
        # isdeleted() is reliable only for Python-created objects (the derived
        # destructor notifies SIP). A C++-created child can already be freed
        # with a stale wrapper, so never call one of its methods (#1158).
        if not sip.ispycreated(obj):
            continue
        counts["running_threads"] += int(issubclass(kind, thread_type)
                                         and obj is not app_thread and obj.isRunning())
        counts["foreign_objects"] += int(obj.thread() != app_thread)
    return counts


def shutdown_qt(app=None, *, deadline_s: float = DEFAULT_DEADLINE_S) -> bool:
    """Best-effort GUI-only teardown; return whether the application was released.

    The deadline bounds existing worker waits and the number of event-drain turns,
    not arbitrary Python finalizers. No close handlers are called. Chart joins
    share this deadline after aboutToQuit's existing wait. Off-thread calls are
    quiet no-ops, including GC.
    Repeated/reentrant calls never touch an already deleted native application.
    """
    try:
        widgets = sys.modules.get("PyQt6.QtWidgets")
        if widgets is None:
            return True
        from PyQt6 import sip
        from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QThread

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
            return _shutdown_gui(app, widgets.QWidget, QObject, QThread, sip, QCoreApplication, QEvent, deadline_s)
        finally:
            setattr(app, _ACTIVE_ATTRIBUTE, False)
    except BaseException:
        _event("qt_teardown_incomplete")
        return False


def _shutdown_gui(app, widget_type, object_type, thread_type, sip, core, event, deadline_s: float) -> bool:
    global APPLICATION_RELEASED
    previous_enabled = gc.isenabled()
    gc.disable()
    policy = getattr(app, "_metroliza_gc_policy", None)
    if policy is not None:
        policy.stop()
    deadline = time.monotonic() + min(DEFAULT_DEADLINE_S, max(0.0, deadline_s))
    stopped = _stop_workers(deadline, detached_wait_spent=getattr(app, "_metroliza_detached_exit_wait_spent", False))
    _event("qt_teardown_workers", stopped=int(stopped))
    if not stopped:
        return False
    # Deleting a hidden hierarchy also destroys QThreads it owns; Qt aborts on a
    # running one. Check before any deletion, and again after collection below.
    before = _live_qobjects(widget_type, object_type, thread_type, sip, app.thread())
    if before["running_threads"] or before["foreign_objects"]:
        _event("qt_teardown_retained", running_threads=before["running_threads"],
               foreign_objects=before["foreign_objects"])
        return False
    closed = _delete_hidden_widgets(app, sip, core, event, deadline)
    _event("qt_teardown_widgets", complete=int(closed))
    if not closed:
        _event("qt_teardown_retained", widgets=len(app.topLevelWidgets()))
        return False
    collected = gc.collect()
    _event("qt_teardown_gc", collected=collected)
    _flush(app, core, event)
    # Finalizers/events can create widgets: recheck immediately before release.
    remaining = _live_qobjects(widget_type, object_type, thread_type, sip, app.thread())
    if any(remaining.values()) or app.topLevelWidgets():
        _event("qt_teardown_retained", **remaining)
        return False
    # PyQt6 6.6.1's QApplication destructor runs qtwidgets_cleanup_qobjects;
    # QCoreApplication's destructor runs cleanup_qobjects. SIP invalidates the
    # retained Python wrappers. Dropping local references cannot ensure this:
    # diagnostics, module state and callers may still hold the application.
    sip.delete(app)
    released = sip.isdeleted(app)
    if released:
        APPLICATION_RELEASED = True
        if policy is not None:
            policy.uninstall(application_released=True)
        elif previous_enabled:
            gc.enable()
    _event("qt_teardown_application", released=int(released))
    return released
