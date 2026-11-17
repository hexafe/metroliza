"""Source-window integration: persistent owner and unchanged numeric navigation."""
import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from metroliza.ui.main_window import MainWindow
from metroliza.ui.shortcuts import WORKSPACE_SHORTCUTS
from metroliza.ui.ui_preferences import UiPreferences


def test_home_and_catalog_share_one_controller_and_keep_context(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    preferences = UiPreferences(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    window = MainWindow("test", None, ui_preferences=preferences)
    try:
        original_context = window.db_file
        window._launch_recipe("reports_excel_main")
        workspace = window.recipe_workspace
        controller = workspace.controller
        assert controller.definition.recipe_id == "reports_excel_main"
        window._show_workspace_page("home")
        window._launch_recipe("reports_dashboard_html")
        assert window.recipe_workspace is workspace
        assert workspace.controller is controller
        assert controller.definition.recipe_id == "reports_dashboard_html"
        assert any(entry.definition.recipe_id == "reports_append_excel_main" for entry in workspace.entries())
        assert window.db_file == original_context
        assert WORKSPACE_SHORTCUTS["home"] == "Ctrl+1"
        assert WORKSPACE_SHORTCUTS["reports"] == "Ctrl+2"
        assert window.navigation_combo.findData("receptury") >= 0
        assert app is QApplication.instance()
    finally:
        window.close()


def test_append_via_qt_controller_owns_reports_and_refreshes_current_database(
        tmp_path, qapplication_session, monkeypatch):
    from PyQt6.QtCore import QEventLoop, QTimer

    from metroliza.recipes.contracts import ParameterKey
    from metroliza.recipes.run_state import RunState
    from metroliza.reports.report_schema import ensure_report_schema
    from tests.test_recipe_real_flows import _write_complete_reports

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    preferences = UiPreferences(QSettings(str(tmp_path / "qt.ini"), QSettings.Format.IniFormat))
    window = MainWindow("test", None, ui_preferences=preferences)
    source = tmp_path / "input"
    output, database = tmp_path / "result.xlsx", tmp_path / "existing.db"
    _write_complete_reports(source)
    ensure_report_schema(str(database))
    try:
        assert window.set_directory(str(source))
        assert window.set_db_file(str(database))
        refreshed = []
        monkeypatch.setattr(window.reports_workspace, "refresh_review_after_append", lambda: refreshed.append(True))
        window._launch_recipe()
        workspace = window.recipe_workspace
        row = next(i for i, entry in enumerate(workspace.entries())
                   if entry.definition.recipe_id == "reports_append_excel_main")
        workspace.library.list.setCurrentRow(row)
        workspace.library.run_button.click()
        controller = workspace.controller
        assert workspace.run_page.fields[ParameterKey.INPUT_FOLDER][0].text() == str(source)
        assert workspace.run_page.fields[ParameterKey.EXISTING_DATABASE][0].text() == str(database)
        assert controller.prepare({ParameterKey.OUTPUT_FILE: str(output)})

        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        controller.idle.connect(loop.quit)

        assert controller.start()
        assert controller.append_in_progress and not window._report_start_allowed()
        timeout.start(15_000)
        loop.exec()
        assert timeout.isActive(), "The native append task did not retire."
        timeout.stop()
        assert controller.last_record.state is RunState.COMPLETED
        assert not controller.busy and output.is_file()
        assert refreshed == [True] and window._report_start_allowed()
    finally:
        window.close()


def test_saved_favorite_editor_refreshes_name_and_launches_latest_binding(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QPushButton
    from metroliza.recipes.builtin_recipes import REPORTS_EXCEL_MAIN, builtin_binding
    from metroliza.recipes.storage import copy_recipe
    from metroliza.recipes.contracts import ParameterKey

    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "state"))
    preferences = UiPreferences(QSettings(str(tmp_path / "favorite-ui.ini"), QSettings.Format.IniFormat))
    window = MainWindow("test", None, ui_preferences=preferences)
    try:
        workspace = window._ensure_recipe_workspace()
        copied = copy_recipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
            str(tmp_path / "input"), str(tmp_path / "first.xlsx")), name="Original favorite")
        first = workspace.store.save(copied.definition, copied.binding, expected_revision=None)
        workspace.library.favorites = {first.definition.recipe_id}
        workspace._favorites(workspace.library.favorites)
        assert workspace.quick.favorite_buttons.itemAt(0).widget().text() == "Original favorite"
        workspace.edit(first)
        editor = workspace._editors[0]
        editor.name.setText("Renamed favorite")
        editor.controls[ParameterKey.OUTPUT_FILE][2].setText(str(tmp_path / "updated.xlsx"))
        next(button for button in editor.findChildren(QPushButton)
             if button.text() == "Save revision").click()
        current = workspace.store.load(first.definition.recipe_id)
        assert current.binding.revision == first.binding.revision + 1
        favorite = workspace.quick.favorite_buttons.itemAt(0).widget()
        assert favorite.text() == "Renamed favorite"
        favorite.click()
        assert workspace.controller.binding == current.binding
        assert workspace.controller.binding.value(ParameterKey.OUTPUT_FILE) == str(tmp_path / "updated.xlsx")
        assert app is QApplication.instance()
    finally:
        window.close()


@pytest.mark.parametrize("namespace", ["base", "generation"])
def test_owned_recipe_vetoes_dangerous_database_rebind_before_inspection_but_allows_safe_context(
        qapplication_session, tmp_path, monkeypatch, namespace):
    from pathlib import Path
    from metroliza.recipes.contracts import ParameterKey
    from metroliza.recipes.run_state import RunState
    from metroliza.reports.report_schema import ensure_report_schema

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "state"))
    preferences = UiPreferences(QSettings(str(tmp_path / "owned-ui.ini"), QSettings.Format.IniFormat))
    window = MainWindow("test", None, ui_preferences=preferences)
    runner = None
    try:
        previous = tmp_path / "previous.db"
        safe = tmp_path / "safe.db"
        ensure_report_schema(str(previous))
        ensure_report_schema(str(safe))
        assert window.set_db_file(str(previous))
        workspace = window._ensure_recipe_workspace()
        controller = workspace.controller
        controller.launch("reports_dashboard_html")
        assert controller.prepare({ParameterKey.INPUT_FOLDER: str(tmp_path / "input"),
                                   ParameterKey.OUTPUT_FILE: str(tmp_path / "result.html")})
        plan, runner = controller.plan, controller.runner
        plan.database_file.write_bytes(b"retained previous database")
        record = runner.start(plan)
        assert record.state is RunState.REQUIRES_DECISION and record.ownership
        controller._returned(record)
        base = plan.assets_dir if namespace == "base" else Path(str(plan.assets_dir) + ".generation-old")
        base.mkdir(parents=True)
        forbidden = base / "active.db"
        ensure_report_schema(str(forbidden))
        untouched = forbidden.read_bytes()
        inspected, recovered = [], []
        original_inspect = window._inspect_database
        def inspect(candidate):
            inspected.append(candidate)
            return original_inspect(candidate)
        monkeypatch.setattr(window, "_inspect_database", inspect)
        monkeypatch.setattr(window, "_recover_abandoned_realtime_staging",
                            lambda candidate: recovered.append(candidate))
        assert window.set_db_file(str(forbidden)) is False
        assert not inspected and not recovered
        assert window.db_file == str(previous)
        assert window.workspace_context.snapshot.database_file == str(previous)
        assert forbidden.read_bytes() == untouched
        assert "active recipe" in window.workspace_notice_label.text()
        window._show_workspace_page("home")
        assert window.navigation_combo.currentData() == "home"
        assert window.set_directory(str(tmp_path / "unrelated-folder"))
        assert controller.busy and runner.plan is plan
        assert window.set_db_file(str(safe)) is True
        assert window.db_file == str(safe) and window.workspace_context.snapshot.database_file == str(safe)
        assert inspected == [str(safe)] and recovered == [str(safe)]
        assert controller.busy and runner.plan is plan
    finally:
        if runner is not None:
            runner.cancel()
        window.close()
