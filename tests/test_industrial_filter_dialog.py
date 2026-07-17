from __future__ import annotations

from contextlib import closing
import sqlite3

import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QDialog

    import metroliza.ui.industrial_filter_dialog as industrial_filter_dialog
    from metroliza.industrial.industrial_workflow_state import (
        IndustrialFilterState,
        IndustrialQueryFilter,
        parse_industrial_query_filter_lines,
        parse_reference_values,
    )
    from metroliza.reports.report_schema import ensure_report_schema
    from metroliza.ui.industrial_filter_dialog import IndustrialFilterDialog
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    QDialog = None
    QTest = None
    Qt = None
    IndustrialFilterDialog = None
    IndustrialFilterState = None
    IndustrialQueryFilter = None
    ensure_report_schema = None
    parse_industrial_query_filter_lines = None
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


def test_query_filter_parser_accepts_simple_filter_lines():
    assert parse_industrial_query_filter_lines(
        "station = S1\nstatus IN OK, NOK\nprocess_timestamp >= 2026-01-01"
    ) == (
        IndustrialQueryFilter("station", "=", ("S1",)),
        IndustrialQueryFilter("status", "IN", ("OK", "NOK")),
        IndustrialQueryFilter("process_timestamp", ">=", ("2026-01-01",)),
    )


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
    dialog.query_filters_edit.setPlainText("station = S1")

    dialog.apply_filter()

    assert parent.state == IndustrialFilterState(
        reference_column="reference",
        references=("REF1", "REF2"),
        query_filters=(IndustrialQueryFilter("station", "=", ("S1",)),),
    )


def test_filter_dialog_builder_appends_filter_without_overwriting_references():
    _app()
    dialog = IndustrialFilterDialog(
        state=IndustrialFilterState(reference_column="reference", references=("REF1",))
    )
    dialog.query_filters_edit.setPlainText("station = S1")
    dialog.filter_column_combo.setCurrentIndex(dialog.filter_column_combo.findData("process_status"))
    dialog.filter_operator_combo.setCurrentIndex(dialog.filter_operator_combo.findData("IN"))
    dialog.filter_value_edit.setText("OK, NOK")

    dialog.add_filter_from_builder()

    assert dialog.references_edit.toPlainText() == "REF1"
    assert dialog.query_filters_edit.toPlainText().splitlines() == [
        "station = S1",
        "process_status IN OK, NOK",
    ]
    assert dialog.current_state().query_filters == (
        IndustrialQueryFilter("station", "=", ("S1",)),
        IndustrialQueryFilter("process_status", "IN", ("OK", "NOK")),
    )
    dialog.close()


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
    with closing(sqlite3.connect(db_path)) as conn, conn:
        timestamp = "2026-06-23T00:00:00"
        conn.executemany(
            """
            INSERT INTO source_files(id, sha256, source_format, discovered_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (index, f"sha-{index}", "pdf", timestamp)
                for index in range(1, 6)
            ],
        )
        conn.executemany(
            """
            INSERT INTO parsed_reports(
                id,
                source_file_id,
                parser_id,
                template_family,
                parse_status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (index, index, "test", "test", "parsed", timestamp, timestamp)
                for index in range(1, 6)
            ],
        )
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
    assert dialog.summary_label.text().startswith("1 active condition.")
    assert "2 value(s) loaded" in dialog.source_context_label.text()
    dialog.close()


def test_filter_dialog_uses_inline_validation_and_clear_paths(monkeypatch):
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

    assert len(warnings) == 1
    assert "Select a Metroliza report database" in warnings[0][2]
    assert not dialog.apply_button.isEnabled()
    assert not dialog.validation_error_label.isHidden()
    assert "reference column" in dialog.validation_error_label.text()
    dialog.close()


def test_filter_dialog_exposes_count_accessibility_and_semantic_actions():
    _app()
    dialog = IndustrialFilterDialog(
        state=IndustrialFilterState(
            references=("REF-1", "REF-2"),
            query_filters=(IndustrialQueryFilter("station", "=", ("S1",)),),
        )
    )

    assert dialog.summary_label.text().startswith("2 active conditions.")
    assert dialog.summary_label.accessibleName() == "Industrial sync filter draft summary"
    assert dialog.validation_error_label.accessibleName() == "Industrial sync filter error"
    assert dialog.apply_button.property("buttonRole") == "primary"
    assert dialog.apply_button.isDefault()
    assert dialog.cancel_button.property("buttonRole") == "secondary"
    assert dialog.clear_button.property("buttonRole") == "quiet"
    assert dialog.clear_button.text() == "Reset filters"
    dialog.close()


def test_filter_dialog_reset_and_cancel_discard_only_confirmed_draft_changes(monkeypatch):
    _app()

    class _ParentDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.calls = []

        def set_industrial_filter_state(self, state):
            self.calls.append(state)

    parent = _ParentDialog()
    committed = IndustrialFilterState(references=("REF-1",))
    dialog = IndustrialFilterDialog(parent=parent, state=committed)
    answers = iter(
        (
            industrial_filter_dialog.QMessageBox.StandardButton.No,
            industrial_filter_dialog.QMessageBox.StandardButton.Yes,
            industrial_filter_dialog.QMessageBox.StandardButton.Yes,
        )
    )
    prompts = []
    monkeypatch.setattr(
        industrial_filter_dialog.QMessageBox,
        "question",
        lambda *args: prompts.append(args) or next(answers),
    )

    dialog.references_edit.setPlainText("REF-2")
    dialog._request_reset_filter()
    assert dialog.current_state().references == ("REF-2",)

    dialog._request_reset_filter()
    assert dialog.current_state() == IndustrialFilterState()
    assert parent.calls == []

    dialog.references_edit.setPlainText("REF-3")
    dialog.show()
    _app().processEvents()
    dialog._request_cancel()
    assert dialog.current_state() == committed
    assert parent.calls == []
    assert len(prompts) == 3


def test_filter_dialog_clean_cancel_and_window_close_do_not_prompt(monkeypatch):
    _app()
    dialog = IndustrialFilterDialog(state=IndustrialFilterState(references=("REF-1",)))
    monkeypatch.setattr(
        industrial_filter_dialog.QMessageBox,
        "question",
        lambda *_args: pytest.fail("clean cancel should not ask for confirmation"),
    )
    dialog._request_cancel()

    dialog = IndustrialFilterDialog(state=IndustrialFilterState())
    dialog.references_edit.setPlainText("REF-2")
    dialog.close()


def test_filter_dialog_dirty_x_and_escape_restore_without_parent_commit(monkeypatch):
    app = _app()

    class _ParentDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.calls = []

        def set_industrial_filter_state(self, state):
            self.calls.append(state)

    parent = _ParentDialog()
    committed = IndustrialFilterState(references=("REF-1",))
    dialog = IndustrialFilterDialog(parent=parent, state=committed)
    answers = iter(
        (
            industrial_filter_dialog.QMessageBox.StandardButton.No,
            industrial_filter_dialog.QMessageBox.StandardButton.Yes,
            industrial_filter_dialog.QMessageBox.StandardButton.No,
            industrial_filter_dialog.QMessageBox.StandardButton.Yes,
        )
    )
    monkeypatch.setattr(
        industrial_filter_dialog.QMessageBox,
        "question",
        lambda *_args, **_kwargs: next(answers),
    )
    try:
        dialog.show()
        app.processEvents()
        dialog.references_edit.setPlainText("REF-2")

        assert dialog.close() is False
        assert dialog.isVisible()
        assert dialog.current_state().references == ("REF-2",)
        assert dialog.close() is True
        assert not dialog.isVisible()
        assert dialog.current_state() == committed
        assert parent.calls == []

        dialog.show()
        app.processEvents()
        dialog.references_edit.setPlainText("REF-3")
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert dialog.isVisible()
        assert dialog.current_state().references == ("REF-3",)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert not dialog.isVisible()
        assert dialog.current_state() == committed
        assert parent.calls == []
    finally:
        dialog.close()
        parent.close()
