"""Production analytics filter dialog."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from metroliza.industrial.industrial_analytics_state import (
    DynamicFieldFilter,
    ProductionFilterState,
    parse_reference_values,
)
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_dialog_button_roles,
    configure_window_size,
    section_label,
    secondary_label,
    set_status_variant,
    status_chip,
)


TEXT_FILTER_FIELDS: tuple[tuple[str, str], ...] = (
    ("source_db_aliases", "Source alias"),
    ("references", "Reference"),
    ("part_numbers", "Part number"),
    ("part_names", "Part name"),
    ("revisions", "Revision"),
    ("serials", "Serial"),
    ("batch_lots", "Batch / lot"),
    ("work_orders", "Work order"),
    ("stations", "Station"),
    ("lines", "Line"),
    ("operators", "Operator"),
    ("process_statuses", "Status"),
)


class IndustrialAnalyticsFilterDialog(QDialog):
    """Edit filters for cached production analytics."""

    def __init__(
        self,
        parent=None,
        *,
        filter_state: ProductionFilterState | None = None,
    ):
        super().__init__(parent)
        self.filter_state = filter_state or ProductionFilterState()
        self._committed_filter_state = self.filter_state
        self._discard_gate_active = False
        self.setWindowTitle("Production analytics filters")
        configure_window_size(self, minimum=(620, 520), initial=(720, 640))

        self.source_profile_ids_field = QLineEdit()
        self.source_profile_ids_field.setPlaceholderText("1, 2, 3")
        self.time_start_field = QLineEdit()
        self.time_start_field.setPlaceholderText("2026-05-10T00:00:00Z")
        self.time_end_field = QLineEdit()
        self.time_end_field.setPlaceholderText("2026-05-11T00:00:00Z")
        self.text_fields: dict[str, QLineEdit] = {}
        for field_name, label in TEXT_FILTER_FIELDS:
            field = QLineEdit()
            field.setPlaceholderText(f"{label} values separated by comma, semicolon, or space")
            self.text_fields[field_name] = field

        self.dynamic_filters_edit = QPlainTextEdit()
        self.dynamic_filters_edit.setPlaceholderText(
            "Examples:\n"
            "cycle_time_s gt 40\n"
            "fixture_text_code contains alpha\n"
            "cavity in 1,2\n"
            "operator_code is_not_null"
        )
        self.dynamic_filters_edit.setMaximumHeight(130)

        self.summary_label = status_chip("", "neutral")
        configure_accessibility(
            self.summary_label,
            name="Production analytics filter draft summary",
            description="Summarizes the active conditions in the uncommitted filter draft.",
        )
        self.validation_error_label = status_chip("", "error")
        configure_accessibility(
            self.validation_error_label,
            name="Production analytics filter error",
            description="Explains why the current filter draft cannot be applied.",
        )
        self.validation_error_label.hide()

        self.apply_button = QPushButton("Apply filters")
        self.clear_button = QPushButton("Reset filters")
        self.cancel_button = QPushButton("Cancel")
        self.apply_button.clicked.connect(self.accept)
        self.clear_button.clicked.connect(self._request_reset_filters)
        self.cancel_button.clicked.connect(self._request_cancel)
        configure_dialog_button_roles(
            primary=self.apply_button,
            secondary=(self.cancel_button,),
            quiet=(self.clear_button,),
        )

        self._build_layout()
        self._populate_from_state(self.filter_state)
        self._connect_draft_signals()
        self._sync_draft_state()
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(self.summary_label)
        layout.addWidget(self.validation_error_label)
        context_label = secondary_label(
            "Scope: cached production analytics rows. Changes stay in this draft until "
            "you apply the filters."
        )
        configure_accessibility(
            context_label,
            name="Production analytics filter scope",
        )
        layout.addWidget(context_label)
        layout.addWidget(section_label("Fixed filters"))
        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.addRow("Source profile ids", self.source_profile_ids_field)
        form.addRow("Time start", self.time_start_field)
        form.addRow("Time end", self.time_end_field)
        for field_name, label in TEXT_FILTER_FIELDS:
            form.addRow(label, self.text_fields[field_name])
        layout.addLayout(form)

        layout.addWidget(section_label("Advanced field expressions"))
        layout.addWidget(
            secondary_label(
                "Use one advanced expression per line: field operator value. "
                "Supported operators match the analytics service."
            )
        )
        layout.addWidget(self.dynamic_filters_edit)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)

    def _populate_from_state(self, state: ProductionFilterState) -> None:
        self.source_profile_ids_field.setText(", ".join(str(value) for value in state.source_profile_ids))
        self.time_start_field.setText(state.time_start or "")
        self.time_end_field.setText(state.time_end or "")
        for field_name, _label in TEXT_FILTER_FIELDS:
            self.text_fields[field_name].setText(", ".join(getattr(state, field_name)))
        self.dynamic_filters_edit.setPlainText(_dynamic_filters_to_text(state.dynamic_filters))

    def _connect_draft_signals(self) -> None:
        self.source_profile_ids_field.textChanged.connect(self._sync_draft_state)
        self.time_start_field.textChanged.connect(self._sync_draft_state)
        self.time_end_field.textChanged.connect(self._sync_draft_state)
        for field in self.text_fields.values():
            field.textChanged.connect(self._sync_draft_state)
        self.dynamic_filters_edit.textChanged.connect(self._sync_draft_state)

    def current_state(self) -> ProductionFilterState:
        return ProductionFilterState(
            source_profile_ids=_parse_int_values(self.source_profile_ids_field.text()),
            time_start=self.time_start_field.text().strip() or None,
            time_end=self.time_end_field.text().strip() or None,
            dynamic_filters=_parse_dynamic_filters(self.dynamic_filters_edit.toPlainText()),
            **{
                field_name: parse_reference_values(field.text())
                for field_name, field in self.text_fields.items()
            },
        )

    def clear_filters(self) -> None:
        self.source_profile_ids_field.clear()
        self.time_start_field.clear()
        self.time_end_field.clear()
        for field in self.text_fields.values():
            field.clear()
        self.dynamic_filters_edit.clear()

    def _is_dirty(self) -> bool:
        try:
            return self.current_state() != self._committed_filter_state
        except ValueError:
            return True

    def _sync_draft_state(self, *_args) -> None:
        try:
            state = self.current_state()
        except ValueError as exc:
            self.summary_label.setText("Draft needs attention")
            set_status_variant(self.summary_label, "warning")
            self.validation_error_label.setText(str(exc))
            self.validation_error_label.show()
            self.apply_button.setEnabled(False)
            return

        count = _active_condition_count(state)
        noun = "condition" if count == 1 else "conditions"
        self.summary_label.setText(f"{count} active {noun}. {state.summary()}")
        set_status_variant(self.summary_label, "success" if count else "neutral")
        self.validation_error_label.clear()
        self.validation_error_label.hide()
        self.apply_button.setEnabled(True)

    def _request_reset_filters(self) -> None:
        if self._is_dirty() and self.current_state_or_none() != ProductionFilterState():
            if not self._confirm_discard(
                "Reset filter draft?",
                "Resetting will discard the filter changes you have not applied.",
            ):
                return
        self.clear_filters()

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
        self._populate_from_state(self._committed_filter_state)
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

    def current_state_or_none(self) -> ProductionFilterState | None:
        try:
            return self.current_state()
        except ValueError:
            return None

    def accept(self) -> None:
        try:
            state = self.current_state()
        except ValueError as exc:
            self.validation_error_label.setText(str(exc))
            self.validation_error_label.show()
            self.apply_button.setEnabled(False)
            return
        self.filter_state = state
        self._committed_filter_state = state
        super().accept()


def _active_condition_count(state: ProductionFilterState) -> int:
    fixed_conditions = (
        state.source_profile_ids,
        state.source_db_aliases,
        state.time_start,
        state.time_end,
        state.references,
        state.part_numbers,
        state.part_names,
        state.revisions,
        state.serials,
        state.batch_lots,
        state.work_orders,
        state.stations,
        state.lines,
        state.operators,
        state.process_statuses,
    )
    return sum(bool(value) for value in fixed_conditions) + len(state.dynamic_filters)


def _parse_int_values(value: str) -> tuple[int, ...]:
    values = []
    for item in parse_reference_values(value):
        try:
            values.append(int(item))
        except ValueError as exc:
            raise ValueError(f"Source profile id must be a number: {item}") from exc
    return tuple(values)


def _parse_dynamic_filters(value: str) -> tuple[DynamicFieldFilter, ...]:
    filters = []
    for line_number, raw_line in enumerate(str(value or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        field_name, operator, raw_value = _parse_dynamic_filter_line(line, line_number=line_number)
        if operator in {"is_null", "is_not_null"}:
            filters.append(DynamicFieldFilter(field_name, operator))
        elif operator in {"in", "not_in"}:
            filters.append(
                DynamicFieldFilter(
                    field_name,
                    operator,
                    values=parse_reference_values(raw_value or ""),
                )
            )
        else:
            filters.append(DynamicFieldFilter(field_name, operator, raw_value))
    return tuple(filters)


def _parse_dynamic_filter_line(
    line: str,
    *,
    line_number: int,
) -> tuple[str, str, str | None]:
    if "=" in line and " " not in line.split("=", 1)[0]:
        field_name, raw_value = line.split("=", 1)
        return field_name.strip(), "eq", raw_value.strip()
    parts = line.split(maxsplit=2)
    if len(parts) < 2:
        raise ValueError(f"Dynamic filter line {line_number} needs at least a field and operator.")
    field_name = parts[0].strip()
    operator = parts[1].strip().lower()
    raw_value = parts[2].strip() if len(parts) > 2 else None
    if operator not in {"is_null", "is_not_null"} and not raw_value:
        raise ValueError(f"Dynamic filter line {line_number} needs a value.")
    return field_name, operator, raw_value


def _dynamic_filters_to_text(filters: tuple[DynamicFieldFilter, ...]) -> str:
    rows = []
    for dynamic_filter in filters:
        if dynamic_filter.operator in {"is_null", "is_not_null"}:
            rows.append(f"{dynamic_filter.field_name} {dynamic_filter.operator}")
        elif dynamic_filter.operator in {"in", "not_in"}:
            rows.append(
                f"{dynamic_filter.field_name} {dynamic_filter.operator} "
                + ", ".join(str(value) for value in dynamic_filter.values)
            )
        else:
            rows.append(f"{dynamic_filter.field_name} {dynamic_filter.operator} {dynamic_filter.value}")
    return "\n".join(rows)


__all__ = [
    "IndustrialAnalyticsFilterDialog",
]
