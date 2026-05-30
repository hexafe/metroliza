"""In-memory CSV/Excel grouping dialog for tabular analytics."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIntValidator
from PyQt6.QtWidgets import (
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

from metroliza.ui import ui_theme_tokens
from metroliza.tabular.csv_summary_utils import CsvGroupingIndex
from metroliza.reports.db import sqlite_connection_scope
from metroliza.shared.grouping_filter_core import (
    DateFilterSpec,
    NumberFilterSpec,
    TextFilterSpec,
    apply_filter_specs,
    looks_like_filter_expression,
    parse_filter_expression,
)
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.shared.list_selection_utils import GroupingShortcutBindings, ListSelectionUtils
from metroliza.exporting.export_grouping_utils import set_default_group_label
from metroliza.tabular.tabular_column_selection import (
    column_sequence_text,
    current_column_from_list,
    populate_column_list,
)
from metroliza.tabular.tabular_analytics_service import (
    TABULAR_DEFAULT_GROUP,
    TabularColumnFilter,
    build_tabular_grouping_dataframe,
    selectable_tabular_source_columns,
)
from metroliza.ui.ui_foundation import (
    apply_list_selection_style,
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    set_status_variant,
    status_chip,
)
try:
    from metroliza.ui.worker_progress_dialog import create_delayed_worker_progress_dialog
except ImportError:  # pragma: no cover - compatibility with lightweight test stubs.
    from metroliza.ui.worker_progress_dialog import (
        create_worker_progress_dialog as create_delayed_worker_progress_dialog,
    )


_SELECTOR_PAGE_SIZE = 1000
_GROUP_MEMBER_PREVIEW_LIMIT = 1000
_NUMBER_FILTER_OPERATOR_SYMBOLS = {
    "equals": "=",
    "eq": "=",
    "not_equals": "!=",
    "ne": "!=",
    "greater_than": ">",
    "gt": ">",
    "greater_or_equal": ">=",
    "gte": ">=",
    "less_than": "<",
    "lt": "<",
    "less_or_equal": "<=",
    "lte": "<=",
}
_DATE_FILTER_OPERATOR_SYMBOLS = {
    "on": "=",
    "equals": "=",
    "eq": "=",
    "not_on": "!=",
    "not_equals": "!=",
    "ne": "!=",
    "after": ">",
    "gt": ">",
    "on_or_after": ">=",
    "gte": ">=",
    "before": "<",
    "lt": "<",
    "on_or_before": "<=",
    "lte": "<=",
}
_ASYNC_SQLITE_SELECTOR_PREVIEW_ROWS = 250_000
_DETACHED_SELECTOR_PREVIEW_THREADS: list[QThread] = []


def _quote_sqlite_identifier(identifier: str) -> str:
    escaped = str(identifier).replace('"', '""')
    return f'"{escaped}"'


def _release_detached_selector_preview_thread(thread: QThread) -> None:
    if thread in _DETACHED_SELECTOR_PREVIEW_THREADS:
        _DETACHED_SELECTOR_PREVIEW_THREADS.remove(thread)
    thread.deleteLater()


@dataclass(frozen=True)
class _SelectorFilterState:
    text: str
    mode: str
    specs: tuple[object, ...] = ()
    match_mode: str = "and"
    parsed_filter: object | None = None
    error: str = ""


@dataclass(frozen=True)
class _PendingSqliteScope:
    selector_columns: tuple[str, ...]
    search_text: str
    filter_columns: tuple[str, ...]
    selected_filter_keys: tuple[tuple[str, ...], ...]
    base_column_filters: tuple[TabularColumnFilter, ...]
    grouping_filter: object | None
    selected_group_keys: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class _SqliteAssignmentOperation:
    kind: str
    group_name: str = ""
    color: str = ""
    row_ids: tuple[int, ...] = ()
    scope: _PendingSqliteScope | None = None
    replacement_group_name: str = ""
    replacement_color: str = ""


class _SqliteSelectorPreviewThread(QThread):
    result_ready = pyqtSignal(int, tuple, int, list, int)
    error_occurred = pyqtSignal(int, str)

    def __init__(
        self,
        *,
        request_id: int,
        sqlite_store,
        selector_columns: tuple[str, ...],
        search_text: str,
        offset: int,
        limit: int,
        scope_kwargs: dict[str, object],
    ):
        super().__init__()
        self.request_id = int(request_id)
        self.sqlite_store = sqlite_store
        self.selector_columns = tuple(selector_columns)
        self.search_text = str(search_text or "")
        self.offset = int(offset)
        self.limit = int(limit)
        self.scope_kwargs = dict(scope_kwargs)

    def run(self) -> None:
        try:
            rows, total = self.sqlite_store.preview_group_rows(
                self.selector_columns,
                search_text=self.search_text,
                offset=self.offset,
                limit=self.limit,
                **self.scope_kwargs,
            )
            self.result_ready.emit(
                self.request_id,
                self.selector_columns,
                self.offset,
                list(rows),
                int(total),
            )
        except Exception as exc:
            self.error_occurred.emit(self.request_id, str(exc))


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
        self._selector_index_source_frame: pd.DataFrame | None = None
        self._selector_preview_cache: dict[tuple[object, ...], tuple[list[dict[str, object]], int]] = {}
        self._selector_page_offset = 0
        self._selector_total_rows = 0
        self._selector_preview_request_id = 0
        self._selector_preview_threads: list[_SqliteSelectorPreviewThread] = []
        self._selector_preview_loading_dialog = None
        self._selector_preview_loading_label = None
        self._selector_preview_loading_bar = None
        self._selector_preview_loading_gif = None
        self._last_group_counts: dict[str, int] = {}
        self._applied_column_search_text = ""
        self._applied_selected_column_search_text = ""
        self._applied_selector_filter_text = ""
        self._selector_filter_state_cache: tuple[tuple[object, ...], _SelectorFilterState] | None = None
        self._scoped_source_dataframe_cache: tuple[tuple[object, ...], pd.DataFrame] | None = None
        self._list_selection_utils = ListSelectionUtils()
        self._grouping_shortcuts = None
        self.default_group = TABULAR_DEFAULT_GROUP
        self.default_group_color = self._resolve_default_group_color()
        self.group_color_column = "GROUP_COLOR"
        self.group_palette = ui_theme_tokens.themed_group_palette(
            dark_mode=self._is_dark_mode_base(self.default_group_color)
        )
        self._initial_group_assignments = self._group_assignments(grouping_dataframe)
        self._temp_group_assignments: dict[int, tuple[str, str]] = {}
        self._sqlite_assignment_operations: list[_SqliteAssignmentOperation] = []
        self._base_grouping_dataframe_cache: pd.DataFrame | None = None
        self.df = self._empty_grouping_dataframe()
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

        list_splitter = QSplitter(Qt.Orientation.Horizontal)
        list_splitter.setMinimumHeight(220)

        selector_widget = QWidget()
        selector_widget.setMinimumHeight(190)
        selector_column = QVBoxLayout(selector_widget)
        selector_column.setContentsMargins(0, 0, 0, 0)
        selector_column.setSpacing(6)
        selector_column.addWidget(QLabel("Matching rows"))
        self.selector_search = QLineEdit()
        self.selector_search.setPlaceholderText(
            "Search values or filter, e.g. Supplier=SUPPLIER AND Value > 1"
        )
        configure_accessibility(self.selector_search, name="Search or filter CSV grouping row selectors")
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
        self.assign_filtered_rows_button = QPushButton("Assign all filtered rows...")
        self.create_group_button = QPushButton("Assign selected row values...")
        self.rename_group_button = QPushButton("Rename group")
        self.delete_group_button = QPushButton("Delete group")
        self.clear_selection_button = QPushButton("Clear selection")
        self.use_grouping_button = QPushButton("Use grouping")
        self.dont_use_grouping_button = QPushButton("Clear grouping")
        for button in (
            self.assign_filtered_rows_button,
            self.create_group_button,
            self.rename_group_button,
            self.delete_group_button,
            self.clear_selection_button,
            self.use_grouping_button,
            self.dont_use_grouping_button,
        ):
            if hasattr(button, "setDefault"):
                button.setDefault(False)
            if hasattr(button, "setAutoDefault"):
                button.setAutoDefault(False)
        configure_accessibility(
            self.create_group_button,
            name="Assign selected CSV row values to a CSV analytics group",
        )
        configure_accessibility(
            self.assign_filtered_rows_button,
            name="Assign all rows matching current search or filter",
        )
        configure_accessibility(self.rename_group_button, name="Rename selected CSV analytics group")
        configure_accessibility(self.delete_group_button, name="Delete selected CSV analytics group")
        configure_accessibility(self.clear_selection_button, name="Clear selected matching rows")
        configure_accessibility(self.dont_use_grouping_button, name="Clear CSV analytics grouping")
        configure_accessibility(self.use_grouping_button, name="Use CSV analytics grouping")
        footer.addWidget(self.assign_filtered_rows_button)
        footer.addWidget(self.create_group_button)
        footer.addWidget(self.rename_group_button)
        footer.addWidget(self.delete_group_button)
        footer.addWidget(self.clear_selection_button)
        footer.addStretch(1)
        footer.addWidget(self.dont_use_grouping_button)
        footer.addWidget(self.use_grouping_button)
        layout.addLayout(footer)

        self.column_search.returnPressed.connect(self._apply_column_search)
        self.selected_column_search.returnPressed.connect(self._apply_selected_column_search)
        self.available_columns_list.itemDoubleClicked.connect(lambda _item: self.add_selector_column())
        self.selected_columns_list.itemDoubleClicked.connect(self.remove_selected_selector_column)
        self.selected_columns_list.itemSelectionChanged.connect(
            lambda: self._sync_status(recompute_counts=False, recompute_scope=False)
        )
        self.selector_search.returnPressed.connect(self._apply_selector_filter)
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
            focused_line_edits=(
                (self.column_search, self._apply_column_search),
                (self.selected_column_search, self._apply_selected_column_search),
                (self.selector_search, self._apply_selector_filter),
                (self.page_jump_input, self.jump_selector_page),
            ),
            qt_namespace=Qt,
        )
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
        used = {
            self._normalized_group_color(color)
            for group_name, color in self._temp_assignments().values()
            if group_name != self.default_group and str(color or "").strip()
        }
        used.update(
            self._normalized_group_color(operation.color)
            for operation in getattr(self, "_sqlite_assignment_operations", ())
            if operation.kind in {"rows", "scope"}
            and operation.group_name != self.default_group
            and str(operation.color or "").strip()
        )
        used.update(
            self._normalized_group_color(operation.replacement_color)
            for operation in getattr(self, "_sqlite_assignment_operations", ())
            if operation.kind == "rename_group"
            and operation.replacement_group_name != self.default_group
            and str(operation.replacement_color or "").strip()
        )
        for color in self.group_palette:
            if color not in used:
                return color
        return ui_theme_tokens.generate_group_color(
            len(used),
            dark_mode=self._is_dark_mode_base(self.default_group_color),
        )

    def _ensure_group_color_integrity(self) -> None:
        assignments = self._temp_assignments()
        if not assignments:
            return
        group_colors: dict[str, str] = {}
        for group_name, color in assignments.values():
            if group_name == self.default_group:
                continue
            normalized = self._normalized_group_color(color)
            if normalized != self.default_group_color:
                group_colors.setdefault(group_name, normalized)
        for row_id, (group_name, color) in list(assignments.items()):
            group_name = str(group_name or self.default_group).strip() or self.default_group
            if group_name == self.default_group:
                assignments.pop(row_id, None)
                continue
            assigned_color = group_colors.get(group_name)
            if assigned_color is None:
                assigned_color = self._next_group_color()
                group_colors[group_name] = assigned_color
            assignments[int(row_id)] = (group_name, assigned_color)

    def _group_color_for_group(self, group_name: str | None) -> str:
        if not group_name or group_name == self.default_group:
            return self.default_group_color
        color = next(
            (
                assignment_color
                for assignment_group, assignment_color in self._temp_assignments().values()
                if assignment_group == group_name and str(assignment_color or "").strip()
            ),
            self.default_group_color,
        )
        if color == self.default_group_color:
            color = next(
                (
                    assignment_color
                    for assignment_color in reversed(self._sqlite_assignment_operation_colors(group_name))
                    if str(assignment_color or "").strip()
                ),
                self.default_group_color,
            )
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
        ):
            return {}, set()

        visible_keys = {tuple(row["key"]) for row in preview_rows}
        row_ids_by_key = self._current_selector_index().row_ids_by_key(visible_keys)
        if not row_ids_by_key:
            return {}, set()

        color_map: dict[tuple[str, ...], str] = {}
        mixed_keys: set[tuple[str, ...]] = set()
        assignments = self._temp_assignments()
        for key_tuple, row_ids in row_ids_by_key.items():
            groups: set[str] = set()
            colors: set[str] = set()
            for row_id in row_ids:
                group_name, color = assignments.get(
                    int(row_id),
                    (self.default_group, self.default_group_color),
                )
                groups.add(str(group_name))
                colors.add(self._normalized_group_color(color))
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

    def _scope_filter_columns(self) -> list[str]:
        return self._source_columns()

    def _selector_filter_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        source_columns = set(self._scope_filter_columns())
        for normalized, original in self.column_labels.items():
            if normalized in source_columns:
                aliases[str(original)] = str(normalized)
                aliases[str(normalized)] = str(normalized)
        for column in source_columns:
            aliases.setdefault(str(column), str(column))
            aliases.setdefault(str(column).replace("_", " "), str(column))
        return aliases

    def _selector_filter_text(self) -> str:
        return str(getattr(self, "_applied_selector_filter_text", "") or "").strip()

    def _selector_filter_input_text(self) -> str:
        selector_search = vars(self).get("selector_search")
        if selector_search is None or not hasattr(selector_search, "text"):
            return ""
        return str(selector_search.text() or "").strip()

    @staticmethod
    def _looks_like_filter_expression(text: str) -> bool:
        return looks_like_filter_expression(text)

    def _selector_filter_state(self) -> _SelectorFilterState:
        text = self._selector_filter_text()
        columns = tuple(self._scope_filter_columns())
        aliases = tuple(sorted(self._selector_filter_aliases().items()))
        cache_key = (text, columns, aliases)
        cached = vars(self).get("_selector_filter_state_cache")
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        if not text:
            state = _SelectorFilterState(text="", mode="none")
            self._selector_filter_state_cache = (cache_key, state)
            return state
        if not self._looks_like_filter_expression(text):
            state = _SelectorFilterState(text=text, mode="search")
            self._selector_filter_state_cache = (cache_key, state)
            return state
        try:
            parsed = parse_filter_expression(
                text,
                columns,
                aliases=dict(aliases),
            )
        except (KeyError, TypeError, ValueError) as exc:
            state = _SelectorFilterState(text=text, mode="invalid", error=str(exc))
            self._selector_filter_state_cache = (cache_key, state)
            return state
        specs = tuple(parsed.specs)
        if not specs:
            state = _SelectorFilterState(text=text, mode="search")
            self._selector_filter_state_cache = (cache_key, state)
            return state
        match_mode = "or" if str(parsed.match_mode).casefold() == "or" else "and"
        state = _SelectorFilterState(
            text=text,
            mode="expression",
            specs=specs,
            match_mode=match_mode,
            parsed_filter=parsed,
        )
        self._selector_filter_state_cache = (cache_key, state)
        return state

    def _tabular_filters_for_expression_specs(
        self,
        specs: tuple[object, ...],
    ) -> tuple[TabularColumnFilter, ...] | None:
        filters: list[TabularColumnFilter] = []
        seen_columns: set[str] = set()
        for spec in specs:
            column_filter = self._tabular_filter_for_expression_spec(spec)
            if column_filter is None or column_filter.column in seen_columns:
                return None
            seen_columns.add(column_filter.column)
            filters.append(column_filter)
        return tuple(filters)

    def _tabular_filter_for_expression_spec(self, spec: object) -> TabularColumnFilter | None:
        if isinstance(spec, TextFilterSpec):
            operator = str(spec.operator or "").strip().casefold()
            if operator != "equals":
                return None
            return TabularColumnFilter(
                column=spec.column,
                selected_values=(str(spec.value or "").strip(),),
            )
        if isinstance(spec, NumberFilterSpec):
            operator = _NUMBER_FILTER_OPERATOR_SYMBOLS.get(
                str(spec.operator or "").strip().casefold()
            )
            if operator is None:
                return None
            return TabularColumnFilter(
                column=spec.column,
                numeric_operator=operator,
                numeric_value=spec.value,
            )
        if isinstance(spec, DateFilterSpec):
            operator = _DATE_FILTER_OPERATOR_SYMBOLS.get(
                str(spec.operator or "").strip().casefold()
            )
            if operator is None:
                return None
            return TabularColumnFilter(
                column=spec.column,
                date_operator=operator,
                date_value=str(spec.value or "").strip(),
            )
        return None

    def _sqlite_scope_kwargs(self) -> dict[str, object]:
        state = self._selector_filter_state()
        return {
            "filter_columns": self.sqlite_filter_columns,
            "selected_filter_keys": self.sqlite_selected_filter_keys,
            "base_column_filters": self.sqlite_column_filters,
            "column_filters": (),
            "column_filter_match_mode": "and",
            "grouping_filter": state.parsed_filter if state.mode == "expression" else None,
            "grouping_filter_aliases": self._selector_filter_aliases(),
        }

    def _pending_sqlite_scope(self, state: _SelectorFilterState | None = None) -> _PendingSqliteScope:
        current_state = state or self._selector_filter_state()
        return _PendingSqliteScope(
            selector_columns=tuple(self.selector_columns),
            search_text=self._selector_label_search_text(current_state),
            filter_columns=self.sqlite_filter_columns,
            selected_filter_keys=self.sqlite_selected_filter_keys,
            base_column_filters=self.sqlite_column_filters,
            grouping_filter=current_state.parsed_filter if current_state.mode == "expression" else None,
        )

    def _pending_sqlite_selected_keys_scope(
        self,
        state: _SelectorFilterState | None = None,
    ) -> _PendingSqliteScope:
        current_state = state or self._selector_filter_state()
        return _PendingSqliteScope(
            selector_columns=tuple(self.selector_columns),
            search_text="",
            filter_columns=self.sqlite_filter_columns,
            selected_filter_keys=self.sqlite_selected_filter_keys,
            base_column_filters=self.sqlite_column_filters,
            grouping_filter=current_state.parsed_filter if current_state.mode == "expression" else None,
            selected_group_keys=tuple(sorted(self.selected_selector_keys)),
        )

    def _sqlite_scope_query(self, scope: _PendingSqliteScope) -> tuple[str, list[object]]:
        if scope.selected_group_keys:
            return self._sqlite_selected_group_keys_query(scope)
        if scope.search_text:
            return self.sqlite_store.source_row_number_query_for_group_search(
                scope.selector_columns,
                search_text=scope.search_text,
                filter_columns=scope.filter_columns,
                selected_filter_keys=scope.selected_filter_keys,
                base_column_filters=scope.base_column_filters,
                grouping_filter=scope.grouping_filter,
            )
        return self.sqlite_store.source_row_number_query(
            filter_columns=scope.filter_columns,
            selected_filter_keys=scope.selected_filter_keys,
            base_column_filters=scope.base_column_filters,
            grouping_filter=scope.grouping_filter,
        )

    def _sqlite_selected_group_keys_query(
        self,
        scope: _PendingSqliteScope,
    ) -> tuple[str, list[object]]:
        if not scope.selector_columns or not scope.selected_group_keys:
            return "", []
        where_builder = getattr(self.sqlite_store, "_where_clause_for_group_keys", None)
        if where_builder is None:
            return "", []
        where_sql, params = where_builder(
            scope.selector_columns,
            scope.selected_group_keys,
            filter_columns=scope.filter_columns,
            selected_filter_keys=scope.selected_filter_keys,
            base_column_filters=scope.base_column_filters,
            grouping_filter=scope.grouping_filter,
        )
        if not where_sql:
            return "", []
        row_column = _quote_sqlite_identifier("source_row_number")
        table_name = _quote_sqlite_identifier(self.sqlite_store.table_name)
        return f"SELECT {row_column} FROM {table_name}{where_sql}", params

    def _sqlite_effective_assignment_required(self) -> bool:
        return any(
            operation.kind in {"scope", "delete_group", "rename_group"}
            for operation in vars(self).get("_sqlite_assignment_operations", ())
        )

    def _append_sqlite_row_assignment_operation(
        self,
        row_ids: list[int] | tuple[int, ...],
        group_name: str,
        color: str,
    ) -> None:
        if not self._is_sqlite_backed() or not row_ids:
            return
        self._sqlite_assignment_operations.append(
            _SqliteAssignmentOperation(
                kind="rows",
                group_name=str(group_name),
                color=self._normalized_group_color(color),
                row_ids=tuple(dict.fromkeys(int(row_id) for row_id in row_ids)),
            )
        )

    def _sqlite_assignment_operation_colors(self, group_name: str | None) -> list[str]:
        if not group_name:
            return []
        colors: list[str] = []
        for operation in vars(self).get("_sqlite_assignment_operations", ()):
            if operation.kind in {"rows", "scope"} and operation.group_name == group_name:
                colors.append(operation.color)
            elif operation.kind == "rename_group" and operation.replacement_group_name == group_name:
                colors.append(operation.replacement_color)
        return colors

    def _populate_sqlite_effective_assignment_table(self, connection) -> str:
        table_name = "temp_grouping_assignments"
        connection.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {table_name} ("
            "row_id INTEGER PRIMARY KEY, "
            "group_name TEXT NOT NULL, "
            "color TEXT NOT NULL)"
        )
        connection.execute(f"DELETE FROM {table_name}")
        for operation in vars(self).get("_sqlite_assignment_operations", ()):
            if operation.kind == "rows":
                self._apply_sqlite_row_assignment_operation(connection, table_name, operation)
            elif operation.kind == "scope":
                self._apply_sqlite_scope_assignment_operation(connection, table_name, operation)
            elif operation.kind == "delete_group":
                connection.execute(
                    f"DELETE FROM {table_name} WHERE group_name = ?",
                    (operation.group_name,),
                )
            elif operation.kind == "rename_group":
                connection.execute(
                    f"UPDATE {table_name} SET group_name = ?, color = ? WHERE group_name = ?",
                    (
                        operation.replacement_group_name,
                        operation.replacement_color,
                        operation.group_name,
                    ),
                )
        return table_name

    def _apply_sqlite_row_assignment_operation(
        self,
        connection,
        table_name: str,
        operation: _SqliteAssignmentOperation,
    ) -> None:
        row_ids = tuple(int(row_id) for row_id in operation.row_ids)
        if not row_ids:
            return
        if operation.group_name == self.default_group:
            for start in range(0, len(row_ids), 900):
                chunk = row_ids[start : start + 900]
                placeholders = ", ".join("?" for _row_id in chunk)
                connection.execute(
                    f"DELETE FROM {table_name} WHERE row_id IN ({placeholders})",
                    chunk,
                )
            return
        connection.executemany(
            f"INSERT INTO {table_name} (row_id, group_name, color) VALUES (?, ?, ?) "
            "ON CONFLICT(row_id) DO UPDATE SET "
            "group_name = excluded.group_name, color = excluded.color",
            ((row_id, operation.group_name, operation.color) for row_id in row_ids),
        )

    def _apply_sqlite_scope_assignment_operation(
        self,
        connection,
        table_name: str,
        operation: _SqliteAssignmentOperation,
    ) -> None:
        if operation.scope is None:
            return
        query, params = self._sqlite_scope_query(operation.scope)
        if not query:
            return
        scope_table = "temp_grouping_assignment_scope"
        connection.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {scope_table} (row_id INTEGER PRIMARY KEY)"
        )
        connection.execute(f"DELETE FROM {scope_table}")
        connection.execute(
            f"INSERT OR IGNORE INTO {scope_table} (row_id) SELECT source_row_number FROM ({query})",
            params,
        )
        if operation.group_name == self.default_group:
            connection.execute(
                f"DELETE FROM {table_name} WHERE row_id IN (SELECT row_id FROM {scope_table})"
            )
            return
        connection.execute(
            f"UPDATE {table_name} SET group_name = ?, color = ? "
            f"WHERE row_id IN (SELECT row_id FROM {scope_table})",
            (operation.group_name, operation.color),
        )
        connection.execute(
            f"INSERT OR IGNORE INTO {table_name} (row_id, group_name, color) "
            f"SELECT row_id, ?, ? FROM {scope_table}",
            (operation.group_name, operation.color),
        )

    def _scoped_source_dataframe(self) -> pd.DataFrame:
        if self._is_sqlite_backed():
            return pd.DataFrame()
        state = self._selector_filter_state()
        cache_key = (state.text, state.mode, state.match_mode, state.specs, state.parsed_filter)
        cached = vars(self).get("_scoped_source_dataframe_cache")
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        if state.mode == "invalid":
            scoped = self.source_dataframe.iloc[0:0].copy()
            self._scoped_source_dataframe_cache = (cache_key, scoped)
            return scoped
        if state.mode != "expression":
            self._scoped_source_dataframe_cache = (cache_key, self.source_dataframe)
            return self.source_dataframe
        try:
            scoped = apply_filter_specs(
                self.source_dataframe,
                (state.parsed_filter,) if state.parsed_filter is not None else state.specs,
                match_mode=state.match_mode,
            )
        except (KeyError, TypeError, ValueError):
            scoped = self.source_dataframe.iloc[0:0].copy()
        self._scoped_source_dataframe_cache = (cache_key, scoped)
        return scoped

    def _selector_label_search_text(self, state: _SelectorFilterState | None = None) -> str:
        current_state = state or self._selector_filter_state()
        return current_state.text if current_state.mode == "search" else ""

    def _sqlite_matching_selector_rows_for_search(self, search_text: str) -> list[dict[str, object]]:
        if not self._is_sqlite_backed() or not self.selector_columns or not search_text:
            return []
        rows, _total = self.sqlite_store.preview_group_rows(
            tuple(self.selector_columns),
            search_text=search_text,
            offset=0,
            limit=None,
            **self._sqlite_scope_kwargs(),
        )
        return rows

    def _matching_selector_keys_for_search(self, search_text: str) -> tuple[tuple[str, ...], ...]:
        if not self.selector_columns or not search_text:
            return ()
        return self._current_selector_index().matching_keys(search_text=search_text)

    def _scope_row_count(self) -> int:
        state = self._selector_filter_state()
        if state.mode == "invalid":
            return 0
        search_text = self._selector_label_search_text(state)
        if search_text:
            if not self.selector_columns:
                return 0
            if self._is_sqlite_backed():
                return self.sqlite_store.count_rows_for_group_search(
                    tuple(self.selector_columns),
                    search_text=search_text,
                    **self._sqlite_scope_kwargs(),
                )
            keys = self._matching_selector_keys_for_search(search_text)
            return int(self._current_selector_index().count_rows(keys)) if keys else 0
        if self._is_sqlite_backed():
            return int(self.sqlite_store.count_rows(**self._sqlite_scope_kwargs()))
        return int(len(self._scoped_source_dataframe().index))

    def _scope_has_rows(self) -> bool:
        state = self._selector_filter_state()
        if state.mode == "invalid":
            return False
        search_text = self._selector_label_search_text(state)
        if search_text:
            if not self.selector_columns:
                return False
            if self._is_sqlite_backed():
                return self.sqlite_store.has_rows_for_group_search(
                    tuple(self.selector_columns),
                    search_text=search_text,
                    **self._sqlite_scope_kwargs(),
                )
            keys = self._matching_selector_keys_for_search(search_text)
            return bool(keys and self._current_selector_index().count_rows(keys) > 0)
        if self._is_sqlite_backed():
            return bool(self.sqlite_store.has_rows(**self._sqlite_scope_kwargs()))
        return bool(len(self._scoped_source_dataframe().index))

    def _refresh_available_columns(self) -> None:
        populate_column_list(
            self.available_columns_list,
            self._available_columns(),
            label_for=self._column_label,
            search_text=getattr(self, "_applied_column_search_text", ""),
            fallback="first",
        )

    def _apply_column_search(self) -> None:
        self._applied_column_search_text = str(self.column_search.text() or "").strip()
        self._refresh_available_columns()

    def _build_grouping_dataframe(self) -> pd.DataFrame:
        if self._is_sqlite_backed():
            return self._empty_grouping_dataframe()
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

    def _empty_grouping_dataframe(self) -> pd.DataFrame:
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

    def _base_grouping_dataframe(self) -> pd.DataFrame:
        if self._is_sqlite_backed():
            return self._empty_grouping_dataframe()
        cached = vars(self).get("_base_grouping_dataframe_cache")
        if cached is None:
            cached = self._build_grouping_dataframe()
            self._base_grouping_dataframe_cache = cached
        return cached

    def _temp_assignments(self) -> dict[int, tuple[str, str]]:
        assignments = vars(self).get("_temp_group_assignments")
        if assignments is None:
            assignments = {}
            self._temp_group_assignments = assignments
        return assignments

    def _source_row_ids(self) -> set[int]:
        if self._is_sqlite_backed() or "source_row_number" not in self.source_dataframe.columns:
            return set()
        return set(
            pd.to_numeric(self.source_dataframe["source_row_number"], errors="coerce")
            .dropna()
            .astype(int)
            .tolist()
        )

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

    def _sqlite_assignment_dataframe(
        self,
        row_ids: list[int] | tuple[int, ...],
        group_name: str | None = None,
        color: str | None = None,
        *,
        group_names: list[str] | tuple[str, ...] | None = None,
        colors: list[str] | tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        index = pd.RangeIndex(len(row_ids))
        frame = pd.DataFrame(index=index)
        frame["REPORT_ID"] = pd.Series(row_ids, index=index, dtype="int64")
        frame["REFERENCE"] = ""
        frame["DATE"] = ""
        frame["SAMPLE_NUMBER"] = ""
        frame["PART_NAME"] = ""
        frame["FILENAME"] = ""
        frame["GROUP"] = (
            list(group_names)
            if group_names is not None
            else str(group_name or self.default_group).strip() or self.default_group
        )
        frame[self.group_color_column] = (
            list(colors)
            if colors is not None
            else self._normalized_group_color(color or self.default_group_color)
        )
        frame["GROUP_KEY"] = frame["REPORT_ID"]
        return frame[
            [
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
        ]

    def _apply_group_assignments(self, assignments: dict[int, tuple[str, str | None]]) -> None:
        temp_assignments = self._temp_assignments()
        temp_assignments.clear()
        sqlite_operations = vars(self).get("_sqlite_assignment_operations")
        if sqlite_operations is not None:
            sqlite_operations.clear()
        for report_id, assignment in assignments.items():
            if isinstance(assignment, tuple):
                group_name, color = assignment
            else:
                group_name, color = str(assignment), None
            group_name = str(group_name or self.default_group).strip() or self.default_group
            if group_name == self.default_group:
                continue
            temp_assignments[int(report_id)] = (
                group_name,
                self._normalized_group_color(color or self.default_group_color),
            )
        if self._is_sqlite_backed() and temp_assignments:
            for group_name, color in sorted(set(temp_assignments.values())):
                row_ids = [
                    row_id
                    for row_id, assignment in sorted(temp_assignments.items())
                    if assignment == (group_name, color)
                ]
                self._append_sqlite_row_assignment_operation(row_ids, group_name, color)
        self._ensure_group_color_integrity()

    def _materialize_grouping_dataframe(self) -> pd.DataFrame:
        assignments = self._temp_assignments()
        if self._is_sqlite_backed():
            if self._sqlite_effective_assignment_required():
                with sqlite_connection_scope(self.sqlite_store.path) as connection:
                    table_name = self._populate_sqlite_effective_assignment_table(connection)
                    records = connection.execute(
                        f"SELECT row_id, group_name, color FROM {table_name} ORDER BY row_id"
                    ).fetchall()
                return self._sqlite_assignment_dataframe(
                    [int(row_id) for row_id, _group_name, _color in records],
                    group_names=[str(group_name) for _row_id, group_name, _color in records],
                    colors=[self._normalized_group_color(color) for _row_id, _group_name, color in records],
                )
            row_ids: list[int] = []
            group_names: list[str] = []
            colors: list[str] = []
            for report_id, (group_name, color) in sorted(assignments.items()):
                row_ids.append(int(report_id))
                group_names.append(group_name)
                colors.append(self._normalized_group_color(color))
            return self._sqlite_assignment_dataframe(
                row_ids,
                group_names=group_names,
                colors=colors,
            )

        frame = self._base_grouping_dataframe().copy()
        if frame.empty or "REPORT_ID" not in frame.columns:
            return frame
        group_assignments = {row_id: group for row_id, (group, _color) in assignments.items()}
        color_assignments = {row_id: color for row_id, (_group, color) in assignments.items()}
        report_ids = pd.to_numeric(frame["REPORT_ID"], errors="coerce")
        frame["GROUP"] = report_ids.map(group_assignments).fillna(self.default_group).astype(str)
        frame[self.group_color_column] = (
            report_ids.map(color_assignments).fillna(self.default_group_color).astype(str)
        )
        frame.loc[frame["GROUP"] == self.default_group, self.group_color_column] = (
            self.default_group_color
        )
        frame["GROUP_KEY"] = report_ids.astype("Int64")
        return frame

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
        self._invalidate_selector_cache()
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
        state = self._selector_filter_state()
        if state.mode == "invalid":
            return [], 0
        return self.sqlite_store.preview_group_rows(
            tuple(self.selector_columns),
            search_text=self._selector_label_search_text(state),
            offset=offset,
            limit=limit,
            **self._sqlite_scope_kwargs(),
        )

    def _sqlite_selector_preview_should_run_async(self) -> bool:
        if not self._is_sqlite_backed() or not self.selector_columns:
            return False
        try:
            row_count = int(getattr(self.sqlite_store, "row_count", 0) or 0)
        except (TypeError, ValueError):
            row_count = 0
        return bool(row_count >= _ASYNC_SQLITE_SELECTOR_PREVIEW_ROWS and len(self.selector_columns) > 1)

    def _start_sqlite_selector_preview(self, filter_state: _SelectorFilterState) -> None:
        self._selector_preview_request_id += 1
        request_id = self._selector_preview_request_id
        self.selector_preview_label.setText("Loading matching groups...")
        set_status_variant(self.selector_preview_label, "neutral")
        self._close_selector_preview_loading_dialog()
        (
            self._selector_preview_loading_dialog,
            self._selector_preview_loading_label,
            self._selector_preview_loading_bar,
            self._selector_preview_loading_gif,
        ) = create_delayed_worker_progress_dialog(
            self,
            window_title="Loading CSV / Excel groups...",
            initial_status_text="Loading matching groups...\nReading SQLite grouping preview\nETA --",
            on_cancel=self._cancel_sqlite_selector_preview,
        )
        self._selector_preview_loading_bar.setRange(0, 0)
        thread = _SqliteSelectorPreviewThread(
            request_id=request_id,
            sqlite_store=self.sqlite_store,
            selector_columns=tuple(self.selector_columns),
            search_text=self._selector_label_search_text(filter_state),
            offset=self._selector_page_offset,
            limit=_SELECTOR_PAGE_SIZE,
            scope_kwargs=self._sqlite_scope_kwargs(),
        )
        self._selector_preview_threads.append(thread)
        thread.result_ready.connect(self._on_sqlite_selector_preview_ready)
        thread.error_occurred.connect(self._on_sqlite_selector_preview_error)
        thread.finished.connect(lambda thread=thread: self._on_sqlite_selector_preview_stopped(thread))
        thread.start()
        self._selector_preview_loading_dialog.show()

    def _cancel_sqlite_selector_preview(self) -> None:
        self._selector_preview_request_id += 1
        for thread in tuple(self._selector_preview_threads):
            thread.requestInterruption()
        if self._selector_preview_loading_label is not None:
            self._selector_preview_loading_label.setText(
                "Canceling group preview...\nWaiting for the current SQLite read to stop\nETA --"
            )
        self.selector_preview_label.setText("Group preview canceled.")
        set_status_variant(self.selector_preview_label, "warning")
        self._close_selector_preview_loading_dialog()

    def _close_selector_preview_loading_dialog(self) -> None:
        if self._selector_preview_loading_dialog is not None:
            self._selector_preview_loading_dialog.close()
        self._selector_preview_loading_dialog = None
        self._selector_preview_loading_label = None
        self._selector_preview_loading_bar = None
        self._selector_preview_loading_gif = None

    def _on_sqlite_selector_preview_ready(
        self,
        request_id: int,
        selector_columns: tuple,
        offset: int,
        preview_rows: list,
        total_rows: int,
    ) -> None:
        if request_id != self._selector_preview_request_id:
            return
        if tuple(selector_columns) != tuple(self.selector_columns) or int(offset) != self._selector_page_offset:
            return
        filter_state = self._selector_filter_state()
        if self._selector_page_offset >= total_rows and total_rows:
            self._selector_page_offset = max(
                0,
                ((int(total_rows) - 1) // _SELECTOR_PAGE_SIZE) * _SELECTOR_PAGE_SIZE,
            )
            self._refresh_selectors()
            return
        self._render_selector_preview(filter_state, preview_rows, int(total_rows))

    def _on_sqlite_selector_preview_error(self, request_id: int, message: str) -> None:
        if request_id != self._selector_preview_request_id:
            return
        self.selector_preview_label.setText(f"Could not load groups: {message}")
        set_status_variant(self.selector_preview_label, "danger")

    def _on_sqlite_selector_preview_stopped(self, thread: _SqliteSelectorPreviewThread) -> None:
        if thread in self._selector_preview_threads:
            self._selector_preview_threads.remove(thread)
        if thread.request_id == self._selector_preview_request_id:
            self._close_selector_preview_loading_dialog()
        thread.deleteLater()

    def _detach_sqlite_selector_preview_threads(self) -> None:
        self._selector_preview_request_id += 1
        self._close_selector_preview_loading_dialog()
        for thread in tuple(self._selector_preview_threads):
            for signal, slot in (
                (thread.result_ready, self._on_sqlite_selector_preview_ready),
                (thread.error_occurred, self._on_sqlite_selector_preview_error),
            ):
                try:
                    signal.disconnect(slot)
                except TypeError:
                    pass
            try:
                thread.finished.disconnect()
            except TypeError:
                pass
            thread.requestInterruption()
            self._selector_preview_threads.remove(thread)
            if not thread.isRunning():
                thread.deleteLater()
                continue
            _DETACHED_SELECTOR_PREVIEW_THREADS.append(thread)
            thread.finished.connect(lambda thread=thread: _release_detached_selector_preview_thread(thread))

    def _sqlite_selector_row_count(self) -> int:
        if not self._is_sqlite_backed():
            return 0
        if not self.selector_columns or not self.selected_selector_keys:
            return self._scope_row_count()
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
        state = self._selector_filter_state()
        if state.mode == "invalid":
            return 0
        return self.sqlite_store.count_rows(**self._sqlite_scope_kwargs())

    def _sqlite_filters_active(self) -> bool:
        state = self._selector_filter_state()
        return bool(
            self.sqlite_column_filters
            or (self.sqlite_filter_columns and self.sqlite_selected_filter_keys)
            or state.mode == "expression"
        )

    def _sqlite_group_counts(self) -> dict[str, int]:
        total = int(self.sqlite_store.count_rows())
        if self._sqlite_effective_assignment_required():
            with sqlite_connection_scope(self.sqlite_store.path) as connection:
                table_name = self._populate_sqlite_effective_assignment_table(connection)
                records = connection.execute(
                    f"SELECT group_name, COUNT(*) FROM {table_name} GROUP BY group_name"
                ).fetchall()
                assigned_custom_count = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0] or 0
                )
            group_counts = {
                str(group_name): int(row_count or 0)
                for group_name, row_count in records
                if str(group_name) != self.default_group
            }
            default_count = max(0, total - assigned_custom_count)
            if default_count or not group_counts:
                group_counts[self.default_group] = default_count
            return group_counts
        group_counts: dict[str, int] = {}
        for row_id, (group_name, _color) in self._temp_assignments().items():
            if group_name == self.default_group:
                continue
            group_counts[str(group_name)] = group_counts.get(str(group_name), 0) + 1
        assigned_custom_count = int(sum(group_counts.values()))
        default_count = max(0, total - assigned_custom_count)
        if default_count or not group_counts:
            group_counts[self.default_group] = default_count
        return {str(group): int(count) for group, count in group_counts.items()}

    def _sqlite_group_member_row_ids(self, group_name: str) -> tuple[list[int], int]:
        if not self._sqlite_effective_assignment_required():
            row_ids = [
                row_id
                for row_id, (assigned_group, _color) in sorted(self._temp_assignments().items())
                if assigned_group == group_name
            ]
            return row_ids[:_GROUP_MEMBER_PREVIEW_LIMIT], len(row_ids)
        with sqlite_connection_scope(self.sqlite_store.path) as connection:
            table_name = self._populate_sqlite_effective_assignment_table(connection)
            records = connection.execute(
                f"SELECT row_id FROM {table_name} WHERE group_name = ? ORDER BY row_id LIMIT ?",
                (group_name, _GROUP_MEMBER_PREVIEW_LIMIT),
            ).fetchall()
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE group_name = ?",
                    (group_name,),
                ).fetchone()[0] or 0
            )
        return [int(row[0]) for row in records], total

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
        self._invalidate_selector_cache()
        self._selector_page_offset = 0
        self._rebuild_preserving_groups()
        self._refresh_all()

    def clear_selector_columns(self) -> None:
        self.selector_columns = []
        self.selected_selector_keys = set()
        self._invalidate_selector_cache()
        self._selector_page_offset = 0
        self._rebuild_preserving_groups()
        self._refresh_all()

    def clear_selection(self) -> None:
        self.selected_selector_keys = set()
        self.selector_list.clearSelection()
        self._sync_status(recompute_counts=False, recompute_scope=False)

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
        self._base_grouping_dataframe_cache = None
        self._ensure_group_color_integrity()

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
        self._sync_status(recompute_counts=False, recompute_scope=False)

    def _row_ids_for_selected_keys(self) -> list[int]:
        if not self.selector_columns or not self.selected_selector_keys:
            return []
        if self._is_sqlite_backed():
            return self._sqlite_row_ids_for_selected_keys()
        return self._current_selector_index().row_ids_for_keys(self.selected_selector_keys)

    def _row_ids_for_scope(self) -> list[int]:
        state = self._selector_filter_state()
        if state.mode == "invalid":
            return []
        search_text = self._selector_label_search_text(state)
        if search_text:
            if not self.selector_columns:
                return []
            if self._is_sqlite_backed():
                return self.sqlite_store.row_ids_for_group_search(
                    tuple(self.selector_columns),
                    search_text=search_text,
                    **self._sqlite_scope_kwargs(),
                )
            keys = self._matching_selector_keys_for_search(search_text)
            if not keys:
                return []
            return self._current_selector_index().row_ids_for_keys(keys)
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

    def _assignment_color_for_group(self, group_name: str) -> str:
        if group_name == self.default_group:
            return self.default_group_color
        assignments = self._temp_assignments()
        group_exists = any(group == group_name for group, _color in assignments.values()) or bool(
            self._sqlite_assignment_operation_colors(group_name)
        )
        return self._group_color_for_group(group_name) if group_exists else self._next_group_color()

    def _assign_rows_to_group(self, row_ids: list[int], group_name: str) -> None:
        if not row_ids or not group_name:
            return
        assignments = self._temp_assignments()
        assigned_color = self._assignment_color_for_group(group_name)
        for row_id in dict.fromkeys(int(row_id) for row_id in row_ids):
            if group_name == self.default_group:
                assignments.pop(row_id, None)
            else:
                assignments[row_id] = (group_name, assigned_color)
        self._append_sqlite_row_assignment_operation(row_ids, group_name, assigned_color)
        self._ensure_group_color_integrity()

    def _sqlite_selected_keys_have_rows(self) -> bool:
        state = self._selector_filter_state()
        if (
            state.mode == "invalid"
            or not self._is_sqlite_backed()
            or not self.selector_columns
            or not self.selected_selector_keys
        ):
            return False
        return bool(
            self.sqlite_store.count_rows_for_group_keys(
                tuple(self.selector_columns),
                self.selected_selector_keys,
                **self._sqlite_scope_kwargs(),
            )
        )

    def _assign_sqlite_selected_keys_to_group(self, group_name: str) -> None:
        if not group_name or not self._is_sqlite_backed() or not self.selected_selector_keys:
            return
        assigned_color = self._assignment_color_for_group(group_name)
        self._sqlite_assignment_operations.append(
            _SqliteAssignmentOperation(
                kind="scope",
                group_name=group_name,
                color=assigned_color,
                scope=self._pending_sqlite_selected_keys_scope(),
            )
        )
        self._ensure_group_color_integrity()

    def create_group(self, initial_group_name: str | None = None) -> None:
        if self._is_sqlite_backed():
            row_ids: list[int] = []
            has_rows = self._sqlite_selected_keys_have_rows()
        else:
            row_ids = self._row_ids_for_selected_keys()
            has_rows = bool(row_ids)
        if not has_rows:
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
        if self._is_sqlite_backed():
            self._assign_sqlite_selected_keys_to_group(group_name)
        else:
            self._assign_rows_to_group(row_ids, group_name)
        self.selected_selector_keys = set()
        self.selector_list.clearSelection()
        self._refresh_all(preferred_group=group_name)

    def assign_filtered_rows(self, initial_group_name: str | None = None) -> None:
        if self._is_sqlite_backed():
            has_rows = self._scope_has_rows()
        else:
            row_ids = self._row_ids_for_scope()
            has_rows = bool(row_ids)
        if not has_rows:
            QMessageBox.information(
                self,
                self.windowTitle(),
                "No rows match the current search or filter.",
            )
            return
        selected_group = str(self._selected_group_name() or "").strip()
        default_name = str(initial_group_name or "").strip()
        if not default_name and selected_group and selected_group != self.default_group:
            default_name = selected_group
        if initial_group_name is None:
            group_name, accepted = QInputDialog.getText(
                self,
                "Assign all filtered rows",
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
        if self._is_sqlite_backed():
            assigned_color = self._assignment_color_for_group(group_name)
            self._sqlite_assignment_operations.append(
                _SqliteAssignmentOperation(
                    kind="scope",
                    group_name=group_name,
                    color=assigned_color,
                    scope=self._pending_sqlite_scope(),
                )
            )
        else:
            self._assign_rows_to_group(row_ids, group_name)
        self.selected_selector_keys = set()
        self.selector_list.clearSelection()
        self._refresh_all(preferred_group=group_name)

    def _current_selector_index(self) -> CsvGroupingIndex:
        selector_index = vars(self).get("_selector_index")
        source_frame = self._scoped_source_dataframe()
        if (
            selector_index is None
            or self._selector_index_source_frame is None
            or tuple(self.selector_columns) != selector_index.grouping_columns
            or selector_index.row_count != int(len(source_frame.index))
            or not source_frame.index.equals(self._selector_index_source_frame.index)
        ):
            self._selector_index = CsvGroupingIndex(source_frame, self.selector_columns)
            self._selector_index_source_frame = source_frame
        return self._selector_index

    def _invalidate_selector_cache(self) -> None:
        self._selector_index = None
        self._selector_index_source_frame = None
        self._selector_preview_cache.clear()
        self._selector_filter_state_cache = None
        self._scoped_source_dataframe_cache = None

    def _apply_selector_filter(self) -> None:
        self._applied_selector_filter_text = self._selector_filter_input_text()
        self._invalidate_selector_cache()
        self._selector_page_offset = 0
        self._refresh_selectors()
        self._sync_status(recompute_counts=False, recompute_scope=True)

    def _cached_selector_preview_rows(
        self,
        *,
        filter_state: _SelectorFilterState,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, object]], int]:
        cache_key = (
            tuple(self.selector_columns),
            filter_state.mode,
            filter_state.text,
            int(offset),
            int(limit),
        )
        cached = self._selector_preview_cache.get(cache_key)
        if cached is not None:
            return cached
        preview = self._current_selector_index().preview_rows(
            search_text=self._selector_label_search_text(filter_state),
            offset=offset,
            limit=limit,
        )
        self._selector_preview_cache[cache_key] = preview
        return preview

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
        assignments = self._temp_assignments()
        assigned_color = (
            self._group_color_for_group(new_name)
            if any(group == new_name for group, _color in assignments.values())
            else self._group_color_for_group(selected_group)
        )
        for row_id, (group_name, _color) in list(assignments.items()):
            if group_name == selected_group:
                assignments[row_id] = (new_name, assigned_color)
        if self._is_sqlite_backed():
            self._sqlite_assignment_operations.append(
                _SqliteAssignmentOperation(
                    kind="rename_group",
                    group_name=selected_group,
                    replacement_group_name=new_name,
                    replacement_color=assigned_color,
                )
            )
        if selected_group == self.default_group:
            self.default_group = new_name
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
        assignments = self._temp_assignments()
        for row_id, (group_name, _color) in list(assignments.items()):
            if group_name == selected_group:
                assignments.pop(row_id, None)
        if self._is_sqlite_backed():
            self._sqlite_assignment_operations.append(
                _SqliteAssignmentOperation(kind="delete_group", group_name=selected_group)
            )
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
        assignments = self._temp_assignments()
        for row_id in row_ids:
            if assignments.get(int(row_id), (None, None))[0] == selected_group:
                assignments.pop(int(row_id), None)
        self._append_sqlite_row_assignment_operation(row_ids, self.default_group, self.default_group_color)
        self._ensure_group_color_integrity()
        self._refresh_all(preferred_group=selected_group)

    def _sync_status(
        self,
        *,
        recompute_counts: bool = True,
        recompute_scope: bool = True,
    ) -> None:
        filter_state = self._selector_filter_state()
        if not self.selector_columns:
            self.selector_status_label.setText("No grouping columns selected")
            set_status_variant(self.selector_status_label, "neutral")
        else:
            columns_text = self._selector_columns_text()
            if self.selected_selector_keys:
                if recompute_counts:
                    row_count = (
                        self._sqlite_selector_row_count()
                        if self._is_sqlite_backed()
                        else self._current_selector_index().count_rows(self.selected_selector_keys)
                    )
                    self.selector_status_label.setText(
                        f"{columns_text}: {len(self.selected_selector_keys)} selected group(s), {row_count} rows"
                    )
                else:
                    self.selector_status_label.setText(
                        f"{columns_text}: {len(self.selected_selector_keys)} selected group(s)"
                    )
            else:
                self.selector_status_label.setText(f"{columns_text}: all rows")
            set_status_variant(
                self.selector_status_label,
                "warning" if filter_state.mode == "invalid" else "success",
            )
        self.create_group_button.setEnabled(
            bool(self.selector_columns and self.selected_selector_keys and filter_state.mode != "invalid")
        )
        if recompute_scope:
            self.assign_filtered_rows_button.setEnabled(self._scope_has_rows())
        selected_group = self._selected_group_name()
        self.rename_group_button.setEnabled(bool(selected_group))
        self.delete_group_button.setEnabled(bool(selected_group and selected_group != self.default_group))
        self.clear_selection_button.setEnabled(bool(self.selected_selector_keys))

    def _refresh_selectors(self) -> None:
        self.selector_list.blockSignals(True)
        self.selector_list.clear()
        filter_state = self._selector_filter_state()
        if filter_state.mode == "invalid":
            preview_rows, total_rows = [], 0
        elif self._sqlite_selector_preview_should_run_async():
            self.selector_list.blockSignals(False)
            self._start_sqlite_selector_preview(filter_state)
            return
        elif self._is_sqlite_backed():
            preview_rows, total_rows = self._sqlite_preview_rows(
                offset=self._selector_page_offset,
                limit=_SELECTOR_PAGE_SIZE,
            )
        else:
            preview_rows, total_rows = self._cached_selector_preview_rows(
                filter_state=filter_state,
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
                preview_rows, total_rows = self._cached_selector_preview_rows(
                    filter_state=filter_state,
                    offset=self._selector_page_offset,
                    limit=_SELECTOR_PAGE_SIZE,
                )
            self._selector_total_rows = total_rows
        self._render_selector_preview(filter_state, preview_rows, total_rows)

    def _render_selector_preview(
        self,
        filter_state: _SelectorFilterState,
        preview_rows: list[dict[str, object]],
        total_rows: int,
    ) -> None:
        self._selector_total_rows = int(total_rows)
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
        if filter_state.mode == "invalid":
            self.selector_preview_label.setText(f"Invalid filter: {filter_state.error}")
            set_status_variant(self.selector_preview_label, "warning")
        elif not self.selector_columns:
            self.selector_preview_label.setText("Add a grouping column to preview row groups.")
            set_status_variant(self.selector_preview_label, "neutral")
        elif total_rows > len(preview_rows):
            self.selector_preview_label.setText(
                f"Showing {start}-{end} of {total_rows}; Assign all filtered rows skips paging."
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
            search_text=getattr(self, "_applied_selected_column_search_text", ""),
            current_column=current_column_from_list(self.selected_columns_list),
            fallback="last",
            block_signals=True,
        )

    def _apply_selected_column_search(self) -> None:
        self._applied_selected_column_search_text = str(
            self.selected_column_search.text() or ""
        ).strip()
        self._refresh_selected_columns()

    def _refresh_groups(self, preferred_group: str | None = None) -> None:
        self.groups_list.blockSignals(True)
        self.groups_list.clear()
        group_counts = self._group_counts()
        if not group_counts:
            group_counts[self.default_group] = 0
        self._last_group_counts = {str(group): int(count) for group, count in group_counts.items()}
        non_default_group_index = 0
        for group_name, count in sorted(group_counts.items(), key=lambda item: (item[0] != self.default_group, str(item[0]))):
            group_name = str(group_name)
            if group_name == self.default_group:
                label = f"{group_name} (n={int(count)})"
            else:
                non_default_group_index += 1
                label = f"{group_name} [{non_default_group_index}] (n={int(count)})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, group_name)
            self._apply_item_color(item, self._group_color_for_group(group_name))
            self.groups_list.addItem(item)
            if preferred_group == group_name:
                item.setSelected(True)
                self.groups_list.setCurrentItem(item)
        if self.groups_list.currentItem() is None and self.groups_list.count():
            self.groups_list.setCurrentRow(0)
        self.groups_list.blockSignals(False)

    def _group_counts(self) -> dict[str, int]:
        if self._is_sqlite_backed():
            return self._sqlite_group_counts()
        total = int(len(self.source_dataframe.index))
        valid_row_ids = self._source_row_ids()
        assigned_ids: set[int] = set()
        group_counts: dict[str, int] = {}
        for row_id, (group_name, _color) in self._temp_assignments().items():
            if group_name == self.default_group:
                continue
            if valid_row_ids and int(row_id) not in valid_row_ids:
                continue
            assigned_ids.add(int(row_id))
            group_counts[str(group_name)] = group_counts.get(str(group_name), 0) + 1
        default_count = max(0, total - len(assigned_ids))
        if default_count or not group_counts:
            group_counts[self.default_group] = default_count
        return group_counts

    def _populate_group_members(self, *, recompute_status_counts: bool = False) -> None:
        self.group_members_list.clear()
        selected_group = self._selected_group_name()
        if not selected_group:
            self._sync_status(
                recompute_counts=recompute_status_counts,
                recompute_scope=recompute_status_counts,
            )
            return
        if selected_group == self.default_group:
            group_counts = self._last_group_counts or self._group_counts()
            total_rows = group_counts.get(self.default_group, 0)
            item = QListWidgetItem(
                f"{self.default_group} contains {total_rows} unassigned row(s). "
                "Select row values and assign a group to create custom groups."
            )
            self._apply_item_color(item, self.default_group_color)
            self.group_members_list.addItem(item)
            self._sync_status(
                recompute_counts=recompute_status_counts,
                recompute_scope=recompute_status_counts,
            )
            return
        if self._is_sqlite_backed():
            row_ids, total_rows = self._sqlite_group_member_row_ids(selected_group)
        else:
            row_ids = [
                row_id
                for row_id, (group_name, _color) in sorted(self._temp_assignments().items())
                if group_name == selected_group
            ]
            total_rows = len(row_ids)
        rows = self._group_member_rows(row_ids, selected_group)
        preview = rows.head(_GROUP_MEMBER_PREVIEW_LIMIT)
        column_positions = {str(column): index for index, column in enumerate(preview.columns)}

        def _row_value(values: tuple[object, ...], column: str) -> object:
            position = column_positions.get(column)
            if position is None or position >= len(values):
                return None
            return values[position]

        for values in preview.itertuples(index=False, name=None):
            label = str(
                _row_value(values, "REFERENCE")
                or _row_value(values, "PART_NAME")
                or _row_value(values, "SAMPLE_NUMBER")
                or ""
            )
            if not label:
                label = f"Row {_row_value(values, 'REPORT_ID')}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, _row_value(values, "REPORT_ID"))
            color = _row_value(values, self.group_color_column)
            self._apply_item_color(
                item,
                self.default_group_color if pd.isna(color) or not str(color).strip() else str(color),
            )
            self.group_members_list.addItem(item)
        if total_rows > _GROUP_MEMBER_PREVIEW_LIMIT:
            item = QListWidgetItem(
                f"Showing first {_GROUP_MEMBER_PREVIEW_LIMIT} of {total_rows} row(s)."
            )
            self.group_members_list.addItem(item)
        self._sync_status(
            recompute_counts=recompute_status_counts,
            recompute_scope=recompute_status_counts,
        )

    def _group_member_rows(self, row_ids: list[int], group_name: str) -> pd.DataFrame:
        if not row_ids:
            return self._empty_grouping_dataframe()
        color = self._group_color_for_group(group_name)
        if self._is_sqlite_backed():
            return self._sqlite_assignment_dataframe(row_ids, group_name, color)
        frame = self._base_grouping_dataframe()
        if frame.empty or "REPORT_ID" not in frame.columns:
            return self._empty_grouping_dataframe()
        report_ids = pd.to_numeric(frame["REPORT_ID"], errors="coerce")
        rows = frame.loc[report_ids.isin(row_ids)].copy()
        rows["GROUP"] = group_name
        rows[self.group_color_column] = color
        return rows

    def _refresh_all(self, preferred_group: str | None = None) -> None:
        self._refresh_available_columns()
        self._refresh_selected_columns()
        self._refresh_selectors()
        self._refresh_groups(preferred_group=preferred_group)
        self._populate_group_members(recompute_status_counts=True)

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
                focused_line_edits=(
                    (self.column_search, self._apply_column_search),
                    (self.selected_column_search, self._apply_selected_column_search),
                    (self.selector_search, self._apply_selector_filter),
                    (self.page_jump_input, self.jump_selector_page),
                ),
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
        materialized = self._materialize_grouping_dataframe()
        set_default_group_label(materialized, self.default_group)
        self.df = materialized
        if parent is not None:
            parent.set_df_for_grouping(materialized)
            parent.set_grouping_applied(True)
        self.accept()

    def dont_use_grouping(self) -> None:
        parent = self.parent()
        self._temp_assignments().clear()
        self._sqlite_assignment_operations.clear()
        self.df = self._empty_grouping_dataframe()
        if parent is not None:
            parent.set_df_for_grouping(None)
            parent.set_grouping_applied(False)
        self.accept()

    def accept(self) -> None:
        self._detach_sqlite_selector_preview_threads()
        super().accept()

    def reject(self) -> None:
        self._detach_sqlite_selector_preview_threads()
        super().reject()

    def closeEvent(self, event) -> None:
        self._detach_sqlite_selector_preview_threads()
        super().closeEvent(event)


__all__ = ["TabularAnalyticsGroupingDialog"]
