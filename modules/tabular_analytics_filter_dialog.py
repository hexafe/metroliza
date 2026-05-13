"""Visual row filter dialog for CSV/Excel analytics inputs."""

from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from modules.csv_summary_utils import CsvGroupingIndex
from modules.help_menu import attach_help_menu_to_layout
from modules.list_selection_utils import ListSelectionUtils
from modules.tabular_analytics_service import (
    TabularColumnFilter,
    apply_tabular_row_filter,
    selectable_tabular_source_columns,
)
from modules.ui_foundation import (
    apply_list_selection_style,
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    section_label,
    set_status_variant,
    status_chip,
)


_MAX_VISIBLE_MATCHES = 1000


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
        column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("CSV / Excel row filter")
        configure_window_size(self, minimum=(860, 560), initial=(1060, 720))

        self.source_dataframe = dataframe.copy() if isinstance(dataframe, pd.DataFrame) else pd.DataFrame()
        self.column_labels = {
            normalized: original
            for original, normalized in (column_mapping or {}).items()
            if isinstance(normalized, str) and isinstance(original, str)
        }
        initial_filters = tuple(column_filters or ())
        self.filter_columns: list[str] = []
        self.value_filters: dict[str, set[str]] = {}
        self.date_filters: dict[str, dict[str, str | None]] = {}
        self._date_filterable_cache: dict[str, bool] = {}
        self._value_index_by_column: dict[str, CsvGroupingIndex] = {}
        self._list_selection_utils = ListSelectionUtils()
        self._syncing_current_filter = False
        if initial_filters:
            self._load_column_filters(initial_filters)
        else:
            self._load_legacy_filter(filter_columns, selected_filter_keys)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("CSV Summary manual", "csv_summary")])

        self.status_label = status_chip("No row filter selected", "neutral")
        layout.addWidget(section_label("Column filters"))
        layout.addWidget(self.status_label)

        columns_grid = QGridLayout()
        columns_grid.setContentsMargins(0, 0, 0, 0)
        columns_grid.setHorizontalSpacing(10)
        columns_grid.setVerticalSpacing(6)
        columns_grid.addWidget(QLabel("Available columns"), 0, 0)
        columns_grid.addWidget(QLabel("Selected columns"), 0, 1)

        self.column_search = QLineEdit()
        self.column_search.setPlaceholderText("Search columns")
        self.selected_column_search = QLineEdit()
        self.selected_column_search.setPlaceholderText("Search selected columns")
        columns_grid.addWidget(self.column_search, 1, 0)
        columns_grid.addWidget(self.selected_column_search, 1, 1)

        self.column_list = QListWidget()
        self.selected_columns_list = QListWidget()
        for list_widget in (self.column_list, self.selected_columns_list):
            apply_list_selection_style(list_widget)
            list_widget.setMinimumHeight(160)
            list_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        configure_accessibility(self.column_search, name="Search CSV filter columns")
        configure_accessibility(self.selected_column_search, name="Search selected CSV filter columns")
        configure_accessibility(self.column_list, name="Available CSV filter columns")
        configure_accessibility(self.selected_columns_list, name="Selected CSV filter columns")
        columns_grid.addWidget(self.column_list, 2, 0)
        columns_grid.addWidget(self.selected_columns_list, 2, 1)
        columns_grid.setColumnStretch(0, 1)
        columns_grid.setColumnStretch(1, 1)
        layout.addLayout(columns_grid, 1)

        column_actions = QHBoxLayout()
        column_actions.setSpacing(8)
        self.add_column_button = QPushButton("Add column")
        self.remove_column_button = QPushButton("Remove selected column")
        self.clear_columns_button = QPushButton("Clear columns")
        column_actions.addWidget(self.add_column_button)
        column_actions.addWidget(self.remove_column_button)
        column_actions.addWidget(self.clear_columns_button)
        column_actions.addStretch(1)
        layout.addLayout(column_actions)

        layout.addWidget(QLabel("Values for selected column"))
        self.matching_search = QLineEdit()
        self.matching_search.setPlaceholderText("Search values in selected column")
        configure_accessibility(self.matching_search, name="Search CSV row-filter values")
        layout.addWidget(self.matching_search)
        self.matching_status_label = status_chip("", "neutral")
        layout.addWidget(self.matching_status_label)
        self.matching_list = QListWidget()
        self.matching_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        apply_list_selection_style(self.matching_list)
        self.matching_list.setMinimumHeight(190)
        self.matching_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        configure_accessibility(self.matching_list, name="CSV row-filter values")
        layout.addWidget(self.matching_list, 2)

        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        self.date_mode_combo = QComboBox()
        self.date_mode_combo.addItem("Any date", "any")
        self.date_mode_combo.addItem("On or after", "from")
        self.date_mode_combo.addItem("On or before", "to")
        self.date_mode_combo.addItem("Between", "between")
        self.date_from_calendar = QDateEdit(calendarPopup=True)
        self.date_from_calendar.setCalendarPopup(True)
        self.date_from_calendar.setDisplayFormat("yyyy-MM-dd")
        self.date_to_calendar = QDateEdit(calendarPopup=True)
        self.date_to_calendar.setCalendarPopup(True)
        self.date_to_calendar.setDisplayFormat("yyyy-MM-dd")
        configure_accessibility(self.date_mode_combo, name="CSV date filter mode")
        configure_accessibility(self.date_from_calendar, name="CSV date filter from")
        configure_accessibility(self.date_to_calendar, name="CSV date filter to")
        self.date_filter_label = QLabel("Date")
        date_row.addWidget(self.date_filter_label)
        date_row.addWidget(self.date_mode_combo)
        date_row.addWidget(self.date_from_calendar)
        date_row.addWidget(self.date_to_calendar)
        date_row.addStretch(1)
        self.date_filter_widgets = (
            self.date_filter_label,
            self.date_mode_combo,
            self.date_from_calendar,
            self.date_to_calendar,
        )
        layout.addLayout(date_row)

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
        self.selected_column_search.textChanged.connect(self._refresh_selected_columns)
        self.column_list.itemDoubleClicked.connect(lambda _item: self.add_filter_column())
        self.selected_columns_list.itemSelectionChanged.connect(self._handle_selected_column_changed)
        self.selected_columns_list.itemDoubleClicked.connect(lambda _item: self.remove_selected_filter_column())
        self.add_column_button.clicked.connect(self.add_filter_column)
        self.remove_column_button.clicked.connect(self.remove_selected_filter_column)
        self.clear_columns_button.clicked.connect(self.clear_filter_columns)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.clear_filter_button.clicked.connect(self.clear_filter)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.accept)
        self.matching_search.textChanged.connect(self._refresh_values)
        self.matching_list.itemSelectionChanged.connect(self._store_current_selection)
        self.date_mode_combo.currentIndexChanged.connect(self._store_current_date_filter)
        self.date_from_calendar.dateChanged.connect(self._store_current_date_filter)
        self.date_to_calendar.dateChanged.connect(self._store_current_date_filter)

        apply_metroliza_theme(self)
        self._list_selection_utils.connect_shift_range_behavior(self.matching_list)
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

    def _load_column_filters(self, column_filters: tuple[TabularColumnFilter, ...]) -> None:
        for item in column_filters:
            if not isinstance(item, TabularColumnFilter) or item.column not in self.source_dataframe.columns:
                continue
            column = str(item.column)
            if column not in self.filter_columns:
                self.filter_columns.append(column)
            self.value_filters[column] = set(item.selected_values)
            self.date_filters[column] = {
                "mode": item.date_mode if item.date_mode in {"from", "to", "between"} else "any",
                "from": item.date_from,
                "to": item.date_to,
            }

    def _load_legacy_filter(self, filter_columns, selected_filter_keys) -> None:
        columns = [column for column in (filter_columns or ()) if column in self.source_dataframe.columns]
        self.filter_columns = list(columns)
        for index, column in enumerate(columns):
            values = {
                str(key[index])
                for key in (selected_filter_keys or ())
                if isinstance(key, (list, tuple)) and len(key) == len(columns)
            }
            self.value_filters[column] = values
            self.date_filters[column] = {"mode": "any", "from": None, "to": None}

    def _current_filter_column(self) -> str | None:
        item = self.selected_columns_list.currentItem()
        if item is None:
            return None
        column = item.data(Qt.ItemDataRole.UserRole)
        return str(column) if column is not None else None

    def _filter_for_column(self, column: str) -> TabularColumnFilter:
        date_filter = self.date_filters.get(column, {})
        return TabularColumnFilter(
            column=column,
            selected_values=tuple(sorted(self.value_filters.get(column, set()))),
            date_mode=str(date_filter.get("mode") or "any"),
            date_from=date_filter.get("from"),
            date_to=date_filter.get("to"),
        )

    def _active_column_filters(self) -> tuple[TabularColumnFilter, ...]:
        return tuple(
            item for item in (self._filter_for_column(column) for column in self.filter_columns)
            if item.is_active
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

    def _refresh_selected_columns(self) -> None:
        current_column = self._current_filter_column()
        search = self.selected_column_search.text().strip().casefold()
        self.selected_columns_list.blockSignals(True)
        self.selected_columns_list.clear()
        for column in self.filter_columns:
            label = self._selected_column_label(column)
            if search and search not in label.casefold() and search not in column.casefold():
                continue
            self.selected_columns_list.addItem(label)
            item = self.selected_columns_list.item(self.selected_columns_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, column)
            if column == current_column:
                item.setSelected(True)
                self.selected_columns_list.setCurrentItem(item)
        if self.selected_columns_list.currentItem() is None and self.selected_columns_list.count():
            self.selected_columns_list.setCurrentRow(0)
        self.selected_columns_list.blockSignals(False)

    def _selected_column_label(self, column: str) -> str:
        column_filter = self._filter_for_column(column)
        details: list[str] = []
        if column_filter.selected_values:
            details.append(f"{len(column_filter.selected_values)} value(s)")
        if column_filter.has_date_filter:
            if column_filter.date_mode == "from":
                details.append(f">= {column_filter.date_from}")
            elif column_filter.date_mode == "to":
                details.append(f"<= {column_filter.date_to}")
            elif column_filter.date_mode == "between":
                details.append(f"{column_filter.date_from} to {column_filter.date_to}")
        suffix = f": {', '.join(details)}" if details else ": all values"
        return f"{self._column_label(column)}{suffix}"

    def add_filter_column(self) -> None:
        item = self.column_list.currentItem()
        if item is None:
            return
        column = item.data(Qt.ItemDataRole.UserRole)
        if not column or column in self.filter_columns:
            return
        column = str(column)
        self.filter_columns.append(column)
        self.value_filters.setdefault(column, set())
        self.date_filters.setdefault(column, {"mode": "any", "from": None, "to": None})
        self._refresh_all()
        self._set_current_selected_column(column)

    def remove_selected_filter_column(self) -> None:
        column = self._current_filter_column()
        if column is None and self.filter_columns:
            column = self.filter_columns[-1]
        if column is None or column not in self.filter_columns:
            return
        self.filter_columns.remove(column)
        self.value_filters.pop(column, None)
        self.date_filters.pop(column, None)
        self._value_index_by_column.pop(column, None)
        self._refresh_all()

    def clear_filter_columns(self) -> None:
        self.filter_columns = []
        self.value_filters = {}
        self.date_filters = {}
        self._value_index_by_column = {}
        self._refresh_all()

    def clear_selection(self) -> None:
        column = self._current_filter_column()
        if column is not None:
            self.value_filters[column] = set()
        self.matching_list.clearSelection()
        self._store_current_date_filter(force_clear=True)
        self._refresh_all()

    def clear_filter(self) -> None:
        self.filter_columns = []
        self.value_filters = {}
        self.date_filters = {}
        self._value_index_by_column = {}
        self._refresh_all()

    def _store_current_selection(self) -> None:
        if self._syncing_current_filter:
            return
        column = self._current_filter_column()
        if column is None:
            return
        visible_values = {
            str(self.matching_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.matching_list.count())
        }
        selected_visible_values = {
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self.matching_list.selectedItems()
        }
        existing = set(self.value_filters.get(column, set()))
        self.value_filters[column] = (existing - visible_values) | selected_visible_values
        self._refresh_selected_columns()
        self._sync_status()

    def _handle_selected_column_changed(self) -> None:
        self._refresh_values()
        self._sync_date_controls()
        self._sync_status()

    def _set_current_selected_column(self, column: str) -> None:
        for index in range(self.selected_columns_list.count()):
            item = self.selected_columns_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == column:
                self.selected_columns_list.setCurrentItem(item)
                return

    def _value_index(self, column: str) -> CsvGroupingIndex:
        index = self._value_index_by_column.get(column)
        if index is None:
            index = CsvGroupingIndex(self.source_dataframe, (column,))
            self._value_index_by_column[column] = index
        return index

    def _refresh_values(self) -> None:
        column = self._current_filter_column()
        self._syncing_current_filter = True
        self.matching_list.blockSignals(True)
        self.matching_list.clear()
        if column is None:
            self.matching_status_label.setText("Add a filter column to preview values.")
            set_status_variant(self.matching_status_label, "neutral")
            self.matching_list.blockSignals(False)
            self._syncing_current_filter = False
            return
        preview_rows, total_rows = self._value_index(column).preview_rows(
            search_text=self.matching_search.text(),
            limit=_MAX_VISIBLE_MATCHES,
        )
        selected_values = set(self.value_filters.get(column, set()))
        for row in preview_rows:
            self.matching_list.addItem(f"{row['label']} (n={row['row_count']})")
            item = self.matching_list.item(self.matching_list.count() - 1)
            value = str(tuple(row["key"])[0])
            item.setData(Qt.ItemDataRole.UserRole, value)
            if value in selected_values:
                item.setSelected(True)
        self.matching_list.blockSignals(False)
        self._syncing_current_filter = False
        if total_rows > len(preview_rows):
            self.matching_status_label.setText(
                f"Showing {len(preview_rows)} of {total_rows} value(s). Search to narrow."
            )
            set_status_variant(self.matching_status_label, "warning")
        else:
            self.matching_status_label.setText(f"Showing {total_rows} value(s).")
            set_status_variant(self.matching_status_label, "info" if total_rows else "warning")

    def _is_date_filterable(self, column: str | None) -> bool:
        if not column or column not in self.source_dataframe.columns:
            return False
        cached = self._date_filterable_cache.get(column)
        if cached is not None:
            return cached
        series = self.source_dataframe[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            self._date_filterable_cache[column] = True
            return True
        if pd.api.types.is_numeric_dtype(series):
            self._date_filterable_cache[column] = False
            return False
        column_key = column.casefold()
        if not any(token in column_key for token in ("date", "time", "timestamp", "created", "updated")):
            self._date_filterable_cache[column] = False
            return False
        sample = series.dropna().head(200)
        if sample.empty:
            self._date_filterable_cache[column] = False
            return False
        parsed = pd.to_datetime(sample, errors="coerce")
        is_date = bool(parsed.notna().mean() >= 0.6)
        self._date_filterable_cache[column] = is_date
        return is_date

    def _column_date_bounds(self, column: str) -> tuple[QDate, QDate]:
        parsed = pd.to_datetime(self.source_dataframe[column], errors="coerce").dropna()
        if parsed.empty:
            today = QDate.currentDate()
            return today, today
        start = parsed.min().date()
        end = parsed.max().date()
        return QDate(start.year, start.month, start.day), QDate(end.year, end.month, end.day)

    def _qdate_to_text(self, value: QDate) -> str:
        return value.toString("yyyy-MM-dd")

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

    def _sync_date_controls(self) -> None:
        column = self._current_filter_column()
        is_date = self._is_date_filterable(column)
        for widget in self.date_filter_widgets:
            widget.setVisible(is_date)
        if not is_date or column is None:
            return
        lower, upper = self._column_date_bounds(column)
        date_filter = self.date_filters.setdefault(column, {"mode": "any", "from": None, "to": None})
        self._syncing_current_filter = True
        self.date_from_calendar.setDate(
            QDate.fromString(str(date_filter.get("from") or ""), "yyyy-MM-dd")
            if date_filter.get("from")
            else lower
        )
        if not self.date_from_calendar.date().isValid():
            self.date_from_calendar.setDate(lower)
        self.date_to_calendar.setDate(
            QDate.fromString(str(date_filter.get("to") or ""), "yyyy-MM-dd")
            if date_filter.get("to")
            else upper
        )
        if not self.date_to_calendar.date().isValid():
            self.date_to_calendar.setDate(upper)
        self._set_combo_data(self.date_mode_combo, str(date_filter.get("mode") or "any"))
        self._syncing_current_filter = False

    def _store_current_date_filter(self, *_args, force_clear: bool = False) -> None:
        if self._syncing_current_filter:
            return
        column = self._current_filter_column()
        if column is None:
            return
        if force_clear:
            self.date_filters[column] = {"mode": "any", "from": None, "to": None}
        else:
            mode = str(self.date_mode_combo.currentData() or "any")
            self.date_filters[column] = {
                "mode": mode,
                "from": self._qdate_to_text(self.date_from_calendar.date()) if mode in {"from", "between"} else None,
                "to": self._qdate_to_text(self.date_to_calendar.date()) if mode in {"to", "between"} else None,
            }
        self._refresh_selected_columns()
        self._sync_status()

    def _sync_status(self) -> None:
        active_filters = self._active_column_filters()
        if not self.filter_columns:
            self.status_label.setText("No row filter selected")
            set_status_variant(self.status_label, "neutral")
        elif active_filters:
            row_count = len(
                apply_tabular_row_filter(self.source_dataframe, column_filters=active_filters).dataframe.index
            )
            self.status_label.setText(f"{len(active_filters)} column filter(s), {row_count} rows")
            set_status_variant(self.status_label, "success" if row_count else "danger")
        else:
            self.status_label.setText(f"{self._filter_columns_text()}: all rows")
            set_status_variant(self.status_label, "info")
        self.remove_column_button.setEnabled(bool(self.filter_columns))
        self.clear_columns_button.setEnabled(bool(self.filter_columns))
        current_column = self._current_filter_column()
        self.clear_selection_button.setEnabled(
            bool(current_column and self._filter_for_column(current_column).is_active)
        )
        self.clear_filter_button.setEnabled(bool(self.filter_columns or active_filters))

    def _refresh_all(self) -> None:
        self._refresh_available_columns()
        self._refresh_selected_columns()
        self._refresh_values()
        self._sync_date_controls()
        self._sync_status()

    def get_column_filters(self) -> tuple[TabularColumnFilter, ...]:
        return self._active_column_filters()

    def get_filter(self) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
        active_filters = self._active_column_filters()
        if not active_filters:
            return (), ()
        filtered = apply_tabular_row_filter(self.source_dataframe, column_filters=active_filters).dataframe
        columns = tuple(item.column for item in active_filters)
        if filtered.empty:
            return columns, ()
        preview_rows, _total = CsvGroupingIndex(filtered, columns).preview_rows()
        keys = {tuple(row["key"]) for row in preview_rows}
        return columns, tuple(sorted(keys))


__all__ = ["TabularAnalyticsFilterDialog"]
