"""Background loading in the Industrial Data dialog: CSV Summary cache view and Oznak status."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

try:
    from PyQt6 import sip
    from PyQt6.QtGui import QCloseEvent
    from PyQt6.QtWidgets import QApplication, QMessageBox

    import metroliza.ui.industrial_data_dialog as industrial_data_dialog
    from metroliza.ui.industrial_data_dialog import IndustrialDataDialog
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

from metroliza.ui import detached_threads
from metroliza.industrial.industrial_tabular_bridge import IndustrialCacheLoadCanceled
from metroliza.industrial.oznak_adapter import OznakAdapterStatus

pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)

_QT_APP = None
_MAIN_THREAD = threading.get_ident()
_TIMEOUT_S = 20


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _wait_until(predicate, timeout=_TIMEOUT_S):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _app().processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class _FakeStore:
    def __init__(self):
        self.cleaned = 0

    def cleanup(self):
        self.cleaned += 1


def _fake_loaded(row_count=3):
    return SimpleNamespace(row_count=row_count, sqlite_store=_FakeStore())


@pytest.fixture()
def dialog_factory(tmp_path, monkeypatch):
    _app()
    monkeypatch.setattr(industrial_data_dialog, "default_industrial_source_config_path",
                        lambda: tmp_path / "sources.yaml")
    # A temporary cache with no data is closed without a save prompt.
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *_a: pytest.fail("the dialog must not ask about discarding data"))
    created = []

    def factory(adapter=None):
        monkeypatch.setattr(
            industrial_data_dialog, "get_oznak_adapter_status",
            adapter or (lambda: OznakAdapterStatus(available=False, error="synthetic")),
        )
        dialog = IndustrialDataDialog(db_file=str(tmp_path / "metroliza.db"))
        created.append(dialog)
        return dialog

    yield factory
    for dialog in created:
        dialog._stop_background_threads()
        dialog.close()
    _wait_until(lambda: not detached_threads.running_threads())


class _FakeAnalyticsDialog:
    created: list = []

    def __init__(self, parent, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.executed = False
        _FakeAnalyticsDialog.created.append(self)

    def exec(self):
        self.executed = True


@pytest.fixture()
def fake_analytics(monkeypatch):
    _FakeAnalyticsDialog.created = []
    monkeypatch.setattr(industrial_data_dialog, "IndustrialAnalyticsDialog", _FakeAnalyticsDialog)
    return _FakeAnalyticsDialog


def test_cache_view_is_built_off_the_gui_thread_and_the_dialog_opens_when_ready(
    dialog_factory, fake_analytics, monkeypatch,
):
    dialog = dialog_factory()
    release = threading.Event()
    calls = []

    def fake_load(db_file, **kwargs):
        calls.append((threading.get_ident(), db_file, kwargs["source_profile_ids"]))
        release.wait(_TIMEOUT_S)
        return _fake_loaded(4)

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", fake_load)
    try:
        dialog.open_analytics_dialog()
        # The click returns at once; the loading indicator exists, the buttons are locked.
        assert dialog.is_loading_analytics_cache()
        assert dialog._analytics_progress_dialog is not None
        assert not dialog.analyze_button.isEnabled()
        assert not dialog.sync_button.isEnabled()
        assert not dialog.select_database_button.isEnabled()
        assert not fake_analytics.created

        # A second click cannot start a second load.
        dialog.open_analytics_dialog()
        dialog.analyze_button.click()
        assert _wait_until(lambda: len(calls) >= 1)
        assert len(calls) == 1
        assert calls[0][0] != _MAIN_THREAD
        assert calls[0][1] == dialog.db_file
        assert calls[0][2] is None

        release.set()
        assert _wait_until(lambda: bool(fake_analytics.created))
    finally:
        release.set()
    analytics = fake_analytics.created[0]
    assert analytics.executed
    assert analytics.parent is dialog
    assert analytics.kwargs["presentation_mode"] == "industrial_cache"
    assert analytics.kwargs["source_label_override"] == "Industrial cache for CSV Summary: 4 rows"
    assert not dialog.is_loading_analytics_cache()
    assert dialog._analytics_progress_dialog is None
    assert dialog.analyze_button.isEnabled()
    assert len(calls) == 1


def test_loading_indicator_shows_after_the_delay_and_is_released(dialog_factory, fake_analytics, monkeypatch):
    dialog = dialog_factory()
    release = threading.Event()
    monkeypatch.setattr(
        industrial_data_dialog, "load_industrial_cache_tabular_result",
        lambda *_a, **_k: (release.wait(_TIMEOUT_S), _fake_loaded())[1],
    )
    try:
        dialog.open_analytics_dialog()
        progress = dialog._analytics_progress_dialog
        assert not progress.isVisible()
        assert _wait_until(progress.isVisible, timeout=5)
        release.set()
        assert _wait_until(lambda: bool(fake_analytics.created))
        assert not progress.isVisible()
    finally:
        release.set()
    assert dialog._analytics_progress_dialog is None


def test_selected_source_is_captured_at_click_time(dialog_factory, fake_analytics, monkeypatch):
    dialog = dialog_factory()
    dialog.analysis_source_combo.clear()
    dialog.analysis_source_combo.addItem("Line A (3 rows)", 7)
    dialog.analysis_source_combo.addItem("Line B (3 rows)", 8)
    seen = {}
    release = threading.Event()

    def fake_load(_db_file, **kwargs):
        seen["ids"] = kwargs["source_profile_ids"]
        release.wait(_TIMEOUT_S)
        return _fake_loaded(3)

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", fake_load)
    try:
        dialog.analysis_source_combo.setCurrentIndex(0)
        dialog.open_analytics_dialog()
        dialog.analysis_source_combo.setCurrentIndex(1)
        release.set()
        assert _wait_until(lambda: bool(fake_analytics.created))
    finally:
        release.set()
    assert seen["ids"] == (7,)
    assert fake_analytics.created[0].kwargs["source_label_override"] == (
        "Industrial cache for CSV Summary (Line A (3 rows)): 3 rows"
    )


def test_load_error_and_empty_cache_messages_are_unchanged(dialog_factory, fake_analytics, monkeypatch):
    dialog = dialog_factory()
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, title, text, *_a: warnings.append((title, text)),
    )

    def failing(*_args, **_kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", failing)
    dialog.open_analytics_dialog()
    assert _wait_until(lambda: bool(warnings))
    assert warnings == [("Industrial data", "Could not load industrial cache: synthetic failure")]
    assert dialog.analyze_button.isEnabled()
    assert not dialog.is_loading_analytics_cache()

    warnings.clear()
    empty = _fake_loaded(0)
    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result",
                        lambda *_a, **_k: empty)
    dialog.open_analytics_dialog()
    assert _wait_until(lambda: bool(warnings))
    assert warnings == [(
        "Industrial data",
        "Fetch industrial data into the local cache before creating CSV Summary analytics.",
    )]
    assert not fake_analytics.created
    assert dialog.analyze_button.isEnabled()


def test_transient_database_lock_is_retried_in_the_worker(dialog_factory, fake_analytics, monkeypatch):
    dialog = dialog_factory()
    attempts = []

    def flaky(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise sqlite3.OperationalError("database is locked")
        return _fake_loaded()

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", flaky)
    dialog.open_analytics_dialog()
    assert _wait_until(lambda: bool(fake_analytics.created))
    assert len(attempts) == 3

    attempts.clear()
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, title, text, *_a: warnings.append(text),
    )

    def other_error(*_args, **_kwargs):
        attempts.append(1)
        raise sqlite3.OperationalError("no such table: nope")

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", other_error)
    dialog.open_analytics_dialog()
    assert _wait_until(lambda: bool(warnings))
    assert attempts == [1]
    assert warnings == ["Could not load industrial cache: no such table: nope"]


def test_closing_the_dialog_while_loading_interrupts_the_worker(dialog_factory, fake_analytics, monkeypatch):
    dialog = dialog_factory()
    state = {"started": threading.Event(), "saw_cancel": False}

    def cancellable(_db_file, *, cancel_check, **_kwargs):
        state["started"].set()
        deadline = time.monotonic() + _TIMEOUT_S
        while time.monotonic() < deadline:
            if cancel_check():
                state["saw_cancel"] = True
                raise IndustrialCacheLoadCanceled()
            time.sleep(0.005)
        return _fake_loaded()

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", cancellable)
    dialog.open_analytics_dialog()
    thread = dialog._analytics_load_thread
    assert state["started"].wait(_TIMEOUT_S)

    started = time.monotonic()
    dialog.reject()
    assert time.monotonic() - started < industrial_data_dialog.BACKGROUND_STOP_WAIT_MS / 1000 + 1
    assert _wait_until(lambda: not detached_threads.is_registered(thread), timeout=1)
    assert state["saw_cancel"]
    assert sip.isdeleted(thread) or not thread.isRunning()
    assert not dialog.is_loading_analytics_cache()
    assert dialog._analytics_progress_dialog is None
    _app().processEvents()
    assert not fake_analytics.created


def test_stuck_worker_is_detached_without_blocking_close_and_its_result_is_cleaned(
    dialog_factory, fake_analytics, monkeypatch,
):
    dialog = dialog_factory()
    monkeypatch.setattr(industrial_data_dialog, "BACKGROUND_STOP_WAIT_MS", 50)
    release = threading.Event()
    started = threading.Event()
    result = _fake_loaded()

    def stuck(*_args, **_kwargs):
        started.set()
        release.wait(_TIMEOUT_S)
        return result

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", stuck)
    try:
        dialog.open_analytics_dialog()
        thread = dialog._analytics_load_thread
        assert started.wait(_TIMEOUT_S)
        began = time.monotonic()
        dialog.reject()
        assert time.monotonic() - began < 2
        # The running QThread stays referenced until it finishes: it is never destroyed while running.
        assert thread.isRunning()
        assert detached_threads.is_registered(thread)
    finally:
        release.set()
    assert _wait_until(lambda: sip.isdeleted(thread) or not thread.isRunning())
    assert _wait_until(lambda: not detached_threads.is_registered(thread))
    # The dropped result releases its cache view.
    assert result.sqlite_store.cleaned == 1
    assert not fake_analytics.created


def test_cancel_from_the_indicator_restores_the_dialog(dialog_factory, fake_analytics, monkeypatch):
    dialog = dialog_factory()
    started = threading.Event()

    def cancellable(_db_file, *, cancel_check, **_kwargs):
        started.set()
        while not cancel_check():
            time.sleep(0.005)
        raise IndustrialCacheLoadCanceled()

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", cancellable)
    dialog.open_analytics_dialog()
    assert started.wait(_TIMEOUT_S)
    dialog._cancel_analytics_load()
    assert not dialog.is_loading_analytics_cache()
    assert dialog.analyze_button.isEnabled()
    assert dialog.status_label.text() == industrial_data_dialog.ANALYTICS_LOAD_CANCELED_TEXT
    assert not fake_analytics.created


def _use_populated_temporary_cache(dialog):
    from metroliza.industrial.industrial_cache_target import create_temporary_industrial_cache_target
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository

    target = create_temporary_industrial_cache_target()
    assert dialog._set_cache_target(target)
    repository = IndustrialDataRepository(target.cache_db_file)
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="line_a",
        database_type="sqlite",
        source_object_name="events",
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=({"source_record_key": "row-1", "measurement": 12.5},),
    )
    dialog.refresh_status()
    return target


def test_cancelling_the_save_prompt_restores_the_stopped_csv_summary_load(
    dialog_factory, fake_analytics, monkeypatch,
):
    dialog = dialog_factory()
    target = _use_populated_temporary_cache(dialog)
    started = threading.Event()

    def cancellable(_db_file, *, cancel_check, **_kwargs):
        started.set()
        while not cancel_check():
            time.sleep(0.005)
        raise IndustrialCacheLoadCanceled()

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", cancellable)
    dialog.open_analytics_dialog()
    assert started.wait(_TIMEOUT_S)
    assert not dialog.analyze_button.isEnabled()

    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_a: asked.append(1) or QMessageBox.StandardButton.Cancel,
    )
    dialog.reject()

    assert asked == [1]
    # The dialog stays open: the stopped load is reported and the actions are usable again.
    assert not dialog.is_loading_analytics_cache()
    assert dialog.analyze_button.isEnabled()
    assert dialog.sync_button.isEnabled()
    assert dialog.select_database_button.isEnabled()
    assert dialog.status_label.text() == industrial_data_dialog.ANALYTICS_LOAD_CANCELED_TEXT
    assert dialog.cache_target == target
    assert os.path.exists(target.cache_db_file)
    assert not fake_analytics.created

    # The same close with Discard removes the temporary files.
    monkeypatch.setattr(QMessageBox, "question", lambda *_a: QMessageBox.StandardButton.Discard)
    dialog.reject()
    assert _wait_until(lambda: not os.path.exists(target.cache_db_file))


def test_closing_event_cancel_also_restores_the_stopped_csv_summary_load(
    dialog_factory, fake_analytics, monkeypatch,
):
    dialog = dialog_factory()
    target = _use_populated_temporary_cache(dialog)
    started = threading.Event()

    def cancellable(_db_file, *, cancel_check, **_kwargs):
        started.set()
        while not cancel_check():
            time.sleep(0.005)
        raise IndustrialCacheLoadCanceled()

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", cancellable)
    dialog.open_analytics_dialog()
    assert started.wait(_TIMEOUT_S)
    monkeypatch.setattr(QMessageBox, "question", lambda *_a: QMessageBox.StandardButton.Cancel)

    event = QCloseEvent()
    dialog.closeEvent(event)

    assert not event.isAccepted()
    assert dialog.analyze_button.isEnabled()
    assert dialog.status_label.text() == industrial_data_dialog.ANALYTICS_LOAD_CANCELED_TEXT
    assert os.path.exists(target.cache_db_file)
    monkeypatch.setattr(QMessageBox, "question", lambda *_a: QMessageBox.StandardButton.Discard)
    dialog.reject()


def test_temporary_cache_removal_waits_for_a_detached_loader(dialog_factory, fake_analytics, monkeypatch):
    dialog = dialog_factory()
    target = _use_populated_temporary_cache(dialog)
    monkeypatch.setattr(industrial_data_dialog, "BACKGROUND_STOP_WAIT_MS", 50)
    release = threading.Event()
    started = threading.Event()

    def stuck(*_args, **_kwargs):
        started.set()
        release.wait(_TIMEOUT_S)
        return _fake_loaded()

    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", stuck)
    monkeypatch.setattr(QMessageBox, "question", lambda *_a: QMessageBox.StandardButton.Discard)
    try:
        dialog.open_analytics_dialog()
        thread = dialog._analytics_load_thread
        assert started.wait(_TIMEOUT_S)
        dialog.reject()
        # The detached loader may still hold the file (Windows): its removal is deferred, not lost.
        assert thread.isRunning()
        assert os.path.exists(target.cache_db_file)
    finally:
        release.set()
    assert _wait_until(lambda: not os.path.exists(target.cache_db_file))
    assert not fake_analytics.created


def test_temporary_cache_removal_is_immediate_without_a_detached_loader(dialog_factory, monkeypatch):
    dialog = dialog_factory()
    target = _use_populated_temporary_cache(dialog)
    monkeypatch.setattr(QMessageBox, "question", lambda *_a: QMessageBox.StandardButton.Discard)

    dialog.reject()

    assert not os.path.exists(target.cache_db_file)


def test_stale_result_is_dropped_and_cleaned(dialog_factory, fake_analytics):
    dialog = dialog_factory()
    stale = _fake_loaded()
    dialog._on_analytics_cache_loaded(dialog._analytics_load_request_id, stale)
    assert stale.sqlite_store.cleaned == 1
    assert not fake_analytics.created


def test_storage_change_is_refused_while_loading(dialog_factory, fake_analytics, monkeypatch):
    dialog = dialog_factory()
    release = threading.Event()
    monkeypatch.setattr(
        industrial_data_dialog, "load_industrial_cache_tabular_result",
        lambda *_a, **_k: (release.wait(_TIMEOUT_S), _fake_loaded())[1],
    )
    try:
        dialog.open_analytics_dialog()
        assert dialog.update_db_file(None) is False
        assert "CSV Summary cache load" in dialog.status_label.text()
    finally:
        release.set()
    assert _wait_until(lambda: bool(fake_analytics.created))


# --- Oznak connector status ------------------------------------------------------------------------


def _earlier_format_oznak_status(status) -> str:
    """The status text as the dialog produced it before the check moved to a background thread."""
    if not status.available:
        return f"Unavailable ({status.error})"
    version = status.version or "unknown version"
    fetch_state = "fetch ready" if status.fetch_available else "fetch unavailable"
    contract_state = "contracts ready" if status.contracts_available else "contracts incomplete"
    sql_state = "SQL ready" if status.raw_sql_available else "SQL unavailable"
    return f"{version}, {contract_state}, {fetch_state}, {sql_state}"


_OZNAK_STATUSES = (
    OznakAdapterStatus(available=False, error="No module named 'oznak'"),
    OznakAdapterStatus(available=False, error=None),
    OznakAdapterStatus(available=True, version="0.3.1", fetch_available=True, contracts_available=True,
                       raw_sql_available=True),
    OznakAdapterStatus(available=True, version=None),
    OznakAdapterStatus(available=True, version="1.0", fetch_available=False, contracts_available=True,
                       raw_sql_available=False, diagnostics={"import_path": "oznak"}),
    OznakAdapterStatus(available=True, version="2", fetch_available=True, contracts_available=False,
                       raw_sql_available=True),
)


@pytest.mark.parametrize("status", _OZNAK_STATUSES)
def test_oznak_status_text_matches_the_earlier_format(status):
    assert industrial_data_dialog._format_oznak_status(status) == _earlier_format_oznak_status(status)
    assert IndustrialDataDialog._format_oznak_status(status) == _earlier_format_oznak_status(status)


@pytest.mark.parametrize("status", _OZNAK_STATUSES)
def test_oznak_status_is_computed_off_the_gui_thread_and_replaces_the_placeholder(dialog_factory, status):
    release = threading.Event()
    threads = []

    def adapter_status():
        threads.append(threading.get_ident())
        release.wait(_TIMEOUT_S)
        return status

    try:
        dialog = dialog_factory(adapter_status)
        assert dialog.oznak_label.text() == industrial_data_dialog.OZNAK_CHECKING_TEXT
        assert _wait_until(lambda: bool(threads))
        assert len(threads) == 1 and threads[0] != _MAIN_THREAD
        dialog.refresh_status()
        assert dialog.oznak_label.text() == industrial_data_dialog.OZNAK_CHECKING_TEXT
        release.set()
        expected = _earlier_format_oznak_status(status)
        assert _wait_until(lambda: dialog.oznak_label.text() == expected)
    finally:
        release.set()
    # Later refreshes keep the final text and do not start another check.
    dialog.refresh_status()
    assert dialog.oznak_label.text() == expected
    assert len(threads) == 1


def test_oznak_check_failure_shows_an_unavailable_status(dialog_factory):
    def broken():
        raise RuntimeError("synthetic import failure")

    dialog = dialog_factory(broken)
    assert _wait_until(lambda: dialog.oznak_label.text() == "Unavailable (synthetic import failure)")


def test_closing_while_the_oznak_check_runs_does_not_destroy_the_thread(dialog_factory, monkeypatch):
    release = threading.Event()
    started = threading.Event()

    def slow():
        started.set()
        release.wait(_TIMEOUT_S)
        return OznakAdapterStatus(available=False, error="late")

    monkeypatch.setattr(industrial_data_dialog, "BACKGROUND_STOP_WAIT_MS", 50)
    try:
        dialog = dialog_factory(slow)
        thread = dialog._oznak_status_thread
        assert started.wait(_TIMEOUT_S)
        began = time.monotonic()
        dialog.reject()
        assert time.monotonic() - began < 2
        assert thread.isRunning()
        assert detached_threads.is_registered(thread)
    finally:
        release.set()
    assert _wait_until(lambda: sip.isdeleted(thread) or not thread.isRunning())
    assert _wait_until(lambda: not detached_threads.is_registered(thread))


def test_source_combo_lists_profiles_with_cached_rows_only(tmp_path, monkeypatch):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository

    _app()
    monkeypatch.setattr(industrial_data_dialog, "default_industrial_source_config_path",
                        lambda: tmp_path / "sources.yaml")
    monkeypatch.setattr(industrial_data_dialog, "get_oznak_adapter_status",
                        lambda: OznakAdapterStatus(available=False, error="synthetic"))
    db_file = str(tmp_path / "metroliza.db")
    repository = IndustrialDataRepository(db_file)
    expected = {}
    for key, name, rows in (("a", "Line A", 3), ("b", "Line B", 0), ("c", "Line C", 1)):
        profile = repository.upsert_source_profile(
            profile_key=key, profile_name=name, source_db_alias=key,
            database_type="sqlite", source_object_name="events",
        )
        repository.upsert_industrial_records_from_rows(
            source_profile_id=profile.id, source_db_alias=key,
            rows=({"source_record_key": f"{key}-{index}", "length_mm": str(index)} for index in range(rows)),
        )
        expected[profile.id] = (name, rows)
    dialog = IndustrialDataDialog(db_file=db_file)
    try:
        items = [
            (dialog.analysis_source_combo.itemText(index), dialog.analysis_source_combo.itemData(index))
            for index in range(dialog.analysis_source_combo.count())
        ]
    finally:
        dialog._stop_background_threads()
        dialog.close()
    assert items[0] == ("All sources (4 rows)", None)
    assert items[1:] == [
        (f"{name} ({rows:,} rows)", profile_id)
        for profile_id, (name, rows) in expected.items()
        if rows
    ]


@pytest.mark.parametrize("operation", ["cancel", "reject", "destroy"])
def test_native_loader_ownership_cleanup_and_gui_delivery(dialog_factory, monkeypatch, operation):
    from PyQt6.QtCore import QCoreApplication, QEvent
    entered, release = threading.Event(), threading.Event()
    result = _fake_loaded()
    cleanup_threads = []
    cleanup = result.sqlite_store.cleanup
    def observed_cleanup():
        cleanup_threads.append(threading.get_ident())
        cleanup()
    result.sqlite_store.cleanup = observed_cleanup
    def held(*args, **kwargs):
        entered.set()
        release.wait(5)
        return result
    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", held)
    dialog = dialog_factory()
    dialog.open_analytics_dialog()
    worker = dialog._analytics_load_thread
    destroyed = []
    worker.destroyed.connect(lambda: destroyed.append(threading.get_ident()))
    try:
        assert entered.wait(2)
        began = time.monotonic()
        with monkeypatch.context() as m:
            m.setattr(worker, "wait", lambda *args: pytest.fail("GUI waited for running native worker"))
            if operation == "destroy":
                dialog.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            else:
                getattr(dialog, "_cancel_analytics_load" if operation == "cancel" else "reject")()
        assert time.monotonic() - began < 1
        assert detached_threads.is_registered(worker)
        assert result.sqlite_store.cleaned == 0
    finally:
        release.set()
    assert _wait_until(lambda: not detached_threads.is_registered(worker), timeout=1)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert result.sqlite_store.cleaned == 1
    assert cleanup_threads == [_MAIN_THREAD]
    assert destroyed == [_MAIN_THREAD]
    if operation != "destroy":
        assert dialog._cache_holding_threads == []
    if operation == "destroy":
        # The factory's live-widget teardown must not revisit the explicitly deleted parent.
        dialog._stop_background_threads = lambda: None
        dialog.close = lambda: None


@pytest.mark.parametrize("terminal", ["success", "error"])
def test_native_delivery_retains_owner_through_reentrant_parent_deletion(
    dialog_factory, fake_analytics, monkeypatch, terminal,
):
    from PyQt6.QtCore import QCoreApplication, QEvent
    dialog = dialog_factory()
    seen = []
    def destroy_owner(*args, **kwargs):
        worker = seen[0]
        assert detached_threads.is_registered(worker)
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert detached_threads.is_registered(worker)
    if terminal == "error":
        def load(*args, **kwargs):
            raise ValueError("synthetic")
        monkeypatch.setattr(QMessageBox, "warning", destroy_owner)
    else:
        def load(*args, **kwargs):
            return _fake_loaded()
        monkeypatch.setattr(_FakeAnalyticsDialog, "exec", destroy_owner)
    monkeypatch.setattr(industrial_data_dialog, "load_industrial_cache_tabular_result", load)
    dialog.open_analytics_dialog()
    seen.append(dialog._analytics_load_thread)
    assert _wait_until(lambda: not detached_threads.is_registered(seen[0]))
    assert sip.isdeleted(dialog)
    dialog._stop_background_threads = lambda: None
    dialog.close = lambda: None
