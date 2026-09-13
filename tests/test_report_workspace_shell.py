"""The production MainWindow owns one real report workflow across navigation."""

from contextlib import closing
import sqlite3
from threading import Event
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

from metroliza.ui.main_window import MainWindow
from metroliza.ui.ui_preferences import UiPreferences
from tests.test_report_planner_integration import reports as reports, wait_until


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    preferences = UiPreferences(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    window = MainWindow("synthetic", None, ui_preferences=preferences)
    window.show()
    app.processEvents()
    yield window
    host = window.reports_workspace
    workers = tuple(worker for worker in (host.preflight_thread, host.parse_thread) if worker is not None)
    host._request_active_worker_cancellation()
    for worker in workers:
        assert worker.wait(20000)
    app.processEvents()
    window.industrial_data_dialog = None
    window.close()
    window.deleteLater()
    for worker in workers:
        worker.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(window)


def prepare_review(app, window, reports):
    source, database = reports
    assert window.set_directory(str(source))
    assert window.set_db_file(str(database))
    host = window.launch_parsing_dialog()
    host.scan_button.click()
    wait_until(app, host.can_change_workspace)
    assert host.report_planner.model.counts["ready"] == 5
    assert not database.exists()
    return host, source, database


def test_home_has_one_recommended_action_and_reports_has_one_owner(window):
    host = window.reports_workspace
    assert window.parsing_dialog is host
    assert window.window_coordinator.get("parsing") is None
    assert [button for button in window.home_page.findChildren(QPushButton) if not button.isHidden()] == [
        window.home_next_action,
    ]
    for button in (window.modifydb_button, window.export_button, window.map_characteristics_button):
        assert window.reports_page.isAncestorOf(button)
        assert not window.home_page.isAncestorOf(button)
    for page in ("reports", "home", "tools", "reports"):
        window._show_workspace_page(page)
        assert window.reports_workspace is host
    assert window.launch_parsing_dialog() is host
    assert window.window_coordinator.get("parsing") is None


def test_real_selected_import_survives_navigation_and_preserves_outcome(app, window, reports):
    host, _source, database = prepare_review(app, window, reports)
    planner = host.report_planner
    model = planner.model
    model.clear_selection()
    for row in (1, 3):
        model.setData(model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    selected = model.selected_ids
    planner.search.setText("report-1")
    assert planner.proxy.rowCount() == 1
    for page in ("home", "tools", "reports"):
        window._show_workspace_page(page)
        assert window.reports_workspace.report_planner.model is model
        assert model.selected_ids == selected
        assert planner.search.text() == "report-1"
    host.parse_button.click()
    worker = host.parse_thread
    window._show_workspace_page("home")
    wait_until(app, host.can_change_workspace)
    assert worker.last_parse_result.imported_files == 2
    with closing(sqlite3.connect(database)) as connection:
        assert set(connection.execute("SELECT file_name FROM source_file_locations")) == {
            ("report-1.pdf",), ("report-3.pdf",),
        }
        assert connection.execute("SELECT COUNT(*) FROM report_measurements").fetchone()[0] > 0
    outcome = planner.outcome.toPlainText()
    assert "Saved: 2 report files" in outcome
    assert not window.home_report_result.isHidden()
    window._show_workspace_page("tools")
    window.launch_parsing_dialog()
    assert planner.outcome.toPlainText() == outcome
    assert window.reports_workspace is host


def test_accepted_and_rejected_context_changes_keep_one_authority(app, window, reports, monkeypatch):
    host, source, database = prepare_review(app, window, reports)
    host.report_planner.show_outcome("Import outcome\nSaved: 2 report files")
    previous = window.workspace_context.snapshot
    rejected = database.with_name("rejected.db")
    window.industrial_data_dialog = SimpleNamespace(isVisible=lambda: True, update_db_file=lambda _path: False)
    monkeypatch.setattr("metroliza.ui.parsing_dialog.QFileDialog.getSaveFileName", lambda *_args: (str(rejected), ""))
    host.select_database()
    assert window.workspace_context.snapshot is previous
    assert window.db_file == host.db_file == str(database)
    assert host.report_planner.model.selected_count == 5
    window.industrial_data_dialog = None
    assert window.set_db_file(str(rejected))
    assert window.db_file == host.db_file == str(rejected)
    assert host.directory == str(source)
    assert not host.report_planner.model.valid
    assert host.report_planner.model.selected_count == 0
    assert host.report_planner.outcome.toPlainText() == ""
    assert str(rejected) in window.database_status_label.text()


@pytest.mark.parametrize("stage", ["review", "import"])
def test_busy_owner_rejects_duplicate_context_and_defers_main_close(app, window, reports, monkeypatch, stage):
    from metroliza.parsing.preflight import ParsePreflightService
    from metroliza.reports.report_repository import ReportRepository

    entered, release = Event(), Event()
    if stage == "import":
        host, source, database = prepare_review(app, window, reports)
        target, name = ReportRepository, "import_report_if_absent"
    else:
        source, database = reports
        window.set_directory(str(source))
        window.set_db_file(str(database))
        host = window.launch_parsing_dialog()
        target, name = ParsePreflightService, "scan_source"
    original = getattr(target, name)

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, gated)
    try:
        (host.parse_button if stage == "import" else host.scan_button).click()
        wait_until(app, entered.is_set)
        worker = host.parse_thread if stage == "import" else host.preflight_thread
        snapshot = window.workspace_context.snapshot
        window._show_workspace_page("home")
        assert not window.home_cancel_report.isHidden()
        assert window.launch_parsing_dialog() is host
        host.scan_reports()
        host._import_reviewed_reports()
        assert (host.parse_thread if stage == "import" else host.preflight_thread) is worker
        assert window.set_directory(str(source / "other")) is False
        assert window.set_db_file(str(database.with_name("other.db"))) is False
        assert window.workspace_context.snapshot is snapshot
        assert window.close() is False
        assert window.isVisible()
        assert host.is_close_deferred()
        release.set()
        wait_until(app, lambda: host.can_change_workspace() and not window.isVisible())
        assert not worker.isRunning()
    finally:
        release.set()


def test_tools_shortcuts_use_existing_primary_navigation(window):
    for action, page in (
        (window.csv_summary_action, "csv_analytics"),
        (window.industrial_data_action, "industrial_data"),
        (window.realtime_monitoring_action, "realtime_monitor"),
        (window.parser_profiles_action, "parser_profiles"),
    ):
        action.trigger()
        assert window.navigation_combo.currentData() == page
    assert window.window_coordinator.open_window_ids == ()


def test_optional_incident_action_is_normal_lazy_menu_binding(window, monkeypatch):
    from metroliza.ui import main_window

    action = window.diagnostic_incidents_action
    assert action in window.help_menu.actions()
    assert action.text() == "Diagnostic incidents…"
    monkeypatch.setattr(main_window.importlib.util, "find_spec", lambda _name: None)
    window._refresh_incident_action()
    assert not action.isEnabled()
    assert "unavailable" in action.toolTip()
    calls = []
    monkeypatch.setattr(main_window.importlib.util, "find_spec", lambda _name: object())

    def import_viewer(name):
        calls.append(name)
        return SimpleNamespace(open_incident_viewer=lambda parent: calls.append(parent))

    monkeypatch.setattr(main_window.importlib, "import_module", import_viewer)
    window._refresh_incident_action()
    assert action.isEnabled() and calls == []
    action.trigger()
    assert calls == ["metroliza.ui.incident_dialog", window]


@pytest.mark.parametrize("failure", [ImportError("private diagnostic text"), SyntaxError("private diagnostic text")])
def test_installed_broken_incident_feature_is_reported_not_absent(window, monkeypatch, failure):
    from metroliza.ui import main_window

    messages = []
    monkeypatch.setattr(main_window.importlib.util, "find_spec", lambda _name: object())
    window._refresh_incident_action()

    def broken(_name):
        raise failure

    monkeypatch.setattr(main_window.importlib, "import_module", broken)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    window.diagnostic_incidents_action.trigger()
    assert window.diagnostic_incidents_action.isEnabled()
    assert messages == ["The installed diagnostic feature could not be loaded."]
