"""Production shell geometry and keyboard operation with the real Qt platform."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from tests.test_report_planner_geometry import _assert_contained, _assert_geometry, _review
from tests.test_report_workspace_shell import app as app, window as window


def _show_review(window, app):
    window.set_directory("/synthetic/reports")
    window.set_db_file("/synthetic/reports.sqlite3")
    host = window.launch_parsing_dialog()
    host.on_preflight_completed(_review())
    window.activateWindow()
    QTest.qWait(5)
    app.processEvents()
    return host


def _assert_shell(window, app, size):
    window.resize(*size)
    app.processEvents()
    assert window.size() == QSize(*size)
    host = window.reports_workspace
    compact = size[0] < 1000
    navigation = window.navigation_combo if compact else window.navigation_list
    assert navigation.isVisible()
    assert (window.navigation_list if compact else window.navigation_combo).isHidden()
    for control in (navigation, host, window.modifydb_button, window.map_characteristics_button, window.export_button):
        _assert_contained(window, control)
    for pane in (None, "details", "outcome"):
        _assert_geometry(host, app, pane=pane)
        assert window.size() == QSize(*size), f"Opening {pane} enlarged the main window"
    planner = host.report_planner
    planner.details_button.setChecked(False)
    planner.outcome_button.setChecked(False)
    app.processEvents()
    ready_row = next(row for row in range(planner.proxy.rowCount())
                     if planner.proxy.data(planner.proxy.index(row, planner.model.LOCATION_COLUMN)) == "nested/ready-a.pdf")
    planner.table.setCurrentIndex(planner.proxy.index(ready_row, planner.model.LOCATION_COLUMN))
    planner.table.setFocus()
    assert planner.table.hasFocus()
    selected = planner.model.selected_ids
    QTest.keyClick(planner.table, Qt.Key.Key_Space)
    assert planner.model.selected_ids != selected
    host.directory_button.setFocus()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is host.archive_button
    # Page transitions preserve the same active table and return focus to Reports.
    for page in ("home", "tools", "reports"):
        window._show_workspace_page(page)
        app.processEvents()
        assert window.size() == QSize(*size)
    assert window.launch_parsing_dialog() is host


@pytest.mark.parametrize("size", ((720, 480), (1280, 800)))
def test_shell_compact_and_large_layout(window, app, size, tmp_path, request):
    available = app.primaryScreen().availableGeometry()
    if size[0] + 40 > available.width() or size[1] + 40 > available.height():
        if sys.platform != "win32":
            assert os.environ.get("REPORT_WORKSPACE_LARGE_INNER") != "1"
            screen = tmp_path / "screen.json"
            screen.write_text(json.dumps({"screens": [{
                "name": "workspace-test", "width": 1600, "height": 1000,
                "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1,
            }]}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
                env=dict(os.environ, REPORT_WORKSPACE_LARGE_INNER="1", QT_QPA_PLATFORM=f"offscreen:configfile={screen}",
                         METROLIZA_EXPECT_QT_PLATFORM="offscreen"),
                capture_output=True, text=True, timeout=45,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "1 passed" in result.stdout
            return
        size = (min(size[0], available.width() - 40), min(size[1], available.height() - 40))
        assert size[0] >= 850 and size[1] >= 600
    _show_review(window, app)
    _assert_shell(window, app, size)


def test_windows_scale_inner_workspace(window, app):
    if sys.platform != "win32" or os.environ.get("REPORT_WORKSPACE_SCALE_INNER") != "1":
        pytest.skip("The body runs only inside the native Windows scale matrix.")
    assert app.platformName().casefold() == "windows"
    screen = app.primaryScreen()
    ratio = screen.devicePixelRatio()
    assert ratio == pytest.approx(float(os.environ["QT_SCALE_FACTOR"]), abs=0.05)
    assert os.environ.get("METROLIZA_EXPECT_WORKSPACE_SCREEN") == "1920x1080"
    assert (round(screen.size().width() * ratio), round(screen.size().height() * ratio)) == (1920, 1080)
    _show_review(window, app)
    _assert_shell(window, app, (720, 480))
    available = screen.availableGeometry()
    # Move the tested frame inside the work area; its size includes native chrome.
    window.move(available.topLeft() + (window.pos() - window.frameGeometry().topLeft()))
    app.processEvents()
    assert available.contains(window.frameGeometry())
    print(f"workspace-geometry dpr={ratio} client={window.size().width()}x{window.size().height()} "
          f"frame={window.frameGeometry().getRect()} available={available.getRect()}")


@pytest.mark.parametrize("scale", ("1", "1.25", "1.5", "2"))
def test_windows_workspace_scale_subprocess(scale):
    if sys.platform != "win32" or os.environ.get("REPORT_WORKSPACE_SCALE_INNER") == "1":
        pytest.skip("Native Windows scaling only.")
    environment = dict(os.environ, REPORT_WORKSPACE_SCALE_INNER="1", QT_SCALE_FACTOR=scale,
                       QT_QPA_PLATFORM="windows", METROLIZA_EXPECT_QT_PLATFORM="windows")
    environment["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-s", __file__, "-k", "windows_scale_inner_workspace"],
        env=environment, capture_output=True, text=True, timeout=45,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout
    assert "workspace-geometry" in completed.stdout
    print(completed.stdout)
