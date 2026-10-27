"""Keep background QThreads alive until they finish, and bound the wait for them at application exit.

A dialog that stops a worker waits only a short time for it; a worker that has not finished by then is
detached: it runs to completion in the background and its result is dropped. Such threads are registered
here so that

* a running ``QThread`` is never garbage-collected (Qt aborts with "Destroyed while thread is still
  running"),
* application exit waits for them for a bounded total time before the interpreter finalizes, and
* cleanup that must not run while a detached worker still holds a resource (for example the temporary
  industrial cache database on Windows) can be deferred with ``run_when_finished``.

The module imports Qt lazily so that modules that stub Qt in tests can still import it.
Non-cancellable owners may opt in to deferring normal Quit events until native completion;
direct exit, process termination and unrelated shutdown hooks are outside that guarantee.
"""

from __future__ import annotations

import functools
import logging
import time
import weakref
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

# Upper bound for the whole wait at application exit, not per thread.
QUIT_WAIT_TOTAL_MS = 5000
# ``finished`` is emitted by the worker just before it leaves ``QThread::finish()``; this bounds the
# wait for that last step before the registry lets go of the thread.
FINISH_SETTLE_MS = 200

_REGISTERED: set = set()
_DEFERRED: list[tuple[tuple, Callable[[], None]]] = []
_HOOKED_APPS: list = []
_QUIT_BLOCKERS: dict[int, object] = {}


def _is_finished(thread) -> bool:
    try:
        return bool(thread.isFinished())
    except RuntimeError:  # the native object is already gone
        return True


def register(thread, *, defer_quit: bool = False, owner=None, on_finished=None) -> None:
    """Keep ``thread`` referenced until it has finished; call before ``thread.start()``.

    Call it on the GUI thread (the thread that owns ``thread``). The ``finished`` hook must not hold a
    strong reference to ``thread``: a connected closure that captures it forms a reference cycle through
    the native slot proxy, and the cyclic garbage collector then destroys the ``QThread`` in whichever
    thread happens to run a collection, for example another worker, instead of on the GUI thread.
    ``defer_quit=True`` requires a live application and never interrupts or joins this worker.
    Optional ``on_finished(owner, thread)`` keeps ownership pending through the entire GUI callback;
    destruction of the weakly held owner abandons delivery. Use an unbound callback, not a bound method.
    """

    if on_finished is not None:
        if not defer_quit or owner is None:
            raise ValueError("GUI completion requires an owner and Quit deferral")
        thread._metroliza_delivery_pending = True
        thread_ref = weakref.ref(thread)
        owner.destroyed.connect(functools.partial(_abandon_delivery, thread_ref))
        thread.finished.connect(functools.partial(_consume_delivery, weakref.ref(owner), thread_ref, on_finished))
    if defer_quit:
        _quit_deferral()
    _REGISTERED.add(thread)
    _install_quit_hook()
    if defer_quit:
        _QUIT_BLOCKERS[id(thread)] = thread
    thread.finished.connect(functools.partial(_on_thread_finished, weakref.ref(thread)))


def _abandon_delivery(thread_ref, *_args) -> None:
    thread = thread_ref()
    if thread is not None and not vars(thread).get("_metroliza_delivery_active", False):
        thread._metroliza_delivery_pending = False
        discard(thread)


def _consume_delivery(owner_ref, thread_ref, callback) -> None:
    thread, owner = thread_ref(), owner_ref()
    if thread is None or not thread._metroliza_delivery_pending:
        return
    thread._metroliza_delivery_active = True
    try:
        if owner is not None:
            callback(owner, thread)
    finally:
        thread._metroliza_delivery_active = False
        _abandon_delivery(thread_ref)


def _completion_ready(thread) -> bool:
    if id(thread) not in _QUIT_BLOCKERS:
        return _is_finished(thread)
    if getattr(thread, "_metroliza_delivery_pending", False):
        return False
    # finished precedes native cleanup, so isFinished() alone cannot release ownership.
    if not _is_finished(thread):
        return False
    try:
        from PyQt6.QtCore import QDeadlineTimer, Qt

        # Qt 6.6.1 maps wait(0) to a sentinel deadline with a negative POSIX tv_nsec.
        # A real, already-expired instant polls native completion without that invalid timeout.
        return bool(thread.wait(QDeadlineTimer.current(Qt.TimerType.PreciseTimer)))
    except RuntimeError:
        return True


def _settled(thread) -> bool:
    """Return True once ``thread`` has completely finished, waiting briefly for its last step."""

    if id(thread) in _QUIT_BLOCKERS:
        return _completion_ready(thread)
    if _is_finished(thread):
        return True
    try:
        return bool(thread.wait(FINISH_SETTLE_MS))
    except RuntimeError:  # the native object is already gone
        return True


def discard(thread) -> None:
    """Drop ``thread`` from the registry once it has finished (GUI thread).

    A thread that is still running stays registered, so a ``QThread`` is never released while running.
    """

    opted_in = id(thread) in _QUIT_BLOCKERS
    unstarted = opted_in and _unstarted(thread)
    if unstarted:
        thread._metroliza_delivery_pending = False
    if thread in _REGISTERED and (_settled(thread) or unstarted):
        _REGISTERED.discard(thread)
        _QUIT_BLOCKERS.pop(id(thread), None)
    _run_ready_deferred(unstarted=thread if unstarted else None)
    if opted_in:
        _quit_deferral().timer.start()


def _unstarted(thread) -> bool:
    try:
        return not thread.isRunning() and not thread.isFinished()
    except RuntimeError:
        return True


def is_registered(thread) -> bool:
    return thread in _REGISTERED


def running_threads() -> tuple:
    """Return the registered threads that have not finished, dropping finished ones."""

    for thread in tuple(_REGISTERED):
        if _completion_ready(thread):
            _REGISTERED.discard(thread)
            _QUIT_BLOCKERS.pop(id(thread), None)
    return tuple(_REGISTERED)


def _on_thread_finished(thread_ref) -> None:
    thread = thread_ref()
    if thread is not None:
        discard(thread)
    else:
        _run_ready_deferred()


def run_when_finished(threads: Iterable, callback: Callable[[], None]) -> None:
    """Call ``callback`` once every thread in ``threads`` has finished (now, if none is running).

    Ordinary pending callbacks also run after the bounded exit wait. Callbacks holding opted-in
    workers remain deferred until native completion, including on an explicit shutdown() call.
    """

    pending = tuple(thread for thread in threads if not _completion_ready(thread))
    if not pending:
        callback()
        return
    _DEFERRED.append((pending, callback))
    _install_quit_hook()


def _run_ready_deferred(*, force: bool = False, unstarted=None) -> None:
    ready = [entry for entry in _DEFERRED
             if (force and not any(id(thread) in _QUIT_BLOCKERS for thread in entry[0]))
             or all(thread is unstarted or _completion_ready(thread) for thread in entry[0])]
    for entry in ready:
        try:
            _DEFERRED.remove(entry)
        except ValueError:
            continue
        try:
            entry[1]()
        except Exception as exc:  # a failing cleanup must not break the signal or exit
            logger.warning("Deferred thread cleanup failed: %s: %s", type(exc).__name__, exc)


def wait_for_all(total_timeout_ms: int = QUIT_WAIT_TOTAL_MS) -> bool:
    """Ask every registered thread to stop and wait for them for at most ``total_timeout_ms`` in total.

    Return True when no registered thread is left running.
    """

    threads = running_threads()
    for thread in threads:
        if id(thread) in _QUIT_BLOCKERS:
            continue
        interrupt = getattr(thread, "interrupt_query", None) or thread.requestInterruption
        try:
            interrupt()
        except RuntimeError:
            pass
    deadline = time.monotonic() + max(0, total_timeout_ms) / 1000.0
    for thread in threads:
        if id(thread) in _QUIT_BLOCKERS:
            continue
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        try:
            finished = thread.wait(remaining_ms)
        except RuntimeError:
            finished = True
        if finished:
            _REGISTERED.discard(thread)
    return not running_threads()


def shutdown(total_timeout_ms: int = QUIT_WAIT_TOTAL_MS) -> bool:
    """Application-exit hook: bounded wait for detached threads, then the deferred cleanups."""

    stopped = wait_for_all(total_timeout_ms)
    _run_ready_deferred(force=True)
    return stopped


def _quit_deferral():
    """Lazily install the opt-in application's normal-Quit admission filter."""
    from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QTimer

    app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError("Quit deferral requires a live application on the GUI thread")
    controller = getattr(app, "_metroliza_detached_quit", None)
    if controller is not None:
        return controller

    controller = _create_quit_deferral(app, QEvent, QObject, QTimer)
    app._metroliza_detached_quit = controller
    return controller


def _create_quit_deferral(app, QEvent, QObject, QTimer):
    class QuitDeferral(QObject):
        def __init__(self):
            super().__init__(app)
            self.pending = False
            self.replay_queued = False
            self.timer = QTimer(self)
            self.timer.setInterval(10)  # polling cadence, never a completion deadline
            self.timer.timeout.connect(self.check)
            app.installEventFilter(self)

        def eventFilter(self, receiver, event):
            if receiver is app and event.type() == QEvent.Type.Quit:
                if _QUIT_BLOCKERS:
                    event.ignore()
                    self.pending = True
                    self.timer.start()
                    return True
                self.pending = False
            return False

        def check(self):
            running_threads()
            _run_ready_deferred()
            if _QUIT_BLOCKERS:
                return
            self.timer.stop()
            if self.pending and not self.replay_queued:
                self.pending = False
                self.replay_queued = True
                QTimer.singleShot(0, self.replay)

        def replay(self):
            self.replay_queued = False
            app.quit()  # the filter rechecks jobs admitted since the replay was queued

    return QuitDeferral()


def _install_quit_hook() -> None:
    try:
        from PyQt6.QtCore import QCoreApplication
    except ImportError:  # pragma: no cover - Qt unavailable
        return
    app = QCoreApplication.instance()
    if app is None or any(app is hooked for hooked in _HOOKED_APPS):
        return
    _HOOKED_APPS.append(app)
    app.aboutToQuit.connect(shutdown)
