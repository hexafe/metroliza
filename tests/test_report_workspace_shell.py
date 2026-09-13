"""The production MainWindow owns one real report workflow across navigation."""

from contextlib import closing
import os
import sqlite3
import subprocess
import sys
from threading import Event
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

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


@pytest.mark.parametrize("saved_page", ["home", "reports"])
def test_report_stack_initializes_after_first_paint_or_user_entry(tmp_path, saved_page):
    code = '''
import sys
from PyQt6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QSettings
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from metroliza.ui.main_window import MainWindow
from metroliza.ui.ui_preferences import UiPreferences
app = QApplication([])
preferences = UiPreferences(QSettings(sys.argv[1], QSettings.Format.IniFormat))
preferences.set("presentation/navigation/page", sys.argv[2])
class ObservedWindow(MainWindow):
    first_paint_seen = False
    report_stack_present_at_first_paint = None

    def paintEvent(self, event):
        if not self.first_paint_seen:
            self.report_stack_present_at_first_paint = "metroliza.ui.parsing_dialog" in sys.modules
            self.first_paint_seen = True
        super().paintEvent(event)

window = ObservedWindow("synthetic", None, ui_preferences=preferences)
try:
    assert "metroliza.ui.parsing_dialog" not in sys.modules, "Reports loaded before first paint"
    window.show()
    elapsed = QElapsedTimer()
    elapsed.start()
    while elapsed.elapsed() < 5000:
        QTest.qWait(10)
        if window.first_paint_seen and (sys.argv[2] == "home" or window._reports_workspace is not None):
            break
    assert window.first_paint_seen, "The window never painted"
    assert window.report_stack_present_at_first_paint is False, "Reports loaded before first paint"
    if sys.argv[2] == "home":
        assert "metroliza.ui.parsing_dialog" not in sys.modules
    else:
        assert window._reports_workspace is not None
    host = window.launch_parsing_dialog()
    assert window.launch_parsing_dialog() is host
    assert window.parsing_dialog is host
finally:
    window.close()
    window.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
'''
    completed = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "startup.ini"), saved_page],
        env=os.environ.copy(), capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


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
    assert window.home_next_action.toolTip() == "Open Reports and focus the next available report action."


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
        progress = host.loading_dialog if stage == "import" else host.scan_loading_dialog
        assert progress.windowModality() == Qt.WindowModality.NonModal
        assert QApplication.activeModalWidget() is None
        snapshot = window.workspace_context.snapshot
        # Exercise real keyboard navigation while the operation is blocked.
        window.activateWindow()
        navigation = window.navigation_combo if window.navigation_combo.isVisible() else window.navigation_list
        navigation.setFocus()
        QTest.keyClick(navigation, Qt.Key.Key_Home)
        app.processEvents()
        assert window.workspace_stack.currentWidget() is window.home_page
        assert not window.home_cancel_report.isHidden()
        assert not window.enrich_metadata_action.isEnabled()
        window.on_metadata_enrichment_finished()
        assert not window.enrich_metadata_action.isEnabled()
        assert all(not button.isEnabled() for button in window._database_workflow_buttons)
        window.enrich_metadata_action.trigger()
        for button in window._database_workflow_buttons:
            button.click()
        for launch in (window.launch_metadata_enrichment, window.launch_modifydb_dialog,
                       window.launch_export_dialog, window.launch_characteristic_mapping_dialog,
                       window.launch_industrial_data_dialog, window.launch_realtime_industrial_monitoring_dialog):
            launch()
        assert window.metadata_enrichment_thread is None
        assert window.window_coordinator.open_window_ids == ()
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
        assert window.enrich_metadata_action.isEnabled()
        assert all(button.isEnabled() for button in window._database_workflow_buttons)
    finally:
        release.set()


def test_existing_database_window_blocks_report_start_without_losing_its_work(app, window, reports):
    host, _source, database = prepare_review(app, window, reports)
    writer = QDialog(window)
    writer.db_file = str(database)
    button = QPushButton("Existing database action", writer)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    window.export_dialog = writer
    writer.show()
    app.processEvents()
    try:
        selected = host.report_planner.model.selected_ids
        host.scan_button.click()
        host.parse_button.click()
        assert host.can_change_workspace()
        assert host.report_planner.model.selected_ids == selected
        assert not database.exists()
        assert writer.isVisible() and button.isEnabled()
        assert clicks == []
        assert "Finish or close Export" in window.workspace_notice_label.text()
        writer.close()
        host.parse_button.click()
        wait_until(app, host.can_change_workspace)
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
    finally:
        window.export_dialog = None
        writer.close()
        writer.deleteLater()


@pytest.mark.parametrize("workflow", ["export", "modifydb"])
@pytest.mark.parametrize("stage", ["review", "import"])
def test_preserved_window_cannot_switch_onto_active_report_database(app, window, reports, monkeypatch, workflow, stage):
    from metroliza.parsing.preflight import ParsePreflightService
    from metroliza.reports.report_repository import ReportRepository
    from metroliza.ui import export_dialog

    source, database = reports
    database = database.with_suffix(".db")
    previous = database.with_name("previous.db")
    monkeypatch.setattr(export_dialog.ExportDialog, "_load_dialog_config", lambda _self: {})
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Cancel)
    window.set_directory(str(source))
    window.set_db_file(str(previous))
    getattr(window, f"launch_{workflow}_dialog")()
    writer = getattr(window, f"{workflow}_dialog")
    assert writer.windowModality() == Qt.WindowModality.NonModal
    assert QApplication.activeModalWidget() is None
    if workflow == "modifydb":
        writer.populate_table(writer.reference_table, [("original", 1)])
        writer.reference_table.item(0, 1).setText("retained draft")
    else:
        writer.filter_query = "WHERE 1 = 0"
    assert window.set_db_file(str(database))
    assert writer.isVisible() and writer.db_file == str(previous)
    host = window.launch_parsing_dialog()
    if stage == "import":
        host.scan_button.click()
        wait_until(app, host.can_change_workspace)
        assert host.report_planner.model.counts["ready"] == 5
    target, name = ((ReportRepository, "import_report_if_absent") if stage == "import"
                    else (ParsePreflightService, "scan_source"))
    original = getattr(target, name)
    entered, release = Event(), Event()

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, gated)
    monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getOpenFileName", lambda *_args: (str(database), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Discard)
    try:
        (host.parse_button if stage == "import" else host.scan_button).click()
        wait_until(app, entered.is_set)
        snapshot = window.workspace_context.snapshot
        window.activateWindow()
        navigation = window.navigation_combo if window.navigation_combo.isVisible() else window.navigation_list
        navigation.setFocus()
        QTest.keyClick(navigation, Qt.Key.Key_Home)
        app.processEvents()
        assert window.workspace_stack.currentWidget() is window.home_page
        assert QApplication.activeModalWidget() is None
        writer.select_db_file()
        assert writer.db_file == str(previous)
        assert writer.isVisible() and writer.isEnabled()
        assert window.workspace_context.snapshot is snapshot
        if workflow == "modifydb":
            assert writer.reference_table.item(0, 1).text() == "retained draft"
            assert writer.has_pending_changes()
        else:
            assert writer.filter_query == "WHERE 1 = 0"
            assert writer._update_database_context(str(database)) is False
            assert writer.filter_query == "WHERE 1 = 0"
        release.set()
        wait_until(app, host.can_change_workspace)
        if stage == "review":
            host.parse_button.click()
            wait_until(app, host.can_change_workspace)
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
        writer.select_db_file()
        assert writer.db_file == str(database)
    finally:
        release.set()
        wait_until(app, host.can_change_workspace)
        writer.close()


def test_enrichment_on_another_database_does_not_block_real_report_import(app, window, reports, monkeypatch):
    from metroliza.parsing import metadata_enrichment_thread

    source, database = reports
    other = database.with_name("metadata.sqlite")
    entered, release = Event(), Event()
    original = metadata_enrichment_thread.discover_metadata_enrichment_work

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(metadata_enrichment_thread, "discover_metadata_enrichment_work", gated)
    window.set_directory(str(source))
    window.set_db_file(str(other))
    window.launch_metadata_enrichment()
    worker = window.metadata_enrichment_thread
    try:
        wait_until(app, entered.is_set)
        assert worker.db_file == str(other)
        assert window._report_start_allowed() is False
        assert window.set_db_file(str(database))
        host = window.launch_parsing_dialog()
        host.scan_button.click()
        wait_until(app, host.can_change_workspace)
        assert host.report_planner.model.counts["ready"] == 5
        host.parse_button.click()
        wait_until(app, host.can_change_workspace)
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
        assert worker.isRunning() and worker.db_file == str(other)
    finally:
        release.set()
        wait_until(app, lambda: window.metadata_enrichment_thread is None)
        assert worker.wait(20000)
        worker.deleteLater()


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
