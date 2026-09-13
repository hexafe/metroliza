"""Native-Windows DPI qualification for the industrial workflow dialogs."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")

try:
    from PyQt6.QtCore import QPoint, QRect, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QWidget

    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.ui.industrial_data_dialog import IndustrialDataDialog
    from metroliza.ui.industrial_source_profiles_dialog import IndustrialSourceProfilesDialog
    from metroliza.ui.industrial_sync_dialog import IndustrialSyncDialog
except Exception as exc:  # pragma: no cover - depends on the native Qt runtime.
    QApplication = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

if QApplication is None and os.environ.get("METROLIZA_EXPECT_QT_PLATFORM"):
    raise RuntimeError(
        "A required native Qt platform could not initialize for industrial geometry coverage."
    ) from PYQT_IMPORT_ERROR


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial geometry checks are unavailable: {PYQT_IMPORT_ERROR}",
)


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    expected_platform = os.environ.get("METROLIZA_EXPECT_QT_PLATFORM")
    if expected_platform:
        assert application.platformName().casefold() == expected_platform.casefold()
    if os.environ.get("INDUSTRIAL_GEOMETRY_SCALE_INNER") == "1":
        expected_screen = os.environ.get("METROLIZA_EXPECT_INDUSTRIAL_SCREEN")
        assert expected_screen == "1920x1080", "Native industrial display qualification is required"
        screen = application.primaryScreen()
        ratio = screen.devicePixelRatio()
        physical_size = (round(screen.size().width() * ratio), round(screen.size().height() * ratio))
        assert physical_size == (1920, 1080), f"Required native display unavailable: {physical_size}"
    return application


def _assert_frame_contained(dialog) -> None:
    available = dialog.screen().availableGeometry()
    assert available.contains(dialog.frameGeometry()), (
        f"{type(dialog).__name__} frame {dialog.frameGeometry().getRect()} "
        f"outside {available.getRect()}"
    )


def _assert_visible_control(dialog, control: QWidget) -> None:
    assert control.isVisibleTo(dialog)
    assert control.isEnabled()
    rectangle = QRect(control.mapTo(dialog, QPoint(0, 0)), control.size())
    assert QRect(QPoint(0, 0), dialog.size()).contains(rectangle)


def _assert_scroll_reachable(dialog, scroll, control: QWidget, app) -> None:
    scroll.ensureWidgetVisible(control)
    app.processEvents()
    point = control.mapTo(scroll.viewport(), QPoint(0, 0))
    assert 0 <= point.y()
    assert point.y() + control.height() <= scroll.viewport().height()
    _assert_visible_control(dialog, control)


def _assert_tab_reaches_visible_control(dialog, control: QWidget, app) -> None:
    dialog.activateWindow()
    control.setFocus()
    app.processEvents()
    assert control.hasFocus()
    QTest.keyClick(control, Qt.Key.Key_Tab)
    app.processEvents()
    focused = QApplication.focusWidget()
    assert focused is not None
    assert focused.isVisibleTo(dialog)
    assert focused.isEnabled()


def _source_db(tmp_path: Path) -> str:
    db_path = tmp_path / "industrial.sqlite"
    IndustrialDataRepository(str(db_path)).upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="production_events",
    )
    return str(db_path)


def _show_at_compact_size(dialog, app) -> None:
    dialog.show()
    QTest.qWait(5)
    app.processEvents()
    available = dialog.screen().availableGeometry()
    requested = (
        min(max(760, dialog.minimumWidth()), available.width() - 40),
        min(max(480, dialog.minimumHeight()), available.height() - 40),
    )
    dialog.resize(*requested)
    app.processEvents()
    assert dialog.width() == requested[0]
    assert dialog.height() == requested[1]
    _assert_frame_contained(dialog)


def test_windows_scale_inner_industrial_geometry(app, tmp_path):
    """Inner body invoked by the Windows scale-factor subprocess matrix."""

    if sys.platform != "win32" or os.environ.get("INDUSTRIAL_GEOMETRY_SCALE_INNER") != "1":
        pytest.skip("This test is only executed inside the Windows scale matrix.")
    assert app.platformName().casefold() == "windows"
    actual_ratio = app.primaryScreen().devicePixelRatio()
    assert actual_ratio == pytest.approx(float(os.environ["QT_SCALE_FACTOR"]), abs=0.05)
    db_path = _source_db(tmp_path)
    dialogs = (
        IndustrialDataDialog(db_file=db_path),
        IndustrialSourceProfilesDialog(
            db_file=db_path,
            config_path=tmp_path / "industrial_sources.yaml",
        ),
        IndustrialSyncDialog(db_file=db_path, config_path=tmp_path / "industrial_sources.yaml"),
    )
    try:
        data, profiles, sync = dialogs
        for dialog in dialogs:
            _show_at_compact_size(dialog, app)

        assert data.status_label.height() >= data.status_label.sizeHint().height()
        _assert_scroll_reachable(data, data.content_scroll, data.status_label, app)
        _assert_tab_reaches_visible_control(data, data.sync_button, app)

        assert profiles.status_label.height() >= profiles.status_label.sizeHint().height()
        _assert_scroll_reachable(profiles, profiles.form_scroll, profiles.timestamp_column_edit, app)
        _assert_tab_reaches_visible_control(profiles, profiles.timestamp_column_edit, app)

        first = sync.select_all_sources_button.geometry()
        second = sync.current_source_only_button.geometry()
        assert first.intersected(second).isEmpty()
        assert sync.source_check_list.height() >= max(first.height(), second.height())
        _assert_visible_control(sync, sync.select_all_sources_button)
        _assert_visible_control(sync, sync.current_source_only_button)
        _assert_tab_reaches_visible_control(sync, sync.current_source_only_button, app)

        screen = app.primaryScreen()
        print(
            "industrial-geometry "
            f"platform={app.platformName()} dpr={actual_ratio:.2f} "
            f"screen={screen.size().width()}x{screen.size().height()} "
            f"physical={round(screen.size().width() * actual_ratio)}x"
            f"{round(screen.size().height() * actual_ratio)} "
            f"clients={'/'.join(f'{dialog.width()}x{dialog.height()}' for dialog in dialogs)} "
            f"frames={'/'.join(f'{dialog.frameGeometry().width()}x{dialog.frameGeometry().height()}' for dialog in dialogs)}"
        )
    finally:
        for dialog in dialogs:
            dialog.close()
            dialog.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("scale", ("1", "1.25", "1.5", "2"))
def test_windows_scale_factor_subprocess(scale):
    if sys.platform != "win32" or os.environ.get("INDUSTRIAL_GEOMETRY_SCALE_INNER") == "1":
        pytest.skip("Native Windows scaling only.")
    environment = os.environ.copy()
    environment.update(
        {
            "INDUSTRIAL_GEOMETRY_SCALE_INNER": "1",
            "QT_SCALE_FACTOR": scale,
            "METROLIZA_EXPECT_QT_PLATFORM": "windows",
            "PYTHONPATH": str(Path.cwd() / "src") + os.pathsep + environment.get("PYTHONPATH", ""),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-s", __file__, "-k", "windows_scale_inner_industrial_geometry"],
        cwd=Path.cwd(),
        env=environment,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, (
        f"QT_SCALE_FACTOR={scale} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "1 passed" in completed.stdout, "Native scale body did not execute"
    assert "industrial-geometry platform=windows" in completed.stdout
    print(completed.stdout, end="")
