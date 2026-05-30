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
    configure_window_size,
    section_label,
    secondary_label,
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

        self.apply_button = QPushButton("Apply filters")
        self.clear_button = QPushButton("Clear")
        self.cancel_button = QPushButton("Cancel")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self.accept)
        self.clear_button.clicked.connect(self.clear_filters)
        self.cancel_button.clicked.connect(self.reject)

        self._build_layout()
        self._populate_from_state(self.filter_state)
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

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

        layout.addWidget(section_label("Dynamic fields"))
        layout.addWidget(
            secondary_label("Use one rule per line: field operator value. Supported operators match the analytics service.")
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

    def accept(self) -> None:
        try:
            self.filter_state = self.current_state()
        except ValueError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()


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
