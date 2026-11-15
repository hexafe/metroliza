"""Source-window integration: persistent owner and unchanged numeric navigation."""
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
        assert window.db_file == original_context
        assert WORKSPACE_SHORTCUTS["home"] == "Ctrl+1"
        assert WORKSPACE_SHORTCUTS["reports"] == "Ctrl+2"
        assert window.navigation_combo.findData("receptury") >= 0
        assert app is QApplication.instance()
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
