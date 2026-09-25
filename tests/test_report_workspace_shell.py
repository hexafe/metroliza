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
from PyQt6.QtGui import QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

from metroliza.ui.main_window import MainWindow
from metroliza.ui.ui_preferences import UiPreferences
from metroliza.ui import ui_theme_tokens
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
        # Selecting the already active database must not rebind a separate cache either.
        assert window.set_db_file(str(database)) is False
        assert industrial.cache_target is temporary
        industrial.select_database_file()
        assert industrial.cache_target is temporary
        assert industrial.db_file == temporary.cache_db_file and industrial.report_db_file is None
        assert window.workspace_context.snapshot is snapshot
        assert len(repository.list_source_profiles(include_disabled=True)) == 1
        release.set()
        wait_until(app, host.can_change_workspace)
        if stage == "review":
            host.parse_button.click()
            wait_until(app, host.can_change_workspace)
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
        industrial.select_database_file()
        assert industrial.db_file == str(database) and industrial.report_db_file == str(database)
    finally:
        release.set()
        wait_until(app, host.can_change_workspace)
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
        wait_until(app, host.can_change_workspace)
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
        wait_until(app, host.can_change_workspace)
        if stage == "review":
            host.parse_button.click()
            wait_until(app, host.can_change_workspace)
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
        wait_until(app, host.can_change_workspace)
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
        wait_until(app, host.can_change_workspace)
    getattr(writer, f"open_{child_kind}_window")()
    child = getattr(writer, f"{child_kind}_window")
    assert child.isVisible()
    if child_kind == "filter":
        child.expression_input.setText("MEAS > 1")
        assert child._is_dirty()
    else:
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
        wait_until(app, host.can_change_workspace)
        if stage == "review":
            host.parse_button.click()
            wait_until(app, host.can_change_workspace)
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM source_file_locations").fetchone()[0] == 5
    finally:
        release.set()
        wait_until(app, host.can_change_workspace)
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
        if not sip.isdeleted(writer):
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
