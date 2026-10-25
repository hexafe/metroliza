"""Registry of detached background threads: bounded wait at exit, dropped when finished, deferred cleanup."""

from __future__ import annotations

import gc
import subprocess
import sys
import threading
import time
import weakref

import pytest

try:
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

from metroliza.ui import detached_threads

pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 is not available: {PYQT_IMPORT_ERROR}",
)

_TIMEOUT_S = 20


@pytest.fixture(scope="module", autouse=True)
def _qt_app():
    yield QApplication.instance() or QApplication([])


class _GatedThread(QThread):
    """Runs until ``release`` is set, or until interruption is requested when ``stop_on_interrupt``."""

    def __init__(self, release: threading.Event, *, stop_on_interrupt: bool = False):
        super().__init__()
        self.release = release
        self.stop_on_interrupt = stop_on_interrupt

    def run(self):
        deadline = time.monotonic() + _TIMEOUT_S
        while time.monotonic() < deadline and not self.release.is_set():
            if self.stop_on_interrupt and self.isInterruptionRequested():
                return
            time.sleep(0.005)


@pytest.fixture()
def gate():
    release = threading.Event()
    threads: list[_GatedThread] = []

    def make(**kwargs):
        thread = _GatedThread(release, **kwargs)
        threads.append(thread)
        detached_threads.register(thread)
        return thread

    make.release = release
    yield make
    release.set()
    for thread in threads:
        assert thread.wait(_TIMEOUT_S * 1000)
        detached_threads.discard(thread)
    QApplication.processEvents()
    assert not detached_threads.running_threads()
    detached_threads._DEFERRED.clear()


def _wait_until(predicate, timeout=_TIMEOUT_S):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_finished_threads_are_dropped_from_the_registry(gate):
    thread = gate()
    thread.start()
    assert detached_threads.is_registered(thread)
    assert detached_threads.running_threads() == (thread,)

    gate.release.set()
    assert thread.wait(_TIMEOUT_S * 1000)

    # Dropped by the finished signal and, independent of event processing, by the running_threads() scan.
    assert detached_threads.running_threads() == ()
    assert _wait_until(lambda: not detached_threads.is_registered(thread))


def test_wait_for_all_is_bounded_by_one_total_timeout_not_per_thread(gate):
    threads = [gate() for _ in range(3)]
    for thread in threads:
        thread.start()

    started = time.monotonic()
    assert detached_threads.wait_for_all(300) is False
    elapsed = time.monotonic() - started

    assert elapsed < 1.5  # three threads at 300 ms each would be 0.9 s plus overhead; the total is 0.3 s
    assert set(detached_threads.running_threads()) == set(threads)


def test_wait_for_all_interrupts_threads_and_returns_once_they_stopped(gate):
    cooperative = [gate(stop_on_interrupt=True) for _ in range(2)]
    for thread in cooperative:
        thread.start()

    assert detached_threads.wait_for_all(5000) is True

    assert not detached_threads.running_threads()
    assert all(not detached_threads.is_registered(thread) for thread in cooperative)


def test_wait_for_all_without_threads_returns_immediately():
    started = time.monotonic()
    assert detached_threads.wait_for_all(5000) is True
    assert time.monotonic() - started < 0.5


def test_application_exit_hook_waits_for_the_detached_threads(gate):
    thread = gate(stop_on_interrupt=True)
    thread.start()

    QApplication.instance().aboutToQuit.emit()

    assert thread.isFinished()
    assert not detached_threads.is_registered(thread)


def test_run_when_finished_runs_at_once_when_nothing_is_running(gate):
    calls = []
    thread = gate()
    thread.start()
    gate.release.set()
    assert thread.wait(_TIMEOUT_S * 1000)

    detached_threads.run_when_finished([thread], lambda: calls.append("now"))
    detached_threads.run_when_finished([], lambda: calls.append("empty"))

    assert calls == ["now", "empty"]


def test_run_when_finished_defers_until_every_listed_thread_finished(gate):
    other_release = threading.Event()
    first = gate()
    second = _GatedThread(other_release)
    detached_threads.register(second)
    first.start()
    second.start()
    calls = []
    try:
        detached_threads.run_when_finished([first, second], lambda: calls.append("done"))
        assert calls == []

        gate.release.set()
        assert first.wait(_TIMEOUT_S * 1000)
        QApplication.processEvents()
        assert calls == []  # the second thread still runs

        other_release.set()
        assert _wait_until(lambda: calls == ["done"])
    finally:
        other_release.set()
        assert second.wait(_TIMEOUT_S * 1000)
        detached_threads.discard(second)
    assert calls == ["done"]


def test_exit_runs_deferred_callbacks_once_even_when_a_thread_is_stuck(gate):
    thread = gate()
    thread.start()
    calls = []
    detached_threads.run_when_finished([thread], lambda: calls.append("cleanup"))

    started = time.monotonic()
    assert detached_threads.shutdown(200) is False
    assert time.monotonic() - started < 1.5

    assert calls == ["cleanup"]
    gate.release.set()
    assert thread.wait(_TIMEOUT_S * 1000)
    QApplication.processEvents()
    assert calls == ["cleanup"]  # never run a second time


def test_a_failing_deferred_callback_does_not_break_the_registry(gate, caplog):
    thread = gate()
    thread.start()
    calls = []

    def failing():
        raise OSError("synthetic")

    detached_threads.run_when_finished([thread], failing)
    detached_threads.run_when_finished([thread], lambda: calls.append("second"))
    gate.release.set()
    assert thread.wait(_TIMEOUT_S * 1000)

    assert _wait_until(lambda: calls == ["second"])
    assert any(record.name == "metroliza.ui.detached_threads"
               and record.levelname == "WARNING"
               and "OSError: synthetic" in record.getMessage() for record in caplog.records)


class _TrackedThread(QThread):
    """Records the Python thread that finalizes the wrapper, i.e. where the native QThread is destroyed."""

    finalized_in: list = []

    def run(self):
        time.sleep(0.01)

    def __del__(self):
        type(self).finalized_in.append(threading.current_thread())


def _collect_in_another_thread():
    collector = threading.Thread(target=gc.collect, name="collector")
    collector.start()
    collector.join()


def test_finished_thread_is_released_on_the_gui_thread_not_by_a_foreign_garbage_collection():
    """The registry hook must not make the QThread part of a reference cycle.

    A connected closure that captures the thread is reachable from the native slot proxy, so only the
    cyclic collector could free the thread, and it then destroys the QThread in whichever thread runs the
    collection (for example a worker). With the cycle gone, dropping the last reference frees it at once,
    in the thread that dropped it.
    """

    _TrackedThread.finalized_in = []
    gc.collect()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        thread = _TrackedThread()
        detached_threads.register(thread)
        reference = weakref.ref(thread)
        thread.start()
        assert thread.wait(_TIMEOUT_S * 1000)
        assert _wait_until(lambda: not detached_threads.is_registered(reference()))
        del thread

        assert reference() is None, "the thread is kept alive by a reference cycle"
        _collect_in_another_thread()
    finally:
        if was_enabled:
            gc.enable()

    assert [item.name for item in _TrackedThread.finalized_in] == [threading.current_thread().name]


def test_registry_drops_a_thread_only_after_it_finished():
    release = threading.Event()
    thread = _GatedThread(release)
    detached_threads.register(thread)
    thread.start()
    try:
        detached_threads.discard(thread)
        assert detached_threads.is_registered(thread)
    finally:
        release.set()
        assert thread.wait(_TIMEOUT_S * 1000)
    detached_threads.discard(thread)
    assert not detached_threads.is_registered(thread)


def test_opt_in_native_settling_is_warning_free():
    script = '''
import functools
from PyQt6.QtCore import QThread, QTimer, qInstallMessageHandler, qVersion, PYQT_VERSION_STR
from PyQt6.QtWidgets import QApplication
from metroliza.ui import detached_threads
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
messages, waits, cleanup, beats = [], [], [], []
qInstallMessageHandler(lambda kind, context, message: messages.append(message))
class Worker(QThread):
    def run(self):
        self.msleep(100)
    def wait(self, timeout):
        assert timeout == 0 and self.isFinished(), 'GUI wait before finished'
        waits.append(timeout)
        return super().wait(timeout)
thread = Worker()
detached_threads.register(thread, defer_quit=True)
detached_threads.run_when_finished([thread], functools.partial(cleanup.append, 'settled'))
heartbeat = QTimer()
heartbeat.timeout.connect(functools.partial(beats.append, 1))
heartbeat.start(5)
thread.start()
QTimer.singleShot(10, app.quit)
QTimer.singleShot(3000, functools.partial(app.exit, 99))
code = app.exec()
assert code == 0 and cleanup == ['settled'] and len(beats) >= 5
assert waits and not messages, messages
assert not detached_threads.running_threads()
print('warning-free native settle', PYQT_VERSION_STR, qVersion(), len(beats), waits)
'''
    child = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
    assert child.returncode == 0, child.stdout + child.stderr
    assert "warning-free native settle 6." in child.stdout
    assert child.stderr == ""


@pytest.mark.parametrize("mode", ["quit", "lastwindow", "directexit", "rejected"])
def test_opt_in_native_quit_routes_and_replay_race(mode):
    script = '''
import functools, sys, threading
from PyQt6.QtCore import QEvent, QThread, QTimer, Qt, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication, QWidget
from metroliza.ui import detached_threads as registry
app = QApplication([])
mode = sys.argv[1]
class Owner(QWidget):
    allow_close = False
    rejections = 0
    def closeEvent(self, event):
        if mode == 'rejected' and not self.allow_close:
            self.rejections += 1; event.ignore(); return
        super().closeEvent(event)
owner = Owner(); owner.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose); owner.show()
jobs, cleanups, beats, messages, exits = [], [], [], [], []
qInstallMessageHandler(lambda kind, context, message: messages.append(message))
class Worker(QThread):
    def __init__(self, name):
        super().__init__(); self.name = name; self.release = threading.Event(); self.error = None
    def run(self):
        try:
            assert self.release.wait(3), 'control expired'
            if self.name == 'second':
                raise OSError('literal worker error')
        except Exception as error:
            self.error = str(error)
    def wait(self, timeout):
        assert timeout == 0 and self.isFinished(), 'blocking or premature GUI wait'
        return super().wait(timeout)
    def requestInterruption(self):
        raise AssertionError('noncancellable work interrupted')
def add(name, delay):
    job = Worker(name); jobs.append(job)
    registry.register(job, defer_quit=True); job.start()
    registry.run_when_finished([job], functools.partial(cleanups.append, name))
    QTimer.singleShot(delay, job.release.set)
add('first', 150); add('second', 250)
controller = app._metroliza_detached_quit
def admit_late():
    if controller.replay_queued and len(jobs) == 2:
        add('late', 120)
controller.timer.timeout.connect(admit_late)
heartbeat = QTimer(); heartbeat.timeout.connect(functools.partial(beats.append, 1)); heartbeat.start(5)
def at_exit():
    exits.append([job.name for job in jobs if not job.isFinished()])
app.aboutToQuit.connect(at_exit)
assert registry.shutdown(0) is False and cleanups == []
if mode == 'lastwindow':
    QTimer.singleShot(30, owner.close)
elif mode in ('quit', 'rejected'):
    QTimer.singleShot(30, app.quit); QTimer.singleShot(60, app.quit)
else:
    QTimer.singleShot(30, functools.partial(app.exit, 23))
if mode == 'rejected':
    def resolve_close_guard():
        assert owner.rejections == 1 and not controller.pending and not controller.timer.isActive()
        owner.allow_close = True; app.quit()
    QTimer.singleShot(600, resolve_close_guard)
QTimer.singleShot(3000, functools.partial(app.exit, 99))
code = app.exec()
if mode == 'directexit':
    assert code == 23 and exits == [['first', 'second']]
    for job in jobs:
        job.release.set()
        assert QThread.wait(job, 1000)  # test rescue after the intentionally unprotected exit
    registry.running_threads(); registry._run_ready_deferred()
else:
    assert code == 0 and exits == [[]] and len(jobs) == 3
    assert cleanups == ['first', 'second', 'late'] and len(beats) > 30
    assert jobs[1].error == 'literal worker error'
assert not registry.running_threads() and not registry._QUIT_BLOCKERS
assert not messages, messages
app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
print(mode, code, 'native routes settled', len(beats), cleanups)
sys.exit(code)
'''
    child = subprocess.run([sys.executable, "-c", script, mode], capture_output=True, text=True, timeout=10)
    assert child.returncode == (23 if mode == "directexit" else 0), child.stdout + child.stderr
    assert "native routes settled" in child.stdout
    assert child.stderr == ""


def test_opt_in_defers_cleanup_past_finished_until_native_settle(qapplication_session):
    class Signal:
        def connect(self, slot):
            pass

    class Thread:
        finished = Signal()
        settled = False

        def isFinished(self):
            return True

        def isRunning(self):
            return False

        def wait(self, timeout):
            assert timeout == 0
            return self.settled

    thread, calls = Thread(), []
    detached_threads.register(thread, defer_quit=True)
    detached_threads.run_when_finished([thread], lambda: calls.append("cleanup"))
    detached_threads.discard(thread)
    assert detached_threads.shutdown(0) is False and calls == []
    assert detached_threads.is_registered(thread)
    thread.settled = True
    detached_threads.discard(thread)
    detached_threads.discard(thread)
    assert calls == ["cleanup"] and not detached_threads.is_registered(thread)


def test_opt_in_unstarted_and_deleted_wrappers_release(qapplication_session):
    from PyQt6.QtCore import QEvent

    thread = QThread()
    detached_threads.register(thread, defer_quit=True)
    calls = []
    detached_threads.run_when_finished([thread], lambda: calls.append("aborted"))
    detached_threads.discard(thread)  # start failure, without a native wait
    detached_threads.discard(thread)
    assert calls == ["aborted"] and not detached_threads.is_registered(thread)
    detached_threads.register(thread, defer_quit=True)
    thread.deleteLater()
    qapplication_session.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert thread not in detached_threads.running_threads()
    assert not detached_threads._QUIT_BLOCKERS


def test_registry_import_remains_qt_lazy():
    child = subprocess.run([sys.executable, "-c", '''
import sys
from metroliza.ui import detached_threads
assert not any(name.startswith('PyQt6') for name in sys.modules)
assert detached_threads.QUIT_WAIT_TOTAL_MS == 5000
'''], capture_output=True, text=True, timeout=10)
    assert child.returncode == 0, child.stdout + child.stderr


@pytest.mark.parametrize("mode", ["consume", "destroy", "startfailure"])
def test_opt_in_gui_acknowledgement_native_process(mode):
    script = r"""
import functools
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QEventLoop, QThread, QTimer
from PyQt6.QtWidgets import QApplication, QWidget
from metroliza.ui import detached_threads
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
owner = QWidget()
consumed, cleaned, observed = [], [], []
class Worker(QThread):
    def run(self): self.msleep(40)
    def wait(self, timeout):
        assert timeout == 0 and self.isFinished()
        return super().wait(timeout)
thread = Worker()
def consume(current_owner, current_thread):
    assert current_owner is owner and current_thread is thread
    consumed.append(1)
    loop = QEventLoop()
    def during():
        detached_threads._quit_deferral().check()
        observed.append((thread.isFinished(), detached_threads.is_registered(thread), bool(cleaned)))
        app.quit()
        # Even destruction inside a reentrant handler must not release its worker.
        current_owner.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        observed.append((detached_threads.is_registered(thread), bool(cleaned)))
        loop.quit()
    QTimer.singleShot(30, during)
    loop.exec()
detached_threads.register(thread, defer_quit=True, owner=owner, on_finished=consume)
detached_threads.run_when_finished([thread], functools.partial(cleaned.append, 1))
detached_threads.run_when_finished([thread], thread.deleteLater)
mode = __import__('sys').argv[1]
if mode == 'startfailure':
    detached_threads.discard(thread)
    detached_threads.discard(thread)
    QTimer.singleShot(0, app.quit)
else:
    thread.start()
    if mode == 'destroy':
        owner.deleteLater()
        QTimer.singleShot(1, app.quit)
QTimer.singleShot(3000, functools.partial(app.exit, 99))
assert app.exec() == 0
assert cleaned == [1] and not detached_threads.running_threads()
assert consumed == ([1] if mode == 'consume' else [])
assert observed == ([(True, True, False), (True, False)] if mode == 'consume' else [])
assert sip.isdeleted(thread)
print('native GUI acknowledgement complete', mode, observed)
"""
    child = subprocess.run([sys.executable, "-c", script, mode], capture_output=True, text=True, timeout=8)
    assert child.returncode == 0, child.stdout + child.stderr
    assert "native GUI acknowledgement complete" in child.stdout
    assert child.stderr == ""
