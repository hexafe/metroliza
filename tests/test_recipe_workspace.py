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
