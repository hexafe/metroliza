"""Normal-exit child census and bounded, callback-free teardown controls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from metroliza.app import qt_teardown as teardown

ROOT = Path(__file__).resolve().parents[1]
CHILD = '''
import gc, json, os, threading
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton, QDialog, QListWidget
from metroliza.app import bootstrap
from metroliza.charts import chart_render_service
from metroliza.charts.chart_render_service import BoundedWorkerPool
from metroliza.ui import detached_threads
from metroliza.shared.diagnostic_fatal_probe import _wrapper_inventory, _live_application_wrapper
print(bootstrap.__file__, flush=True)
print(chart_render_service.__file__, flush=True)
previous, thresholds = gc.isenabled(), gc.get_threshold()
app = bootstrap.get_or_create_qapplication()
if os.environ.get('METROLIZA_TEST_QUIT_WAIT_SPENT') == '1':
    app._metroliza_detached_exit_wait_spent = True
pool = BoundedWorkerPool(max_workers=2, max_queue_size=1)
assert pool.submit(lambda: 7).result(timeout=2) == 7
assert all(worker.is_alive() for worker in pool._threads)
class FinishedThread(QThread):
    def run(self):
        pass
detached = FinishedThread()
detached_threads.register(detached)
detached.start()
assert detached.wait(2000)
window = QMainWindow()
central = QWidget(window)
window.setCentralWidget(central)
layout = QVBoxLayout(central)
for i in range(12):
    layout.addWidget(QLabel('synthetic', central))
    layout.addWidget(QPushButton('synthetic', central))
menu = window.menuBar().addMenu('synthetic')
menu.addAction('synthetic')
dialog = QDialog()
listing = QListWidget(dialog)
listing.addItems(['one', 'two', 'three'])
timers = [QTimer() for _ in range(3)]
actions = [QAction('synthetic') for _ in range(3)]
for timer in timers:
    timer.start(1000)
try:
    from metroliza.app.qt_teardown import shutdown_qt
except ModuleNotFoundError:
    shutdown_qt = None  # Base discriminator: observe, then clean up normally below.
try:
    if shutdown_qt is not None:
        results = []
        worker = threading.Thread(target=lambda: results.append(shutdown_qt(app)))
        worker.start()
        worker.join()
        assert results == [False] and not sip.isdeleted(app) and not gc.isenabled()
        released = shutdown_qt(app)
        if released:
            assert shutdown_qt(app)
    else:
        released = False
    objects = gc.get_objects()
    observed = _wrapper_inventory(objects, sip)
    observed.update(qapp_alive=_live_application_wrapper(objects, sip, QApplication),
                    live_widgets=sum(isinstance(o, QWidget) and not sip.isdeleted(o) for o in objects),
                    shutdown_result=released,
                    chart_workers=sum(t.name.startswith('chart-worker-') for t in threading.enumerate()),
                    gc_restored=gc.isenabled() == previous and gc.get_threshold() == thresholds)
    del objects
    print(json.dumps(observed, sort_keys=True), flush=True)
finally:
    # The RED control also exits normally, with explicit cleanup after its census.
    # No deliberate native failure, exit bypass, or worker-thread collection.
    pool.shutdown(wait=True)
    if not sip.isdeleted(detached):
        assert detached.wait(2000)
        sip.delete(detached)
    if not sip.isdeleted(app):
        detached_threads.shutdown()
        for widget in app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        policy = getattr(app, '_metroliza_gc_policy', None)
        if policy is not None:
            policy.uninstall()
        gc.collect()
        sip.delete(app)
'''


@pytest.mark.parametrize("quit_wait_spent", [False, True])
def test_shutdown_child_releases_application_widgets_and_gc(quit_wait_spent):
    source = os.environ.get("METROLIZA_QT_TEARDOWN_SOURCE", str(ROOT / "src"))
    result = subprocess.run(
        [sys.executable, "-u", "-c", CHILD], cwd=Path(source).parent,
        env=dict(os.environ, PYTHONPATH=source, QT_QPA_PLATFORM="offscreen",
                 METROLIZA_TEST_QUIT_WAIT_SPENT=str(int(quit_wait_spent))),
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
    assert Path(result.stdout.splitlines()[0]) == Path(source) / "metroliza/app/bootstrap.py"
    assert Path(result.stdout.splitlines()[1]) == Path(source) / "metroliza/charts/chart_render_service.py"
    observed = json.loads(result.stdout.splitlines()[-1])
    assert observed["shutdown_result"] is True, observed
    assert observed["qapp_alive"] is False, observed
    assert observed["live_widgets"] == 0, observed
    assert observed["gc_restored"] is True, observed
    assert observed["chart_workers"] == 0, observed


def test_shutdown_child_busy_pool_retains_qt_and_exits_normally():
    child = '''
import gc, json, threading
from PyQt6 import sip
from metroliza.app import bootstrap
from metroliza.app.qt_teardown import shutdown_qt
from metroliza.charts.chart_render_service import BoundedWorkerPool
previous, thresholds = gc.isenabled(), gc.get_threshold()
app = bootstrap.get_or_create_qapplication()
entered, release = threading.Event(), threading.Event()
pool = BoundedWorkerPool(max_workers=1, max_queue_size=1)
def blocked():
    entered.set()
    release.wait(5)
pool.submit(blocked)
try:
    assert entered.wait(2)
    result = shutdown_qt(app, deadline_s=0.02)
    observed = dict(shutdown_result=result, qapp_alive=not sip.isdeleted(app),
                    worker_alive=pool._threads[0].is_alive(), gc_retained=not gc.isenabled())
finally:
    release.set()
    pool.shutdown(wait=True)
    cleanup_released = shutdown_qt(app)
    if not cleanup_released:
        policy = vars(app).get('_metroliza_gc_policy')
        if policy is not None:
            policy.uninstall()
        sip.delete(app)
assert gc.isenabled() == previous and gc.get_threshold() == thresholds
print(json.dumps(observed), flush=True)
'''
    result = subprocess.run(
        [sys.executable, "-u", "-c", child], cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=str(ROOT / "src"), QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "shutdown_result": False, "qapp_alive": True, "worker_alive": True, "gc_retained": True,
    }


@pytest.fixture
def fake_qt(monkeypatch):
    class Object:
        deleted = False
        def thread(self):
            return "gui"

    class Widget(Object):
        pass

    class Thread(Object):
        currentThread = staticmethod(lambda: "gui")
        def isRunning(self):
            return False

    class App:
        deleted = False
        def thread(self):
            return "gui"

        def topLevelWidgets(self):
            return []

        def processEvents(self):
            calls.append("events")

    app, calls = App(), []
    sip = SimpleNamespace(isdeleted=lambda obj: obj.deleted,
                          delete=lambda obj: (calls.append("delete_app"), setattr(obj, "deleted", True)))
    core = SimpleNamespace(
        QCoreApplication=SimpleNamespace(sendPostedEvents=lambda *_: calls.append("deferred")),
        QEvent=SimpleNamespace(Type=SimpleNamespace(DeferredDelete=1)),
        QThread=Thread, QObject=Object,
    )
    widgets = SimpleNamespace(QApplication=SimpleNamespace(instance=lambda: app), QWidget=Widget)
    monkeypatch.setitem(sys.modules, "PyQt6", SimpleNamespace(sip=sip))
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", core)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", widgets)
    monkeypatch.setattr(teardown, "_stop_workers", lambda deadline, **kwargs: calls.append("workers") or True)
    objects, gc_state = [], {"enabled": False}
    monkeypatch.setattr(teardown, "APPLICATION_RELEASED", False, raising=False)
    monkeypatch.setattr(teardown.gc, "get_objects", lambda: objects)
    monkeypatch.setattr(teardown.gc, "isenabled", lambda: gc_state["enabled"])
    monkeypatch.setattr(teardown.gc, "disable", lambda: gc_state.update(enabled=False))
    monkeypatch.setattr(teardown.gc, "enable", lambda: gc_state.update(enabled=True))
    monkeypatch.setattr(teardown.gc, "collect", lambda: calls.append("gc") or 0)
    monkeypatch.setattr(teardown, "record_event", lambda name, **counts: calls.append((name, counts)))
    return SimpleNamespace(app=app, calls=calls, core=core, sip=sip, objects=objects,
                           gc_state=gc_state, widget_type=Widget)


def test_idempotent_order_and_closed_events(fake_qt):
    fake_qt.app._metroliza_gc_policy = SimpleNamespace(
        stop=lambda: fake_qt.calls.append("stop"),
        uninstall=lambda **kwargs: fake_qt.calls.append("uninstall"))
    assert teardown.shutdown_qt(fake_qt.app)
    count = len(fake_qt.calls)
    assert teardown.shutdown_qt(fake_qt.app)
    assert len(fake_qt.calls) == count
    actions = [call for call in fake_qt.calls if isinstance(call, str)]
    assert actions == ["stop", "workers", "deferred", "events", "gc", "deferred", "events", "delete_app", "uninstall"]
    assert all(type(value) is int for call in fake_qt.calls if isinstance(call, tuple) for value in call[1].values())


@pytest.mark.parametrize("failure", [RuntimeError, SystemExit, KeyboardInterrupt])
def test_exception_containment_retains_application(fake_qt, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure("PRIVATE_TEXT")
    monkeypatch.setattr(teardown, "_stop_workers", fail)
    assert teardown.shutdown_qt(fake_qt.app) is False
    assert not fake_qt.app.deleted
    assert "PRIVATE_TEXT" not in repr(fake_qt.calls)


def test_visible_window_is_untouched_and_retains_application(fake_qt):
    window = SimpleNamespace(deleted=False, isVisible=lambda: True,
                             close=lambda: pytest.fail("close event delivered"),
                             deleteLater=lambda: pytest.fail("visible window deleted"))
    fake_qt.app.topLevelWidgets = lambda: [window]
    assert teardown.shutdown_qt(fake_qt.app, deadline_s=5) is False
    assert fake_qt.calls.count("events") == 0
    assert "gc" not in fake_qt.calls and not fake_qt.app.deleted
    assert ("qt_teardown_retained", {"widgets": 1}) in fake_qt.calls


def test_hidden_widget_delete_loop_is_bounded_without_close(fake_qt):
    deletes = []
    window = SimpleNamespace(deleted=False, isVisible=lambda: False,
                             close=lambda: pytest.fail("close event delivered"),
                             deleteLater=lambda: deletes.append(1))
    fake_qt.app.topLevelWidgets = lambda: [window]
    assert teardown.shutdown_qt(fake_qt.app) is False
    assert deletes == [1]
    assert fake_qt.calls.count("events") == teardown.MAX_DELETE_PASSES


def test_expired_deadline_makes_only_one_delete_pass(fake_qt):
    window = SimpleNamespace(deleted=False, isVisible=lambda: False, deleteLater=lambda: None)
    fake_qt.app.topLevelWidgets = lambda: [window]
    assert teardown.shutdown_qt(fake_qt.app, deadline_s=0) is False
    assert fake_qt.calls.count("events") == 1


def test_off_gui_thread_does_not_mutate_or_collect(fake_qt):
    fake_qt.core.QThread.currentThread = lambda: "worker"
    assert teardown.shutdown_qt(fake_qt.app) is False
    assert not fake_qt.app.deleted
    assert fake_qt.calls == [("qt_teardown_off_thread", {})]


def test_incomplete_workers_prevent_widget_or_gc_cleanup(fake_qt, monkeypatch):
    monkeypatch.setattr(teardown, "_stop_workers", lambda deadline, **kwargs: False)
    assert teardown.shutdown_qt(fake_qt.app) is False
    assert fake_qt.calls == [("qt_teardown_workers", {"stopped": 0})]


def test_widget_created_during_gc_prevents_application_release(fake_qt, monkeypatch):
    fake_qt.objects.append(fake_qt.widget_type())
    assert teardown.shutdown_qt(fake_qt.app) is False
    assert not fake_qt.app.deleted


def test_profile_failure_and_reentrancy_do_not_change_shutdown(fake_qt, monkeypatch):
    def collect():
        assert teardown.shutdown_qt(fake_qt.app) is False
        return 0
    def fail(*args, **kwargs):
        raise RuntimeError("private")
    monkeypatch.setattr(teardown.gc, "collect", collect)
    monkeypatch.setattr(teardown, "record_event", fail)
    assert teardown.shutdown_qt(fake_qt.app)


def test_worker_shutdown_uses_only_existing_wait_budget(monkeypatch):
    calls = []
    charts = SimpleNamespace(shutdown=lambda **kwargs: calls.append(kwargs) or True)
    detached = SimpleNamespace(QUIT_WAIT_TOTAL_MS=5000,
                               shutdown=lambda **kwargs: calls.append(kwargs) or True)
    monkeypatch.setitem(sys.modules, "metroliza.charts.chart_render_service", charts)
    monkeypatch.setitem(sys.modules, "metroliza.ui.detached_threads", detached)
    monkeypatch.setattr(teardown.time, "monotonic", lambda: 10.0)
    assert teardown._stop_workers(11.25)
    assert calls == [{"deadline": 11.25}, {"total_timeout_ms": 1250}]


def test_absent_optional_services_are_not_imported(monkeypatch):
    monkeypatch.delitem(sys.modules, "metroliza.charts.chart_render_service", raising=False)
    monkeypatch.delitem(sys.modules, "metroliza.ui.detached_threads", raising=False)
    assert teardown._stop_workers(0)


@pytest.mark.parametrize("join_finished_at,expected", [(10.5, 750), (11.25, None)])
def test_chart_joins_spend_the_same_detached_wait_budget(monkeypatch, join_finished_at, expected):
    calls = []
    charts = SimpleNamespace(shutdown=lambda **kwargs: calls.append(kwargs) or True)
    detached = SimpleNamespace(QUIT_WAIT_TOTAL_MS=5000, running_threads=lambda: (object(),),
                               shutdown=lambda **kwargs: calls.append(kwargs) or True)
    monkeypatch.setitem(sys.modules, "metroliza.charts.chart_render_service", charts)
    monkeypatch.setitem(sys.modules, "metroliza.ui.detached_threads", detached)
    monkeypatch.setattr(teardown.time, "monotonic", lambda: join_finished_at)
    assert teardown._stop_workers(11.25) is (expected is not None)
    assert calls == [{"deadline": 11.25}] + ([] if expected is None else [{"total_timeout_ms": expected}])


def test_expired_worker_budget_never_calls_qthread_wait_zero(monkeypatch):
    detached = SimpleNamespace(QUIT_WAIT_TOTAL_MS=5000, running_threads=lambda: (object(),),
                               shutdown=lambda **kwargs: pytest.fail("wait after expired budget"))
    monkeypatch.delitem(sys.modules, "metroliza.charts.chart_render_service", raising=False)
    monkeypatch.setitem(sys.modules, "metroliza.ui.detached_threads", detached)
    assert teardown._stop_workers(0) is False


def test_about_to_quit_wait_is_not_spent_twice(fake_qt, monkeypatch):
    fake_qt.app._metroliza_detached_exit_wait_spent = True
    monkeypatch.setattr(teardown.time, "monotonic", lambda: 10.0)
    deadlines = []
    monkeypatch.setattr(teardown, "_stop_workers", lambda deadline, **kwargs: deadlines.append((deadline, kwargs)) or False)
    assert teardown.shutdown_qt(fake_qt.app) is False
    assert deadlines == [(15.0, {"detached_wait_spent": True})]


def test_quit_hook_marks_wait_spent_before_existing_shutdown(monkeypatch):
    import weakref
    from metroliza.ui import detached_threads

    class App:
        pass
    app, calls = App(), []
    monkeypatch.setattr(detached_threads, "shutdown", lambda: calls.append(app._metroliza_detached_exit_wait_spent))
    detached_threads._shutdown_on_quit(weakref.ref(app))
    assert calls == [True]


@pytest.mark.parametrize("stage", ["widgets", "policy", "gc", "flush", "release"])
def test_step_errors_never_escape(fake_qt, monkeypatch, stage):
    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_TEXT")
    if stage == "widgets":
        fake_qt.app.topLevelWidgets = fail
    elif stage == "policy":
        fake_qt.app._metroliza_gc_policy = SimpleNamespace(stop=fail)
    elif stage == "gc":
        monkeypatch.setattr(teardown.gc, "collect", fail)
    elif stage == "flush":
        fake_qt.core.QCoreApplication.sendPostedEvents = fail
    else:
        fake_qt.sip.delete = fail
    assert teardown.shutdown_qt(fake_qt.app) is False
    assert not fake_qt.app.deleted
    assert "PRIVATE_TEXT" not in repr(fake_qt.calls)


@pytest.mark.parametrize("kind", ["running_thread", "foreign_object"])
def test_live_qobject_scan_retains_unsafe_wrappers(fake_qt, kind):
    obj = fake_qt.core.QThread() if kind == "running_thread" else fake_qt.core.QObject()
    if kind == "running_thread":
        obj.isRunning = lambda: True
    else:
        obj.thread = lambda: "worker"
    fake_qt.objects.append(obj)
    assert teardown.shutdown_qt(fake_qt.app) is False
    assert not fake_qt.app.deleted
    field = "running_threads" if kind == "running_thread" else "foreign_objects"
    assert any(isinstance(call, tuple) and call[0] == "qt_teardown_retained"
               and call[1].get(field) == 1 for call in fake_qt.calls)


def test_gc_scan_uses_actual_type_without_class_property_dispatch(fake_qt):
    class Pretender:
        @property
        def __class__(self):
            pytest.fail("gc census dispatched __class__")
    fake_qt.objects.append(Pretender())
    assert teardown.shutdown_qt(fake_qt.app)


@pytest.mark.parametrize("retain", [False, True])
def test_gc_stays_disabled_through_release_decision(fake_qt, monkeypatch, retain):
    fake_qt.gc_state["enabled"] = False
    def uninstall(**kwargs):
        fake_qt.gc_state["enabled"] = True
        fake_qt.calls.append("uninstall")
    fake_qt.app._metroliza_gc_policy = SimpleNamespace(
        stop=lambda: fake_qt.calls.append("stop"), uninstall=uninstall)
    if retain:
        fake_qt.objects.append(fake_qt.widget_type())
    during_collection = []
    monkeypatch.setattr(teardown.gc, "collect",
                        lambda: during_collection.append(teardown.gc.isenabled()) or 0)
    assert teardown.shutdown_qt(fake_qt.app) is (not retain)
    assert during_collection == [False]
    assert fake_qt.gc_state["enabled"] is (not retain)
    assert ("uninstall" in fake_qt.calls) is (not retain)


def test_factory_refuses_after_release_without_constructing_qt(fake_qt, monkeypatch):
    from metroliza.app import bootstrap
    from unittest.mock import Mock

    assert teardown.shutdown_qt(fake_qt.app)
    # Safe also on the RED source: no second native application can be created.
    factory = Mock(return_value=fake_qt.app)
    factory.instance.return_value = None
    monkeypatch.setattr(sys.modules["PyQt6.QtWidgets"], "QApplication", factory)
    with pytest.raises(RuntimeError, match="second application"):
        bootstrap.get_or_create_qapplication(gui_gc=False)
    factory.assert_not_called()


def _run_teardown_child(source_code):
    source = os.environ.get("METROLIZA_QT_TEARDOWN_SOURCE", str(ROOT / "src"))
    result = subprocess.run(
        [sys.executable, "-u", "-c", source_code], cwd=Path(source).parent,
        env=dict(os.environ, PYTHONPATH=source, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
    assert Path(result.stdout.splitlines()[0]) == Path(source) / "metroliza/app/qt_teardown.py"
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.parametrize("visible", [False, True])
def test_shutdown_child_after_exec_never_delivers_close_event(visible):
    observed = _run_teardown_child('''
import gc, json
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
from PyQt6.QtWidgets import QWidget
from metroliza.app import bootstrap, qt_teardown
print(qt_teardown.__file__, flush=True)
app = bootstrap.get_or_create_qapplication()
app.setQuitOnLastWindowClosed(False)
closes = []
class Window(QWidget):
    def closeEvent(self, event):
        closes.append(1)
        super().closeEvent(event)
window = Window()
window.show()
def finish():
    if not VISIBLE:
        assert window.close()
        QTimer.singleShot(0, app.quit)
    else:
        # QApplication.quit itself closes windows on Qt 6.6.1. exit leaves
        # this top-level visible so the post-exec retention case is real.
        QTimer.singleShot(0, lambda: app.exit(0))
QTimer.singleShot(0, finish)
app.exec()
assert window.isVisible() is VISIBLE
assert len(closes) == (0 if VISIBLE else 1)
events = []
qt_teardown.record_event = lambda name, **counts: events.append(name)
released = qt_teardown.shutdown_qt(app)
observed = dict(released=released, closes=len(closes),
                alive=not sip.isdeleted(app), gc_disabled=not gc.isenabled(),
                retained_event='qt_teardown_retained' in events)
# Always perform ordinary safe cleanup before the parent's assertions, also RED.
if not sip.isdeleted(app):
    if not sip.isdeleted(window):
        window.hide()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if not qt_teardown.shutdown_qt(app):
        policy = vars(app).get('_metroliza_gc_policy')
        if policy is not None:
            policy.uninstall()
        sip.delete(app)
print(json.dumps(observed), flush=True)
'''.replace("VISIBLE", repr(visible)))
    assert observed["closes"] == (0 if visible else 1), observed
    assert observed["released"] is (not visible), observed
    assert observed["alive"] is visible, observed
    assert observed["gc_disabled"] is visible, observed
    assert observed["retained_event"] is visible, observed


def test_shutdown_child_retained_policy_timer_stops_and_gc_stays_disabled():
    observed = _run_teardown_child('''
import gc, json
from PyQt6 import sip
from PyQt6.QtCore import QObject
from metroliza.app import bootstrap, qt_teardown
print(qt_teardown.__file__, flush=True)
app = bootstrap.get_or_create_qapplication()
policy = app._metroliza_gc_policy
timer = policy.timer
# A hidden child created during collection prevents release without any close.
from PyQt6.QtWidgets import QWidget
original = gc.collect
windows, during = [], []
def collect():
    during.append(gc.isenabled())
    windows.append(QWidget())
    return original()
gc.collect = collect
try:
    released = qt_teardown.shutdown_qt(app)
finally:
    gc.collect = original
observed = dict(released=released, during=during, disabled=not gc.isenabled(),
                policy_retained=vars(app).get('_metroliza_gc_policy') is policy,
                timer_stopped=sip.isdeleted(timer) or not timer.isActive())
if not qt_teardown.shutdown_qt(app):
    policy = vars(app).get('_metroliza_gc_policy')
    if policy is not None:
        policy.uninstall()
    sip.delete(app)
print(json.dumps(observed), flush=True)
''')
    assert observed == dict(released=False, during=[False], disabled=True,
                            policy_retained=True, timer_stopped=True)


def test_shutdown_child_unregistered_running_qthread_retains_qt():
    observed = _run_teardown_child('''
import json, threading
from PyQt6 import sip
from PyQt6.QtCore import QThread
from metroliza.app import bootstrap, qt_teardown
print(qt_teardown.__file__, flush=True)
app = bootstrap.get_or_create_qapplication()
release = threading.Event()

class Blocked(QThread):
    def run(self):
        release.wait(5)

worker = Blocked()
worker.start()
try:
    released = qt_teardown.shutdown_qt(app)
    alive = not sip.isdeleted(app)
finally:
    release.set()
    worker.wait(5000)
# The GUI thread's own QThread alone must not block release.
second = qt_teardown.shutdown_qt(app)
print(json.dumps(dict(released=released, alive=alive, second=second,
                      after=sip.isdeleted(app))), flush=True)
''')
    assert observed == dict(released=False, alive=True, second=True, after=True)
