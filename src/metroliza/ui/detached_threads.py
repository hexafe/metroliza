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


def _is_finished(thread) -> bool:
    try:
        return bool(thread.isFinished())
    except RuntimeError:  # the native object is already gone
        return True


def register(thread) -> None:
    """Keep ``thread`` referenced until it has finished; call before ``thread.start()``.

    Call it on the GUI thread (the thread that owns ``thread``). The ``finished`` hook must not hold a
    strong reference to ``thread``: a connected closure that captures it forms a reference cycle through
    the native slot proxy, and the cyclic garbage collector then destroys the ``QThread`` in whichever
    thread happens to run a collection, for example another worker, instead of on the GUI thread.
    """

    _REGISTERED.add(thread)
    _install_quit_hook()
    thread.finished.connect(functools.partial(_on_thread_finished, weakref.ref(thread)))


def _settled(thread) -> bool:
    """Return True once ``thread`` has completely finished, waiting briefly for its last step."""

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

    if thread in _REGISTERED and _settled(thread):
        _REGISTERED.discard(thread)
    _run_ready_deferred()


def is_registered(thread) -> bool:
    return thread in _REGISTERED


def running_threads() -> tuple:
    """Return the registered threads that have not finished, dropping finished ones."""

    for thread in tuple(_REGISTERED):
        if _is_finished(thread):
            _REGISTERED.discard(thread)
    return tuple(_REGISTERED)


def _on_thread_finished(thread_ref) -> None:
    thread = thread_ref()
    if thread is not None:
        discard(thread)
    else:
        _run_ready_deferred()


def run_when_finished(threads: Iterable, callback: Callable[[], None]) -> None:
    """Call ``callback`` once every thread in ``threads`` has finished (now, if none is running).

    Pending callbacks are also run at application exit, after the bounded wait, so a deferred cleanup is
    attempted exactly once and never blocks exit.
    """

    pending = tuple(thread for thread in threads if not _is_finished(thread))
    if not pending:
        callback()
        return
    _DEFERRED.append((pending, callback))
    _install_quit_hook()


def _run_ready_deferred(*, force: bool = False) -> None:
    ready = [entry for entry in _DEFERRED if force or all(_is_finished(thread) for thread in entry[0])]
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
        interrupt = getattr(thread, "interrupt_query", None) or thread.requestInterruption
        try:
            interrupt()
        except RuntimeError:
            pass
    deadline = time.monotonic() + max(0, total_timeout_ms) / 1000.0
    for thread in threads:
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
