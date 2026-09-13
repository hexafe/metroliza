"""Real Qt lifecycle coverage for tabular loading and analytics workers.

The service seams delay work in the real ``TabularAnalyticsLoadThread`` and
``IndustrialAnalyticsThread``. They keep queued signals, delayed progress
dialogs, and grouping dialogs intact while making terminal ordering deterministic.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

try:
    from PyQt6 import sip
    from PyQt6.QtCore import (
        QCoreApplication,
        QElapsedTimer,
        QEvent,
        QEventLoop,
        QObject,
        QTimer,
        pyqtSignal,
    )
    from PyQt6.QtGui import QMovie
    from PyQt6.QtTest import QSignalSpy
    from PyQt6.QtWidgets import QApplication, QMessageBox
    import metroliza.ui.industrial_analytics_dialog as industrial_dialog_module
    from metroliza.industrial.industrial_analytics_workflow import (
        AnalyticsCancelled,
        IndustrialAnalyticsRunResult,
    )
    from metroliza.industrial.industrial_workers import (
        IndustrialAnalyticsThread,
        TabularAnalyticsLoadThread,
    )
    from metroliza.tabular.tabular_analytics_service import TabularLoadCancelled
    from metroliza.ui.industrial_analytics_dialog import (
        IndustrialAnalyticsDialog,
        SOURCE_PRODUCTION_CACHE,
        SOURCE_TABULAR_FILE,
    )
    from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog
    from tests.industrial_analytics_fixtures import seed_production_analytics_cache
except ImportError as exc:  # pragma: no cover - depends on optional PyQt availability
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

if PYQT_IMPORT_ERROR is not None:
    if os.environ.get("METROLIZA_EXPECT_QT_PLATFORM", "").strip():
        raise RuntimeError("the requested Qt platform requires PyQt6") from PYQT_IMPORT_ERROR
    pytest.skip(
        f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}",
        allow_module_level=True,
    )


_APP = None
_WAIT_MS = 5_000


def _app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    expected_platform = os.environ.get("METROLIZA_EXPECT_QT_PLATFORM", "").strip()
    if expected_platform:
        actual_platform = _APP.platformName()
        assert actual_platform.casefold() == expected_platform.casefold(), (
            f"expected Qt platform {expected_platform!r}, got {actual_platform!r}"
        )
    return _APP


class _WorkerGate(QObject):
    entered = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.entered_event = Event()
        self.cancel_observed = Event()
        self.release = Event()


class _ShowObserver(QObject):
    shown = pyqtSignal()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt callback spelling
        if event.type() == QEvent.Type.Show:
            self.shown.emit()
        return False


@dataclass
class _StartedLoad:
    dialog: IndustrialAnalyticsDialog
    worker: TabularAnalyticsLoadThread
    gate: _WorkerGate
    source: Path
    progress_dialog: object
    progress_movie: QMovie
    progress_observer: _ShowObserver
    thread_finished: QSignalSpy


@dataclass
class _StartedAnalytics:
    dialog: IndustrialAnalyticsDialog
    worker: IndustrialAnalyticsThread
    gate: _WorkerGate
    progress_dialog: object
    progress_movie: QMovie
    progress_observer: _ShowObserver
    thread_finished: QSignalSpy


def _write_source(path: Path) -> None:
    pd.DataFrame(
        {
            "TraceCode": ["TC-001", "TC-002", "TC-003"],
            "Batch": ["A", "B", "A"],
            "Length mm": [10.0, 10.2, 10.4],
        }
    ).to_csv(path, index=False)


def _wait(spy: QSignalSpy, description: str) -> None:
    if len(spy):
        return
    # wait() observes only emissions after its entry. A worker can emit between
    # the count check above and that entry; the captured signal is the receipt.
    spy.wait(_WAIT_MS)
    assert len(spy), f"timed out waiting for {description}"


def test_wait_accepts_a_real_signal_between_count_check_and_wait_entry():
    _app()

    class Emitter(QObject):
        done = pyqtSignal()

    emitter = Emitter()

    class BetweenCheckAndWaitSpy(QSignalSpy):
        inject_once = True

        def __len__(self):
            count_before_emission = super().__len__()
            if self.inject_once and count_before_emission == 0:
                self.inject_once = False
                emitter.done.emit()
            return count_before_emission

    spy = BetweenCheckAndWaitSpy(emitter.done)
    try:
        _wait(spy, "signal recorded before native wait entry")
        assert QSignalSpy.__len__(spy) == 1
    finally:
        emitter.deleteLater()
        QCoreApplication.sendPostedEvents(emitter, QEvent.Type.DeferredDelete)


def _wait_for_gate(gate: _WorkerGate) -> None:
    """Enter Qt's event loop until the worker reaches its explicit test barrier."""

    if gate.entered_event.is_set():
        return
    event_loop = QEventLoop()
    deadline = QTimer()
    deadline.setSingleShot(True)
    poll = QTimer()
    poll.setInterval(5)

    def check_gate() -> None:
        if gate.entered_event.is_set():
            event_loop.quit()

    deadline.timeout.connect(event_loop.quit)
    poll.timeout.connect(check_gate)
    deadline.start(_WAIT_MS)
    poll.start()
    event_loop.exec()
    poll.stop()
    assert gate.entered_event.is_set(), "timed out waiting for worker entry"


def _wait_for_gui_owner_cleanup(owner, attribute: str, worker, description: str) -> None:
    """Pump GUI events until the finished slot clears this worker's owner reference."""

    live_worker = worker
    deadline = QElapsedTimer()
    deadline.start()
    while getattr(owner, attribute) is live_worker and deadline.elapsed() < _WAIT_MS:
        _app().processEvents()
    assert getattr(owner, attribute) is None, f"timed out waiting for {description}"


def _drain_deferred_deletes() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _app().processEvents()


@contextmanager
def _suppress_cleanup_notices():
    """Let failure cleanup deliver terminal slots without opening a modal dialog."""

    with (
        patch.object(QMessageBox, "information", lambda *_args: None),
        patch.object(QMessageBox, "warning", lambda *_args: None),
    ):
        yield


def _release_and_join(gate: _WorkerGate, worker: TabularAnalyticsLoadThread) -> None:
    """Stop before owner disposal when the worker has not actually joined."""

    gate.release.set()
    try:
        if worker.isRunning():
            worker.cancel()
        joined = worker.wait(_WAIT_MS)
    except RuntimeError:
        assert sip.isdeleted(worker), "worker wrapper failed before a join receipt"
        return
    assert joined, "tabular worker did not join; leaving its Qt owners intact"


def _finish_worker(started: _StartedLoad) -> None:
    """Release and join a test-held worker even after an assertion failure."""

    _release_and_join(started.gate, started.worker)
    with _suppress_cleanup_notices():
        _app().processEvents()
    assert started.dialog.tabular_load_thread is None


def _dispose_dialog(dialog) -> None:
    """Make C++ destruction explicit; close alone deliberately is not that receipt."""

    if dialog is None or sip.isdeleted(dialog):
        return
    dialog.close()
    dialog.deleteLater()
    _drain_deferred_deletes()
    assert sip.isdeleted(dialog), "dialog C++ object remained after deleteLater"


def _install_gated_loader(monkeypatch, gate: _WorkerGate, *, terminal: str):
    run_globals = TabularAnalyticsLoadThread.run.__globals__

    def gated_loader(original_loader):
        def load(*args, **kwargs):
            gate.entered_event.set()
            gate.entered.emit()
            if not gate.release.wait(_WAIT_MS / 1000):
                raise RuntimeError("test loader gate was not released")
            cancel_check = kwargs["cancel_check"]
            if cancel_check():
                gate.cancel_observed.set()
                raise TabularLoadCancelled("controlled cancellation")
            if terminal == "error":
                raise RuntimeError("controlled loader error")
            return original_loader(*args, **kwargs)

        return load

    monkeypatch.setitem(
        run_globals,
        "load_tabular_analytics_file",
        gated_loader(run_globals["load_tabular_analytics_file"]),
    )
    monkeypatch.setitem(
        run_globals,
        "load_tabular_analytics_files",
        gated_loader(run_globals["load_tabular_analytics_files"]),
    )


def _start_visible_load(monkeypatch, tmp_path: Path, *, terminal: str = "success") -> _StartedLoad:
    app = _app()
    source = tmp_path / "lifecycle.csv"
    _write_source(source)
    gate = _WorkerGate()
    _install_gated_loader(monkeypatch, gate, terminal=terminal)

    original_factory = industrial_dialog_module.create_worker_progress_dialog
    observed: list[tuple[object, QMovie, _ShowObserver]] = []

    def observing_factory(*args, **kwargs):
        progress_dialog, label, bar, movie = original_factory(*args, **kwargs)
        observer = _ShowObserver(progress_dialog)
        progress_dialog.installEventFilter(observer)
        observed.append((progress_dialog, movie, observer))
        return progress_dialog, label, bar, movie

    monkeypatch.setattr(
        industrial_dialog_module,
        "create_worker_progress_dialog",
        observing_factory,
    )
    dialog = IndustrialAnalyticsDialog(
        source_kind=SOURCE_TABULAR_FILE,
        input_file=str(source),
    )
    try:
        dialog.show()
        app.processEvents()
        started_at = QElapsedTimer()
        started_at.start()
        dialog.load_metrics()
        assert len(observed) == 1
        progress_dialog, movie, observer = observed[0]
        worker = dialog.tabular_load_thread
        assert isinstance(worker, TabularAnalyticsLoadThread)
        assert worker.isRunning()
        _wait_for_gate(gate)
        shown = QSignalSpy(observer.shown)
        _wait(shown, "delayed progress visibility")
        assert started_at.elapsed() >= 900
        assert progress_dialog.isVisible()
        return _StartedLoad(
            dialog=dialog,
            worker=worker,
            gate=gate,
            source=source,
            progress_dialog=progress_dialog,
            progress_movie=movie,
            progress_observer=observer,
            thread_finished=QSignalSpy(worker.finished),
        )
    except BaseException:
        worker = dialog.tabular_load_thread
        if isinstance(worker, TabularAnalyticsLoadThread):
            _release_and_join(gate, worker)
            with _suppress_cleanup_notices():
                _app().processEvents()
            assert dialog.tabular_load_thread is None
        else:
            gate.release.set()
        _dispose_dialog(dialog)
        raise


def _complete(started: _StartedLoad) -> None:
    started.gate.release.set()
    _wait(started.thread_finished, "tabular worker finish")
    _wait_for_gui_owner_cleanup(
        started.dialog,
        "tabular_load_thread",
        started.worker,
        "tabular GUI owner cleanup",
    )
    assert started.worker not in started.dialog._worker_progress
    assert sip.isdeleted(started.progress_dialog) or not started.progress_dialog.isVisible()
    _drain_deferred_deletes()
    assert sip.isdeleted(started.worker), "finished tabular worker remained alive after deleteLater"


def _install_gated_analytics_service(monkeypatch, gate: _WorkerGate, *, terminal: str) -> None:
    run_globals = IndustrialAnalyticsThread.run.__globals__

    def gated_analytics(**kwargs):
        gate.entered_event.set()
        gate.entered.emit()
        if not gate.release.wait(_WAIT_MS / 1000):
            raise RuntimeError("test analytics gate was not released")
        if kwargs["cancel_check"]():
            gate.cancel_observed.set()
            raise AnalyticsCancelled("controlled analytics cancellation")
        if terminal == "error":
            raise RuntimeError("controlled analytics error")
        return IndustrialAnalyticsRunResult(
            source_kind=SOURCE_PRODUCTION_CACHE,
            html_dashboard_path=str(kwargs["output_dashboard_file"]),
            html_dashboard_assets_path="",
            html_dashboard_chart_count=1,
            row_count=16,
        )

    monkeypatch.setitem(run_globals, "run_production_cache_analytics", gated_analytics)


def _start_visible_analytics(
    monkeypatch, tmp_path: Path, *, terminal: str = "success"
) -> _StartedAnalytics:
    app = _app()
    db_path = tmp_path / "production_analytics.db"
    seed_production_analytics_cache(db_path)
    gate = _WorkerGate()
    _install_gated_analytics_service(monkeypatch, gate, terminal=terminal)

    original_factory = industrial_dialog_module.create_worker_progress_dialog
    observed: list[tuple[object, QMovie, _ShowObserver]] = []

    def observing_factory(*args, **kwargs):
        progress_dialog, label, bar, movie = original_factory(*args, **kwargs)
        observer = _ShowObserver(progress_dialog)
        progress_dialog.installEventFilter(observer)
        observed.append((progress_dialog, movie, observer))
        return progress_dialog, label, bar, movie

    monkeypatch.setattr(
        industrial_dialog_module,
        "create_worker_progress_dialog",
        observing_factory,
    )
    dialog = IndustrialAnalyticsDialog(
        db_file=str(db_path),
        source_kind=SOURCE_PRODUCTION_CACHE,
    )
    try:
        dialog.show()
        app.processEvents()
        dialog.load_metrics()
        assert dialog.start_button.isEnabled()
        started_at = QElapsedTimer()
        started_at.start()
        dialog.show_loading_screen()
        assert len(observed) == 1
        progress_dialog, movie, observer = observed[0]
        worker = dialog.analytics_thread
        assert isinstance(worker, IndustrialAnalyticsThread)
        assert worker.isRunning()
        _wait_for_gate(gate)
        shown = QSignalSpy(observer.shown)
        _wait(shown, "delayed analytics progress visibility")
        assert started_at.elapsed() >= 900
        assert progress_dialog.isVisible()
        return _StartedAnalytics(
            dialog=dialog,
            worker=worker,
            gate=gate,
            progress_dialog=progress_dialog,
            progress_movie=movie,
            progress_observer=observer,
            thread_finished=QSignalSpy(worker.finished),
        )
    except BaseException:
        worker = dialog.analytics_thread
        gate.release.set()
        if isinstance(worker, IndustrialAnalyticsThread):
            if worker.isRunning():
                worker.cancel()
            assert worker.wait(_WAIT_MS), "analytics worker did not join after setup failure"
            with _suppress_cleanup_notices():
                _app().processEvents()
                assert dialog.analytics_thread is None
                if not sip.isdeleted(worker):
                    worker.deleteLater()
                    _drain_deferred_deletes()
        _dispose_dialog(dialog)
        raise


def _finish_analytics(started: _StartedAnalytics) -> None:
    """Release, join, and explicitly dispose a test-held analytics worker."""

    started.gate.release.set()
    try:
        if started.worker.isRunning():
            started.worker.cancel()
        assert started.worker.wait(_WAIT_MS), "analytics worker did not join"
    except RuntimeError:
        assert sip.isdeleted(started.worker), (
            "analytics worker wrapper failed before a join receipt"
        )
        return
    with _suppress_cleanup_notices():
        _app().processEvents()
        assert started.dialog.analytics_thread is None
        if not sip.isdeleted(started.worker):
            started.worker.deleteLater()
            _drain_deferred_deletes()
        if not sip.isdeleted(started.progress_dialog):
            started.progress_movie.stop()
            started.progress_dialog.close()
            started.progress_dialog.deleteLater()
            _drain_deferred_deletes()


def _complete_analytics(started: _StartedAnalytics) -> None:
    started.gate.release.set()
    _wait(started.thread_finished, "analytics worker finish")
    _wait_for_gui_owner_cleanup(
        started.dialog,
        "analytics_thread",
        started.worker,
        "analytics GUI owner cleanup",
    )
    assert started.worker not in started.dialog._worker_progress
    assert sip.isdeleted(started.progress_dialog) or not started.progress_dialog.isVisible()
    _drain_deferred_deletes()


def _group_records(frame) -> tuple[tuple[int, str], ...]:
    if hasattr(frame, "iter_rows"):
        rows = frame.iter_rows(as_dict=True)
        return tuple((int(row["REPORT_ID"]), str(row["GROUP"])) for row in rows)
    return tuple(
        (int(row.REPORT_ID), str(row.GROUP))
        for row in frame.loc[:, ["REPORT_ID", "GROUP"]].itertuples(index=False)
    )


def _item_for_data(list_widget, expected):
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        if item.data(256) == expected:
            return item
    raise AssertionError(f"missing grouping item {expected!r}")


def _drive_real_grouping(parent, *, expected_records: tuple[tuple[int, str], ...] | None = None):
    """Drive the modal dialog through its own API, with a Qt deadline escape hatch."""

    seen: list[TabularAnalyticsGroupingDialog] = []
    failures: list[BaseException] = []
    deadline = QTimer(parent)
    deadline.setSingleShot(True)

    def stop_modal() -> None:
        failures.append(AssertionError("timed out opening real grouping dialog"))
        modal = _app().activeModalWidget()
        if isinstance(modal, TabularAnalyticsGroupingDialog):
            modal.reject()

    def drive() -> None:
        modal = _app().activeModalWidget()
        if not isinstance(modal, TabularAnalyticsGroupingDialog):
            return
        try:
            assert modal.parent() is parent
            assert "batch" in modal.column_labels
            if expected_records is None:
                batch = _item_for_data(modal.available_columns_list, "batch")
                modal.available_columns_list.setCurrentItem(batch)
                modal.add_selector_column()
                matching = _item_for_data(modal.selector_list, ("A",))
                modal.selector_list.setCurrentItem(matching)
                matching.setSelected(True)
                modal._store_current_selection()
                modal.create_group(initial_group_name="Fixture A")
            else:
                assert _group_records(modal._materialize_grouping_dataframe()) == expected_records
            seen.append(modal)
            modal.use_grouping()
        except BaseException as exc:  # retain failure until exec() returns cleanly
            failures.append(exc)
            modal.reject()

    deadline.timeout.connect(stop_modal)
    deadline.start(_WAIT_MS)
    QTimer.singleShot(0, drive)
    parent.open_grouping_dialog()
    deadline.stop()
    assert not failures
    assert len(seen) == 1
    return seen[0]


@pytest.mark.parametrize(
    ("terminal", "expected_notice"),
    [
        ("success", None),
        ("success_stale_package_attribute", None),
        ("error", "Could not create analytics: controlled analytics error"),
        ("cancel", "controlled analytics cancellation"),
    ],
)
def test_analytics_terminal_stops_and_releases_progress_while_parent_remains_alive(
    monkeypatch,
    tmp_path,
    terminal,
    expected_notice,
):
    notices: list[str] = []
    exports: list[tuple[object, ...]] = []
    trap_calls: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: notices.append(_args[-1]))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: notices.append(_args[-1]))
    export_dialog_module = importlib.import_module("metroliza.ui.export_dialog")
    assert sys.modules["metroliza.ui.export_dialog"] is export_dialog_module
    if terminal == "success_stale_package_attribute":
        ui_package = importlib.import_module("metroliza.ui")
        stale_export_dialog = SimpleNamespace(
            show_export_result_message=lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(ui_package, "export_dialog", stale_export_dialog)
        monkeypatch.setattr(
            export_dialog_module,
            "show_export_result_message",
            lambda *_args, **_kwargs: trap_calls.append("actual producer"),
        )
    monkeypatch.setattr(
        export_dialog_module,
        "show_export_result_message",
        lambda *args, **_kwargs: exports.append(args),
    )
    started = _start_visible_analytics(monkeypatch, tmp_path, terminal=terminal)
    movie_states = QSignalSpy(started.progress_movie.stateChanged)
    try:
        assert started.progress_movie.state() == QMovie.MovieState.Running
        if terminal == "cancel":
            started.dialog.cancel_analytics()
        _complete_analytics(started)

        if terminal.startswith("success"):
            assert len(exports) == 1
            assert trap_calls == []
        else:
            assert notices == [expected_notice]
        assert started.gate.cancel_observed.is_set() is (terminal == "cancel")
        assert not sip.isdeleted(started.dialog)
        assert started.dialog.isVisible()
        assert any(
            arguments[0] == QMovie.MovieState.NotRunning
            or arguments[0] == QMovie.MovieState.NotRunning.value
            for arguments in movie_states
        )
        assert sip.isdeleted(started.progress_dialog)
        assert sip.isdeleted(started.worker)
    finally:
        _finish_analytics(started)
        _dispose_dialog(started.dialog)


@pytest.mark.parametrize(
    ("family", "owner_attribute"),
    [
        ("tabular", "tabular_load_thread"),
        ("analytics", "analytics_thread"),
    ],
)
def test_native_joined_worker_waits_for_gui_owner_cleanup(
    monkeypatch, tmp_path, family, owner_attribute
):
    """A native join does not itself deliver the queued GUI finished slot."""

    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    if family == "tabular":
        started = _start_visible_load(monkeypatch, tmp_path, terminal="cancel")
        cancel = started.dialog.cancel_tabular_load
        complete = _complete
        finish = _finish_worker
    else:
        started = _start_visible_analytics(monkeypatch, tmp_path, terminal="cancel")
        cancel = started.dialog.cancel_analytics
        complete = _complete_analytics
        finish = _finish_analytics

    try:
        cancel()
        started.gate.release.set()
        assert started.worker.wait(_WAIT_MS), f"{family} worker did not join"
        assert len(started.thread_finished) > 0
        assert getattr(started.dialog, owner_attribute) is started.worker
        assert started.worker in started.dialog._worker_progress

        complete(started)

        assert getattr(started.dialog, owner_attribute) is None
        assert started.worker not in started.dialog._worker_progress
        assert sip.isdeleted(started.worker)
        assert sip.isdeleted(started.progress_dialog)
    finally:
        finish(started)
        _dispose_dialog(started.dialog)


@pytest.mark.parametrize("phase", ["running", "finished_pending"])
def test_running_analytics_blocks_second_analytics_and_tabular_starts(monkeypatch, tmp_path, phase):
    _app()
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    source = tmp_path / "analytics-guard.csv"
    _write_source(source)
    gate = _WorkerGate()
    run_globals = IndustrialAnalyticsThread.run.__globals__

    def gated_tabular_analytics(**kwargs):
        gate.entered_event.set()
        gate.entered.emit()
        if not gate.release.wait(_WAIT_MS / 1000):
            raise RuntimeError("test analytics guard was not released")
        if kwargs["cancel_check"]():
            gate.cancel_observed.set()
            raise AnalyticsCancelled("controlled analytics cancellation")
        raise AssertionError("guarded analytics worker completed unexpectedly")

    monkeypatch.setitem(run_globals, "run_tabular_file_analytics", gated_tabular_analytics)
    dialog = IndustrialAnalyticsDialog(
        source_kind=SOURCE_TABULAR_FILE,
        input_file=str(source),
    )
    attempted_starts: list[str] = []
    try:
        dialog.show()
        _app().processEvents()
        dialog.show_loading_screen()
        first = dialog.analytics_thread
        assert isinstance(first, IndustrialAnalyticsThread)
        assert first.isRunning()
        _wait_for_gate(gate)
        if phase == "finished_pending":
            first.cancel()
            gate.release.set()
            assert first.wait(_WAIT_MS), "pending analytics worker did not join"
            assert dialog.analytics_thread is first

        def forbid_second_analytics_worker():
            attempted_starts.append("analytics")
            raise AssertionError("second analytics worker construction reached")

        def forbid_tabular_load_worker(*_args, **_kwargs):
            attempted_starts.append("tabular")
            raise AssertionError("tabular worker construction reached while analytics runs")

        monkeypatch.setattr(dialog, "create_analytics_thread", forbid_second_analytics_worker)
        monkeypatch.setattr(
            industrial_dialog_module,
            "TabularAnalyticsLoadThread",
            forbid_tabular_load_worker,
        )
        for start in (dialog.show_loading_screen, dialog.show_tabular_load_screen):
            try:
                start()
            except AssertionError:
                pass
        assert attempted_starts == []
    finally:
        gate.release.set()
        worker = dialog.analytics_thread
        if isinstance(worker, IndustrialAnalyticsThread):
            if worker.isRunning():
                worker.cancel()
            assert worker.wait(_WAIT_MS), "guarded analytics worker did not join"
            with _suppress_cleanup_notices():
                _app().processEvents()
                assert dialog.analytics_thread is None
                if not sip.isdeleted(worker):
                    worker.deleteLater()
                    _drain_deferred_deletes()
        _dispose_dialog(dialog)


def test_tabular_load_visible_success_preserves_rows_through_real_grouping_reopen(
    monkeypatch, tmp_path
):
    started = _start_visible_load(monkeypatch, tmp_path)
    first_grouping: TabularAnalyticsGroupingDialog | None = None
    second_grouping: TabularAnalyticsGroupingDialog | None = None
    sqlite_path: Path | None = None
    try:
        _complete(started)
        loaded = started.dialog.tabular_load_result
        assert loaded is not None
        assert loaded.row_count == 3
        assert loaded.sqlite_store is not None
        sqlite_path = Path(loaded.sqlite_store.path)
        assert sqlite_path.exists()
        assert loaded.source_file == str(started.source)
        assert loaded.source_files == (str(started.source),)
        assert tuple(loaded.sqlite_store.row_ids()) == (1, 2, 3)

        first_grouping = _drive_real_grouping(started.dialog)
        records = _group_records(started.dialog.df_for_grouping)
        assert records == ((1, "Fixture A"), (3, "Fixture A"))
        assert started.dialog.grouping_applied

        second_grouping = _drive_real_grouping(started.dialog, expected_records=records)
        assert _group_records(started.dialog.df_for_grouping) == records
        assert not first_grouping.isVisible()
        assert not second_grouping.isVisible()
        assert not sip.isdeleted(first_grouping)
        assert not sip.isdeleted(second_grouping)
    finally:
        _finish_worker(started)
        _dispose_dialog(started.dialog)
    assert first_grouping is not None
    assert second_grouping is not None
    assert sqlite_path is not None
    assert sip.isdeleted(started.progress_dialog)
    assert sip.isdeleted(first_grouping)
    assert sip.isdeleted(second_grouping)
    assert not sqlite_path.exists()


def test_sequential_real_dialog_loads_release_first_parent_before_second_load(
    monkeypatch, tmp_path
):
    from tests.test_industrial_analytics_dialog import _dispose_dialog as dispose_test_dialog

    first = _start_visible_load(monkeypatch, tmp_path)
    first_sqlite_path: Path | None = None
    try:
        _complete(first)
        first_loaded = first.dialog.tabular_load_result
        assert first_loaded is not None
        assert first_loaded.sqlite_store is not None
        first_sqlite_path = Path(first_loaded.sqlite_store.path)
        assert first_sqlite_path.exists()
        assert tuple(first_loaded.sqlite_store.row_ids()) == (1, 2, 3)
    finally:
        _finish_worker(first)
        dispose_test_dialog(first.dialog)
    assert first_sqlite_path is not None
    assert sip.isdeleted(first.dialog)
    assert sip.isdeleted(first.progress_dialog)
    assert not first_sqlite_path.exists()

    second = _start_visible_load(monkeypatch, tmp_path)
    second_sqlite_path: Path | None = None
    try:
        _complete(second)
        second_loaded = second.dialog.tabular_load_result
        assert second_loaded is not None
        assert second_loaded.sqlite_store is not None
        second_sqlite_path = Path(second_loaded.sqlite_store.path)
        assert second_sqlite_path.exists()
        assert second_loaded.source_file == str(second.source)
        assert tuple(second_loaded.sqlite_store.row_ids()) == (1, 2, 3)
    finally:
        _finish_worker(second)
        dispose_test_dialog(second.dialog)
    assert second_sqlite_path is not None
    assert sip.isdeleted(second.dialog)
    assert sip.isdeleted(second.progress_dialog)
    assert not second_sqlite_path.exists()


def test_terminal_progress_cleanup_keeps_callback_replacement_bundle(monkeypatch, tmp_path):
    original_factory = industrial_dialog_module.create_worker_progress_dialog
    first = _start_visible_load(monkeypatch, tmp_path)
    replacement: list[tuple[object, object, object, QMovie]] = []
    failures: list[BaseException] = []

    def replace_shared_progress(state) -> None:
        if replacement or failures:
            return
        if state not in (
            QMovie.MovieState.NotRunning,
            QMovie.MovieState.NotRunning.value,
        ):
            return
        try:
            progress_dialog, label, bar, movie = original_factory(
                first.dialog,
                window_title="Replacement progress",
                initial_status_text="Preparing replacement progress\nKeeping shared widgets live\nETA --",
                on_cancel=lambda: None,
            )
            first.dialog.loading_dialog = progress_dialog
            first.dialog.loading_label = label
            first.dialog.loading_bar = bar
            first.dialog.loading_gif = movie
            replacement.append((progress_dialog, label, bar, movie))
        except BaseException as exc:  # Qt signal callbacks must not raise into Qt.
            failures.append(exc)

    first.progress_movie.stateChanged.connect(replace_shared_progress)
    try:
        _complete(first)
        assert not failures
        assert len(replacement) == 1
        replacement_dialog, replacement_label, replacement_bar, replacement_movie = replacement[0]
        assert sip.isdeleted(first.worker)
        assert sip.isdeleted(first.progress_dialog)
        assert not sip.isdeleted(replacement_dialog)
        assert not sip.isdeleted(replacement_movie)
        assert first.dialog._worker_progress == {}
        assert first.dialog.loading_dialog is replacement_dialog
        assert first.dialog.loading_label is replacement_label
        assert first.dialog.loading_bar is replacement_bar
        assert first.dialog.loading_gif is replacement_movie
    finally:
        if replacement:
            replacement_dialog, _replacement_label, _replacement_bar, replacement_movie = (
                replacement[0]
            )
            replacement_movie.stop()
            replacement_dialog.close()
            replacement_dialog.deleteLater()
            _drain_deferred_deletes()
        _finish_worker(first)
        _dispose_dialog(first.dialog)


@pytest.mark.parametrize(
    ("terminal", "expected_notice"),
    [
        ("success", None),
        ("error", "Could not load metrics: controlled loader error"),
        ("cancel", "controlled cancellation"),
    ],
)
def test_terminal_tabular_load_stops_and_releases_progress_while_parent_remains_alive(
    monkeypatch,
    tmp_path,
    terminal,
    expected_notice,
):
    notices: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: notices.append(_args[-1]))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: notices.append(_args[-1]))
    started = _start_visible_load(monkeypatch, tmp_path, terminal=terminal)
    movie_states = QSignalSpy(started.progress_movie.stateChanged)
    try:
        assert started.progress_movie.state() == QMovie.MovieState.Running
        if terminal == "cancel":
            started.dialog.cancel_tabular_load()
        _complete(started)

        if terminal == "success":
            loaded = started.dialog.tabular_load_result
            assert loaded is not None
            assert loaded.source_file == str(started.source)
            assert loaded.sqlite_store is not None
            assert tuple(loaded.sqlite_store.row_ids()) == (1, 2, 3)
        else:
            assert notices == [expected_notice]
            assert started.dialog.tabular_load_result is None

        assert not sip.isdeleted(started.dialog)
        assert started.dialog.isVisible()
        progress_movie_stopped = any(
            arguments[0] == QMovie.MovieState.NotRunning
            or arguments[0] == QMovie.MovieState.NotRunning.value
            for arguments in movie_states
        )
        progress_dialog_deleted = sip.isdeleted(started.progress_dialog)
        assert progress_movie_stopped and progress_dialog_deleted, (
            "terminal tabular load retained progress: "
            f"movie_stopped={progress_movie_stopped}, dialog_deleted={progress_dialog_deleted}"
        )
    finally:
        _finish_worker(started)
        _dispose_dialog(started.dialog)


@pytest.mark.parametrize(
    ("terminal", "expected_message"),
    [
        ("error", "Could not load metrics: controlled loader error"),
        ("cancel", "controlled cancellation"),
    ],
)
def test_visible_tabular_load_error_and_cancel_have_no_result(
    monkeypatch, tmp_path, terminal, expected_message
):
    notices: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: notices.append(_args[-1]))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: notices.append(_args[-1]))
    started = _start_visible_load(monkeypatch, tmp_path, terminal=terminal)
    try:
        if terminal == "cancel":
            started.dialog.cancel_tabular_load()
        _complete(started)
        assert notices == [expected_message]
        assert started.dialog.tabular_load_result is None
        assert started.gate.cancel_observed.is_set() is (terminal == "cancel")
    finally:
        _finish_worker(started)
        _dispose_dialog(started.dialog)
    assert sip.isdeleted(started.progress_dialog)


@pytest.mark.parametrize("close_action", ["close", "reject"])
def test_parent_close_and_reject_stay_guarded_while_visible_tabular_load_runs(
    monkeypatch,
    tmp_path,
    close_action,
):
    notices: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: notices.append(_args[-1]))
    started = _start_visible_load(monkeypatch, tmp_path)
    try:
        getattr(started.dialog, close_action)()
        assert started.dialog.isVisible()
        assert notices == ["Wait for CSV/Excel loading to finish."]
        _complete(started)
        assert started.dialog.close() is True
    finally:
        _finish_worker(started)
        _dispose_dialog(started.dialog)
    assert sip.isdeleted(started.progress_dialog)
