"""The production MainWindow owns one real report workflow across navigation."""

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PyQt6.QtGui import QAction, QKeySequence, QPalette, QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton, QVBoxLayout

from metroliza.ui.main_window import MainWindow
from metroliza.ui.shortcuts import plain_text
from metroliza.ui.ui_preferences import UiPreferences
from metroliza.ui import help_menu, ui_theme_tokens
from metroliza.ui.ui_foundation import apply_metroliza_application_theme
from tests.test_report_planner_integration import reports as reports, wait_until


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    preferences = UiPreferences(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    window = MainWindow("synthetic", None, ui_preferences=preferences)
    window.show()
    app.processEvents()
    yield window
    host = window.reports_workspace
    workers = tuple(worker for worker in (host.preflight_thread, host.parse_thread) if worker is not None)
    host._request_active_worker_cancellation()
    for worker in workers:
        assert worker.wait(20000)
    for worker in tuple(host._metadata_threads):  # the automatic metadata read (#1100)
        assert worker.wait(20000)
    app.processEvents()
    window.industrial_data_dialog = None
    window.close()
    window.deleteLater()
    for worker in workers:
        worker.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(window)


def workspace_idle(host):
    """No report worker is active, including the automatic metadata read of a review (#1100)."""

    return lambda: host.can_change_workspace() and host.metadata_thread is None


def prepare_review(app, window, reports):
    source, database = reports
    assert window.set_directory(str(source))
    assert window.set_db_file(str(database))
    host = window.launch_parsing_dialog()
    host.scan_button.click()
    wait_until(app, workspace_idle(host))
    assert host.report_planner.model.counts["ready"] == 5
    assert all(row.state != "pending" for row in host.report_planner.model.selected_metadata_rows())
    assert not database.exists()
    return host, source, database


def assert_reports_theme(app, window, host, *, dark_mode):
    palette = ui_theme_tokens.theme_tokens(dark_mode=dark_mode)
    role = QPalette.ColorRole

    def color(widget, color_role, group=QPalette.ColorGroup.Active):
        return widget.palette().color(group, color_role).name().upper()

    assert host.styleSheet() == "", "Embedded Reports must inherit the current application theme"
    assert color(window.reports_page, role.Window) == palette["WINDOW_BACKGROUND"]
    assert color(host, role.Window) == palette["WINDOW_BACKGROUND"]
    assert color(host.directory_label, role.WindowText) == palette["TEXT_PRIMARY"]
    assert color(host.mode_guidance_label, role.WindowText) == palette["TEXT_SECONDARY"]
    assert color(host.readiness_label, role.WindowText) == palette["STATUS_COLORS"]["warning"][0]
    assert color(host.readiness_label, role.Window) == palette["STATUS_COLORS"]["warning"][1]

    planner = host.report_planner
    for control in (host.directory_button, planner.select_ready):
        assert color(control, role.Button) == palette["SURFACE_BACKGROUND"]
        assert color(control, role.ButtonText) == palette["TEXT_PRIMARY"]
    for control in (planner.search, planner.status_filter, planner.table):
        assert color(control, role.Base) == palette["SURFACE_BACKGROUND"]
        assert color(control, role.Text) == palette["TEXT_PRIMARY"]
    assert color(planner.table.horizontalHeader(), role.WindowText) == palette["TEXT_PRIMARY"]
    assert color(planner.table, role.Highlight) == ui_theme_tokens.SELECTED_ROW_BACKGROUND_FALLBACK
    assert ui_theme_tokens.contrast_ratio(
        color(planner.table, role.HighlightedText), color(planner.table, role.Highlight)
    ) >= 4.5
    for pane in (planner.details, planner.outcome, host.directory_text_label):
        assert pane.isReadOnly()
        assert color(pane, role.Base) == palette["SURFACE_MUTED_BACKGROUND"]
        assert color(pane, role.Text) == palette["TEXT_SECONDARY"]
        assert ui_theme_tokens.contrast_ratio(color(pane, role.Text), color(pane, role.Base)) >= 4.5
    assert not host.parse_button.isEnabled()
    assert color(host.parse_button, role.ButtonText, QPalette.ColorGroup.Disabled) == (
        palette["DISABLED_TEXT"]
    )
    assert palette["TEXT_PRIMARY"] in app.styleSheet()
    assert palette["SURFACE_MUTED_BACKGROUND"] in app.styleSheet()
    assert palette["BORDER_SUBTLE"] in app.styleSheet()


@pytest.mark.parametrize("initial,target", [("light", "dark"), ("dark", "light")])
def test_existing_reports_inherits_runtime_theme(app, window, initial, target):
    window._set_theme_mode(initial)
    host = window.launch_parsing_dialog()
    app.processEvents()

    window._set_theme_mode(target)
    app.processEvents()

    assert_reports_theme(app, window, host, dark_mode=target == "dark")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_reports_created_after_theme_switch_inherits_theme(app, window, mode):
    assert window._reports_workspace is None
    window._set_theme_mode(mode)
    host = window.launch_parsing_dialog()
    app.processEvents()
    assert_reports_theme(app, window, host, dark_mode=mode == "dark")


def test_persisted_dark_theme_precedes_lazy_reports_creation(app, tmp_path):
    preferences = UiPreferences(QSettings(str(tmp_path / "persisted.ini"), QSettings.Format.IniFormat))
    preferences.set("theme/mode", "dark")
    window = MainWindow("synthetic", None, ui_preferences=preferences)
    try:
        assert window._reports_workspace is None
        window.show()
        app.processEvents()
        host = window.launch_parsing_dialog()
        app.processEvents()
        assert_reports_theme(app, window, host, dark_mode=True)
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        apply_metroliza_application_theme(app, mode="system")


def test_embedded_reports_restores_system_high_contrast_and_system_theme(app, window):
    host = window.launch_parsing_dialog()
    window._set_theme_mode("dark")
    app.processEvents()
    assert_reports_theme(app, window, host, dark_mode=True)

    window._set_theme_mode("high_contrast")
    app.processEvents()
    assert host.styleSheet() == ""
    assert window.styleSheet() == ""
    assert host.palette().color(QPalette.ColorRole.Window) == app.palette().color(
        QPalette.ColorRole.Window
    )
    assert host.report_planner.search.palette().color(QPalette.ColorRole.Text) == app.palette().color(
        QPalette.ColorRole.Text
    )

    window._set_theme_mode("system")
    app.processEvents()
    assert host.styleSheet() == ""
    system_dark = ui_theme_tokens.is_dark_mode_base(
        app._metroliza_system_palette.color(QPalette.ColorRole.Window).name()
    )
    assert_reports_theme(app, window, host, dark_mode=system_dark)


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
        *(window._module_launch_buttons[page][0][0] for page in (
            "reports", "csv_summary", "industrial_data", "realtime_monitor", "parser_profiles", "tools"
        )),
    ]
    for button in (window.modifydb_button, window.export_button, window.map_characteristics_button):
        assert window.reports_page.isAncestorOf(button)
        assert not window.home_page.isAncestorOf(button)
    for page in ("reports", "home", "tools", "reports"):
        window._show_workspace_page(page)
        assert window.reports_workspace is host
    assert window.launch_parsing_dialog() is host
    assert window.window_coordinator.get("parsing") is None
    assert window.home_next_action.toolTip().startswith("Open Reports and focus the next available report action.")


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
    wait_until(app, workspace_idle(host))
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
    assert str(rejected) not in window.recent_locations.paths("databases")
    assert window.workspace_context.snapshot is previous
    assert window.db_file == host.db_file == str(database)
    assert host.report_planner.model.selected_count == 5
    window.industrial_data_dialog = None
    assert window.set_db_file(str(rejected))
    # Not created yet: recorded only once the file exists (after a successful import).
    assert str(rejected) not in window.recent_locations.paths("databases")
    assert window.db_file == host.db_file == str(rejected)
    assert host.directory == str(source)
    assert not host.report_planner.model.valid
    assert host.report_planner.model.selected_count == 0
    assert host.report_planner.outcome.toPlainText() == ""
    assert str(rejected) == window.database_path_field.text()


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
        window.file_menu.actions()[-1].trigger()
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
        wait_until(app, workspace_idle(host))
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
        wait_until(app, workspace_idle(host))
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
        wait_until(app, workspace_idle(host))
        if stage == "review":
            host.parse_button.click()
            wait_until(app, workspace_idle(host))
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
        writer.select_db_file()
        assert writer.db_file == str(database)
    finally:
        release.set()
        wait_until(app, workspace_idle(host))
        writer.close()


@pytest.mark.parametrize("stage", ["review", "import"])
def test_temporary_industrial_cache_cannot_rebind_to_active_report_database(app, window, reports, monkeypatch, stage):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.parsing.preflight import ParsePreflightService
    from metroliza.reports.report_repository import ReportRepository

    source, database = reports
    window.set_directory(str(source))
    window.set_db_file(str(database))
    window.launch_industrial_data_dialog()
    industrial = window.industrial_data_dialog
    industrial.use_temporary_cache()
    temporary = industrial.cache_target
    assert temporary.is_temporary and industrial.report_db_file is None
    assert window.db_file == industrial._workspace_db_file == str(database)
    repository = IndustrialDataRepository(temporary.cache_db_file)
    repository.upsert_source_profile(
        profile_key="synthetic", profile_name="Synthetic", source_db_alias="synthetic",
        database_type="sqlite", source_object_name="events",
    )
    host = window.launch_parsing_dialog()
    if stage == "import":
        host.scan_button.click()
        wait_until(app, workspace_idle(host))
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
        # Selecting the already active database must not rebind a separate cache either.
        assert window.set_db_file(str(database)) is False
        assert industrial.cache_target is temporary
        industrial.select_database_file()
        assert industrial.cache_target is temporary
        assert industrial.db_file == temporary.cache_db_file and industrial.report_db_file is None
        assert window.workspace_context.snapshot is snapshot
        assert len(repository.list_source_profiles(include_disabled=True)) == 1
        release.set()
        wait_until(app, workspace_idle(host))
        if stage == "review":
            host.parse_button.click()
            wait_until(app, workspace_idle(host))
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
        industrial.select_database_file()
        assert industrial.db_file == str(database) and industrial.report_db_file == str(database)
    finally:
        release.set()
        wait_until(app, workspace_idle(host))
        industrial.close()



@pytest.mark.parametrize("workflow", ["industrial", "export", "modifydb"])
@pytest.mark.parametrize("stage", ["review", "import"])
@pytest.mark.parametrize("nested_entry", ["picker", "discard"])
def test_database_picker_rechecks_reports_started_in_nested_event_loop(app, window, reports, monkeypatch, workflow, stage, nested_entry):
    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.parsing.preflight import ParsePreflightService
    from metroliza.reports.report_repository import ReportRepository
    from metroliza.ui import export_dialog, industrial_data_dialog

    source, database = reports
    database = database.with_suffix(".db")
    previous = database.with_name("previous.db")
    monkeypatch.setattr(export_dialog.ExportDialog, "_load_dialog_config", lambda _self: {})
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Cancel)
    window.set_directory(str(source))
    window.set_db_file(str(database if workflow == "industrial" else previous))
    if workflow == "industrial":
        window.launch_industrial_data_dialog()
        writer = window.industrial_data_dialog
        writer.use_temporary_cache()
        previous_target = writer.cache_target
        previous_db = writer.db_file
        IndustrialDataRepository(previous_db).upsert_source_profile(
            profile_key="synthetic", profile_name="Synthetic", source_db_alias="synthetic",
            database_type="sqlite", source_object_name="events",
        )
    else:
        getattr(window, f"launch_{workflow}_dialog")()
        writer = getattr(window, f"{workflow}_dialog")
        previous_db = writer.db_file
        if workflow == "modifydb":
            writer.populate_table(writer.reference_table, [("original", 1)])
            writer.reference_table.item(0, 1).setText("retained draft")
        assert window.set_db_file(str(database))
    assert writer.isVisible() and writer.db_file == previous_db
    host = window.launch_parsing_dialog()
    if stage == "import":
        host.scan_button.click()
        wait_until(app, workspace_idle(host))
        assert host.report_planner.model.counts["ready"] == 5
    target, name = ((ReportRepository, "import_report_if_absent") if stage == "import"
                    else (ParsePreflightService, "scan_source"))
    original = getattr(target, name)
    entered, release = Event(), Event()
    picker_calls, nested_calls = [], []

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    def start_in_nested_loop():
        nested_calls.append(True)
        assert host.can_change_workspace()
        (host.parse_button if stage == "import" else host.scan_button).click()
        if workflow == "export" and nested_entry == "discard":
            assert host.can_change_workspace()
            assert not entered.is_set()
            assert window.statusBar().currentMessage() == "Report start was blocked during Export database selection."
        else:
            wait_until(app, entered.is_set)

    def picker(*_args):
        picker_calls.append(True)
        if nested_entry == "picker":
            start_in_nested_loop()
        return str(database), ""

    def discard(*_args):
        if nested_entry == "discard":
            start_in_nested_loop()
        return QMessageBox.StandardButton.Discard

    if workflow == "export" and nested_entry == "discard":
        class DraftWindow(QDialog):
            def closeEvent(self, event):
                start_in_nested_loop()
                event.accept()

        writer.filter_window = DraftWindow(writer)
        writer.filter_window.show()

    monkeypatch.setattr(target, name, gated)
    monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getOpenFileName", picker)
    monkeypatch.setattr(QMessageBox, "question", discard)
    snapshot = window.workspace_context.snapshot
    try:
        if workflow == "industrial":
            writer.select_database_file()
            assert writer.cache_target is previous_target
            created = []
            create_target = industrial_data_dialog.create_temporary_industrial_cache_target

            def tracked_target():
                target = create_target()
                created.append(target)
                return target

            monkeypatch.setattr(industrial_data_dialog, "create_temporary_industrial_cache_target", tracked_target)
            assert writer.update_db_file(None) is False
            assert len(created) == 1
            assert not os.path.exists(created[0].cache_db_file)
            assert os.path.exists(previous_target.cache_db_file)
            assert writer.cache_target is previous_target
        else:
            writer.select_db_file()
        assert picker_calls == [True]
        assert nested_calls == [True]
        if workflow == "export" and nested_entry == "discard":
            assert host.can_change_workspace()
            assert writer.db_file == str(database)
            assert not writer.database_context_transition_active
            writer.close()
            release.set()
            (host.parse_button if stage == "import" else host.scan_button).click()
        else:
            assert not host.can_change_workspace()
            assert writer.db_file == previous_db
        assert window.workspace_context.snapshot is snapshot
        release.set()
        wait_until(app, workspace_idle(host))
        if stage == "review":
            host.parse_button.click()
            wait_until(app, workspace_idle(host))
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
        monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getOpenFileName", lambda *_args: (str(database), ""))
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Discard)
        if workflow == "industrial":
            writer.select_database_file()
        elif not (workflow == "export" and nested_entry == "discard"):
            writer.select_db_file()
        assert writer.db_file == str(database)
    finally:
        release.set()
        wait_until(app, workspace_idle(host))
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Discard)
        if not sip.isdeleted(writer):
            writer.close()



@pytest.mark.parametrize("child_kind", ["filter", "grouping"])
@pytest.mark.parametrize("discard", [False, True])
@pytest.mark.parametrize("stage", ["review", "import"])
def test_export_context_transition_protects_real_child_drafts(app, window, reports, monkeypatch, child_kind, discard, stage):
    from metroliza.parsing.preflight import ParsePreflightService
    from metroliza.reports.report_repository import ReportRepository
    from metroliza.ui import export_dialog

    source, database = reports
    previous = database.with_name("previous.db")
    monkeypatch.setattr(export_dialog.ExportDialog, "_load_dialog_config", lambda _self: {})
    window.set_directory(str(source))
    window.set_db_file(str(previous))
    window.launch_export_dialog()
    writer = window.export_dialog
    window.set_db_file(str(database))
    host = window.launch_parsing_dialog()
    if stage == "import":
        host.scan_button.click()
        wait_until(app, workspace_idle(host))
    getattr(writer, f"open_{child_kind}_window")()
    child = getattr(writer, f"{child_kind}_window")
    assert child.isVisible()
    if child_kind == "filter":
        child.expression_input.setText("MEAS > 1")
        assert child._is_dirty()
    else:
        # Export opens Grouping with a background load; its controls are enabled once loaded.
        wait_until(app, lambda: not child.is_loading_grouping())
        child.default_group = "RETAINED GROUP"
        assert child._is_grouping_dirty()
    target, name = ((ReportRepository, "import_report_if_absent") if stage == "import"
                    else (ParsePreflightService, "scan_source"))
    original = getattr(target, name)
    entered, release = Event(), Event()
    observations = []

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    def confirm(*_args):
        (host.parse_button if stage == "import" else host.scan_button).click()
        observations.append((host.can_change_workspace(), host.preflight_thread, host.parse_thread))
        return QMessageBox.StandardButton.Yes if discard else QMessageBox.StandardButton.No

    monkeypatch.setattr(target, name, gated)
    monkeypatch.setattr(QMessageBox, "question", confirm)
    selected = host.report_planner.model.selected_ids
    snapshot = window.workspace_context.snapshot
    notice = (window.workspace_notice_label.text(), window.workspace_notice_label.isVisible())
    try:
        accepted = writer._update_database_context(str(database))
        assert observations == [(True, None, None)]
        assert not entered.is_set()
        assert host.report_planner.model.selected_ids == selected
        assert window.workspace_context.snapshot is snapshot
        assert accepted is discard
        assert not writer.database_context_transition_active
        assert (window.workspace_notice_label.text(), window.workspace_notice_label.isVisible()) == notice
        assert window.statusBar().currentMessage() == "Report start was blocked during Export database selection."
        if discard:
            assert writer.db_file == str(database)
            assert getattr(writer, f"{child_kind}_window") is None
            writer.close()
        else:
            assert writer.db_file == str(previous)
            assert getattr(writer, f"{child_kind}_window") is child and child.isVisible()
            if child_kind == "filter":
                assert child.expression_input.text() == "MEAS > 1" and child._is_dirty()
            else:
                assert child.default_group == "RETAINED GROUP" and child._is_grouping_dirty()
        assert window._report_start_allowed()
        release.set()
        (host.parse_button if stage == "import" else host.scan_button).click()
        try:
            wait_until(app, workspace_idle(host))
        except AssertionError as error:
            worker = host.parse_thread if stage == "import" else host.preflight_thread
            raise AssertionError(
                "report_worker_terminal_timeout: "
                f"stage={stage} target_entered={entered.is_set()} "
                f"worker_present={worker is not None} "
                f"worker_running={worker.isRunning() if worker is not None else False} "
                f"parse_error={bool(host.parse_error_message)} "
                f"cancelled={host.parsing_canceled}"
            ) from error
        if stage == "review":
            host.parse_button.click()
            wait_until(app, workspace_idle(host))
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
    finally:
        active_failure = sys.exc_info()[0] is not None
        release.set()
        try:
            wait_until(app, workspace_idle(host))
        except AssertionError:
            if not active_failure:
                raise
        finally:
            monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
            if not sip.isdeleted(writer):
                writer.close()


def test_enrichment_on_another_database_serializes_real_report_import(app, window, reports, monkeypatch):
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
        assert host.preflight_thread is None
        assert not window._report_start_allowed()
        assert worker.isRunning() and worker.db_file == str(other)
        release.set()
        wait_until(app, lambda: window.metadata_enrichment_thread is None)
        host.scan_button.click()
        wait_until(app, workspace_idle(host))
        assert host.report_planner.model.counts["ready"] == 5
        host.parse_button.click()
        wait_until(app, workspace_idle(host))
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
        assert not worker.isRunning()
    finally:
        release.set()
        wait_until(app, lambda: window.metadata_enrichment_thread is None)
        assert worker.wait(20000)
        worker.deleteLater()


def _install_pdf_probe_for_test(monkeypatch, reports):
    """Hold real QThreads at open_report without entering PyMuPDF concurrently."""
    from metroliza.parsing.cmm_report_parser import CMMReportParser
    from metroliza.parsing.metadata_enrichment_thread import MetadataEnrichmentThread
    from tests.metadata_review_fakes import make_selection

    entered = {owner: Event() for owner in ("review", "enrichment")}
    release = {owner: Event() for owner in entered}
    active, overlaps = set(), []
    lock = Lock()

    def open_report(parser):
        owner = getattr(parser, "probe_owner", "review")
        with lock:
            if active:
                overlaps.append((owner, tuple(active)))
            active.add(owner)
        entered[owner].set()
        try:
            if not release[owner].wait(20):
                overlaps.append((owner, "probe timeout"))
        finally:
            with lock:
                active.discard(owner)

    def enrich(worker):
        parser = CMMReportParser(str(next(reports[0].glob("*.pdf"))), worker.db_file)
        parser.probe_owner = "enrichment"
        parser.open_report()

    monkeypatch.setattr(CMMReportParser, "open_report", open_report)
    monkeypatch.setattr(CMMReportParser, "extract_metadata", lambda _: make_selection({"reference": "SYNTHETIC"}))
    monkeypatch.setattr(MetadataEnrichmentThread, "run", enrich)
    return SimpleNamespace(entered=entered, release=release, overlaps=overlaps)


def _release_pdf_probe(app, window, probe):
    for gate in probe.release.values():
        gate.set()
    wait_until(app, lambda: not window.reports_workspace._metadata_workers_running())
    wait_until(app, lambda: window.metadata_enrichment_thread is None)


def _request_review_read(host, mode, review):
    if mode == "light":
        host.on_preflight_completed(review)  # automatic fast read after Review
    else:
        host.start_metadata_ocr()  # the planner's Read with OCR action
    return host.metadata_thread is not None


@pytest.mark.parametrize("mode", ["light", "complete"])
@pytest.mark.parametrize("retired", [False, True])
def test_shell_enrichment_waits_for_review_pdf_work(app, window, reports, monkeypatch, mode, retired):
    host, _source, _database = prepare_review(app, window, reports)
    review = host._preflight_result
    # Install only after preflight: its real PDF inspection is already complete.
    probe = _install_pdf_probe_for_test(monkeypatch, reports)
    try:
        monkeypatch.setattr(host, "_ocr_unavailable_reason", lambda: "")
        assert _request_review_read(host, mode, review)
        wait_until(app, probe.entered["review"].is_set)
        if retired:
            host._invalidate_preflight()
            assert host.metadata_thread is None and host._metadata_workers_running()
        window.launch_metadata_enrichment()
        assert window.metadata_enrichment_thread is None
        assert not window.enrich_metadata_action.isEnabled()
    finally:
        _release_pdf_probe(app, window, probe)
    window.launch_metadata_enrichment()
    wait_until(app, probe.entered["enrichment"].is_set)
    wait_until(app, lambda: window.metadata_enrichment_thread is None)
    assert not probe.overlaps


@pytest.mark.parametrize("mode", ["light", "complete"])
def test_shell_review_waits_for_enrichment_pdf_work(app, window, reports, monkeypatch, mode):
    host, _source, database = prepare_review(app, window, reports)
    review = host._preflight_result
    probe = _install_pdf_probe_for_test(monkeypatch, reports)
    try:
        monkeypatch.setattr(host, "_ocr_unavailable_reason", lambda: "")
        # Enrichment keeps running even after the selected database changes.
        window.launch_metadata_enrichment()
        wait_until(app, probe.entered["enrichment"].is_set)
        assert window.set_db_file(str(database.with_name("another.sqlite3")))
        review = replace(review, database_path=host.db_file)
        window.stop_metadata_enrichment()
        window.metadata_enrichment_thread.enrichment_finished.emit()
        assert not window.enrich_metadata_action.isEnabled()
        # An accepted review completion must also use the shell admission guard.
        host.on_preflight_completed(review)
        assert not _request_review_read(host, mode, review)
        assert host.metadata_thread is None
    finally:
        _release_pdf_probe(app, window, probe)
    assert _request_review_read(host, mode, review)
    wait_until(app, probe.entered["review"].is_set)
    wait_until(app, lambda: not host._metadata_workers_running())
    assert not probe.overlaps


def test_tools_shortcuts_open_named_workflows(window, monkeypatch):
    from metroliza.ui import industrial_analytics_dialog, industrial_data_dialog, parser_plugin_wizard

    calls = []
    class Tool(QDialog):
        def __init__(self, *_args, **_kwargs):
            super().__init__(window)
            calls.append(self)
        def exec(self):
            calls.append("csv")
            return 0
    for module, name in ((industrial_analytics_dialog, "IndustrialAnalyticsDialog"),
                         (industrial_data_dialog, "IndustrialDataDialog"),
                         (parser_plugin_wizard, "ParserPluginWizardDialog")):
        monkeypatch.setattr(module, name, Tool)
    window.csv_summary_action.trigger()
    assert "csv" not in calls
    assert window.window_coordinator.get("csv_summary").isVisible()
    for action, key in ((window.industrial_data_action, "industrial_data"),
                        (window.parser_profiles_action, "parser_profiles")):
        action.trigger()
        opened = window.window_coordinator.get(key)
        assert opened is not None and opened.isVisible()
        action.trigger()
        assert window.window_coordinator.get(key) is opened
        opened.close()
    calls.clear()
    monkeypatch.setattr(window, "launch_realtime_industrial_monitoring_dialog", lambda: calls.append("realtime"))
    window.realtime_monitoring_action.trigger()
    assert calls == ["realtime"]
    assert window.navigation_combo.findData("csv_summary") >= 0
    assert window.navigation_combo.findText("CSV Analytics") == -1


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


def test_file_menu_recent_acceptance_guards_and_clear(window, tmp_path, monkeypatch):
    menus = [action.text() for action in window.menuBar().actions()]
    assert menus == ["&File", "&Tools", "&View", "&Help"]
    assert [action.text() for action in window.file_menu.actions()] == [
        "Open database…", "Choose report folder…", "Recent databases", "Recent report folders",
        "Clear recent lists", "", "Exit",
    ]
    database = tmp_path / "accepted.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE parsed_reports (id INTEGER)")
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("metroliza.ui.main_window.QFileDialog.getOpenFileName", lambda *_: (str(database), ""))
    window.open_database_action.trigger()
    assert window.db_file == str(database)
    assert window.recent_locations.paths("databases") == [str(database)]
    assert window.recent_database_menu.actions()[0].toolTip() == str(database)
    assert window.recent_database_menu.actions()[0].statusTip() == str(database)
    assert window.recent_database_menu.actions()[0].text() == database.name
    host = window.reports_workspace
    monkeypatch.setattr(host, "can_change_workspace", lambda: False)
    window.choose_report_folder_action.trigger()
    assert window.directory is None
    assert window.recent_locations.paths("folders") == []
    monkeypatch.setattr(host, "can_change_workspace", lambda: True)
    monkeypatch.setattr("metroliza.ui.main_window.QFileDialog.getExistingDirectory", lambda *_: str(tmp_path))
    window.choose_report_folder_action.trigger()
    assert window.recent_locations.paths("folders") == [str(tmp_path)]
    database.unlink()
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    window.recent_database_menu.actions()[0].trigger()
    assert "Open database" in messages[-1]
    assert window.recent_locations.paths("databases") == []
    assert not database.exists()
    window.clear_recent_action.trigger()
    assert window.recent_locations.paths("folders") == []


def test_rejected_database_is_not_recorded(window, tmp_path):
    invalid = tmp_path / "invalid.sqlite"
    invalid.write_text("not SQLite")
    assert window.set_db_file(str(invalid)) is False
    assert window.db_file is None
    assert window.recent_locations.paths("databases") == []
    window.industrial_data_dialog = SimpleNamespace(isVisible=lambda: True, update_db_file=lambda _: False)
    assert window.set_db_file(str(tmp_path / "new.db")) is False
    assert window.recent_locations.paths("databases") == []


def test_recent_store_bounded_validated_and_windows_dedup(tmp_path):
    from metroliza.ui.recent_locations import RecentLocations

    settings = QSettings(str(tmp_path / "recent.ini"), QSettings.Format.IniFormat)
    store = RecentLocations(settings, windows=True)
    for index in range(10):
        store.record("databases", f"C:/Reports/{index}.db")
    store.record("databases", "c:/reports/9.DB")
    assert len(store.paths("databases")) == 8
    assert store.paths("databases")[0] == "c:/reports/9.DB"
    assert store.paths("databases")[-1] == "C:/Reports/2.db"
    assert RecentLocations(settings, windows=True).paths("databases") == store.paths("databases")
    for bad in (None, 12, {"path": "/private"}, "relative.db", "https://host/file.db"):
        settings.setValue("metroliza_recent/v1/databases", bad)
        assert store.paths("databases") == []
    settings.setValue("metroliza_recent/v1/databases", ["relative", "C:/valid.db", 42])
    assert store.paths("databases") == ["C:/valid.db"]
    settings.setValue("metroliza_recent/_schema_version", 99)
    assert store.paths("databases") == []


def test_recent_paths_absent_from_incident_export(window, tmp_path):
    import zipfile
    from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus
    from tests.test_diagnostic_store import _incident

    private = tmp_path / "PRIVATE-RECENT-LOCATION"
    private.mkdir()
    assert window.set_directory(str(private))
    assert window.recent_locations.paths("folders") == [str(private)]
    database = private / "private.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE parsed_reports (id INTEGER)")
    assert window.set_db_file(str(database))
    assert window.recent_locations.paths("databases") == [str(database)]
    store = IncidentStore(tmp_path / "diagnostics")
    incident = _incident()
    assert store.publish(incident).status is StoreStatus.SAVED
    bundle = tmp_path / "support.zip"
    assert store.export(incident.report_id, bundle).status is StoreStatus.EXPORTED
    with zipfile.ZipFile(bundle) as archive:
        assert set(archive.namelist()) == {"incident.json", "manifest.json", "summary.json"}
        for member in archive.namelist():
            assert str(private).encode() not in archive.read(member)
            assert b"PRIVATE-RECENT-LOCATION" not in archive.read(member)


@pytest.mark.parametrize("table", ["parsed_reports", "REPORTS"])
def test_home_paths_and_export_readiness(window, tmp_path, monkeypatch, table):
    from PyQt6.QtWidgets import QLineEdit

    assert isinstance(window.source_path_field, QLineEdit)
    assert window.source_path_field.isReadOnly() and window.database_path_field.isReadOnly()
    menu = window.source_path_field.createStandardContextMenu()
    assert not menu.actions()[1].isEnabled()
    menu.deleteLater()
    assert window.set_directory(str(tmp_path))
    menu = window.source_path_field.createStandardContextMenu()
    assert menu.actions()[1].isEnabled()
    assert window.source_path_field.toolTip() == str(tmp_path)
    menu.actions()[1].trigger()
    menu.deleteLater()
    assert QApplication.clipboard().text() == str(tmp_path)
    assert window.set_db_file(str(tmp_path / "not-created.db"))
    assert plain_text(window.home_next_action.text()) != "Export Workbook [Ctrl+E]"
    assert str(tmp_path / "not-created.db") not in window.recent_locations.paths("databases")
    database = tmp_path / "reports.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(f"CREATE TABLE {table} (id INTEGER)")
        connection.commit()
        assert window.set_db_file(str(database))
        assert plain_text(window.home_next_action.text()) != "Export Workbook [Ctrl+E]"
        connection.execute(f"INSERT INTO {table} VALUES (1)")
        connection.commit()
    assert window.set_db_file(str(database))
    assert plain_text(window.home_next_action.text()) == "Export Workbook [Ctrl+E]"
    assert window.home_next_action.property("buttonRole") == "primary"
    assert window.home_review_action.property("buttonRole") == "secondary"
    assert not window.home_review_action.isHidden()
    calls = []
    monkeypatch.setattr(window, "launch_export_dialog", lambda: calls.append("export"))
    window.home_next_action.click()
    assert calls == ["export"]
    host = window.reports_workspace
    assert window.export_button.property("buttonRole") == "primary"
    assert host.scan_button.property("buttonRole") == "secondary"
    assert window.set_db_file(str(tmp_path / "another-empty.db"))
    assert plain_text(window.home_next_action.text()) != "Export Workbook [Ctrl+E]"
    assert window.export_button.property("buttonRole") == "secondary"
    assert host.scan_button.property("buttonRole") == "primary"


def test_import_success_promotes_export_and_green_status(app, window, reports):
    host, _, _ = prepare_review(app, window, reports)
    assert plain_text(window.home_next_action.text()) != "Export Workbook [Ctrl+E]"
    host.parse_button.click()
    wait_until(app, workspace_idle(host))
    assert "Import successful" in host.report_planner.outcome.toPlainText()
    assert plain_text(window.home_next_action.text()) == "Export Workbook [Ctrl+E]"
    assert window.recent_locations.paths("databases")[0] == window.db_file
    assert window.export_button.property("buttonRole") == "primary"
    assert host.scan_button.property("buttonRole") == "secondary"
    assert host.readiness_label.property("statusVariant") == "success"


@pytest.mark.parametrize("kind", ["databases", "folders"])
def test_recent_change_respects_report_draft(app, window, reports, monkeypatch, tmp_path, kind):
    host, _, database = prepare_review(app, window, reports)
    row = next(iter(host.report_planner.model.metadata_rows.values()))
    row.cells["reference"].user_set = True
    row.cells["reference"].user_value = "unsaved correction"
    target = tmp_path if kind == "folders" else database.with_name("other.db")
    if kind == "databases":
        with closing(sqlite3.connect(target)) as connection:
            connection.execute("CREATE TABLE parsed_reports (id INTEGER)")
    snapshot = window.workspace_context.snapshot
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.No)
    window._open_recent_location(kind, str(target))
    assert window.workspace_context.snapshot is snapshot
    assert str(target) not in window.recent_locations.paths(kind)
    assert row.cells["reference"].user_value == "unsaved correction"


@pytest.mark.parametrize("warning", [True, False])
def test_import_completion_variant_requires_per_report_evidence(window, monkeypatch, warning):
    host = window.reports_workspace
    monkeypatch.setattr("metroliza.ui.parsing_dialog._build_parse_completion_summary",
                        lambda *_args, **_kwargs: ("warning" if warning else "info", "Outcome", "Details"))
    host.parse_thread = SimpleNamespace(last_parse_result=SimpleNamespace(imported_files=1),
                                        last_enrichment_result=None)
    host.parse_error_message = None
    host.parsing_canceled = False
    host._pending_modeless_metadata_enrichment = False
    host.on_parse_finished()
    host.parse_thread = None
    host._sync_readiness_state()
    # Aggregate-only evidence, with no reviewed occurrence receipts, proves no row succeeded.
    assert host.import_succeeded is False
    assert host.readiness_label.property("statusVariant") == "warning"
    # A later review run must also keep the old outcome from turning green.
    monkeypatch.setattr(host, "_defer_until_metadata_idle", lambda *_args, **_kwargs: True)
    host.scan_reports()
    host._sync_readiness_state()
    assert host.import_succeeded is False
    assert host.readiness_label.property("statusVariant") == "warning"


def test_recent_single_entry_survives_reload_from_ini(tmp_path):
    from metroliza.ui.recent_locations import RecentLocations

    path = str(tmp_path / "recent.ini")
    RecentLocations(QSettings(path, QSettings.Format.IniFormat), windows=False).record("databases", "/data/a.db")
    # A fresh QSettings reads a one-item list back from INI as a plain string.
    reloaded = RecentLocations(QSettings(path, QSettings.Format.IniFormat), windows=False)
    assert reloaded.paths("databases") == ["/data/a.db"]


def test_database_inspection_uses_plain_path_and_keeps_busy_database(window, tmp_path, monkeypatch):
    database = tmp_path / "reports.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE parsed_reports (id INTEGER)")
        connection.execute("INSERT INTO parsed_reports VALUES (1)")
        connection.commit()
    warnings, calls = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    from metroliza.reports.db import sqlite_query_only_connection_scope

    real_scope = sqlite_query_only_connection_scope

    def recording_scope(*args, **kwargs):
        calls.append((args, kwargs))
        return real_scope(*args, **kwargs)

    monkeypatch.setattr("metroliza.ui.main_window.sqlite_query_only_connection_scope", recording_scope)
    assert window.set_db_file(str(database))
    # No file: URI (SQLite rejects URI authorities such as UNC hosts).
    assert calls and calls[0] == ((str(database),), {"plain_path": True, "timeout_s": 0.1})
    assert plain_text(window.home_next_action.text()) == "Export Workbook [Ctrl+E]"

    monkeypatch.setattr("metroliza.ui.main_window.sqlite_query_only_connection_scope", real_scope)
    other = tmp_path / "busy.db"
    other.write_bytes(database.read_bytes())
    # Busy/locked (another process writing): not export-ready, but not rejected.
    def busy_scope(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("metroliza.ui.main_window.sqlite_query_only_connection_scope", busy_scope)
    assert window._inspect_database(str(other)) is False
    monkeypatch.setattr("metroliza.ui.main_window.sqlite_query_only_connection_scope", real_scope)
    assert warnings == []
    assert window._inspect_database(str(other)) is True

    broken = tmp_path / "not-sqlite.db"
    broken.write_bytes(b"not a database" * 100)
    assert window.set_db_file(str(broken)) is False
    assert window.db_file == str(database) and len(warnings) == 1


# Wave 1 P5a keyboard and shared path-menu regressions.
def key(app, widget, sequence):
    widget.window().activateWindow()
    widget.setFocus()
    app.processEvents()
    combination = QKeySequence(sequence)[0]
    QTest.keyClick(widget, combination.key(), combination.keyboardModifiers())
    app.processEvents()


def action_for(window, sequence):
    matches = [action for action in window.findChildren(QAction)
               if action.shortcut().toString() == sequence]
    assert len(matches) == 1, (sequence, matches)
    return matches[0]


def test_global_navigation_and_menu_shortcuts(app, window, monkeypatch):
    assert window._reports_workspace is None
    for name in ("launch_csv_summary_dialog", "launch_industrial_data_dialog",
                 "launch_realtime_industrial_monitoring_dialog", "launch_parser_plugin_wizard"):
        monkeypatch.setattr(window, name, lambda: None)
    for index in range(5):
        key(app, window.navigation_list, f"Ctrl+{index + 1}")
        assert window.navigation_list.currentRow() == index
    for width in (640, 1200):
        window.resize(width, 800)
        key(app, window.navigation_combo, "Ctrl+1")
        assert window.navigation_combo.currentIndex() == 0
    page_action = action_for(window, "Ctrl+2")
    page_action.setEnabled(False)
    key(app, window.navigation_list, "Ctrl+2")
    page_action.trigger()
    assert window.navigation_list.currentRow() == 0
    page_action.setEnabled(True)
    calls = []
    monkeypatch.setattr("metroliza.ui.main_window.QFileDialog.getOpenFileName",
                        lambda *_: (calls.append("open") or "", ""))
    key(app, window.navigation_list, "Ctrl+O")
    assert calls == ["open"]
    assert window.open_database_action.shortcut().toString() == "Ctrl+D"
    window.open_database_action.setEnabled(False)
    key(app, window.navigation_list, "Ctrl+O")
    window.open_database_action.trigger()
    assert calls == ["open"]


@pytest.mark.parametrize("sequence,button", [("Ctrl+R", "scan_button"), ("Ctrl+S", "parse_button")])
def test_reports_shortcut_uses_enabled_button(app, window, monkeypatch, sequence, button):
    host = window.reports_workspace
    control = getattr(host, button)
    control.clicked.disconnect()
    calls = []
    control.clicked.connect(lambda: calls.append(button))
    for enabled in (False, True, False):
        control.setEnabled(enabled)
        window._sync_workflow_next_step()
        action = action_for(window, sequence)
        assert action.isEnabled() == enabled
        window._show_workspace_page("home")
        before = len(calls)
        key(app, window.home_next_action, sequence)
        action.trigger()
        assert len(calls) == before + (2 if enabled else 0)
        if enabled:
            assert window.navigation_combo.currentData() == "reports"
        assert sequence in control.toolTip()


def test_review_shortcut_creates_lazy_workspace(app, window, monkeypatch, tmp_path):
    from metroliza.ui.parsing_dialog import ReportsWorkspace

    calls = []
    monkeypatch.setattr(ReportsWorkspace, "scan_reports", lambda self: calls.append(self))
    window.set_directory(str(tmp_path))
    window.set_db_file(str(tmp_path / "new.db"))
    assert window._reports_workspace is None
    key(app, window.home_next_action, "Ctrl+R")
    assert calls == [window._reports_workspace]
    assert window.navigation_combo.currentData() == "reports"


def test_export_shortcut_follows_readiness(app, window, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(window, "launch_export_dialog", lambda: calls.append("export"))
    # Use the existing button connection, with its heavy workflow replaced.
    window.export_button.clicked.disconnect()
    window.export_button.clicked.connect(window.launch_export_dialog)
    for enabled in (False, True, False):
        window.db_file = str(tmp_path / "test.db") if enabled else None
        window._sync_workflow_next_step()
        action = action_for(window, "Ctrl+E")
        assert action.isEnabled() == enabled
        before = len(calls)
        key(app, window.home_next_action, "Ctrl+E")
        action.trigger()
        assert len(calls) == before + (2 if enabled else 0)
    assert "Ctrl+E" in window.export_button.toolTip()


def test_f1_main_including_embedded_reports(app, window, monkeypatch):
    opened = []
    # Patch the help_menu module object MainWindow actually uses (stub-heavy suites can leave a
    # different copy importable under the same name; a real open_manual would block on a dialog).
    window_help_globals = sys.modules[type(window).__module__].build_help_menu.__globals__
    monkeypatch.setitem(window_help_globals, "open_manual", lambda owner, name: opened.append((owner, name)))
    host = window.reports_workspace
    for control in (window.home_next_action, host.scan_button):
        window._show_workspace_page("reports" if control is host.scan_button else "home")
        key(app, control, "F1")
    assert opened == [(window, "main_window")] * 2
    action = action_for(window, "F1")
    assert action in window.help_menu.actions()
    action.setEnabled(False)
    key(app, host.scan_button, "F1")
    action.trigger()
    assert opened == [(window, "main_window")] * 2


@pytest.mark.parametrize("manual", help_menu.MANUAL_RELATIVE_PATHS)
@pytest.mark.parametrize("modal", [False, True])
def test_dialog_f1_and_main_shortcut_isolation(app, window, monkeypatch, manual, modal):
    opened, calls = [], []
    monkeypatch.setattr(help_menu, "open_manual", lambda owner, name: opened.append((owner, name)))
    monkeypatch.setattr("metroliza.ui.main_window.QFileDialog.getOpenFileName",
                        lambda *_: (calls.append("open") or "", ""))
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    _, menu = help_menu.attach_help_menu_to_layout(layout, dialog, [("Window manual", manual),
                                                                 ("Other manual", "main_window")])
    button = QPushButton("Focus", dialog)
    layout.addWidget(button)
    dialog.setModal(modal)
    dialog.show()
    try:
        for sequence in ("Ctrl+2", "Ctrl+O", "Ctrl+R", "Ctrl+I", "Ctrl+E"):
            key(app, button, sequence)
        assert window.navigation_list.currentRow() == 0 and calls == []
        key(app, button, "F1")
        assert opened == [(dialog, manual)]
        assert menu.actions()[0].shortcut().toString() == "F1"
        assert menu.actions()[1].shortcut().isEmpty()
        menu.actions()[0].setEnabled(False)
        key(app, button, "F1")
        menu.actions()[0].trigger()
        assert opened == [(dialog, manual)]
    finally:
        dialog.close()
        dialog.deleteLater()


def test_main_shortcut_and_mnemonic_inventory(window):
    window.reports_workspace
    sequences = [shortcut.toString() for action in window.findChildren(QAction)
                 for shortcut in action.shortcuts() if not shortcut.isEmpty()]
    sequences.extend(shortcut.key().toString() for shortcut in window.findChildren(QShortcut))
    assert len(sequences) == len(set(sequences))
    expected = {"Ctrl+O", "Ctrl+D", "Ctrl+Shift+D", "Ctrl+R", "Ctrl+S", "Ctrl+I", "Ctrl+E", "Ctrl+F", "Ctrl+Shift+F", "Ctrl+Shift+T", "F1"}
    expected.update(f"Ctrl+{index + 1}" for index in range(min(5, window.navigation_list.count())))
    assert set(sequences) == expected
    reserved = {f"Ctrl+{letter}" for letter in "CVXZY A".replace(" ", "")}
    reserved.update(("Tab", "Return", "Enter", "Space", "Delete", "Backspace", "Left", "Right",
                     "Up", "Down", "Home", "End", "PgUp", "PgDown"))
    assert not set(sequences) & reserved
    assert all(action.shortcutContext() == Qt.ShortcutContext.WindowShortcut
               for action in window.findChildren(QAction) if not action.shortcut().isEmpty())
    controls = [window.home_next_action, window.home_review_action, window.home_cancel_report,
                window.modifydb_button, window.map_characteristics_button, window.export_button,
                window.reports_workspace.scan_button, window.reports_workspace.parse_button]
    labels = [action.text() for action in window.menuBar().actions()] + [button.text() for button in controls]
    mnemonics = [text[text.index("&") + 1].lower() for text in labels if "&" in text]
    assert len(mnemonics) == len(labels) == len(set(mnemonics))
    button_keys = [button.shortcut().toString() for button in window.findChildren(QPushButton)
                   if not button.shortcut().isEmpty()]
    assert len(button_keys) == len(set(button_keys))
    assert all("&" not in button.accessibleName() for button in controls)


def test_definitions_match_manual_and_actions(window):
    from metroliza.ui.shortcuts import MAIN_SHORTCUTS, PAGE_SHORTCUTS

    manual = Path("docs/user_manual/main_window.md").read_text(encoding="utf-8")
    for sequence, description in MAIN_SHORTCUTS.values():
        assert f"| {sequence} | {description} |" in manual
        action_for(window, sequence)
    for sequence in PAGE_SHORTCUTS[:window.navigation_list.count()]:
        assert sequence in manual
        action_for(window, sequence)


@pytest.mark.parametrize("name", ["source_path_field", "database_path_field"])
def test_home_shared_context_menu(window, tmp_path, name):
    field = getattr(window, name)
    assert field.contextMenuPolicy() == Qt.ContextMenuPolicy.DefaultContextMenu
    assert field.actions() == []
    menu = field.createStandardContextMenu()
    try:
        assert not menu.actions()[1].isEnabled()
    finally:
        menu.deleteLater()
    value = str(tmp_path) if name == "source_path_field" else str(tmp_path / "new.db")
    (window.set_directory if name == "source_path_field" else window.set_db_file)(value)
    menu = field.createStandardContextMenu()
    try:
        menu.actions()[1].trigger()
        assert QApplication.clipboard().text() == value
        assert field.text() == value
        assert field.toolTip() == value
    finally:
        menu.deleteLater()


def test_set_mnemonic_tolerates_missing_letter_and_literal_ampersand(app):
    from PyQt6.QtWidgets import QPushButton
    from metroliza.ui.shortcuts import plain_text, set_mnemonic

    button = QPushButton("Review reports")
    set_mnemonic(button, "z")  # letter absent: no mnemonic, no exception
    assert button.text() == "Review reports"
    button.setText("R&&D export")
    set_mnemonic(button, "e")
    assert button.text() == "R&&D &export"
    assert plain_text(button.text()) == "R&D export"


def test_csv_session_is_nonmodal_reused_and_independent(app, window, tmp_path):
    """The real CSV owner survives all shell entry points and report-context changes."""
    from metroliza.ui.industrial_analytics_dialog import SOURCE_TABULAR_FILE

    csv = window.launch_csv_summary_dialog()
    assert csv is window.csv_summary_dialog
    assert csv.source_kind == SOURCE_TABULAR_FILE
    assert csv.windowModality() == Qt.WindowModality.NonModal
    assert not csv.isModal()
    csv.output_dashboard_file = str(tmp_path / "retained.html")
    csv.output_workbook_file = str(tmp_path / "retained.xlsx")
    csv.metric_limits = {"synthetic": (1, 2)}
    window._show_workspace_page("home")
    window.csv_summary_action.trigger()
    assert window.csv_summary_dialog is csv
    window._show_workspace_page("reports")
    host = window.reports_workspace
    assert window.set_db_file(str(tmp_path / "report.db"))
    assert host.db_file == str(tmp_path / "report.db")
    assert csv.db_file == ""
    assert csv.metric_limits == {"synthetic": (1, 2)}
    assert csv.output_dashboard_file == str(tmp_path / "retained.html")
    window._show_workspace_page("home")
    key(app, window.home_next_action, "Ctrl+3")
    assert window.csv_summary_dialog is csv
    csv.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert window.csv_summary_dialog is None
    reopened = window.launch_csv_summary_dialog()
    assert reopened is not csv
    reopened.close()


@pytest.mark.parametrize("owner", ["tabular_load_thread", "analytics_thread", "scope"])
def test_csv_active_owner_blocks_child_and_main_close(app, window, owner):
    csv = window.launch_csv_summary_dialog()
    if owner == "scope":
        csv._scope_query_running = True
    else:
        setattr(csv, owner, SimpleNamespace(isRunning=lambda: True))
    try:
        assert csv.close() is False
        assert window.close() is False
        assert window.csv_summary_dialog is csv
        assert window.window_coordinator.get("csv_summary") is csv
        assert csv.isVisible() and window.isVisible()
        window.csv_summary_action.trigger()
        assert window.csv_summary_dialog is csv
    finally:
        if owner == "scope":
            csv._scope_query_running = False
        else:
            setattr(csv, owner, None)
        csv.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("stage", ["empty", "ready", "reviewed", "imported"])
def test_reports_composed_tab_order_real_keys(app, window, reports, stage):
    """Late insertion must connect navigation to source, rather than downstream actions."""
    window._show_workspace_page("reports")
    host = window.reports_workspace
    if stage in ("reviewed", "imported"):
        host, _source, _database = prepare_review(app, window, reports)
    elif stage == "ready":
        source, database = reports
        window.set_directory(str(source))
        window.set_db_file(str(database))
    if stage == "imported":
        host.parse_button.click()
        wait_until(app, workspace_idle(host))
        assert host.import_succeeded
    for width in (1200, 800):
        window.resize(width, 800)
        app.processEvents()
        navigation = window.navigation_list if window.navigation_list.isVisible() else window.navigation_combo
        window.activateWindow()
        # Process the worker progress window's queued activation/close events
        # before placing keyboard focus, as a user's subsequent click would.
        wait_until(app, window.isActiveWindow)
        navigation.setFocus()
        assert navigation.hasFocus()
        expected = (host.directory_text_label, host.directory_button, host.archive_button,
                    host.database_text_label, host.database_button, host.metadata_mode_combo)
        expected = tuple(control for control in expected if control.isEnabled() and control.isVisibleTo(window))
        for control in expected:
            QTest.keyClick(app.focusWidget(), Qt.Key.Key_Tab)
            assert app.focusWidget() is control, (stage, width, control.accessibleName(), app.focusWidget().accessibleName())
        for control in reversed((navigation,) + expected[:-1]):
            QTest.keyClick(app.focusWidget(), Qt.Key.Key_Backtab)
            assert app.focusWidget() is control
        window._show_workspace_page("home")
        window._show_workspace_page("reports")


def test_shell_search_and_editing_keep_active_context(app, window):
    host = window.reports_workspace
    window._show_workspace_page("reports")
    host.report_planner.search.setText("synthetic")
    key(app, host.report_planner.search, "Ctrl+A")
    assert host.report_planner.search.selectedText() == "synthetic"
    key(app, host.directory_button, "Ctrl+F")
    assert host.report_planner.search.hasFocus()
    window._show_workspace_page("home")
    key(app, window.home_next_action, "Ctrl+F")
    assert not host.report_planner.search.hasFocus()
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    button = QPushButton("Keep child focus", dialog)
    layout.addWidget(button)
    dialog.show()
    try:
        key(app, button, "Ctrl+3")
        key(app, button, "Ctrl+F")
        assert window.csv_summary_dialog is None
        assert not host.report_planner.search.hasFocus()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_home_module_choices_scroll_in_compact_window(app, window):
    from PyQt6.QtCore import QSize

    window._show_workspace_page("home")
    window.resize(720, 480)
    app.processEvents()
    assert window.size() == QSize(720, 480)
    for page in ("reports", "csv_summary", "industrial_data", "realtime_monitor", "parser_profiles", "tools"):
        button = window._module_launch_buttons[page][0][0]
        window.home_page.ensureWidgetVisible(button)
        app.processEvents()
        assert button.isVisibleTo(window)
        assert "[Ctrl+" in button.text()
        assert window.size() == QSize(720, 480)
