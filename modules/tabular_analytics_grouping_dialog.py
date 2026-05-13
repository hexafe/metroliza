"""In-memory CSV/Excel grouping dialog for tabular analytics."""

from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from modules.csv_summary_utils import CsvGroupingIndex
from modules.help_menu import attach_help_menu_to_layout
from modules.list_selection_utils import ListSelectionUtils
from modules.tabular_analytics_service import (
    TABULAR_DEFAULT_GROUP,
    build_tabular_grouping_dataframe,
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


_SELECTOR_PAGE_SIZE = 1000


class TabularAnalyticsGroupingDialog(QDialog):
    """Create manual row groups from user-selected CSV/Excel selector columns."""

    def __init__(
        self,
        parent=None,
        *,
        dataframe: pd.DataFrame | None = None,
        column_mapping: dict[str, str] | None = None,
        grouping_dataframe: pd.DataFrame | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("CSV / Excel groups")
        configure_window_size(self, minimum=(720, 440), initial=(900, 620))
        self.source_dataframe = dataframe.copy() if isinstance(dataframe, pd.DataFrame) else pd.DataFrame()
        self.column_labels = {
            normalized: original
            for original, normalized in (column_mapping or {}).items()
            if isinstance(normalized, str) and isinstance(original, str)
        }
        self.selector_columns: list[str] = []
        self.selected_selector_keys: set[tuple[str, ...]] = set()
        self._selector_index: CsvGroupingIndex | None = None
        self._selector_page_offset = 0
        self._selector_total_rows = 0
        self._list_selection_utils = ListSelectionUtils()
        self.default_group = TABULAR_DEFAULT_GROUP
        self._initial_group_assignments = self._group_assignments(grouping_dataframe)
        self.df = self._build_grouping_dataframe()
        self._apply_group_assignments(self._initial_group_assignments)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("CSV Summary manual", "csv_summary")])

        self.selector_status_label = status_chip("No grouping columns selected", "neutral")
        layout.addWidget(section_label("Grouping columns"))
        layout.addWidget(self.selector_status_label)

        column_area = QWidget()
        columns_grid = QGridLayout(column_area)
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

        self.available_columns_list = QListWidget()
        self.selected_columns_list = QListWidget()
        for list_widget in (self.available_columns_list, self.selected_columns_list):
            apply_list_selection_style(list_widget)
            list_widget.setMinimumHeight(150)
            list_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.selected_columns_list.setMinimumHeight(150)
        configure_accessibility(self.column_search, name="Search CSV grouping columns")
        configure_accessibility(self.selected_column_search, name="Search selected CSV grouping columns")
        configure_accessibility(self.available_columns_list, name="Available CSV grouping columns")
        configure_accessibility(self.selected_columns_list, name="Selected CSV grouping columns")
        columns_grid.addWidget(self.available_columns_list, 2, 0)
        columns_grid.addWidget(self.selected_columns_list, 2, 1)
        columns_grid.setColumnStretch(0, 1)
        columns_grid.setColumnStretch(1, 1)
        layout.addWidget(column_area, 1)

        selector_actions = QHBoxLayout()
        selector_actions.setSpacing(8)
        self.add_column_button = QPushButton("Add column")
        self.remove_column_button = QPushButton("Remove selected column")
        self.clear_columns_button = QPushButton("Clear columns")
        selector_actions.addWidget(self.add_column_button)
        selector_actions.addWidget(self.remove_column_button)
        selector_actions.addWidget(self.clear_columns_button)
        selector_actions.addStretch(1)
        layout.addLayout(selector_actions)

        list_splitter = QSplitter(Qt.Orientation.Horizontal)

        selector_widget = QWidget()
        selector_column = QVBoxLayout(selector_widget)
        selector_column.setContentsMargins(0, 0, 0, 0)
        selector_column.setSpacing(6)
        selector_column.addWidget(QLabel("Matching rows"))
        self.selector_search = QLineEdit()
        self.selector_search.setPlaceholderText("Search matching row values")
        configure_accessibility(self.selector_search, name="Search CSV grouping row selectors")
        selector_column.addWidget(self.selector_search)
        self.selector_preview_label = status_chip("", "neutral")
        selector_column.addWidget(self.selector_preview_label)
        self.selector_list = QListWidget()
        self.selector_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        apply_list_selection_style(self.selector_list)
        self.selector_list.setMinimumHeight(220)
        self.selector_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        configure_accessibility(self.selector_list, name="CSV grouping row selectors")
        selector_column.addWidget(self.selector_list)
        selector_paging = QHBoxLayout()
        selector_paging.setSpacing(8)
        self.select_visible_button = QPushButton("Select visible")
        self.select_all_matching_button = QPushButton("Select all matching")
        self.clear_matching_button = QPushButton("Clear matching")
        self.previous_page_button = QPushButton("Previous")
        self.next_page_button = QPushButton("Next")
        self.selector_page_label = status_chip("", "neutral")
        selector_paging.addWidget(self.select_visible_button)
        selector_paging.addWidget(self.select_all_matching_button)
        selector_paging.addWidget(self.clear_matching_button)
        selector_paging.addStretch(1)
        selector_paging.addWidget(self.previous_page_button)
        selector_paging.addWidget(self.next_page_button)
        selector_column.addLayout(selector_paging)
        selector_column.addWidget(self.selector_page_label)
        list_splitter.addWidget(selector_widget)

        groups_widget = QWidget()
        groups_column = QVBoxLayout(groups_widget)
        groups_column.setContentsMargins(0, 0, 0, 0)
        groups_column.setSpacing(6)
        groups_column.addWidget(QLabel("Groups"))
        self.groups_list = QListWidget()
        apply_list_selection_style(self.groups_list)
        self.groups_list.setMinimumHeight(220)
        self.groups_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        configure_accessibility(self.groups_list, name="CSV analytics groups")
        groups_column.addWidget(self.groups_list)
        list_splitter.addWidget(groups_widget)

        members_widget = QWidget()
        members_column = QVBoxLayout(members_widget)
        members_column.setContentsMargins(0, 0, 0, 0)
        members_column.setSpacing(6)
        members_column.addWidget(QLabel("Rows in selected group"))
        self.group_members_list = QListWidget()
        apply_list_selection_style(self.group_members_list)
        self.group_members_list.setMinimumHeight(220)
        self.group_members_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        configure_accessibility(self.group_members_list, name="Rows in selected CSV group")
        members_column.addWidget(self.group_members_list)
        list_splitter.addWidget(members_widget)
        list_splitter.setStretchFactor(0, 2)
        list_splitter.setStretchFactor(1, 1)
        list_splitter.setStretchFactor(2, 2)

        layout.addWidget(list_splitter, 3)

        group_actions = QHBoxLayout()
        group_actions.setSpacing(8)
        self.create_group_button = QPushButton("Create or add")
        self.rename_group_button = QPushButton("Rename group")
        self.delete_group_button = QPushButton("Delete group")
        self.clear_selection_button = QPushButton("Clear selection")
        group_actions.addWidget(self.create_group_button)
        group_actions.addWidget(self.rename_group_button)
        group_actions.addWidget(self.delete_group_button)
        group_actions.addWidget(self.clear_selection_button)
        group_actions.addStretch(1)
        layout.addLayout(group_actions)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.use_grouping_button = QPushButton("Use grouping")
        self.dont_use_grouping_button = QPushButton("Clear grouping")
        footer.addStretch(1)
        footer.addWidget(self.dont_use_grouping_button)
        footer.addWidget(self.use_grouping_button)
        layout.addLayout(footer)

        self.column_search.textChanged.connect(self._refresh_available_columns)
        self.selected_column_search.textChanged.connect(self._refresh_selected_columns)
        self.available_columns_list.itemDoubleClicked.connect(lambda _item: self.add_selector_column())
        self.selected_columns_list.itemDoubleClicked.connect(lambda _item: self.remove_selected_selector_column())
        self.selected_columns_list.itemSelectionChanged.connect(self._sync_status)
        self.selector_search.textChanged.connect(self._handle_selector_search_changed)
        self.add_column_button.clicked.connect(self.add_selector_column)
        self.remove_column_button.clicked.connect(self.remove_selected_selector_column)
        self.clear_columns_button.clicked.connect(self.clear_selector_columns)
        self.select_visible_button.clicked.connect(self.select_visible_matching)
        self.select_all_matching_button.clicked.connect(self.select_all_matching)
        self.clear_matching_button.clicked.connect(self.clear_matching_selection)
        self.previous_page_button.clicked.connect(self.previous_selector_page)
        self.next_page_button.clicked.connect(self.next_selector_page)
        self.selector_list.itemSelectionChanged.connect(self._store_current_selection)
        self.groups_list.itemSelectionChanged.connect(self._populate_group_members)
        self.create_group_button.clicked.connect(self.create_group)
        self.rename_group_button.clicked.connect(self.rename_group)
        self.delete_group_button.clicked.connect(self.delete_group)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.use_grouping_button.clicked.connect(self.use_grouping)
        self.dont_use_grouping_button.clicked.connect(self.dont_use_grouping)

        apply_metroliza_theme(self)
        self._configure_stretch_panes()
        self._list_selection_utils.connect_shift_range_behavior(self.selector_list)
        self._list_selection_utils.connect_shift_range_behavior(self.group_members_list)
        self._refresh_all()

    def _configure_stretch_panes(self) -> None:
        pane_specs = (
            (self.available_columns_list, 150),
            (self.selected_columns_list, 150),
            (self.selector_list, 220),
            (self.groups_list, 220),
            (self.group_members_list, 220),
        )
        for widget, minimum_height in pane_specs:
            widget.setMinimumHeight(minimum_height)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _source_columns(self) -> list[str]:
        return selectable_tabular_source_columns(
            self.source_dataframe,
            normalized_source_columns=set(self.column_labels),
        )

    def _available_columns(self) -> list[str]:
        return [column for column in self._source_columns() if column not in self.selector_columns]

    def _column_label(self, column: str) -> str:
        label = str(self.column_labels.get(column, column)).strip()
        return label if label else column

    def _selector_columns_text(self) -> str:
        return " | ".join(self._column_label(column) for column in self.selector_columns)

    def _refresh_available_columns(self) -> None:
        search = self.column_search.text().strip().casefold()
        self.available_columns_list.clear()
        for column in self._available_columns():
            label = self._column_label(column)
            if search and search not in label.casefold() and search not in column.casefold():
                continue
            self.available_columns_list.addItem(label)
            item = self.available_columns_list.item(self.available_columns_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, column)
        if self.available_columns_list.count():
            self.available_columns_list.setCurrentRow(0)
        self.add_column_button.setEnabled(self.available_columns_list.count() > 0)

    def _build_grouping_dataframe(self) -> pd.DataFrame:
        frame = build_tabular_grouping_dataframe(
            self.source_dataframe,
            selector_columns=tuple(self.selector_columns),
        )
        if "GROUP" not in frame.columns:
            frame["GROUP"] = self.default_group
        else:
            frame["GROUP"] = frame["GROUP"].fillna(self.default_group).astype(str)
        frame["GROUP_KEY"] = pd.to_numeric(frame["REPORT_ID"], errors="coerce").astype("Int64")
        return frame

    def _group_assignments(self, dataframe: pd.DataFrame | None) -> dict[int, str]:
        if (
            not isinstance(dataframe, pd.DataFrame)
            or dataframe.empty
            or "REPORT_ID" not in dataframe.columns
            or "GROUP" not in dataframe.columns
        ):
            return {}
        frame = dataframe.loc[:, ["REPORT_ID", "GROUP"]].copy()
        frame["REPORT_ID"] = pd.to_numeric(frame["REPORT_ID"], errors="coerce")
        frame = frame.dropna(subset=["REPORT_ID"])
        if frame.empty:
            return {}
        frame["REPORT_ID"] = frame["REPORT_ID"].astype(int)
        labels = frame["GROUP"].fillna(self.default_group).astype(str).str.strip()
        frame["GROUP"] = labels.mask(labels == "", self.default_group)
        return (
            frame.drop_duplicates(subset=["REPORT_ID"], keep="last")
            .set_index("REPORT_ID")["GROUP"]
            .to_dict()
        )

    def _apply_group_assignments(self, assignments: dict[int, str]) -> None:
        if not assignments or "REPORT_ID" not in self.df.columns:
            return
        self.df["GROUP"] = self.df["REPORT_ID"].map(assignments).fillna(self.default_group).astype(str)

    def _selected_group_name(self) -> str | None:
        item = self.groups_list.currentItem()
        if item is None:
            return None
        group_name = item.data(Qt.ItemDataRole.UserRole)
        return str(group_name) if group_name is not None else item.text()

    def _filtered_source_for_next_level(self) -> pd.DataFrame:
        return self._current_selector_index().filter_rows(self.selected_selector_keys)

    def add_selector_column(self) -> None:
        item = self.available_columns_list.currentItem()
        if item is None:
            return
        column = item.data(Qt.ItemDataRole.UserRole)
        if not column or column in self.selector_columns:
            return
        filtered_source = self._filtered_source_for_next_level()
        previous_filter_active = bool(self.selected_selector_keys)
        self.selector_columns.append(str(column))
        if previous_filter_active:
            child_index = CsvGroupingIndex(filtered_source, self.selector_columns)
            self.selected_selector_keys = child_index.child_keys_for_selected(self.selected_selector_keys)
        else:
            self.selected_selector_keys = set()
        self._selector_index = None
        self._selector_page_offset = 0
        self._rebuild_preserving_groups()
        self._refresh_all()

    def remove_last_selector_column(self) -> None:
        if not self.selector_columns:
            return
        previous_columns = tuple(self.selector_columns)
        self.selector_columns.pop()
        self._after_selector_columns_removed(previous_columns=previous_columns)

    def remove_selected_selector_column(self) -> None:
        item = self.selected_columns_list.currentItem()
        if item is None:
            self.remove_last_selector_column()
            return
        column = item.data(Qt.ItemDataRole.UserRole)
        if column not in self.selector_columns:
            return
        previous_columns = tuple(self.selector_columns)
        self.selector_columns.remove(str(column))
        self._after_selector_columns_removed(previous_columns=previous_columns)

    def _after_selector_columns_removed(self, *, previous_columns: tuple[str, ...] | None = None) -> None:
        if not self.selector_columns:
            self.selected_selector_keys = set()
        else:
            previous = tuple(previous_columns or self.selector_columns)
            projection_indexes = [
                previous.index(column)
                for column in self.selector_columns
                if column in previous
            ]
            self.selected_selector_keys = {
                tuple(key[index] for index in projection_indexes)
                for key in self.selected_selector_keys
                if len(key) >= len(previous) and len(projection_indexes) == len(self.selector_columns)
            }
        self._selector_index = None
        self._selector_page_offset = 0
        self._rebuild_preserving_groups()
        self._refresh_all()

    def clear_selector_columns(self) -> None:
        self.selector_columns = []
        self.selected_selector_keys = set()
        self._selector_index = None
        self._selector_page_offset = 0
        self._rebuild_preserving_groups()
        self._refresh_all()

    def clear_selection(self) -> None:
        self.selected_selector_keys = set()
        self.selector_list.clearSelection()
        self._sync_status()

    def _visible_selector_keys(self) -> set[tuple[str, ...]]:
        return {
            tuple(self.selector_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.selector_list.count())
        }

    def _matching_selector_keys(self) -> set[tuple[str, ...]]:
        return set(
            self._current_selector_index().matching_keys(
                search_text=self.selector_search.text(),
            )
        )

    def select_visible_matching(self) -> None:
        self.selected_selector_keys |= self._visible_selector_keys()
        self._refresh_selectors()
        self._sync_status()

    def select_all_matching(self) -> None:
        self.selected_selector_keys |= self._matching_selector_keys()
        self._refresh_selectors()
        self._sync_status()

    def clear_matching_selection(self) -> None:
        self.selected_selector_keys -= self._matching_selector_keys()
        self._refresh_selectors()
        self._sync_status()

    def previous_selector_page(self) -> None:
        if self._selector_page_offset <= 0:
            return
        self._selector_page_offset = max(0, self._selector_page_offset - _SELECTOR_PAGE_SIZE)
        self._refresh_selectors()

    def next_selector_page(self) -> None:
        next_offset = self._selector_page_offset + _SELECTOR_PAGE_SIZE
        if next_offset >= self._selector_total_rows:
            return
        self._selector_page_offset = next_offset
        self._refresh_selectors()

    def _rebuild_preserving_groups(self) -> None:
        assignments = self._group_assignments(self.df)
        self.df = self._build_grouping_dataframe()
        self._apply_group_assignments(assignments)

    def _store_current_selection(self) -> None:
        visible_keys = {
            tuple(self.selector_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.selector_list.count())
        }
        selected_visible_keys = {
            tuple(item.data(Qt.ItemDataRole.UserRole))
            for item in self.selector_list.selectedItems()
        }
        self.selected_selector_keys = (self.selected_selector_keys - visible_keys) | selected_visible_keys
        self._sync_status()

    def _row_ids_for_selected_keys(self) -> list[int]:
        if not self.selector_columns or not self.selected_selector_keys:
            return []
        filtered = self._current_selector_index().filter_rows(self.selected_selector_keys)
        if "source_row_number" not in filtered.columns:
            return []
        return pd.to_numeric(filtered["source_row_number"], errors="coerce").dropna().astype(int).tolist()

    def create_group(self, initial_group_name: str | None = None) -> None:
        row_ids = self._row_ids_for_selected_keys()
        if not row_ids:
            QMessageBox.information(self, self.windowTitle(), "Select matching rows before creating a group.")
            return
        selected_group = str(initial_group_name or self._selected_group_name() or "").strip()
        if selected_group and selected_group != self.default_group:
            group_name = selected_group
        else:
            group_name, accepted = QInputDialog.getText(self, "New group", "Group name:")
            group_name = str(group_name or "").strip()
            if not accepted or not group_name:
                return
        self.df.loc[self.df["REPORT_ID"].isin(row_ids), "GROUP"] = group_name
        self.selected_selector_keys = set()
        self._refresh_all(preferred_group=group_name)

    def _current_selector_index(self) -> CsvGroupingIndex:
        selector_index = vars(self).get("_selector_index")
        if (
            selector_index is None
            or tuple(self.selector_columns) != selector_index.grouping_columns
        ):
            self._selector_index = CsvGroupingIndex(self.source_dataframe, self.selector_columns)
        return self._selector_index

    def _handle_selector_search_changed(self) -> None:
        self._selector_page_offset = 0
        self._refresh_selectors()

    def rename_group(self) -> None:
        selected_group = self._selected_group_name()
        if not selected_group:
            return
        new_name, accepted = QInputDialog.getText(
            self,
            "Rename group",
            f"New name for '{selected_group}':",
        )
        new_name = str(new_name or "").strip()
        if not accepted or not new_name:
            return
        self.df.loc[self.df["GROUP"] == selected_group, "GROUP"] = new_name
        self._refresh_all(preferred_group=new_name)

    def delete_group(self) -> None:
        selected_group = self._selected_group_name()
        if not selected_group or selected_group == self.default_group:
            return
        self.df.loc[self.df["GROUP"] == selected_group, "GROUP"] = self.default_group
        self._refresh_all(preferred_group=self.default_group)

    def _sync_status(self) -> None:
        if not self.selector_columns:
            self.selector_status_label.setText("No grouping columns selected")
            set_status_variant(self.selector_status_label, "neutral")
        else:
            row_count = self._current_selector_index().count_rows(self.selected_selector_keys)
            columns_text = self._selector_columns_text()
            if self.selected_selector_keys:
                self.selector_status_label.setText(
                    f"{columns_text}: {len(self.selected_selector_keys)} selected group(s), {row_count} rows"
                )
            else:
                self.selector_status_label.setText(f"{columns_text}: all rows")
            set_status_variant(self.selector_status_label, "success")
        self.remove_column_button.setEnabled(bool(self.selector_columns))
        self.clear_columns_button.setEnabled(bool(self.selector_columns))
        self.create_group_button.setEnabled(bool(self.selector_columns and self.selected_selector_keys))
        selected_group = self._selected_group_name()
        self.rename_group_button.setEnabled(bool(selected_group))
        self.delete_group_button.setEnabled(bool(selected_group and selected_group != self.default_group))
        self.clear_selection_button.setEnabled(bool(self.selected_selector_keys))

    def _refresh_selectors(self) -> None:
        self.selector_list.blockSignals(True)
        self.selector_list.clear()
        preview_rows, total_rows = self._current_selector_index().preview_rows(
            search_text=self.selector_search.text(),
            offset=self._selector_page_offset,
            limit=_SELECTOR_PAGE_SIZE,
        )
        self._selector_total_rows = total_rows
        if self._selector_page_offset >= total_rows and total_rows:
            self._selector_page_offset = max(
                0,
                ((total_rows - 1) // _SELECTOR_PAGE_SIZE) * _SELECTOR_PAGE_SIZE,
            )
            preview_rows, total_rows = self._current_selector_index().preview_rows(
                search_text=self.selector_search.text(),
                offset=self._selector_page_offset,
                limit=_SELECTOR_PAGE_SIZE,
            )
            self._selector_total_rows = total_rows
        selected_keys = set(self.selected_selector_keys)
        for row in preview_rows:
            self.selector_list.addItem(f"{row['label']} (n={row['row_count']})")
            item = self.selector_list.item(self.selector_list.count() - 1)
            key = tuple(row["key"])
            item.setData(Qt.ItemDataRole.UserRole, key)
            if key in selected_keys:
                item.setSelected(True)
        self.selector_list.blockSignals(False)
        start = 0 if not total_rows else self._selector_page_offset + 1
        end = min(self._selector_page_offset + len(preview_rows), total_rows)
        if not self.selector_columns:
            self.selector_preview_label.setText("Add a grouping column to preview row groups.")
            set_status_variant(self.selector_preview_label, "neutral")
        elif total_rows > len(preview_rows):
            self.selector_preview_label.setText(
                f"Showing {start}-{end} of {total_rows} matching groups."
            )
            set_status_variant(self.selector_preview_label, "warning")
        else:
            self.selector_preview_label.setText(f"Showing {total_rows} matching group(s).")
            set_status_variant(self.selector_preview_label, "info" if total_rows else "warning")
        self.selector_page_label.setText(
            f"Page {self._selector_page_offset // _SELECTOR_PAGE_SIZE + 1 if total_rows else 0} "
            f"of {((total_rows - 1) // _SELECTOR_PAGE_SIZE + 1) if total_rows else 0}"
        )
        set_status_variant(self.selector_page_label, "neutral")
        self.previous_page_button.setEnabled(self._selector_page_offset > 0)
        self.next_page_button.setEnabled(self._selector_page_offset + len(preview_rows) < total_rows)
        has_visible = bool(preview_rows)
        has_matching = bool(total_rows)
        self.select_visible_button.setEnabled(has_visible)
        self.select_all_matching_button.setEnabled(has_matching)
        self.clear_matching_button.setEnabled(bool(self.selected_selector_keys and has_matching))

    def _refresh_selected_columns(self) -> None:
        current_column = None
        item = self.selected_columns_list.currentItem()
        if item is not None:
            current_column = item.data(Qt.ItemDataRole.UserRole)
        search = self.selected_column_search.text().strip().casefold()
        self.selected_columns_list.blockSignals(True)
        self.selected_columns_list.clear()
        for column in self.selector_columns:
            label = self._column_label(column)
            if search and search not in label.casefold() and search not in column.casefold():
                continue
            self.selected_columns_list.addItem(label)
            new_item = self.selected_columns_list.item(self.selected_columns_list.count() - 1)
            new_item.setData(Qt.ItemDataRole.UserRole, column)
            if column == current_column:
                new_item.setSelected(True)
                self.selected_columns_list.setCurrentItem(new_item)
        if self.selected_columns_list.currentItem() is None and self.selected_columns_list.count():
            self.selected_columns_list.setCurrentRow(self.selected_columns_list.count() - 1)
        self.selected_columns_list.blockSignals(False)

    def _refresh_groups(self, preferred_group: str | None = None) -> None:
        self.groups_list.blockSignals(True)
        self.groups_list.clear()
        group_counts = (
            self.df.groupby("GROUP", dropna=False)["REPORT_ID"].nunique().sort_index().to_dict()
            if not self.df.empty
            else {}
        )
        if self.default_group not in group_counts:
            group_counts[self.default_group] = 0
        for group_name, count in sorted(group_counts.items(), key=lambda item: (item[0] != self.default_group, str(item[0]))):
            label = f"{group_name} (n={int(count)})"
            self.groups_list.addItem(label)
            item = self.groups_list.item(self.groups_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, str(group_name))
            if preferred_group == str(group_name):
                item.setSelected(True)
                self.groups_list.setCurrentItem(item)
        if self.groups_list.currentItem() is None and self.groups_list.count():
            self.groups_list.setCurrentRow(0)
        self.groups_list.blockSignals(False)

    def _populate_group_members(self) -> None:
        self.group_members_list.clear()
        selected_group = self._selected_group_name()
        if not selected_group:
            self._sync_status()
            return
        rows = self.df[self.df["GROUP"] == selected_group]
        for _index, row in rows.iterrows():
            label = str(row.get("REFERENCE") or row.get("PART_NAME") or row.get("SAMPLE_NUMBER") or "")
            self.group_members_list.addItem(label)
        self._sync_status()

    def _refresh_all(self, preferred_group: str | None = None) -> None:
        self._refresh_available_columns()
        self._refresh_selected_columns()
        self._refresh_selectors()
        self._refresh_groups(preferred_group=preferred_group)
        self._populate_group_members()
        self._sync_status()

    def keyPressEvent(self, event) -> None:
        pressed_key = event.key() if event is not None and hasattr(event, "key") else None
        key_enum = getattr(Qt, "Key", None)
        enter_keys = tuple(
            key
            for key in (
                getattr(key_enum, "Key_Return", None),
                getattr(key_enum, "Key_Enter", None),
            )
            if key is not None
        )
        if pressed_key in enter_keys and self._list_or_viewport_has_focus(self.selector_list):
            self.create_group()
            if hasattr(event, "accept"):
                event.accept()
            return
        delete_keys = tuple(
            key
            for key in (
                getattr(key_enum, "Key_Delete", None),
                getattr(key_enum, "Key_Backspace", None),
            )
            if key is not None
        )
        if pressed_key in delete_keys and self._list_or_viewport_has_focus(self.selected_columns_list):
            self.remove_selected_selector_column()
            if hasattr(event, "accept"):
                event.accept()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _list_or_viewport_has_focus(list_widget) -> bool:
        if list_widget is None:
            return False
        if hasattr(list_widget, "hasFocus") and list_widget.hasFocus():
            return True
        viewport = list_widget.viewport() if hasattr(list_widget, "viewport") else None
        return bool(viewport is not None and viewport.hasFocus())

    def use_grouping(self) -> None:
        parent = self.parent()
        if parent is not None:
            parent.set_df_for_grouping(self.df)
            parent.set_grouping_applied(True)
        self.accept()

    def dont_use_grouping(self) -> None:
        parent = self.parent()
        if parent is not None:
            parent.set_df_for_grouping(None)
            parent.set_grouping_applied(False)
        self.accept()


__all__ = ["TabularAnalyticsGroupingDialog"]
