"""In-memory CSV/Excel grouping dialog for tabular analytics."""

from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QBrush, QColor, QIntValidator
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from modules import ui_theme_tokens
from modules.csv_summary_utils import CsvGroupingIndex
from modules.help_menu import attach_help_menu_to_layout
from modules.list_selection_utils import GroupingShortcutBindings, ListSelectionUtils
from modules.export_grouping_utils import set_default_group_label
from modules.tabular_column_selection import (
    column_sequence_text,
    current_column_from_list,
    populate_column_list,
)
from modules.tabular_analytics_service import (
    TABULAR_DEFAULT_GROUP,
    TabularColumnFilter,
    build_tabular_grouping_dataframe,
    selectable_tabular_source_columns,
)
from modules.ui_foundation import (
    apply_list_selection_style,
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    set_status_variant,
    status_chip,
)


_SELECTOR_PAGE_SIZE = 1000
_GROUP_MEMBER_PREVIEW_LIMIT = 1000
_GROUP_SCOPE_NUMERIC_OPERATORS = ("=", "!=", ">", ">=", "<", "<=")


class TabularAnalyticsGroupingDialog(QDialog):
    """Create manual row groups from user-selected CSV/Excel selector columns."""

    def __init__(
        self,
        parent=None,
        *,
        dataframe: pd.DataFrame | None = None,
        column_mapping: dict[str, str] | None = None,
        grouping_dataframe: pd.DataFrame | None = None,
        sqlite_store=None,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("CSV / Excel groups")
        configure_window_size(self, minimum=(760, 560), initial=(980, 700))
        self.source_dataframe = dataframe.copy() if isinstance(dataframe, pd.DataFrame) else pd.DataFrame()
        self.sqlite_store = sqlite_store
        self.sqlite_filter_columns = tuple(str(column) for column in (filter_columns or ()))
        self.sqlite_selected_filter_keys = tuple(
            tuple(str(part) for part in key)
            for key in (selected_filter_keys or ())
            if isinstance(key, (list, tuple))
        )
        self.sqlite_column_filters = tuple(
            item for item in (column_filters or ()) if isinstance(item, TabularColumnFilter)
        )
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
        self._grouping_shortcuts = None
        self.group_scope_filter_rows: list[tuple[QComboBox, QComboBox, QLineEdit, QPushButton]] = []
        self.default_group = TABULAR_DEFAULT_GROUP
        self.default_group_color = self._resolve_default_group_color()
        self.group_color_column = "GROUP_COLOR"
        self.group_palette = ui_theme_tokens.themed_group_palette(
            dark_mode=self._is_dark_mode_base(self.default_group_color)
        )
        self._initial_group_assignments = self._group_assignments(grouping_dataframe)
        self.df = self._build_grouping_dataframe()
        self._apply_group_assignments(self._initial_group_assignments)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("CSV Summary manual", "csv_summary")])

        self.selector_status_label = status_chip("No grouping columns selected", "neutral")
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
            list_widget.setMinimumHeight(80)
            list_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.selected_columns_list.setMinimumHeight(80)
        configure_accessibility(self.column_search, name="Search CSV grouping columns")
        configure_accessibility(self.selected_column_search, name="Search selected CSV grouping columns")
        configure_accessibility(self.available_columns_list, name="Available CSV grouping columns")
        configure_accessibility(self.selected_columns_list, name="Selected CSV grouping columns")
        columns_grid.addWidget(self.available_columns_list, 2, 0)
        columns_grid.addWidget(self.selected_columns_list, 2, 1)
        columns_grid.setColumnStretch(0, 1)
        columns_grid.setColumnStretch(1, 1)
        layout.addWidget(column_area, 1)

        scope_filter_area = QWidget()
        scope_filter_layout = QVBoxLayout(scope_filter_area)
        scope_filter_layout.setContentsMargins(0, 0, 0, 0)
        scope_filter_layout.setSpacing(6)
        scope_filter_header = QHBoxLayout()
        scope_filter_header.setSpacing(8)
        scope_filter_header.addWidget(QLabel("Grouping-scope filters"))
        self.scope_match_mode_combo = QComboBox()
        self.scope_match_mode_combo.addItem("AND", "and")
        self.scope_match_mode_combo.addItem("OR", "or")
        configure_accessibility(self.scope_match_mode_combo, name="CSV grouping filter match mode")
        scope_filter_header.addStretch(1)
        scope_filter_header.addWidget(QLabel("Match"))
        scope_filter_header.addWidget(self.scope_match_mode_combo)
        scope_filter_layout.addLayout(scope_filter_header)
        self.scope_filter_rows_widget = QWidget()
        self.scope_filter_rows_layout = QGridLayout(self.scope_filter_rows_widget)
        self.scope_filter_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.scope_filter_rows_layout.setHorizontalSpacing(8)
        self.scope_filter_rows_layout.setVerticalSpacing(6)
        self.scope_filter_rows_layout.addWidget(QLabel("Column"), 0, 0)
        self.scope_filter_rows_layout.addWidget(QLabel("Operator"), 0, 1)
        self.scope_filter_rows_layout.addWidget(QLabel("Value"), 0, 2)
        scope_filter_layout.addWidget(self.scope_filter_rows_widget)
        scope_filter_actions = QHBoxLayout()
        scope_filter_actions.setSpacing(8)
        self.add_scope_filter_button = QPushButton("Add filter row")
        self.clear_scope_filters_button = QPushButton("Clear scope filters")
        configure_accessibility(self.add_scope_filter_button, name="Add CSV grouping-scope filter row")
        configure_accessibility(self.clear_scope_filters_button, name="Clear CSV grouping-scope filters")
        scope_filter_actions.addWidget(self.add_scope_filter_button)
        scope_filter_actions.addWidget(self.clear_scope_filters_button)
        scope_filter_actions.addStretch(1)
        scope_filter_layout.addLayout(scope_filter_actions)
        self.scope_filter_summary_label = status_chip("", "neutral")
        scope_filter_layout.addWidget(self.scope_filter_summary_label)
        layout.addWidget(scope_filter_area)

        list_splitter = QSplitter(Qt.Orientation.Horizontal)
        list_splitter.setMinimumHeight(220)

        selector_widget = QWidget()
        selector_widget.setMinimumHeight(190)
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
        self.selector_list.setMinimumHeight(48)
        self.selector_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        configure_accessibility(self.selector_list, name="CSV grouping row selectors")
        selector_column.addWidget(self.selector_list, 1)
        selector_paging = QHBoxLayout()
        selector_paging.setSpacing(8)
        self.first_page_button = QPushButton("First")
        self.previous_page_button = QPushButton("Previous")
        self.next_page_button = QPushButton("Next")
        self.last_page_button = QPushButton("Last")
        self.page_jump_input = QLineEdit()
        self.page_jump_input.setPlaceholderText("Page")
        self.page_jump_input.setFixedWidth(64)
        self.page_jump_input.setValidator(QIntValidator(1, 999_999, self))
        self.jump_page_button = QPushButton("Go")
        self.selector_page_label = status_chip("", "neutral")
        configure_accessibility(self.first_page_button, name="First matching rows page")
        configure_accessibility(self.previous_page_button, name="Previous matching rows page")
        configure_accessibility(self.next_page_button, name="Next matching rows page")
        configure_accessibility(self.last_page_button, name="Last matching rows page")
        configure_accessibility(self.page_jump_input, name="Jump to matching rows page")
        configure_accessibility(self.jump_page_button, name="Jump to matching rows page button")
        configure_accessibility(self.selector_page_label, name="Matching rows page")
        selector_paging.addStretch(1)
        selector_paging.addWidget(self.first_page_button)
        selector_paging.addWidget(self.previous_page_button)
        selector_paging.addWidget(self.selector_page_label)
        selector_paging.addWidget(self.next_page_button)
        selector_paging.addWidget(self.last_page_button)
        selector_paging.addWidget(self.page_jump_input)
        selector_paging.addWidget(self.jump_page_button)
        selector_paging.addStretch(1)
        selector_column.addLayout(selector_paging)
        selector_column.setStretch(3, 1)
        selector_column.setStretch(4, 0)
        list_splitter.addWidget(selector_widget)

        groups_widget = QWidget()
        groups_column = QVBoxLayout(groups_widget)
        groups_column.setContentsMargins(0, 0, 0, 0)
        groups_column.setSpacing(6)
        groups_column.addWidget(QLabel("Groups"))
        self.groups_list = QListWidget()
        apply_list_selection_style(self.groups_list)
        self.groups_list.setMinimumHeight(120)
        self.groups_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        configure_accessibility(self.groups_list, name="CSV analytics groups")
        groups_column.addWidget(self.groups_list, 1)
        list_splitter.addWidget(groups_widget)

        members_widget = QWidget()
        members_column = QVBoxLayout(members_widget)
        members_column.setContentsMargins(0, 0, 0, 0)
        members_column.setSpacing(6)
        members_column.addWidget(QLabel("Rows in selected group"))
        self.group_members_list = QListWidget()
        self.group_members_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        apply_list_selection_style(self.group_members_list)
        self.group_members_list.setMinimumHeight(120)
        self.group_members_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        configure_accessibility(self.group_members_list, name="Rows in selected CSV group")
        members_column.addWidget(self.group_members_list, 1)
        list_splitter.addWidget(members_widget)
        list_splitter.setStretchFactor(0, 2)
        list_splitter.setStretchFactor(1, 1)
        list_splitter.setStretchFactor(2, 2)

        layout.addWidget(list_splitter, 3)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.create_group_button = QPushButton("Assign to group...")
        self.assign_filtered_rows_button = QPushButton("Assign filtered rows...")
        self.rename_group_button = QPushButton("Rename group")
        self.delete_group_button = QPushButton("Delete group")
        self.clear_selection_button = QPushButton("Clear selection")
        self.use_grouping_button = QPushButton("Use grouping")
        self.dont_use_grouping_button = QPushButton("Clear grouping")
        configure_accessibility(
            self.create_group_button,
            name="Assign selected rows to a CSV analytics group",
        )
        configure_accessibility(
            self.assign_filtered_rows_button,
            name="Assign filtered CSV rows to a CSV analytics group",
        )
        configure_accessibility(self.rename_group_button, name="Rename selected CSV analytics group")
        configure_accessibility(self.delete_group_button, name="Delete selected CSV analytics group")
        configure_accessibility(self.clear_selection_button, name="Clear selected matching rows")
        configure_accessibility(self.dont_use_grouping_button, name="Clear CSV analytics grouping")
        configure_accessibility(self.use_grouping_button, name="Use CSV analytics grouping")
        footer.addWidget(self.create_group_button)
        footer.addWidget(self.assign_filtered_rows_button)
        footer.addWidget(self.rename_group_button)
        footer.addWidget(self.delete_group_button)
        footer.addWidget(self.clear_selection_button)
        footer.addStretch(1)
        footer.addWidget(self.dont_use_grouping_button)
        footer.addWidget(self.use_grouping_button)
        layout.addLayout(footer)

        self.column_search.textChanged.connect(self._refresh_available_columns)
        self.selected_column_search.textChanged.connect(self._refresh_selected_columns)
        self.available_columns_list.itemDoubleClicked.connect(lambda _item: self.add_selector_column())
        self.selected_columns_list.itemDoubleClicked.connect(self.remove_selected_selector_column)
        self.selected_columns_list.itemSelectionChanged.connect(self._sync_status)
        self.selector_search.textChanged.connect(self._handle_selector_search_changed)
        self.scope_match_mode_combo.currentIndexChanged.connect(self._handle_scope_filters_changed)
        self.add_scope_filter_button.clicked.connect(self.add_scope_filter_row)
        self.clear_scope_filters_button.clicked.connect(self.clear_scope_filter_rows)
        self.first_page_button.clicked.connect(self.first_selector_page)
        self.previous_page_button.clicked.connect(self.previous_selector_page)
        self.next_page_button.clicked.connect(self.next_selector_page)
        self.last_page_button.clicked.connect(self.last_selector_page)
        self.jump_page_button.clicked.connect(self.jump_selector_page)
        self.page_jump_input.returnPressed.connect(self.jump_selector_page)
        self.selector_list.itemSelectionChanged.connect(self._store_current_selection)
        self.selector_list.itemDoubleClicked.connect(self._assign_matching_rows_from_item)
        self.groups_list.itemSelectionChanged.connect(self._populate_group_members)
        self.groups_list.itemDoubleClicked.connect(lambda _item: self.rename_group())
        self.create_group_button.clicked.connect(lambda: self.create_group())
        self.assign_filtered_rows_button.clicked.connect(self.assign_filtered_rows)
        self.rename_group_button.clicked.connect(self.rename_group)
        self.delete_group_button.clicked.connect(self.delete_group)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.use_grouping_button.clicked.connect(self.use_grouping)
        self.dont_use_grouping_button.clicked.connect(self.dont_use_grouping)

        apply_metroliza_theme(self)
        self._configure_stretch_panes()
        self._list_selection_utils.connect_shift_range_behavior(self.selector_list)
        self._list_selection_utils.connect_shift_range_behavior(self.group_members_list)
        self._grouping_shortcuts = GroupingShortcutBindings(
            source_list=self.selector_list,
            groups_list=self.groups_list,
            assigned_list=self.group_members_list,
            selected_columns_list=self.selected_columns_list,
            create_group=self.create_group,
            rename_group=self.rename_group,
            delete_group=self.delete_group,
            remove_from_assigned=self.remove_selected_group_members,
            remove_selected_columns=self.remove_selected_selector_column,
            qt_namespace=Qt,
        )
        self.add_scope_filter_row()
        self._refresh_all()

    def _is_sqlite_backed(self) -> bool:
        return vars(self).get("sqlite_store") is not None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._configure_stretch_panes()
        QTimer.singleShot(0, self._configure_stretch_panes)

    def _configure_stretch_panes(self) -> None:
        pane_specs = (
            (self.available_columns_list, 120),
            (self.selected_columns_list, 120),
            (self.selector_list, 80),
            (self.groups_list, 120),
            (self.group_members_list, 120),
        )
        for widget, minimum_height in pane_specs:
            widget.setMinimumHeight(minimum_height)
            widget.setMinimumSize(widget.minimumWidth(), minimum_height)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            widget.updateGeometry()
        layout = self.layout()
        if layout is not None:
            layout.activate()

    @staticmethod
    def _ideal_text_color(background_hex: str) -> str:
        return ui_theme_tokens.ideal_text_color(background_hex)

    def _resolve_default_group_color(self) -> str:
        palette = self.palette() if hasattr(self, "palette") else None
        base = palette.base().color() if palette is not None and hasattr(palette, "base") else None
        base_hex = base.name() if base is not None and hasattr(base, "isValid") and base.isValid() else None
        return ui_theme_tokens.resolve_base_row_background(base_hex)

    @staticmethod
    def _is_dark_mode_base(base_hex: str) -> bool:
        return ui_theme_tokens.is_dark_mode_base(base_hex)

    def _normalized_group_color(self, color_hex: str | None) -> str:
        dark_mode = self._is_dark_mode_base(self.default_group_color)
        return ui_theme_tokens.normalize_group_display_color(
            str(color_hex or ""),
            dark_mode=dark_mode,
            fallback=self.default_group_color,
        )

    def _next_group_color(self) -> str:
        used = set()
        if self.group_color_column in self.df.columns and "GROUP" in self.df.columns:
            used = set(
                self.df.loc[self.df["GROUP"] != self.default_group, self.group_color_column]
                .dropna()
                .astype(str)
                .tolist()
            )
        for color in self.group_palette:
            if color not in used:
                return color
        return ui_theme_tokens.generate_group_color(
            len(used),
            dark_mode=self._is_dark_mode_base(self.default_group_color),
        )

    def _ensure_group_color_integrity(self) -> None:
        if self.group_color_column not in self.df.columns:
            self.df[self.group_color_column] = self.default_group_color
        if "GROUP" not in self.df.columns:
            return
        self.df[self.group_color_column] = self.df[self.group_color_column].fillna(
            self.default_group_color
        )
        self.df.loc[self.df["GROUP"] == self.default_group, self.group_color_column] = (
            self.default_group_color
        )

        for group_name in self.df["GROUP"].dropna().astype(str).unique():
            if group_name == self.default_group:
                continue
            existing = self.df.loc[
                self.df["GROUP"] == group_name,
                self.group_color_column,
            ].dropna().astype(str)
            assigned_color = next(
                (
                    self._normalized_group_color(value)
                    for value in existing
                    if value and value != self.default_group_color
                ),
                None,
            )
            if assigned_color is None:
                assigned_color = self._next_group_color()
            self.df.loc[self.df["GROUP"] == group_name, self.group_color_column] = assigned_color

    def _group_color_for_group(self, group_name: str | None) -> str:
        if not group_name or group_name == self.default_group or self.group_color_column not in self.df:
            return self.default_group_color
        rows = self.df.loc[self.df["GROUP"] == group_name, self.group_color_column].dropna().astype(str)
        color = next((value for value in rows if value), self.default_group_color)
        return self._normalized_group_color(color)

    def _group_color_for_row(self, row) -> str:
        color = row.get(self.group_color_column, self.default_group_color)
        if pd.isna(color) or not str(color).strip():
            return self.default_group_color
        return self._normalized_group_color(str(color))

    def _apply_item_color(self, item: QListWidgetItem, color_hex: str | None) -> None:
        color = QColor(self._normalized_group_color(color_hex))
        if not color.isValid():
            color = QColor(self.default_group_color)
        resolved_background = color.name().upper()
        item.setBackground(QBrush(color))
        item.setForeground(QBrush(QColor(self._ideal_text_color(resolved_background))))

    def _selector_color_map(
        self,
        preview_rows: list[dict[str, object]],
    ) -> tuple[dict[tuple[str, ...], str], set[tuple[str, ...]]]:
        if self._is_sqlite_backed():
            return {}, set()
        if (
            not preview_rows
            or not self.selector_columns
            or self.source_dataframe.empty
            or "source_row_number" not in self.source_dataframe.columns
            or "REPORT_ID" not in self.df.columns
            or self.group_color_column not in self.df.columns
        ):
            return {}, set()

        visible_keys = {tuple(row["key"]) for row in preview_rows}
        selector_index = self._current_selector_index()
        key_frame = selector_index.key_frame
        if key_frame.empty:
            return {}, set()

        if len(selector_index.grouping_columns) == 1:
            key_series = key_frame[selector_index.grouping_columns[0]].map(lambda value: (str(value),))
        else:
            key_series = pd.Series(
                list(key_frame.loc[:, list(selector_index.grouping_columns)].itertuples(index=False, name=None)),
                index=key_frame.index,
            )
        row_numbers = pd.to_numeric(self.source_dataframe["source_row_number"], errors="coerce")
        selector_rows = pd.DataFrame({"__key": key_series, "REPORT_ID": row_numbers}).dropna(
            subset=["REPORT_ID"]
        )
        if selector_rows.empty:
            return {}, set()
        selector_rows["REPORT_ID"] = selector_rows["REPORT_ID"].astype(int)
        selector_rows = selector_rows[selector_rows["__key"].isin(visible_keys)]
        if selector_rows.empty:
            return {}, set()

        assignments = self.df.loc[:, ["REPORT_ID", "GROUP", self.group_color_column]].copy()
        assignments["REPORT_ID"] = pd.to_numeric(assignments["REPORT_ID"], errors="coerce")
        assignments = assignments.dropna(subset=["REPORT_ID"])
        assignments["REPORT_ID"] = assignments["REPORT_ID"].astype(int)
        merged = selector_rows.merge(assignments, on="REPORT_ID", how="left")
        merged["GROUP"] = merged["GROUP"].fillna(self.default_group).astype(str)
        merged[self.group_color_column] = merged[self.group_color_column].fillna(
            self.default_group_color
        )

        color_map: dict[tuple[str, ...], str] = {}
        mixed_keys: set[tuple[str, ...]] = set()
        for key, rows in merged.groupby("__key", sort=False):
            key_tuple = tuple(key)
            groups = {str(value) for value in rows["GROUP"].dropna().astype(str)}
            colors = {
                self._normalized_group_color(value)
                for value in rows[self.group_color_column].dropna().astype(str)
            }
            if len(groups) == 1 and len(colors) == 1:
                color_map[key_tuple] = next(iter(colors))
            elif len(groups) > 1:
                mixed_keys.add(key_tuple)
        return color_map, mixed_keys

    def _source_columns(self) -> list[str]:
        if self._is_sqlite_backed():
            return selectable_tabular_source_columns(
                pd.DataFrame(columns=list(self.sqlite_store.source_columns)),
                normalized_source_columns=self.sqlite_store.source_columns,
            )
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
        return column_sequence_text(self.selector_columns, label_for=self._column_label)

    def _scope_match_mode(self) -> str:
        combo = vars(self).get("scope_match_mode_combo")
        if combo is None:
            return "and"
        mode = combo.currentData()
        return "or" if str(mode or "").strip().casefold() == "or" else "and"

    def _scope_filter_columns(self) -> list[str]:
        return self._source_columns()

    def _populate_scope_column_combo(self, combo: QComboBox, *, selected_column: str | None = None) -> None:
        current = str(selected_column or combo.currentData() or "").strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Select column", "")
        for column in self._scope_filter_columns():
            combo.addItem(self._column_label(column), column)
        if current:
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _layout_scope_filter_rows(self) -> None:
        for row_index, (column_combo, operator_combo, value_edit, remove_button) in enumerate(
            self.group_scope_filter_rows,
            start=1,
        ):
            self.scope_filter_rows_layout.addWidget(column_combo, row_index, 0)
            self.scope_filter_rows_layout.addWidget(operator_combo, row_index, 1)
            self.scope_filter_rows_layout.addWidget(value_edit, row_index, 2)
            self.scope_filter_rows_layout.addWidget(remove_button, row_index, 3)

    def _sync_scope_filter_controls(self) -> None:
        can_remove = len(self.group_scope_filter_rows) > 1
        for _column_combo, _operator_combo, _value_edit, remove_button in self.group_scope_filter_rows:
            remove_button.setEnabled(can_remove)

    def _refresh_scope_filter_column_choices(self) -> None:
        for column_combo, _operator_combo, _value_edit, _remove_button in self.group_scope_filter_rows:
            self._populate_scope_column_combo(column_combo)

    def add_scope_filter_row(
        self,
        *,
        column: str | None = None,
        operator: str = "=",
        value: str | float | int | None = None,
    ) -> None:
        column_combo = QComboBox()
        self._populate_scope_column_combo(column_combo, selected_column=column)
        operator_combo = QComboBox()
        for item in _GROUP_SCOPE_NUMERIC_OPERATORS:
            operator_combo.addItem(item, item)
        operator_index = operator_combo.findData(operator)
        operator_combo.setCurrentIndex(operator_index if operator_index >= 0 else 0)
        value_edit = QLineEdit()
        value_edit.setPlaceholderText("Numeric value")
        value_edit.setText("" if value is None else str(value))
        remove_button = QPushButton("Remove")
        configure_accessibility(column_combo, name="CSV grouping filter column")
        configure_accessibility(operator_combo, name="CSV grouping filter operator")
        configure_accessibility(value_edit, name="CSV grouping filter value")
        configure_accessibility(remove_button, name="Remove CSV grouping filter row")
        row = (column_combo, operator_combo, value_edit, remove_button)
        remove_button.clicked.connect(lambda _checked=False, row=row: self._remove_scope_filter_row(row))
        column_combo.currentIndexChanged.connect(self._handle_scope_filters_changed)
        operator_combo.currentIndexChanged.connect(self._handle_scope_filters_changed)
        value_edit.editingFinished.connect(self._handle_scope_filters_changed)
        self.group_scope_filter_rows.append(row)
        self._layout_scope_filter_rows()
        self._sync_scope_filter_controls()
        self._handle_scope_filters_changed()

    def _remove_scope_filter_row(self, row) -> None:
        if row not in self.group_scope_filter_rows:
            return
        column_combo, operator_combo, value_edit, remove_button = row
        for widget in (column_combo, operator_combo, value_edit, remove_button):
            self.scope_filter_rows_layout.removeWidget(widget)
            widget.deleteLater()
        self.group_scope_filter_rows.remove(row)
        if not self.group_scope_filter_rows:
            self.add_scope_filter_row()
            return
        self._layout_scope_filter_rows()
        self._sync_scope_filter_controls()
        self._handle_scope_filters_changed()

    def clear_scope_filter_rows(self) -> None:
        rows = list(self.group_scope_filter_rows)
        for row in rows:
            self._remove_scope_filter_row(row)
        if not self.group_scope_filter_rows:
            self.add_scope_filter_row()

    def _active_scope_filters(self) -> tuple[TabularColumnFilter, ...]:
        column_lookup = set(self._scope_filter_columns())
        filters: list[TabularColumnFilter] = []
        for column_combo, operator_combo, value_edit, _remove_button in vars(self).get(
            "group_scope_filter_rows",
            [],
        ):
            column = str(column_combo.currentData() or "").strip()
            operator = str(operator_combo.currentData() or "").strip()
            value = str(value_edit.text() or "").strip()
            if not column or column not in column_lookup or not value:
                continue
            filters.append(
                TabularColumnFilter(
                    column=column,
                    numeric_operator=operator,
                    numeric_value=value,
                )
            )
        return tuple(filters)

    def _scope_filter_expression(self, filters: tuple[TabularColumnFilter, ...]) -> str:
        if not filters:
            return "all rows"
        joiner = " OR " if self._scope_match_mode() == "or" else " AND "
        return joiner.join(
            f"{item.column} {item.numeric_operator} {item.numeric_value}"
            for item in filters
        )

    def _sqlite_scope_kwargs(self) -> dict[str, object]:
        return {
            "filter_columns": self.sqlite_filter_columns,
            "selected_filter_keys": self.sqlite_selected_filter_keys,
            "base_column_filters": self.sqlite_column_filters,
            "column_filters": self._active_scope_filters(),
            "column_filter_match_mode": self._scope_match_mode(),
        }

    def _scoped_source_dataframe(self) -> pd.DataFrame:
        if self._is_sqlite_backed():
            return pd.DataFrame()
        filters = self._active_scope_filters()
        if not filters:
            return self.source_dataframe
        match_mode = self._scope_match_mode()
        mask_by_filter: list[pd.Series] = []
        for item in filters:
            numeric_series = pd.to_numeric(self.source_dataframe[item.column], errors="coerce")
            numeric_value = pd.to_numeric(pd.Series([item.numeric_value]), errors="coerce").iloc[0]
            if pd.isna(numeric_value):
                continue
            operator = str(item.numeric_operator or "").strip()
            if operator == "=":
                mask = numeric_series == float(numeric_value)
            elif operator == "!=":
                mask = numeric_series != float(numeric_value)
            elif operator == ">":
                mask = numeric_series > float(numeric_value)
            elif operator == ">=":
                mask = numeric_series >= float(numeric_value)
            elif operator == "<":
                mask = numeric_series < float(numeric_value)
            elif operator == "<=":
                mask = numeric_series <= float(numeric_value)
            else:
                continue
            mask_by_filter.append(mask.fillna(False))
        if not mask_by_filter:
            return self.source_dataframe.iloc[0:0].copy()
        if match_mode == "or":
            combined_mask = pd.Series(False, index=self.source_dataframe.index)
            for mask in mask_by_filter:
                combined_mask |= mask
        else:
            combined_mask = pd.Series(True, index=self.source_dataframe.index)
            for mask in mask_by_filter:
                combined_mask &= mask
        return self.source_dataframe.loc[combined_mask.fillna(False)].copy()

    def _scope_row_count(self) -> int:
        if self._is_sqlite_backed():
            return int(self.sqlite_store.count_rows(**self._sqlite_scope_kwargs()))
        return int(len(self._scoped_source_dataframe().index))

    def _handle_scope_filters_changed(self) -> None:
        self._selector_index = None
        self._selector_page_offset = 0
        self.selected_selector_keys = set()
        if hasattr(self, "selector_list"):
            self.selector_list.clearSelection()
        if hasattr(self, "scope_filter_summary_label"):
            expression = self._scope_filter_expression(self._active_scope_filters())
            row_count = self._scope_row_count()
            self.scope_filter_summary_label.setText(f"Scope: {expression} ({row_count} rows)")
            set_status_variant(
                self.scope_filter_summary_label,
                "info" if row_count else "warning",
            )
        if hasattr(self, "selector_list"):
            self._refresh_all()

    def _refresh_available_columns(self) -> None:
        populate_column_list(
            self.available_columns_list,
            self._available_columns(),
            label_for=self._column_label,
            search_text=self.column_search.text(),
            fallback="first",
        )

    def _build_grouping_dataframe(self) -> pd.DataFrame:
        if self._is_sqlite_backed():
            return pd.DataFrame(
                columns=[
                    "REPORT_ID",
                    "REFERENCE",
                    "DATE",
                    "SAMPLE_NUMBER",
                    "PART_NAME",
                    "FILENAME",
                    "GROUP",
                    self.group_color_column,
                    "GROUP_KEY",
                ]
            )
        frame = build_tabular_grouping_dataframe(
            self.source_dataframe,
            selector_columns=tuple(self.selector_columns),
        )
        if "GROUP" not in frame.columns:
            frame["GROUP"] = self.default_group
        else:
            frame["GROUP"] = frame["GROUP"].fillna(self.default_group).astype(str)
        if self.group_color_column not in frame.columns:
            frame[self.group_color_column] = self.default_group_color
        else:
            frame[self.group_color_column] = (
                frame[self.group_color_column].fillna(self.default_group_color).astype(str)
            )
        frame["GROUP_KEY"] = pd.to_numeric(frame["REPORT_ID"], errors="coerce").astype("Int64")
        return frame

    def _group_assignments(self, dataframe: pd.DataFrame | None) -> dict[int, tuple[str, str | None]]:
        if (
            not isinstance(dataframe, pd.DataFrame)
            or dataframe.empty
            or "REPORT_ID" not in dataframe.columns
            or "GROUP" not in dataframe.columns
        ):
            return {}
        columns = ["REPORT_ID", "GROUP"]
        if self.group_color_column in dataframe.columns:
            columns.append(self.group_color_column)
        frame = dataframe.loc[:, columns].copy()
        frame["REPORT_ID"] = pd.to_numeric(frame["REPORT_ID"], errors="coerce")
        frame = frame.dropna(subset=["REPORT_ID"])
        if frame.empty:
            return {}
        frame["REPORT_ID"] = frame["REPORT_ID"].astype(int)
        labels = frame["GROUP"].fillna(self.default_group).astype(str).str.strip()
        frame["GROUP"] = labels.mask(labels == "", self.default_group)
        frame = frame[frame["GROUP"] != self.default_group]
        if frame.empty:
            return {}
        if self.group_color_column not in frame.columns:
            frame[self.group_color_column] = None
        deduped = frame.drop_duplicates(subset=["REPORT_ID"], keep="last").set_index("REPORT_ID")
        return {
            int(report_id): (str(row["GROUP"]), row.get(self.group_color_column))
            for report_id, row in deduped.iterrows()
        }

    def _apply_group_assignments(self, assignments: dict[int, tuple[str, str | None]]) -> None:
        if not assignments:
            return
        if self._is_sqlite_backed():
            rows = []
            for report_id, assignment in assignments.items():
                if isinstance(assignment, tuple):
                    group_name, color = assignment
                else:
                    group_name, color = str(assignment), None
                group_name = str(group_name or self.default_group).strip() or self.default_group
                if group_name == self.default_group:
                    continue
                rows.append(
                    {
                        "REPORT_ID": int(report_id),
                        "REFERENCE": f"Row {int(report_id)}",
                        "DATE": "",
                        "SAMPLE_NUMBER": str(int(report_id)),
                        "PART_NAME": f"Row {int(report_id)}",
                        "FILENAME": "",
                        "GROUP": group_name,
                        self.group_color_column: color or self.default_group_color,
                        "GROUP_KEY": int(report_id),
                    }
                )
            if rows:
                self.df = pd.DataFrame(rows)
                self._ensure_group_color_integrity()
            return
        if "REPORT_ID" not in self.df.columns:
            return
        group_assignments = {}
        color_assignments = {}
        for report_id, assignment in assignments.items():
            if isinstance(assignment, tuple):
                group_name, color = assignment
            else:
                group_name, color = str(assignment), None
            group_assignments[int(report_id)] = str(group_name or self.default_group)
            if color is not None and str(color).strip():
                color_assignments[int(report_id)] = str(color)
        report_ids = pd.to_numeric(self.df["REPORT_ID"], errors="coerce")
        self.df["GROUP"] = report_ids.map(group_assignments).fillna(self.default_group).astype(str)
        if self.group_color_column not in self.df.columns:
            self.df[self.group_color_column] = self.default_group_color
        self.df[self.group_color_column] = (
            report_ids.map(color_assignments).fillna(self.default_group_color).astype(str)
        )
        self._ensure_group_color_integrity()

    def _selected_group_name(self) -> str | None:
        item = self.groups_list.currentItem()
        if item is None:
            return None
        group_name = item.data(Qt.ItemDataRole.UserRole)
        return str(group_name) if group_name is not None else item.text()

    def _filtered_source_for_next_level(self) -> pd.DataFrame:
        if self._is_sqlite_backed():
            return pd.DataFrame()
        return self._current_selector_index().filter_rows(self.selected_selector_keys)

    def add_selector_column(self) -> None:
        item = self.available_columns_list.currentItem()
        if item is None:
            return
        column = item.data(Qt.ItemDataRole.UserRole)
        if not column or column in self.selector_columns:
            return
        self.selector_columns.append(str(column))
        if self._is_sqlite_backed():
            self.selected_selector_keys = set()
        else:
            filtered_source = self._filtered_source_for_next_level()
            previous_filter_active = bool(self.selected_selector_keys)
            if previous_filter_active:
                child_index = CsvGroupingIndex(filtered_source, self.selector_columns)
                self.selected_selector_keys = child_index.child_keys_for_selected(self.selected_selector_keys)
            else:
                self.selected_selector_keys = set()
        self._selector_index = None
        self._selector_page_offset = 0
        self._rebuild_preserving_groups()
        self._refresh_all()

    def _sqlite_preview_rows(
        self,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, object]], int]:
        if not self._is_sqlite_backed():
            return [], 0
        return self.sqlite_store.preview_group_rows(
            tuple(self.selector_columns),
            search_text=self.selector_search.text(),
            offset=offset,
            limit=limit,
            **self._sqlite_scope_kwargs(),
        )

    def _sqlite_selector_row_count(self) -> int:
        if not self._is_sqlite_backed():
            return 0
        if not self.selector_columns or not self.selected_selector_keys:
            return self.sqlite_store.count_rows(**self._sqlite_scope_kwargs())
        return self.sqlite_store.count_rows_for_group_keys(
            tuple(self.selector_columns),
            self.selected_selector_keys,
            **self._sqlite_scope_kwargs(),
        )

    def _sqlite_row_ids_for_selected_keys(self) -> list[int]:
        if not self._is_sqlite_backed() or not self.selector_columns or not self.selected_selector_keys:
            return []
        return self.sqlite_store.row_ids_for_group_keys(
            tuple(self.selector_columns),
            self.selected_selector_keys,
            **self._sqlite_scope_kwargs(),
        )

    def _sqlite_total_grouping_rows(self) -> int:
        if not self._is_sqlite_backed():
            return 0
        return self.sqlite_store.count_rows(**self._sqlite_scope_kwargs())

    def _sqlite_filters_active(self) -> bool:
        return bool(
            self.sqlite_column_filters
            or (self.sqlite_filter_columns and self.sqlite_selected_filter_keys)
            or self._active_scope_filters()
        )

    def _sqlite_group_counts(self) -> dict[str, int]:
        total = self._sqlite_total_grouping_rows()
        if self.df.empty or "GROUP" not in self.df.columns or "REPORT_ID" not in self.df.columns:
            return {self.default_group: total}
        assigned = self.df.loc[:, ["REPORT_ID", "GROUP"]].copy()
        assigned["REPORT_ID"] = pd.to_numeric(assigned["REPORT_ID"], errors="coerce")
        assigned = assigned.dropna(subset=["REPORT_ID"])
        if assigned.empty:
            return {self.default_group: total}
        assigned["REPORT_ID"] = assigned["REPORT_ID"].astype(int)
        labels = assigned["GROUP"].fillna(self.default_group).astype(str).str.strip()
        assigned["GROUP"] = labels.mask(labels == "", self.default_group)
        assigned = assigned.drop_duplicates(subset=["REPORT_ID"], keep="last")
        custom_assignments = assigned[assigned["GROUP"] != self.default_group]
        group_counts: dict[str, int] = {}
        for group_name, group_rows in custom_assignments.groupby("GROUP", dropna=False, sort=True):
            row_ids = group_rows["REPORT_ID"].astype(int).tolist()
            count = (
                self.sqlite_store.count_source_row_numbers(row_ids, **self._sqlite_scope_kwargs())
                if self._sqlite_filters_active()
                else len(set(row_ids))
            )
            if count:
                group_counts[str(group_name)] = int(count)
        assigned_custom_count = int(sum(group_counts.values()))
        default_count = max(0, total - assigned_custom_count)
        if default_count or not group_counts:
            group_counts[self.default_group] = default_count
        return {str(group): int(count) for group, count in group_counts.items()}

    def remove_last_selector_column(self) -> None:
        if not self.selector_columns:
            return
        previous_columns = tuple(self.selector_columns)
        self.selector_columns.pop()
        self._after_selector_columns_removed(previous_columns=previous_columns)

    def remove_selected_selector_column(self, item: QListWidgetItem | None = None) -> None:
        item = item or self.selected_columns_list.currentItem()
        if item is None:
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

    def first_selector_page(self) -> None:
        if self._selector_page_offset <= 0:
            return
        self._selector_page_offset = 0
        self._refresh_selectors()

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

    def last_selector_page(self) -> None:
        if self._selector_total_rows <= 0:
            return
        last_offset = ((self._selector_total_rows - 1) // _SELECTOR_PAGE_SIZE) * _SELECTOR_PAGE_SIZE
        if self._selector_page_offset == last_offset:
            return
        self._selector_page_offset = last_offset
        self._refresh_selectors()

    def jump_selector_page(self) -> None:
        page_text = str(self.page_jump_input.text() or "").strip()
        if not page_text:
            return
        try:
            requested_page = max(1, int(page_text))
        except ValueError:
            return
        total_pages = ((self._selector_total_rows - 1) // _SELECTOR_PAGE_SIZE + 1) if self._selector_total_rows else 0
        if total_pages <= 0:
            return
        requested_page = min(requested_page, total_pages)
        offset = (requested_page - 1) * _SELECTOR_PAGE_SIZE
        if offset == self._selector_page_offset:
            return
        self._selector_page_offset = offset
        self._refresh_selectors()

    def _rebuild_preserving_groups(self) -> None:
        if self._is_sqlite_backed():
            self._ensure_group_color_integrity()
            return
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
        if self._is_sqlite_backed():
            return self._sqlite_row_ids_for_selected_keys()
        filtered = self._current_selector_index().filter_rows(self.selected_selector_keys)
        if "source_row_number" not in filtered.columns:
            return []
        return pd.to_numeric(filtered["source_row_number"], errors="coerce").dropna().astype(int).tolist()

    def _row_ids_for_scope(self) -> list[int]:
        if self._is_sqlite_backed():
            return self.sqlite_store.row_ids(**self._sqlite_scope_kwargs())
        scoped = self._scoped_source_dataframe()
        if "source_row_number" not in scoped.columns:
            return []
        return pd.to_numeric(scoped["source_row_number"], errors="coerce").dropna().astype(int).tolist()

    def _assign_matching_rows_from_item(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        clicked_key = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(clicked_key, tuple):
            return
        visible_keys = set()
        for index in range(self.selector_list.count()):
            key = self.selector_list.item(index).data(Qt.ItemDataRole.UserRole)
            if isinstance(key, tuple):
                visible_keys.add(key)
        selected_visible_keys = set()
        for selected_item in self.selector_list.selectedItems():
            key = selected_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(key, tuple):
                selected_visible_keys.add(key)
        if clicked_key not in selected_visible_keys:
            self.selector_list.clearSelection()
            item.setSelected(True)
            selected_visible_keys = {clicked_key}
        self.selected_selector_keys = (self.selected_selector_keys - visible_keys) | selected_visible_keys
        self.create_group()

    def _assign_rows_to_group(self, row_ids: list[int], group_name: str) -> None:
        if not row_ids or not group_name:
            return
        group_exists = bool((self.df["GROUP"] == group_name).any())
        assigned_color = self._group_color_for_group(group_name) if group_exists else self._next_group_color()
        if self._is_sqlite_backed():
            incoming = pd.DataFrame(
                {
                    "REPORT_ID": row_ids,
                    "REFERENCE": [f"Row {row_id}" for row_id in row_ids],
                    "DATE": "",
                    "SAMPLE_NUMBER": [str(row_id) for row_id in row_ids],
                    "PART_NAME": [f"Row {row_id}" for row_id in row_ids],
                    "FILENAME": "",
                    "GROUP": group_name,
                    self.group_color_column: assigned_color,
                    "GROUP_KEY": row_ids,
                }
            )
            existing = self.df.loc[~self.df["REPORT_ID"].isin(row_ids)] if not self.df.empty else self.df
            self.df = pd.concat([existing, incoming], ignore_index=True)
            self._ensure_group_color_integrity()
            return
        row_mask = self.df["REPORT_ID"].isin(row_ids)
        self.df.loc[row_mask, "GROUP"] = group_name
        self.df.loc[row_mask, self.group_color_column] = assigned_color
        self._ensure_group_color_integrity()

    def create_group(self, initial_group_name: str | None = None) -> None:
        row_ids = self._row_ids_for_selected_keys()
        if not row_ids:
            QMessageBox.information(self, self.windowTitle(), "Select matching rows before creating a group.")
            return
        selected_group = str(self._selected_group_name() or "").strip()
        default_name = str(initial_group_name or "").strip()
        if not default_name and selected_group and selected_group != self.default_group:
            default_name = selected_group
        if initial_group_name is None:
            group_name, accepted = QInputDialog.getText(
                self,
                "New group",
                "Group name:",
                text=default_name,
            )
            group_name = str(group_name or "").strip()
            if not accepted or not group_name:
                return
        else:
            group_name = default_name
            if not group_name:
                return
        self._assign_rows_to_group(row_ids, group_name)
        self.selected_selector_keys = set()
        self.selector_list.clearSelection()
        self._refresh_all(preferred_group=group_name)

    def assign_filtered_rows(self, initial_group_name: str | None = None) -> None:
        row_ids = self._row_ids_for_scope()
        if not row_ids:
            QMessageBox.information(
                self,
                self.windowTitle(),
                "No rows match the current parent and grouping-scope filters.",
            )
            return
        selected_group = str(self._selected_group_name() or "").strip()
        default_name = str(initial_group_name or "").strip()
        if not default_name and selected_group and selected_group != self.default_group:
            default_name = selected_group
        if initial_group_name is None:
            group_name, accepted = QInputDialog.getText(
                self,
                "Assign filtered rows",
                "Group name:",
                text=default_name,
            )
            group_name = str(group_name or "").strip()
            if not accepted or not group_name:
                return
        else:
            group_name = default_name
            if not group_name:
                return
        self._assign_rows_to_group(row_ids, group_name)
        self.selected_selector_keys = set()
        self.selector_list.clearSelection()
        self._refresh_all(preferred_group=group_name)

    def _current_selector_index(self) -> CsvGroupingIndex:
        selector_index = vars(self).get("_selector_index")
        source_frame = self._scoped_source_dataframe()
        if (
            selector_index is None
            or tuple(self.selector_columns) != selector_index.grouping_columns
            or selector_index.row_count != int(len(source_frame.index))
        ):
            self._selector_index = CsvGroupingIndex(source_frame, self.selector_columns)
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
        assigned_color = (
            self._group_color_for_group(new_name)
            if (self.df["GROUP"] == new_name).any()
            else self._group_color_for_group(selected_group)
        )
        selected_mask = self.df["GROUP"] == selected_group
        self.df.loc[selected_mask, "GROUP"] = new_name
        self.df.loc[selected_mask, self.group_color_column] = assigned_color
        if selected_group == self.default_group:
            self.default_group = new_name
            self.df.loc[self.df["GROUP"] == self.default_group, self.group_color_column] = (
                self.default_group_color
            )
        self._ensure_group_color_integrity()
        self._refresh_all(preferred_group=new_name)

    def delete_group(self) -> None:
        selected_group = self._selected_group_name()
        if not selected_group or selected_group == self.default_group:
            return
        confirmation = QMessageBox.question(
            self,
            "Delete group",
            f"Delete group '{selected_group}' and return its rows to {self.default_group}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        selected_mask = self.df["GROUP"] == selected_group
        if self._is_sqlite_backed():
            self.df = self.df.loc[~selected_mask].reset_index(drop=True)
        else:
            self.df.loc[selected_mask, "GROUP"] = self.default_group
            self.df.loc[selected_mask, self.group_color_column] = self.default_group_color
        self._ensure_group_color_integrity()
        self._refresh_all(preferred_group=self.default_group)

    def remove_selected_group_members(self) -> None:
        selected_group = self._selected_group_name()
        if not selected_group or selected_group == self.default_group:
            return
        row_ids = []
        for item in self.group_members_list.selectedItems():
            try:
                row_ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
            except (TypeError, ValueError):
                continue
        if not row_ids:
            return
        selected_mask = self.df["REPORT_ID"].isin(row_ids) & (self.df["GROUP"] == selected_group)
        if self._is_sqlite_backed():
            self.df = self.df.loc[~selected_mask].reset_index(drop=True)
        else:
            self.df.loc[selected_mask, "GROUP"] = self.default_group
            self.df.loc[selected_mask, self.group_color_column] = self.default_group_color
        self._ensure_group_color_integrity()
        self._refresh_all(preferred_group=selected_group)

    def _sync_status(self) -> None:
        if not self.selector_columns:
            self.selector_status_label.setText("No grouping columns selected")
            set_status_variant(self.selector_status_label, "neutral")
        else:
            row_count = (
                self._sqlite_selector_row_count()
                if self._is_sqlite_backed()
                else self._current_selector_index().count_rows(self.selected_selector_keys)
            )
            columns_text = self._selector_columns_text()
            if self.selected_selector_keys:
                self.selector_status_label.setText(
                    f"{columns_text}: {len(self.selected_selector_keys)} selected group(s), {row_count} rows"
                )
            else:
                self.selector_status_label.setText(f"{columns_text}: all rows")
            set_status_variant(self.selector_status_label, "success")
        self.create_group_button.setEnabled(bool(self.selector_columns and self.selected_selector_keys))
        self.assign_filtered_rows_button.setEnabled(self._scope_row_count() > 0)
        selected_group = self._selected_group_name()
        self.rename_group_button.setEnabled(bool(selected_group))
        self.delete_group_button.setEnabled(bool(selected_group and selected_group != self.default_group))
        self.clear_selection_button.setEnabled(bool(self.selected_selector_keys))

    def _refresh_selectors(self) -> None:
        self.selector_list.blockSignals(True)
        self.selector_list.clear()
        if self._is_sqlite_backed():
            preview_rows, total_rows = self._sqlite_preview_rows(
                offset=self._selector_page_offset,
                limit=_SELECTOR_PAGE_SIZE,
            )
        else:
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
            if self._is_sqlite_backed():
                preview_rows, total_rows = self._sqlite_preview_rows(
                    offset=self._selector_page_offset,
                    limit=_SELECTOR_PAGE_SIZE,
                )
            else:
                preview_rows, total_rows = self._current_selector_index().preview_rows(
                    search_text=self.selector_search.text(),
                    offset=self._selector_page_offset,
                    limit=_SELECTOR_PAGE_SIZE,
                )
            self._selector_total_rows = total_rows
        selected_keys = set(self.selected_selector_keys)
        color_map, mixed_keys = self._selector_color_map(preview_rows)
        for row in preview_rows:
            item = QListWidgetItem(f"{row['label']} (n={row['row_count']})")
            key = tuple(row["key"])
            item.setData(Qt.ItemDataRole.UserRole, key)
            if key in mixed_keys:
                item.setToolTip("Rows for this value are split across multiple groups.")
            else:
                self._apply_item_color(item, color_map.get(key, self.default_group_color))
            self.selector_list.addItem(item)
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
                f"Showing {start}-{end} of {total_rows} matching group(s)."
            )
            set_status_variant(self.selector_preview_label, "warning")
        else:
            self.selector_preview_label.setText(f"Showing {total_rows} matching group(s).")
            set_status_variant(self.selector_preview_label, "info" if total_rows else "warning")
        current_page = self._selector_page_offset // _SELECTOR_PAGE_SIZE + 1 if total_rows else 0
        total_pages = ((total_rows - 1) // _SELECTOR_PAGE_SIZE + 1) if total_rows else 0
        self.selector_page_label.setText(f"Page {current_page} of {total_pages}")
        set_status_variant(self.selector_page_label, "neutral")
        self.first_page_button.setEnabled(self._selector_page_offset > 0)
        self.previous_page_button.setEnabled(self._selector_page_offset > 0)
        self.next_page_button.setEnabled(self._selector_page_offset + len(preview_rows) < total_rows)
        self.last_page_button.setEnabled(bool(total_rows) and (self._selector_page_offset + len(preview_rows) < total_rows))
        self.page_jump_input.setEnabled(bool(total_pages))
        self.jump_page_button.setEnabled(bool(total_pages))

    def _refresh_selected_columns(self) -> None:
        populate_column_list(
            self.selected_columns_list,
            self.selector_columns,
            label_for=self._column_label,
            search_text=self.selected_column_search.text(),
            current_column=current_column_from_list(self.selected_columns_list),
            fallback="last",
            block_signals=True,
        )

    def _refresh_groups(self, preferred_group: str | None = None) -> None:
        self.groups_list.blockSignals(True)
        self.groups_list.clear()
        group_counts = (
            self._sqlite_group_counts()
            if self._is_sqlite_backed()
            else (
                self.df.groupby("GROUP", dropna=False)["REPORT_ID"].nunique().sort_index().to_dict()
                if not self.df.empty
                else {}
            )
        )
        if not group_counts:
            group_counts[self.default_group] = 0
        for group_name, count in sorted(group_counts.items(), key=lambda item: (item[0] != self.default_group, str(item[0]))):
            label = f"{group_name} (n={int(count)})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(group_name))
            self._apply_item_color(item, self._group_color_for_group(str(group_name)))
            self.groups_list.addItem(item)
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
        total_rows = len(rows.index)
        if self._is_sqlite_backed() and selected_group == self.default_group:
            total_rows = self._sqlite_group_counts().get(self.default_group, 0)
            item = QListWidgetItem(
                f"{self.default_group} contains {total_rows} unassigned row(s). "
                "Select row values and assign a group to create custom groups."
            )
            self._apply_item_color(item, self.default_group_color)
            self.group_members_list.addItem(item)
            self._sync_status()
            return
        for _index, row in rows.head(_GROUP_MEMBER_PREVIEW_LIMIT).iterrows():
            label = str(row.get("REFERENCE") or row.get("PART_NAME") or row.get("SAMPLE_NUMBER") or "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, row.get("REPORT_ID"))
            self._apply_item_color(item, self._group_color_for_row(row))
            self.group_members_list.addItem(item)
        if total_rows > _GROUP_MEMBER_PREVIEW_LIMIT:
            item = QListWidgetItem(
                f"Showing first {_GROUP_MEMBER_PREVIEW_LIMIT} of {total_rows} row(s)."
            )
            self.group_members_list.addItem(item)
        self._sync_status()

    def _refresh_all(self, preferred_group: str | None = None) -> None:
        self._refresh_scope_filter_column_choices()
        self._refresh_available_columns()
        self._refresh_selected_columns()
        self._refresh_selectors()
        self._refresh_groups(preferred_group=preferred_group)
        self._populate_group_members()
        self._sync_status()

    def keyPressEvent(self, event) -> None:
        shortcut_handler = getattr(self, "_grouping_shortcuts", None)
        if shortcut_handler is None:
            shortcut_handler = GroupingShortcutBindings(
                source_list=self.selector_list,
                groups_list=self.groups_list,
                assigned_list=self.group_members_list,
                selected_columns_list=self.selected_columns_list,
                create_group=self.create_group,
                rename_group=self.rename_group,
                delete_group=self.delete_group,
                remove_from_assigned=self.remove_selected_group_members,
                remove_selected_columns=self.remove_selected_selector_column,
                qt_namespace=Qt,
            )
        if shortcut_handler.handle_key_press(event):
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
            set_default_group_label(self.df, self.default_group)
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
