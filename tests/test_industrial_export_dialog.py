from __future__ import annotations

import sys
import types

import pytest

try:
    from PyQt6.QtWidgets import QApplication

    import modules.industrial_export_dialog as industrial_export_dialog
    from modules.industrial_export_dialog import IndustrialExportDialog
    from modules.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    IndustrialExportDialog = None
    IndustrialFilterState = None
    IndustrialGroupingState = None
    industrial_export_dialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial export dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_export_dialog_uses_csv_summary_style_readiness_and_plot_toggle(tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    output_path = str(tmp_path / "industrial.xlsx")
    dialog = IndustrialExportDialog(
        db_file=db_path,
        filter_state=IndustrialFilterState(reference_column="reference", references=("REF-1",)),
        grouping_state=IndustrialGroupingState(fields=("station",)),
        include_plots=False,
    )

    assert not dialog.start_button.isEnabled()
    assert dialog.include_plots_checkbox.text() == "Include plots"
    assert dialog.plot_status_label.text() == "Plots disabled"
    assert dialog.clear_filter_button.isEnabled()
    assert dialog.clear_grouping_button.isEnabled()

    dialog.clear_filter()
    dialog.clear_grouping()

    assert dialog.filter_state.references == ()
    assert dialog.grouping_state.fields == ()
    assert not dialog.clear_filter_button.isEnabled()
    assert not dialog.clear_grouping_button.isEnabled()

    dialog.output_file = output_path
    dialog._sync_ui_state()
    thread = dialog.create_export_thread()

    assert dialog.start_button.isEnabled()
    assert thread.output_file == output_path
    assert thread.filter_state.references == ()
    assert thread.grouping_state.fields == ()
    assert thread.include_charts is False
    dialog.close()


def test_export_dialog_has_no_live_oznak_fetch_dependency():
    assert "fetch_oznak_records_for_source_profile" not in vars(industrial_export_dialog)
    assert "create_oznak_cancellation_token" not in vars(industrial_export_dialog)


def test_export_dialog_completion_uses_export_style_workbook_link(tmp_path, monkeypatch):
    _app()
    output_path = tmp_path / "industrial.xlsx"
    calls = []
    fake_export_dialog = types.SimpleNamespace(
        show_export_result_message=lambda parent, level, title, message, excel_file=None: calls.append(
            (parent, level, title, message, excel_file)
        )
    )
    monkeypatch.setitem(sys.modules, "modules.export_dialog", fake_export_dialog)
    dialog = IndustrialExportDialog(db_file=str(tmp_path / "industrial.db"))

    dialog.on_export_finished(
        {
            "output_file": str(output_path),
            "row_count": 3,
            "summary_rows": 2,
            "charts": True,
        }
    )

    assert calls == [
        (
            dialog,
            "info",
            "Industrial export complete",
            (
                "Industrial export complete.\n\n"
                f"Industrial workbook: {output_path.resolve().as_uri()}\n\n"
                "Rows: 3\n"
                "Summary rows: 2"
            ),
            str(output_path),
        )
    ]
    dialog.close()
