"""Registry of detached background threads: bounded wait at exit, dropped when finished, deferred cleanup."""

from __future__ import annotations

import threading
import time

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


def test_a_failing_deferred_callback_does_not_break_the_registry(gate):
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
