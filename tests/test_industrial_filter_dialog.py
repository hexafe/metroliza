from __future__ import annotations

import sqlite3

import pytest

try:
    from PyQt6.QtWidgets import QApplication, QDialog

    import metroliza.ui.industrial_filter_dialog as industrial_filter_dialog
    from metroliza.industrial.industrial_workflow_state import (
        IndustrialFilterState,
        parse_reference_values,
    )
    from metroliza.reports.report_schema import ensure_report_schema
    from metroliza.ui.industrial_filter_dialog import IndustrialFilterDialog
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    QDialog = None
    IndustrialFilterDialog = None
    IndustrialFilterState = None
    ensure_report_schema = None
    parse_reference_values = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial filter dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_reference_parser_accepts_common_paste_formats():
    assert parse_reference_values("REF1, REF2;REF3\nREF4 REF5\tREF6") == (
        "REF1",
        "REF2",
        "REF3",
        "REF4",
        "REF5",
        "REF6",
    )
    assert parse_reference_values("REF1 REF1,REF2") == ("REF1", "REF2")


def test_filter_dialog_apply_uses_parent_callback():
    _app()
    class _ParentDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.state = None

        def set_industrial_filter_state(self, state):
            self.state = state

    parent = _ParentDialog()
    dialog = IndustrialFilterDialog(parent=parent, state=IndustrialFilterState())
    dialog.reference_column_edit.setText("reference")
    dialog.references_edit.setPlainText("REF1, REF2")

    dialog.apply_filter()

    assert parent.state == IndustrialFilterState(reference_column="reference", references=("REF1", "REF2"))


def test_filter_dialog_rejects_invalid_reference_column():
    _app()
    dialog = IndustrialFilterDialog(state=IndustrialFilterState())
    dialog.reference_column_edit.setText("reference;drop")
    dialog.references_edit.setPlainText("REF1")

    assert dialog.current_state().references == ("REF1",)
    with pytest.raises(ValueError):
        dialog.current_state().validate_for_sync()
    dialog.close()


def test_filter_dialog_loads_references_from_local_metroliza_metadata_only(tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    ensure_report_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO report_metadata(report_id, reference, metadata_version) VALUES (?, ?, ?)",
            [
                (1, "REF-2", "report_metadata_v1"),
                (2, "REF-1", "report_metadata_v1"),
                (3, "REF-1", "report_metadata_v1"),
                (4, "", "report_metadata_v1"),
                (5, None, "report_metadata_v1"),
            ],
        )

    dialog = IndustrialFilterDialog(db_file=db_path, state=IndustrialFilterState())
    dialog.load_database_references()

    assert dialog.references_edit.toPlainText().splitlines() == ["REF-1", "REF-2"]
    dialog.close()


def test_filter_dialog_warning_and_clear_paths(monkeypatch):
    _app()
    warnings = []
    monkeypatch.setattr(
        industrial_filter_dialog.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    dialog = IndustrialFilterDialog(state=IndustrialFilterState(references=("REF-1",)))

    dialog.load_database_references()
    dialog.clear_filter()
    dialog.reference_column_edit.setText("reference;drop")
    dialog.references_edit.setPlainText("REF-2")
    dialog.apply_filter()

    assert len(warnings) == 2
    assert "Select a Metroliza report database" in warnings[0][2]
    assert "cleared" in dialog.summary_label.text()
    assert "reference column" in warnings[1][2]
    dialog.close()
