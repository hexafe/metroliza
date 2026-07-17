"""Filtering dialog for Oznak/industrial production-line sync scope."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
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
    INDUSTRIAL_FILTER_FIELDS,
    INDUSTRIAL_QUERY_FILTER_OPERATOR_CHOICES,
    IndustrialFilterState,
    IndustrialQueryFilter,
    format_industrial_query_filters,
    parse_industrial_query_filter_lines,
    parse_reference_values,
    require_identifier,
)
from metroliza.reports.report_schema import ensure_report_schema
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_dialog_button_roles,
    configure_window_size,
    secondary_label,
    set_status_variant,
    status_chip,
)


class IndustrialFilterDialog(QDialog):
    """Collect Oznak fetch filters in a separate modal dialog."""

    def __init__(self, parent=None, db_file: str | None = None, state: IndustrialFilterState | None = None):
        super().__init__(parent)
        self.db_file = db_file
        self.state = state or IndustrialFilterState()
        self._committed_state = self.state
        self._discard_gate_active = False
        self.setWindowTitle("Industrial sync scope")
        configure_window_size(self, minimum=(520, 340), initial=(680, 460))

        self.summary_label = status_chip(self.state.summary(), "neutral")
        configure_accessibility(
            self.summary_label,
            name="Industrial sync filter draft summary",
            description="Summarizes the active conditions in the uncommitted sync filter draft.",
        )
        self.validation_error_label = status_chip("", "error")
        configure_accessibility(
            self.validation_error_label,
            name="Industrial sync filter error",
            description="Explains why the current sync filter draft cannot be applied.",
        )
        self.validation_error_label.hide()
        self.reference_column_edit = QLineEdit(self.state.reference_column or "reference")
        self.reference_column_edit.setPlaceholderText("reference")
        self.references_edit = QPlainTextEdit()
        self.references_edit.setPlainText("\n".join(self.state.references))
        self.references_edit.setPlaceholderText("REF1, REF2; REF3 REF4")
        self.query_filters_edit = QPlainTextEdit()
        self.query_filters_edit.setPlainText(format_industrial_query_filters(self.state.query_filters))
        self.query_filters_edit.setPlaceholderText(
            "station = S1\nstatus IN OK, NOK\nprocess_timestamp >= 2026-01-01"
        )
        self.filter_column_combo = QComboBox()
        for column, label in INDUSTRIAL_FILTER_FIELDS:
            self.filter_column_combo.addItem(f"{label} ({column})", column)
        self.filter_operator_combo = QComboBox()
        for operator in INDUSTRIAL_QUERY_FILTER_OPERATOR_CHOICES:
            self.filter_operator_combo.addItem(operator, operator)
        self.filter_value_edit = QLineEdit()
        self.filter_value_edit.setPlaceholderText("Value, or comma-separated values for IN")
        self.add_filter_button = QPushButton("Add filter")

        self.load_db_references_button = QPushButton("Use report DB values")
        self.load_db_references_button.setEnabled(bool(self.db_file))
        self.load_db_references_button.setToolTip(
            "Load references from the open Metroliza report database. "
            "Paste values manually when using a temporary industrial cache."
        )
        self.clear_button = QPushButton("Reset filters")
        self.apply_button = QPushButton("Apply filters")
        self.cancel_button = QPushButton("Cancel")

        self.load_db_references_button.clicked.connect(self.load_database_references)
        self.add_filter_button.clicked.connect(self.add_filter_from_builder)
        self.filter_operator_combo.currentIndexChanged.connect(
            lambda _index: self._sync_filter_builder_value_state()
        )
        self.clear_button.clicked.connect(self._request_reset_filter)
        self.apply_button.clicked.connect(self.apply_filter)
        self.cancel_button.clicked.connect(self._request_cancel)
        configure_dialog_button_roles(
            primary=self.apply_button,
            secondary=(self.cancel_button,),
            quiet=(
                self.load_db_references_button,
                self.add_filter_button,
                self.clear_button,
            ),
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("Industrial Data manual", "industrial_data")])
        layout.addWidget(self.summary_label)
        layout.addWidget(self.validation_error_label)
        source_context = (
            "Reference source: open Metroliza report database or manual entry."
            if self.db_file
            else "Reference source: manual entry (no Metroliza report database selected)."
        )
        self.source_context_label = secondary_label(
            f"{source_context} Changes stay in this draft until you apply the filters."
        )
        configure_accessibility(
            self.source_context_label,
            name="Industrial sync reference source",
        )
        layout.addWidget(self.source_context_label)
        layout.addWidget(QLabel("Reference/ID column in production data"))
        layout.addWidget(self.reference_column_edit)
        layout.addWidget(QLabel("Reference/ID values to fetch"))
        layout.addWidget(self.references_edit, 1)
        builder_form = QFormLayout()
        builder_form.setContentsMargins(0, 0, 0, 0)
        builder_row = QHBoxLayout()
        builder_row.setContentsMargins(0, 0, 0, 0)
        builder_row.setSpacing(8)
        builder_row.addWidget(self.filter_column_combo, 2)
        builder_row.addWidget(self.filter_operator_combo, 1)
        builder_row.addWidget(self.filter_value_edit, 2)
        builder_row.addWidget(self.add_filter_button)
        builder_form.addRow("Build filter", builder_row)
        layout.addLayout(builder_form)
        layout.addWidget(QLabel("Advanced filter expressions, one per line"))
        layout.addWidget(self.query_filters_edit, 1)

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
        self._sync_filter_builder_value_state()
        self._connect_draft_signals()
        self._sync_draft_state()

    def current_state(self) -> IndustrialFilterState:
        return IndustrialFilterState(
            reference_column=self.reference_column_edit.text().strip() or "reference",
            references=parse_reference_values(self.references_edit.toPlainText()),
            query_filters=parse_industrial_query_filter_lines(self.query_filters_edit.toPlainText()),
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
        self.source_context_label.setText(
            f"Reference source: {len(references)} value(s) loaded from the open Metroliza "
            "report database. Changes stay in this draft until you apply the filters."
        )
        self._sync_draft_state()

    def clear_filter(self) -> None:
        self.reference_column_edit.setText("reference")
        self.references_edit.clear()
        self.query_filters_edit.clear()

    def _connect_draft_signals(self) -> None:
        self.reference_column_edit.textChanged.connect(self._sync_draft_state)
        self.references_edit.textChanged.connect(self._sync_draft_state)
        self.query_filters_edit.textChanged.connect(self._sync_draft_state)

    def _validated_current_state(self) -> IndustrialFilterState:
        state = self.current_state()
        require_identifier("reference column", state.reference_column)
        return state

    def _is_dirty(self) -> bool:
        try:
            return self.current_state() != self._committed_state
        except ValueError:
            return True

    def _sync_draft_state(self, *_args) -> None:
        try:
            state = self._validated_current_state()
        except ValueError as exc:
            self.summary_label.setText("Draft needs attention")
            set_status_variant(self.summary_label, "warning")
            self.validation_error_label.setText(str(exc))
            self.validation_error_label.show()
            self.apply_button.setEnabled(False)
            return

        count = (1 if state.references else 0) + len(state.query_filters)
        noun = "condition" if count == 1 else "conditions"
        self.summary_label.setText(f"{count} active {noun}. {state.summary()}")
        set_status_variant(self.summary_label, "success" if count else "neutral")
        self.validation_error_label.clear()
        self.validation_error_label.hide()
        self.apply_button.setEnabled(True)

    def _request_reset_filter(self) -> None:
        try:
            current = self.current_state()
        except ValueError:
            current = None
        empty = IndustrialFilterState()
        if self._is_dirty() and current != empty:
            if not self._confirm_discard(
                "Reset filter draft?",
                "Resetting will discard the filter changes you have not applied.",
            ):
                return
        self.clear_filter()

    def _request_cancel(self) -> None:
        self.reject()

    def _discard_draft_if_allowed(self) -> bool:
        if self._discard_gate_active:
            return False
        if not self._is_dirty():
            return True
        if self.isVisible():
            self._discard_gate_active = True
            try:
                allowed = self._confirm_discard(
                    "Discard filter changes?",
                    "Canceling will discard the filter changes you have not applied.",
                )
            finally:
                self._discard_gate_active = False
            if not allowed:
                return False
        self._populate_from_state(self._committed_state)
        return True

    def reject(self) -> None:
        if not self._discard_draft_if_allowed():
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if not self._discard_draft_if_allowed():
            event.ignore()
            return
        super().closeEvent(event)

    def _confirm_discard(self, title: str, message: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _populate_from_state(self, state: IndustrialFilterState) -> None:
        self.reference_column_edit.setText(state.reference_column or "reference")
        self.references_edit.setPlainText("\n".join(state.references))
        self.query_filters_edit.setPlainText(format_industrial_query_filters(state.query_filters))

    def _sync_filter_builder_value_state(self) -> None:
        operator = str(self.filter_operator_combo.currentData() or "").upper()
        value_required = operator not in {"IS NULL", "IS NOT NULL"}
        self.filter_value_edit.setEnabled(value_required)
        if value_required:
            self.filter_value_edit.setPlaceholderText(
                "Value, or comma-separated values for IN"
                if operator in {"IN", "NOT IN"}
                else "Value"
            )
        else:
            self.filter_value_edit.clear()
            self.filter_value_edit.setPlaceholderText("No value required")

    def add_filter_from_builder(self) -> None:
        column = str(self.filter_column_combo.currentData() or "").strip()
        operator = str(self.filter_operator_combo.currentData() or "").strip().upper()
        value_text = self.filter_value_edit.text().strip()
        if operator in {"IS NULL", "IS NOT NULL"}:
            values = ()
        elif operator in {"IN", "NOT IN"}:
            values = parse_reference_values(value_text)
        else:
            values = (value_text,) if value_text else ()
        try:
            filter_state = IndustrialQueryFilter(
                column=column,
                operator=operator,
                values=values,
            ).validated()
        except ValueError as exc:
            self.validation_error_label.setText(str(exc))
            self.validation_error_label.show()
            return
        current_text = self.query_filters_edit.toPlainText().strip()
        filter_line = format_industrial_query_filters((filter_state,))
        self.query_filters_edit.setPlainText(
            f"{current_text}\n{filter_line}" if current_text else filter_line
        )
        self.filter_value_edit.clear()
        self._sync_draft_state()

    def apply_filter(self) -> None:
        try:
            state = self._validated_current_state()
        except ValueError as exc:
            self.validation_error_label.setText(str(exc))
            self.validation_error_label.show()
            self.apply_button.setEnabled(False)
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_industrial_filter_state"):
            parent.set_industrial_filter_state(state)
        self.state = state
        self._committed_state = state
        self.accept()
