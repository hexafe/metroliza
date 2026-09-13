"""Real-Qt geometry, focus, and keyboard coverage for the report planner."""

from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys

import pytest

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")

try:
    from PyQt6.QtCore import QPoint, QRect, QSize, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QWidget

    from metroliza.parsing import report_parser_factory
    from metroliza.parsing.preflight import (
        ParseFilePreflight,
        ParsePreflightResult,
        ParsePreflightStatus,
    )
    from metroliza.ui.parsing_dialog import ParsingDialog
except Exception as exc:  # pragma: no cover - runtime-dependent Qt import
    QApplication = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

if QApplication is None and os.environ.get("METROLIZA_EXPECT_QT_PLATFORM"):
    raise RuntimeError(
        "A required native Qt platform could not initialize for planner geometry coverage."
    ) from PYQT_IMPORT_ERROR


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 planner geometry checks are unavailable: {PYQT_IMPORT_ERROR}",
)


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    expected_platform = os.environ.get("METROLIZA_EXPECT_QT_PLATFORM")
    if expected_platform:
        assert application.platformName().casefold() == expected_platform.casefold()
    expected_screen = os.environ.get("METROLIZA_EXPECT_PLANNER_SCREEN")
    if expected_screen:
        assert expected_screen == "1920x1080", "Unknown planner display qualification"
        screen = application.primaryScreen()
        ratio = screen.devicePixelRatio()
        physical_size = (round(screen.size().width() * ratio), round(screen.size().height() * ratio))
        assert physical_size == (1920, 1080), f"Required native display unavailable: {physical_size}"
    return application


def _review() -> ParsePreflightResult:
    generation_id = report_parser_factory.get_registry_snapshot().generation_id
    files = (
        ParseFilePreflight(
            display_name="nested/ready-a.pdf",
            source_path="/temporary/extraction/ready-a.pdf",
            status=ParsePreflightStatus.READY,
            source_format="pdf",
            fingerprint="sha256:" + "a" * 64,
            parser_id="cmm",
            confidence=91,
            registry_generation_id=generation_id,
            occurrence_id="nested/ready-a.pdf",
        ),
        ParseFilePreflight(
            display_name="nested/already-imported.pdf",
            source_path="/temporary/extraction/already-imported.pdf",
            status=ParsePreflightStatus.DUPLICATE,
            source_format="pdf",
            fingerprint="sha256:" + "b" * 64,
            parser_id="cmm",
            confidence=89,
            registry_generation_id=generation_id,
            occurrence_id="nested/already-imported.pdf",
        ),
        ParseFilePreflight(
            display_name="nested/ready-c.pdf",
            source_path="/temporary/extraction/ready-c.pdf",
            status=ParsePreflightStatus.READY,
            source_format="pdf",
            fingerprint="sha256:" + "c" * 64,
            parser_id="cmm",
            confidence=87,
            registry_generation_id=generation_id,
            occurrence_id="nested/ready-c.pdf",
        ),
        ParseFilePreflight(
            display_name="nested/ambiguous.pdf",
            source_path="/temporary/extraction/ambiguous.pdf",
            status=ParsePreflightStatus.AMBIGUOUS,
            source_format="pdf",
            fingerprint="sha256:" + "d" * 64,
            competing_parser_ids=("cmm",),
            occurrence_id="nested/ambiguous.pdf",
        ),
    )
    return ParsePreflightResult(
        source_path="/synthetic/reports",
        database_path="/synthetic/reports.sqlite3",
        metadata_parsing_mode="light",
        files=files,
    )


@pytest.fixture
def dialog(app):
    value = ParsingDialog(
        parent=None,
        directory="/synthetic/reports",
        db_file="/synthetic/reports.sqlite3",
    )
    value.on_preflight_completed(_review())
    value.show()
    # Let the adaptive initial-size timer finish before exercising a user resize.
    QTest.qWait(5)
    app.processEvents()
    yield value
    value.close()
    app.processEvents()


def _assert_contained(dialog: ParsingDialog, widget: QWidget) -> None:
    assert widget.isVisible(), f"{widget.accessibleName() or widget.objectName()} is hidden"
    assert widget.width() > 0 and widget.height() > 0
    bounds = QRect(QPoint(0, 0), dialog.size())
    rectangle = QRect(widget.mapTo(dialog, QPoint(0, 0)), widget.size())
    assert bounds.contains(rectangle), (
        f"{widget.accessibleName() or widget.objectName()} is clipped: "
        f"{rectangle.getRect()} outside {bounds.getRect()}"
    )


def _assert_requested_size(dialog: ParsingDialog, size: tuple[int, int]) -> None:
    assert dialog.size() == QSize(*size), (
        f"dialog silently grew from requested {size} to "
        f"{dialog.size().width()}x{dialog.size().height()}"
    )


def _assert_geometry(dialog: ParsingDialog, app, *, pane: str | None = None) -> None:
    planner = dialog.report_planner
    requested_size = dialog.size()
    if pane == "details":
        planner.details_button.setChecked(True)
    elif pane == "outcome":
        planner.show_outcome("Synthetic import outcome for compact layout coverage.")
    app.processEvents()
    assert dialog.size() == requested_size, "Opening an evidence pane grew the dialog"
    controls = (
        dialog.directory_button,
        dialog.archive_button,
        dialog.database_button,
        dialog.metadata_mode_combo,
        dialog.scan_button,
        planner.search,
        planner.status_filter,
        planner.parser_filter,
        planner.attention_filter,
        planner.select_ready,
        planner.clear,
        planner.details_button,
        planner.table,
        dialog.parse_button,
    )
    if pane == "details":
        controls += (planner.details,)
    elif pane == "outcome":
        controls += (planner.outcome_button, planner.outcome)
    for control in controls:
        _assert_contained(dialog, control)
    assert planner.table.height() >= 60


@pytest.mark.parametrize("size,pane", [((720, 480), None), ((1280, 800), "details")])
def test_report_planner_controls_fit_compact_and_large_dialogs(dialog, app, size, pane, tmp_path, request):
    available = app.primaryScreen().availableGeometry()
    if available.width() < size[0] + 40 or available.height() < size[1] + 40:
        if sys.platform != "win32":
            # Qt 6.6's real offscreen plugin supports a configured virtual screen.
            # Keep this separate from native Windows platform/DPI evidence.
            assert os.environ.get("REPORT_PLANNER_LARGE_INNER") != "1"
            config = tmp_path / "qt-screen.json"
            config.write_text(json.dumps({"screens": [{
                "name": "planner-test", "width": 1600, "height": 1000,
                "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1,
            }]}), encoding="utf-8")
            environment = dict(
                os.environ, REPORT_PLANNER_LARGE_INNER="1",
                QT_QPA_PLATFORM=f"offscreen:configfile={config}",
                METROLIZA_EXPECT_QT_PLATFORM="offscreen",
            )
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
                env=environment, capture_output=True, text=True, timeout=45,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "1 passed" in result.stdout
            return
        size = (min(size[0], available.width() - 40), min(size[1], available.height() - 40))
        assert size[0] >= 850 and size[1] >= 600, "Native runner cannot host a large planner"
    if size[0] >= 850:
        # Expanding a previously compact table must release the location stretch.
        dialog.resize(720, 480)
        app.processEvents()
    dialog.resize(*size)
    app.processEvents()
    _assert_requested_size(dialog, size)
    _assert_geometry(dialog, app, pane=pane)
    if size[0] >= 850:
        assert not dialog.report_planner.table.isColumnHidden(3)
        assert dialog.report_planner.table.columnWidth(2) >= 150
        assert dialog.report_planner.table.columnWidth(5) >= 150
        planner = dialog.report_planner
        planner.table.setColumnWidth(2, 185)
        planner.invalidate()
        planner.set_review(_review())
        assert planner.table.columnWidth(2) == 185


def test_compact_dialog_preserves_table_while_switching_details_and_outcome(dialog, app):
    dialog.resize(720, 480)
    app.processEvents()
    _assert_requested_size(dialog, (720, 480))
    planner = dialog.report_planner
    _assert_geometry(dialog, app, pane="details")
    assert planner.details.isVisible()
    planner.show_outcome("Synthetic compact outcome.")
    app.processEvents()
    assert planner.outcome.isVisible()
    assert not planner.details.isVisible()
    _assert_geometry(dialog, app, pane="outcome")
    planner.details_button.setChecked(True)
    app.processEvents()
    assert planner.details.isVisible()
    assert not planner.outcome.isVisible()
    _assert_geometry(dialog, app, pane="details")


def test_space_operates_ready_row_from_text_cell_but_blocks_nonready(dialog, app):
    planner = dialog.report_planner
    model = planner.model
    table = planner.table
    ready_id = "nested/ready-a.pdf"
    duplicate_id = "nested/already-imported.pdf"
    assert ready_id in model.selected_ids

    ready_row = next(
        row for row in range(planner.proxy.rowCount())
        if planner.proxy.data(planner.proxy.index(row, model.LOCATION_COLUMN)) == "nested/ready-a.pdf"
    )
    table.setCurrentIndex(planner.proxy.index(ready_row, model.LOCATION_COLUMN))
    table.setFocus()
    app.processEvents()
    assert table.hasFocus()
    QTest.keyClick(table, Qt.Key.Key_Space)
    app.processEvents()
    assert ready_id not in model.selected_ids

    duplicate_row = next(
        row for row in range(planner.proxy.rowCount())
        if planner.proxy.data(planner.proxy.index(row, model.LOCATION_COLUMN))
        == "nested/already-imported.pdf"
    )
    table.setCurrentIndex(planner.proxy.index(duplicate_row, model.LOCATION_COLUMN))
    QTest.keyClick(table, Qt.Key.Key_Space)
    app.processEvents()
    assert duplicate_id not in model.selected_ids
    assert not model.flags(model.index(1, model.CHECKBOX_COLUMN)) & Qt.ItemFlag.ItemIsUserCheckable


def test_filtered_rows_do_not_change_global_selection_and_tab_order_is_deterministic(dialog, app):
    planner = dialog.report_planner
    model = planner.model
    initial_selection = model.selected_ids
    planner.search.setText("ready-a")
    app.processEvents()
    assert planner.proxy.rowCount() == 1
    assert model.selected_ids == initial_selection

    focus_order = (
        dialog.directory_button,
        dialog.archive_button,
        dialog.database_button,
        dialog.metadata_mode_combo,
        dialog.scan_button,
        planner.search,
        planner.status_filter,
        planner.parser_filter,
        planner.attention_filter,
        planner.select_ready,
        planner.clear,
        planner.table,
        dialog.parse_button,
    )
    focus_order[0].setFocus()
    for expected in focus_order[1:]:
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
        app.processEvents()
        assert QApplication.focusWidget() is expected


def test_windows_scale_inner_geometry(app):
    """Inner body invoked by the Windows scale-factor subprocess matrix."""

    if sys.platform != "win32" or os.environ.get("REPORT_PLANNER_SCALE_INNER") != "1":
        pytest.skip("This test is only executed inside the Windows scale matrix.")
    assert QApplication.instance().platformName().casefold() == "windows"
    actual_ratio = app.primaryScreen().devicePixelRatio()
    assert actual_ratio == pytest.approx(float(os.environ["QT_SCALE_FACTOR"]), abs=0.05)
    dialog = ParsingDialog(
        parent=None,
        directory="/synthetic/reports",
        db_file="/synthetic/reports.sqlite3",
    )
    try:
        dialog.on_preflight_completed(_review())
        dialog.show()
        QTest.qWait(5)
        app.processEvents()
        dialog.resize(720, 480)
        app.processEvents()
        _assert_requested_size(dialog, (720, 480))
        _assert_geometry(dialog, app, pane="details")
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("scale", ("1", "1.25", "1.5", "2"))
def test_windows_scale_factor_subprocess(scale):
    if sys.platform != "win32" or os.environ.get("REPORT_PLANNER_SCALE_INNER") == "1":
        pytest.skip("Native Windows scaling only.")
    environment = os.environ.copy()
    environment.update(
        {
            "REPORT_PLANNER_SCALE_INNER": "1",
            "QT_SCALE_FACTOR": scale,
            "METROLIZA_EXPECT_QT_PLATFORM": "windows",
            "PYTHONPATH": str(Path.cwd() / "src") + os.pathsep + environment.get("PYTHONPATH", ""),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-s", __file__, "-k", "windows_scale_inner_geometry"],
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
