"""Visual row filter dialog for CSV/Excel analytics inputs."""

from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from modules.csv_summary_utils import build_csv_grouping_preview, filter_csv_summary_by_group_keys
from modules.help_menu import attach_help_menu_to_layout
from modules.tabular_analytics_service import selectable_tabular_source_columns
from modules.ui_foundation import (
    apply_list_selection_style,
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    section_label,
    set_status_variant,
    status_chip,
)


class TabularAnalyticsFilterDialog(QDialog):
    """Select CSV/Excel rows through user-selected source-column combinations."""

    def __init__(
        self,
        parent=None,
        *,
        dataframe: pd.DataFrame | None = None,
        column_mapping: dict[str, str] | None = None,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("CSV / Excel row filter")
        configure_window_size(self, minimum=(680, 420), initial=(860, 580))

        self.source_dataframe = dataframe.copy() if isinstance(dataframe, pd.DataFrame) else pd.DataFrame()
        self.column_labels = {
            normalized: original
            for original, normalized in (column_mapping or {}).items()
            if isinstance(normalized, str) and isinstance(original, str)
        }
        self.filter_columns = [
            column for column in (filter_columns or ()) if column in self.source_dataframe.columns
        ]
        self.selected_filter_keys = {
            tuple(str(part) for part in key)
            for key in (selected_filter_keys or ())
            if isinstance(key, (list, tuple)) and len(key) == len(self.filter_columns)
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("CSV Summary manual", "csv_summary")])

        self.status_label = status_chip("No row filter selected", "neutral")
        layout.addWidget(section_label("Filter columns"))
        layout.addWidget(self.status_label)

        picker_row = QHBoxLayout()
        picker_row.setSpacing(8)
        self.column_search = QLineEdit()
        self.column_search.setPlaceholderText("Search columns")
        self.column_list = QListWidget()
        self.column_list.setMaximumHeight(110)
        apply_list_selection_style(self.column_list)
        configure_accessibility(self.column_search, name="Search CSV filter columns")
        configure_accessibility(self.column_list, name="Available CSV filter columns")
        picker_row.addWidget(self.column_search, 1)
        layout.addLayout(picker_row)
        layout.addWidget(self.column_list)

        column_actions = QHBoxLayout()
        column_actions.setSpacing(8)
        self.add_column_button = QPushButton("Add column")
        self.remove_column_button = QPushButton("Remove last")
        self.clear_columns_button = QPushButton("Clear columns")
        column_actions.addWidget(self.add_column_button)
        column_actions.addWidget(self.remove_column_button)
        column_actions.addWidget(self.clear_columns_button)
        column_actions.addStretch(1)
        layout.addLayout(column_actions)

        layout.addWidget(QLabel("Matching rows"))
        self.matching_list = QListWidget()
        self.matching_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        apply_list_selection_style(self.matching_list)
        configure_accessibility(self.matching_list, name="CSV row-filter matches")
        layout.addWidget(self.matching_list, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.clear_selection_button = QPushButton("Clear selection")
        self.clear_filter_button = QPushButton("Clear filter")
        self.cancel_button = QPushButton("Cancel")
        self.apply_button = QPushButton("Apply filter")
        self.apply_button.setDefault(True)
        footer.addWidget(self.clear_selection_button)
        footer.addWidget(self.clear_filter_button)
        footer.addStretch(1)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)

        self.column_search.textChanged.connect(self._refresh_available_columns)
        self.column_list.itemDoubleClicked.connect(lambda _item: self.add_filter_column())
        self.add_column_button.clicked.connect(self.add_filter_column)
        self.remove_column_button.clicked.connect(self.remove_last_filter_column)
        self.clear_columns_button.clicked.connect(self.clear_filter_columns)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.clear_filter_button.clicked.connect(self.clear_filter)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.accept)
        self.matching_list.itemSelectionChanged.connect(self._store_current_selection)

        apply_metroliza_theme(self)
        self._refresh_all()

    def _source_columns(self) -> list[str]:
        return selectable_tabular_source_columns(
            self.source_dataframe,
            normalized_source_columns=set(self.column_labels),
        )

    def _available_columns(self) -> list[str]:
        return [column for column in self._source_columns() if column not in self.filter_columns]

    def _column_label(self, column: str) -> str:
        label = str(self.column_labels.get(column, column)).strip()
        return label if label else column

    def _filter_columns_text(self) -> str:
        return " | ".join(self._column_label(column) for column in self.filter_columns)

    def _filtered_source_for_next_level(self) -> pd.DataFrame:
        return filter_csv_summary_by_group_keys(
            self.source_dataframe,
            self.filter_columns,
            list(self.selected_filter_keys),
        )

    def _refresh_available_columns(self) -> None:
        search = self.column_search.text().strip().casefold()
        self.column_list.clear()
        for column in self._available_columns():
            label = self._column_label(column)
            if search and search not in label.casefold() and search not in column.casefold():
                continue
            self.column_list.addItem(label)
            item = self.column_list.item(self.column_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, column)
        if self.column_list.count():
            self.column_list.setCurrentRow(0)
        self.add_column_button.setEnabled(self.column_list.count() > 0)

    def add_filter_column(self) -> None:
        item = self.column_list.currentItem()
        if item is None:
            return
        column = item.data(Qt.ItemDataRole.UserRole)
        if not column or column in self.filter_columns:
            return
        filtered_source = self._filtered_source_for_next_level()
        previous_filter_active = bool(self.selected_filter_keys)
        self.filter_columns.append(str(column))
        if previous_filter_active:
            preview_rows = build_csv_grouping_preview(filtered_source, self.filter_columns)
            self.selected_filter_keys = {tuple(row["key"]) for row in preview_rows}
        else:
            self.selected_filter_keys = set()
        self._refresh_all()

    def remove_last_filter_column(self) -> None:
        if not self.filter_columns:
            return
        self.filter_columns.pop()
        if not self.filter_columns:
            self.selected_filter_keys = set()
        else:
            self.selected_filter_keys = {
                tuple(key[: len(self.filter_columns)])
                for key in self.selected_filter_keys
                if len(key) >= len(self.filter_columns)
            }
        self._refresh_all()

    def clear_filter_columns(self) -> None:
        self.filter_columns = []
        self.selected_filter_keys = set()
        self._refresh_all()

    def clear_selection(self) -> None:
        self.selected_filter_keys = set()
        self.matching_list.clearSelection()
        self._sync_status()

    def clear_filter(self) -> None:
        self.filter_columns = []
        self.selected_filter_keys = set()
        self._refresh_all()

    def _store_current_selection(self) -> None:
        self.selected_filter_keys = {
            tuple(item.data(Qt.ItemDataRole.UserRole))
            for item in self.matching_list.selectedItems()
        }
        self._sync_status()

    def _refresh_matches(self) -> None:
        self.matching_list.blockSignals(True)
        self.matching_list.clear()
        preview_rows = build_csv_grouping_preview(self.source_dataframe, self.filter_columns)
        selected_keys = set(self.selected_filter_keys)
        for row in preview_rows:
            self.matching_list.addItem(f"{row['label']} (n={row['row_count']})")
            item = self.matching_list.item(self.matching_list.count() - 1)
            key = tuple(row["key"])
            item.setData(Qt.ItemDataRole.UserRole, key)
            if key in selected_keys:
                item.setSelected(True)
        self.matching_list.blockSignals(False)

    def _sync_status(self) -> None:
        if not self.filter_columns:
            self.status_label.setText("No row filter selected")
            set_status_variant(self.status_label, "neutral")
        elif self.selected_filter_keys:
            row_count = len(
                filter_csv_summary_by_group_keys(
                    self.source_dataframe,
                    self.filter_columns,
                    list(self.selected_filter_keys),
                ).index
            )
            self.status_label.setText(
                f"{self._filter_columns_text()}: {len(self.selected_filter_keys)} selected, {row_count} rows"
            )
            set_status_variant(self.status_label, "success" if row_count else "danger")
        else:
            self.status_label.setText(f"{self._filter_columns_text()}: all rows")
            set_status_variant(self.status_label, "info")
        self.remove_column_button.setEnabled(bool(self.filter_columns))
        self.clear_columns_button.setEnabled(bool(self.filter_columns))
        self.clear_selection_button.setEnabled(bool(self.selected_filter_keys))
        self.clear_filter_button.setEnabled(bool(self.filter_columns or self.selected_filter_keys))

    def _refresh_all(self) -> None:
        self._refresh_available_columns()
        self._refresh_matches()
        self._sync_status()

    def get_filter(self) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
        return tuple(self.filter_columns), tuple(sorted(self.selected_filter_keys))


__all__ = ["TabularAnalyticsFilterDialog"]
