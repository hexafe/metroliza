"""Background loading of the Data grouping dialog (worker thread, delayed indicator, bounded stop)."""

from __future__ import annotations

import threading
import time

import pytest
from PyQt6.QtWidgets import QApplication, QDialog

from metroliza.ui import data_grouping, detached_threads
from metroliza.ui.data_grouping import DataGrouping
from tests.test_1089_acceptance_analytics import _fixture_db

_APP = None


@pytest.fixture(scope="module", autouse=True)
def _qt_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    yield _APP


class _Parent(QDialog):
    def __init__(self):
        super().__init__()
        self.df_for_grouping = None
        self.grouping_applied = None

    def set_df_for_grouping(self, frame):
        self.df_for_grouping = frame

    def set_grouping_applied(self, applied):
        self.grouping_applied = applied


def _wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _APP.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _list_snapshot(dialog):
    return {
        name: [
            (widget.item(row).text(), widget.item(row).data(data_grouping.Qt.ItemDataRole.UserRole))
            for row in range(widget.count())
        ]
        for name, widget in (
            ("reference", dialog.reference_list),
            ("part", dialog.part_list),
            ("groups", dialog.groups_list),
            ("part_group", dialog.part_group_list),
            ("all_parts", dialog.all_parts_list),
        )
    }


def test_background_load_fills_the_same_lists_as_the_synchronous_load(tmp_path):
    db_path = str(_fixture_db(tmp_path))
    parent = _Parent()
    sync_dialog = DataGrouping(parent=parent, db_file=db_path)
    async_dialog = DataGrouping(parent=parent, db_file=db_path, background_load=True)
    try:
        assert async_dialog.is_loading_grouping()
        assert async_dialog.df is None
        assert not async_dialog.part_list.isEnabled()
        assert not async_dialog.use_grouping_button.isEnabled()

        assert _wait_until(lambda: not async_dialog.is_loading_grouping())

        assert async_dialog.df is not None
        assert async_dialog.part_list.isEnabled()
        assert async_dialog.use_grouping_button.isEnabled()
        assert _list_snapshot(async_dialog) == _list_snapshot(sync_dialog)
        assert async_dialog.df.equals(sync_dialog.df)
        assert not async_dialog._is_grouping_dirty()
    finally:
        sync_dialog.close()
        async_dialog.close()
        parent.close()


def test_background_load_restores_saved_grouping_state(tmp_path):
    db_path = str(_fixture_db(tmp_path))
    parent = _Parent()
    first = DataGrouping(parent=parent, db_file=db_path)
    saved = first.df.copy()
    saved.loc[saved["REPORT_ID"] == 3, ["GROUP", "GROUP_COLOR"]] = ["Alpha", "#112233"]
    parent.df_for_grouping = saved
    first.close()
    dialog = DataGrouping(parent=parent, db_file=db_path, background_load=True)
    try:
        assert _wait_until(lambda: not dialog.is_loading_grouping())

        assert dialog.df.set_index("REPORT_ID")["GROUP"].to_dict() == {1: "POPULATION", 2: "POPULATION", 3: "Alpha"}
        assert [dialog.groups_list.item(row).text() for row in range(dialog.groups_list.count())] == [
            "POPULATION (n=2)",
            "Alpha [1] (n=1)",
        ]
    finally:
        dialog.close()
        parent.close()


def test_use_grouping_is_ignored_while_loading(tmp_path):
    db_path = str(_fixture_db(tmp_path))
    parent = _Parent()
    dialog = DataGrouping(parent=parent, db_file=db_path, background_load=True)
    try:
        assert dialog.is_loading_grouping()
        dialog.use_grouping()
        assert parent.grouping_applied is None
        assert _wait_until(lambda: not dialog.is_loading_grouping())
        dialog.use_grouping()
        assert parent.grouping_applied is True
        assert len(parent.df_for_grouping.index) == 3
    finally:
        dialog.close()
        parent.close()


def test_closing_while_loading_stops_the_worker_without_applying_the_result(tmp_path, monkeypatch):
    db_path = str(_fixture_db(tmp_path))
    started = threading.Event()
    release = threading.Event()
    real_loader = data_grouping.load_grouping_dataframe

    def slow_loader(reader, db_file, filter_query):
        started.set()
        release.wait(5)
        return real_loader(reader, db_file, filter_query)

    monkeypatch.setattr(data_grouping, "load_grouping_dataframe", slow_loader)
    parent = _Parent()
    dialog = DataGrouping(parent=parent, db_file=db_path, background_load=True)
    thread = dialog._load_thread
    try:
        assert started.wait(5)
        started_at = time.monotonic()
        dialog.reject()
        # The stop is bounded: the GUI thread never waits longer than the documented limit.
        assert time.monotonic() - started_at < data_grouping._GROUPING_LOAD_STOP_WAIT_MS / 1000 + 1
        assert not dialog.is_loading_grouping()
        assert dialog.df is None
        assert not dialog.isVisible()
    finally:
        release.set()
        assert thread.wait(5000)
        _APP.processEvents()
        assert dialog.df is None
        assert not detached_threads.is_registered(thread)
        dialog.close()
        parent.close()


def test_closing_while_loading_does_not_wait_forever_for_a_stuck_worker(tmp_path, monkeypatch):
    db_path = str(_fixture_db(tmp_path))
    started = threading.Event()
    release = threading.Event()

    def stuck_loader(_reader, _db_file, _filter_query):
        started.set()
        release.wait(10)
        raise RuntimeError("stopped")

    monkeypatch.setattr(data_grouping, "load_grouping_dataframe", stuck_loader)
    monkeypatch.setattr(data_grouping, "_GROUPING_LOAD_STOP_WAIT_MS", 100)
    parent = _Parent()
    dialog = DataGrouping(parent=parent, db_file=db_path, background_load=True)
    thread = dialog._load_thread
    try:
        assert started.wait(5)
        started_at = time.monotonic()
        dialog.reject()
        assert time.monotonic() - started_at < 2
        # The detached thread stays referenced until it finishes, so it cannot be destroyed while running.
        assert detached_threads.is_registered(thread)
    finally:
        release.set()
        assert thread.wait(5000)
        _APP.processEvents()
        assert not detached_threads.is_registered(thread)
        dialog.close()
        parent.close()


def test_failed_background_load_is_logged_and_leaves_the_dialog_closable(tmp_path, monkeypatch):
    db_path = str(_fixture_db(tmp_path))
    logged = []

    def failing_loader(_reader, _db_file, _filter_query):
        raise ValueError("boom")

    monkeypatch.setattr(data_grouping, "load_grouping_dataframe", failing_loader)
    parent = _Parent()
    dialog = DataGrouping(parent=parent, db_file=db_path, background_load=True)
    monkeypatch.setattr(dialog, "log_and_exit", lambda exc, **_kw: logged.append(str(exc)))
    try:
        assert _wait_until(lambda: not dialog.is_loading_grouping())

        assert logged == ["boom"]
        assert dialog.df is None
        assert "could not be loaded" in dialog.scope_filter_summary_label.text()
        dialog.reject()
        assert not dialog.isVisible()
    finally:
        dialog.close()
        parent.close()


def test_refresh_during_background_load_loads_synchronously_and_drops_the_worker_result(tmp_path):
    db_path = str(_fixture_db(tmp_path))
    parent = _Parent()
    dialog = DataGrouping(parent=parent, db_file=db_path, background_load=True)
    thread = dialog._load_thread
    try:
        assert dialog.is_loading_grouping()

        dialog.refresh_data()

        assert not dialog.is_loading_grouping()
        assert len(dialog.df.index) == 3
        assert dialog.part_list.isEnabled()
        assert thread.wait(5000)
        _APP.processEvents()
        assert len(dialog.df.index) == 3
        assert dialog.groups_list.count() == 1
    finally:
        dialog.close()
        parent.close()


def test_synchronous_construction_is_unchanged_without_the_flag(tmp_path):
    db_path = str(_fixture_db(tmp_path))
    parent = _Parent()
    dialog = DataGrouping(parent=parent, db_file=db_path)
    try:
        assert not dialog.is_loading_grouping()
        assert dialog._load_thread is None
        assert len(dialog.df.index) == 3
    finally:
        dialog.close()
        parent.close()


def test_visible_selection_batches_actual_dialog_update(tmp_path, qapplication_session):
    import importlib
    native = importlib.import_module('metroliza.ui.data_grouping')
    widgets = importlib.import_module('PyQt6.QtWidgets')
    assert native.QListWidget is widgets.QListWidget
    assert native.DataGrouping is DataGrouping
    dialog = native.DataGrouping(db_file=str(_fixture_db(tmp_path)))
    try:
        dialog._populate_part_list()
        assert dialog.part_list.count() == 3
        dialog.part_list.item(1).setHidden(True)
        updates = []
        dialog.part_list.itemSelectionChanged.connect(lambda: updates.append(dialog.selection_summary_label.text()))
        dialog._select_visible_parts_for_grouping()
        assert updates == ['Selected parts: 2']
        assert dialog.create_group_button.isEnabled()
        assert [dialog.part_list.item(i).isSelected() for i in range(3)] == [True, False, True]
    finally:
        dialog.close()
