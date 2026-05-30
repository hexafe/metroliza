"""Filtering dialog for Oznak/industrial production-line sync scope."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from metroliza.reports.db import sqlite_connection_scope
from metroliza.industrial.industrial_workflow_state import (
    IndustrialFilterState,
    parse_reference_values,
    require_identifier,
)
from metroliza.reports.report_schema import ensure_report_schema
from metroliza.ui.ui_foundation import apply_metroliza_theme, configure_window_size, status_chip


class IndustrialFilterDialog(QDialog):
    """Collect Oznak fetch filters in a separate modal dialog."""

    def __init__(self, parent=None, db_file: str | None = None, state: IndustrialFilterState | None = None):
        super().__init__(parent)
        self.db_file = db_file
        self.state = state or IndustrialFilterState()
        self.setWindowTitle("Industrial sync scope")
        configure_window_size(self, minimum=(520, 340), initial=(680, 460))

        self.summary_label = status_chip(self.state.summary(), "neutral")
        self.reference_column_edit = QLineEdit(self.state.reference_column or "reference")
        self.reference_column_edit.setPlaceholderText("reference")
        self.references_edit = QPlainTextEdit()
        self.references_edit.setPlainText("\n".join(self.state.references))
        self.references_edit.setPlaceholderText("REF1, REF2; REF3 REF4")

        self.load_db_references_button = QPushButton("Use report DB values")
        self.clear_button = QPushButton("Clear values")
        self.apply_button = QPushButton("Apply references")
        self.cancel_button = QPushButton("Cancel")

        self.load_db_references_button.clicked.connect(self.load_database_references)
        self.clear_button.clicked.connect(self.clear_filter)
        self.apply_button.clicked.connect(self.apply_filter)
        self.cancel_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.summary_label)
        layout.addWidget(QLabel("Reference/ID column in production data"))
        layout.addWidget(self.reference_column_edit)
        layout.addWidget(QLabel("Reference/ID values to fetch"))
        layout.addWidget(self.references_edit, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.load_db_references_button)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)

        apply_metroliza_theme(self)

    def current_state(self) -> IndustrialFilterState:
        return IndustrialFilterState(
            reference_column=self.reference_column_edit.text().strip() or "reference",
            references=parse_reference_values(self.references_edit.toPlainText()),
        )

    def load_database_references(self) -> None:
        if not self.db_file:
            QMessageBox.warning(self, "Industrial sync scope", "Select a Metroliza report database first.")
            return
        try:
            with sqlite_connection_scope(self.db_file) as conn:
                ensure_report_schema(self.db_file, connection=conn)
                rows = conn.execute(
                    """
                    SELECT DISTINCT TRIM(reference)
                    FROM report_metadata
                    WHERE TRIM(COALESCE(reference, '')) <> ''
                    ORDER BY TRIM(reference) COLLATE NOCASE
                    """
                ).fetchall()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Industrial sync scope",
                f"Could not read references from the selected Metroliza report database: {exc}",
            )
            return

        references = [str(row[0]).strip() for row in rows if str(row[0]).strip()]
        self.references_edit.setPlainText("\n".join(references))
        self.summary_label.setText(
            f"Loaded {len(references)} reference value(s) from the Metroliza report database"
        )

    def clear_filter(self) -> None:
        self.references_edit.clear()
        self.summary_label.setText("Reference/ID values cleared")

    def apply_filter(self) -> None:
        try:
            state = self.current_state()
            require_identifier("reference column", state.reference_column)
        except ValueError as exc:
            QMessageBox.warning(self, "Industrial sync scope", str(exc))
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_industrial_filter_state"):
            parent.set_industrial_filter_state(state)
        self.state = state
        self.accept()
