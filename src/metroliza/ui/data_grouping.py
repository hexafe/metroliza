"""Provide the data-grouping dialog used to curate export grouping presets.

This UI reads report data from SQLite and coordinates with the main window to
store, apply, and clear reference/part grouping assignments.
"""

import inspect
import re
import sqlite3

import metroliza.shared.custom_logger as custom_logger
from metroliza.reports.db import read_sql_dataframe
from metroliza.tabular.data_grouping_service import (
    build_grouping_row_index,
    build_grouping_query as _build_grouping_query,
    build_grouping_scope_query_from_filter_state,
    compute_group_key_for_df as _compute_group_key_for_df,
    load_grouping_dataframe,
    reassign_group_keys_to_default,
)
from metroliza.exporting.export_grouping_utils import set_default_group_label
from metroliza.shared.grouping_filter_core import apply_filter_specs, parse_filter_expression
from metroliza.reports.report_schema import ensure_report_schema
from metroliza.shared.list_selection_utils import GroupingShortcutBindings, ListSelectionUtils
from metroliza.ui import ui_theme_tokens
try:
    from metroliza.ui import ui_foundation
except Exception:  # pragma: no cover - fallback for heavily stubbed tests
    class _UiFoundationFallback:
        @staticmethod
        def apply_metroliza_theme(_widget):
            return None

        @staticmethod
        def configure_window_size(widget, *, minimum=(420, 260), initial=(640, 420), screen_margin=40):
            del minimum, screen_margin
            if hasattr(widget, "resize"):
                widget.resize(*initial)

        @staticmethod
        def status_chip(text, variant="neutral"):
            del variant
            return QtWidgets.QLabel(text)

    ui_foundation = _UiFoundationFallback()
from metroliza.ui.help_menu import attach_help_menu_to_layout
from PyQt6.QtCore import Qt
import PyQt6.QtWidgets as QtWidgets
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import(
    QDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QInputDialog,
    QMessageBox,
)
import pandas as pd


_GROUPING_LIST_PREVIEW_LIMIT = 1000
_SCOPE_FILTER_PLACEHOLDER = "Filter rows, e.g. Supplier IN (SUPPLIER, Partner*) AND Date>=2026-05-01"
_SCOPE_FILTER_ALIAS_CANDIDATES = (
    ("Sample", ("SAMPLE_NUMBER", "sample_number")),
    ("Date", ("DATE", "date", "report_date")),
    ("Part", ("PART_NAME", "part_name")),
    ("Status", ("STATUS_CODE", "status_code")),
    ("Supplier", ("SUPPLIER", "supplier", "SUPPLIER_NAME", "supplier_name")),
)
_SCOPE_FILTER_TERM_SPLIT_RE = re.compile(r"(\s+(?:AND|OR)\s+)", flags=re.IGNORECASE)
_SCOPE_FILTER_FIELD_RE = re.compile(
    r"^(?P<leading>\s*)(?P<field>.+?)(?P<operator>\s*(?:>=|<=|!=|=|>|<|\bNOT\s+IN\b|\bIN\b)\s*)",
    flags=re.IGNORECASE,
)


class DataGrouping(QDialog):
    """DataGrouping public interface used by export and UI workflows."""

    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        self.setWindowTitle("Data grouping")
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())
        self.setModal(True)

        self.db_file = db_file
        self.df = None
        self.default_group = "POPULATION"
        self.default_group_color = self._resolve_default_group_color()
        self.group_color_column = "GROUP_COLOR"
        self.group_palette = ui_theme_tokens.themed_group_palette(
            dark_mode=self._is_dark_mode_base(self.default_group_color)
        )
        self._group_display_to_name = {}
        self._reference_display_to_name = {}
        self._list_selection_utils = ListSelectionUtils()
        self._grouping_shortcuts = None
        self._applied_scope_filter_text = ""
        self._cached_filtered_grouping_dataframe = None
        self._cached_grouping_row_index = None
        self._cached_full_grouping_row_index = None

        self.setup_ui()

        self.read_data_to_df()
        self.add_default_group()
        self._restore_saved_grouping_state()
        self.populate_list_widgets()

    @staticmethod
    def _multi_selection_mode():
        selection_mode_enum = getattr(getattr(QtWidgets, "QAbstractItemView", None), "SelectionMode", None)
        return getattr(selection_mode_enum, "MultiSelection", 2)

    @staticmethod
    def _safe_attr(instance, name, default=None):
        try:
            return getattr(instance, name, default)
        except RuntimeError:
            # PyQt raises this for uninitialized QObject test doubles created
            # with __new__ to exercise pure helper behavior.
            return default

    def setup_ui(self):
        """Handle `setup_ui` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.create_widgets()
            self.arrange_layout()
            self.connect_signals()
            self._refresh_selection_summary()
        except Exception as e:
            self.log_and_exit(e)

    def create_widgets(self):
        """Handle `create_widgets` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            # Create labels and list widgets for each column to be filtered
            self.reference_label = QLabel("Reference:")
            self.reference_list = QListWidget()

            self.part_label = QLabel("Parts:")
            self.part_list = QListWidget()
            self.part_list.setSelectionMode(self._multi_selection_mode())
            self.all_parts_list = QListWidget()
            self.all_parts_list.setSelectionMode(self._multi_selection_mode())

            self.groups_label = QLabel("Groups:")
            self.groups_list = QListWidget()

            self.part_group_label = QLabel("Parts in selected group:")
            self.part_group_list = QListWidget()
            self.part_group_list.setSelectionMode(self._multi_selection_mode())

            # Create separate QLineEdit widgets for searching in each list widget
            self.reference_search_input = QLineEdit()
            self.reference_search_input.setPlaceholderText("Search reference...")
            self.part_search_input = QLineEdit()
            self.part_search_input.setPlaceholderText("Search part...")
            self.group_search_input = QLineEdit()
            self.group_search_input.setPlaceholderText("Search group...")
            self.part_group_search_input = QLineEdit()
            self.part_group_search_input.setPlaceholderText("Search selected group...")

            # Create buttons
            self.create_group_button = QPushButton("Create or add")
            self.create_group_button.setDisabled(True)
            self.rename_group_button = QPushButton("Rename group")
            self.rename_group_button.setDisabled(True)
            self.remove_from_group_button = QPushButton("Remove from group")
            self.remove_from_group_button.setDisabled(True)
            self.delete_group_button = QPushButton("Delete group")
            self.delete_group_button.setDisabled(True)

            self.use_grouping_button = QPushButton("Use grouping")
            self.dont_use_grouping_button = QPushButton("Clear grouping")
            for button in (
                self.create_group_button,
                self.rename_group_button,
                self.remove_from_group_button,
                self.delete_group_button,
                self.use_grouping_button,
                self.dont_use_grouping_button,
            ):
                if hasattr(button, "setDefault"):
                    button.setDefault(False)
                if hasattr(button, "setAutoDefault"):
                    button.setAutoDefault(False)
            self.reference_summary_label = ui_foundation.status_chip("Reference: none", variant="neutral")
            self.group_summary_label = ui_foundation.status_chip("Group: none", variant="neutral")
            self.selection_summary_label = ui_foundation.status_chip("Selected parts: 0", variant="neutral")
            self.scope_filter_input = QLineEdit()
            self.scope_filter_input.setPlaceholderText(self._scope_filter_placeholder())
            self.scope_filter_summary_label = ui_foundation.status_chip("Scope: all rows", variant="neutral")
        except Exception as e:
            self.log_and_exit(e)

    def arrange_layout(self):
        """Handle `arrange_layout` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.layout = QGridLayout(self)
            attach_help_menu_to_layout(self.layout, self, [("Grouping manual", 'export_grouping')])
            self.layout.setContentsMargins(10, 10, 10, 10)
            self.layout.setHorizontalSpacing(8)
            self.layout.setVerticalSpacing(8)
            ui_foundation.apply_metroliza_theme(self)

            summary_row = QtWidgets.QHBoxLayout()
            summary_row.setContentsMargins(0, 0, 0, 0)
            summary_row.setSpacing(8)
            summary_row.addWidget(self.reference_summary_label, 1)
            summary_row.addWidget(self.group_summary_label, 1)
            summary_row.addWidget(self.selection_summary_label, 1)
            summary_row.addWidget(self.scope_filter_input, 2)
            summary_row.addWidget(self.scope_filter_summary_label, 1)
            self.layout.addLayout(summary_row, 0, 0, 1, 4)

            self.layout.addWidget(self.reference_label, 1, 0)
            self.layout.addWidget(self.reference_search_input, 2, 0)
            self.layout.addWidget(self.reference_list, 3, 0)

            self.layout.addWidget(self.part_label, 1, 1)
            self.layout.addWidget(self.part_search_input, 2, 1)
            self.layout.addWidget(self.part_list, 3, 1)

            self.layout.addWidget(self.groups_label, 1, 2)
            self.layout.addWidget(self.group_search_input, 2, 2)
            self.layout.addWidget(self.groups_list, 3, 2)

            self.layout.addWidget(self.part_group_label, 1, 3)
            self.layout.addWidget(self.part_group_search_input, 2, 3)
            self.layout.addWidget(self.part_group_list, 3, 3)

            self._configure_pane_widget(self.reference_search_input, min_width=160)
            self._configure_pane_widget(self.part_search_input, min_width=220)
            self._configure_pane_widget(self.group_search_input, min_width=180)
            self._configure_pane_widget(self.part_group_search_input, min_width=220)
            self._configure_pane_widget(self.reference_list, min_width=160, min_height=220, expands_vertically=True)
            self._configure_pane_widget(self.part_list, min_width=220, min_height=220, expands_vertically=True)
            self._configure_pane_widget(self.groups_list, min_width=180, min_height=220, expands_vertically=True)
            self._configure_pane_widget(self.part_group_list, min_width=220, min_height=220, expands_vertically=True)

            for column in range(4):
                self.layout.setColumnStretch(column, 1 if column in (0, 2) else 2)
                self.layout.setColumnMinimumWidth(column, 150 if column in (0, 2) else 210)
            self.layout.setRowStretch(3, 1)

            actions_row_one = QtWidgets.QHBoxLayout()
            actions_row_one.setContentsMargins(0, 0, 0, 0)
            actions_row_one.setSpacing(8)
            actions_row_one.addWidget(self.create_group_button)
            actions_row_one.addWidget(self.rename_group_button)
            actions_row_one.addStretch(1)
            self.layout.addLayout(actions_row_one, 4, 0, 1, 4)

            actions_row_two = QtWidgets.QHBoxLayout()
            actions_row_two.setContentsMargins(0, 0, 0, 0)
            actions_row_two.setSpacing(8)
            actions_row_two.addWidget(self.remove_from_group_button)
            actions_row_two.addWidget(self.delete_group_button)
            actions_row_two.addStretch(1)
            self.layout.addLayout(actions_row_two, 5, 0, 1, 4)

            final_row = QtWidgets.QHBoxLayout()
            final_row.setContentsMargins(0, 0, 0, 0)
            final_row.setSpacing(8)
            final_row.addStretch(1)
            final_row.addWidget(self.dont_use_grouping_button)
            final_row.addWidget(self.use_grouping_button)
            self.layout.addLayout(final_row, 6, 0, 1, 4)

            ui_foundation.configure_window_size(
                self,
                minimum=(900, 500),
                initial=(1240, 700),
                screen_margin=44,
            )
        except Exception as e:
            self.log_and_exit(e)

    def connect_signals(self):
        """Handle `connect_signals` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.reference_search_input.returnPressed.connect(lambda: self.search_list_widgets(self.reference_list, self.reference_search_input.text()))
            self.part_search_input.returnPressed.connect(lambda: self.search_list_widgets(self.part_list, self.part_search_input.text()))
            self.group_search_input.returnPressed.connect(lambda: self.search_list_widgets(self.groups_list, self.group_search_input.text()))
            self.part_group_search_input.returnPressed.connect(lambda: self.search_list_widgets(self.part_group_list, self.part_group_search_input.text()))
            self.scope_filter_input.returnPressed.connect(self._apply_scope_filter)

            # Connect the itemSelectionChanged signal of the "REFERENCE" list to the on_reference_selection_changed method
            self.reference_list.itemSelectionChanged.connect(self.on_reference_selection_changed)
            self.reference_list.itemDoubleClicked.connect(self.on_reference_item_double_clicked)

            # Connect the itemSelectionChanged signal of the "GROUPS" list to the on_group_selection_changed method
            self.groups_list.itemSelectionChanged.connect(self.on_group_selection_changed)
            self.groups_list.itemDoubleClicked.connect(self.on_group_item_double_clicked)

            # Connect the itemSelectionChanged signal of the "PART #" list to the on_part_selection_changed method
            self.part_list.itemSelectionChanged.connect(self.on_part_selection_changed)
            self.part_list.itemDoubleClicked.connect(self.on_part_item_double_clicked)

            # Connect the itemSelectionChanged signal of the "PART IN SELECTED GROUP" list to the on_part_group_selection_changed method
            self.part_group_list.itemSelectionChanged.connect(self.on_part_group_selection_changed)

            self._connect_shift_range_for_list(self.part_list)
            self._connect_shift_range_for_list(self.part_group_list)
            self._grouping_shortcuts = GroupingShortcutBindings(
                source_list=self.part_list,
                reference_list=self.reference_list,
                groups_list=self.groups_list,
                assigned_list=self.part_group_list,
                create_group=self.create_group,
                rename_group=self.rename_group,
                delete_group=self.delete_group,
                remove_from_source=self._delete_selected_parts_from_part_list,
                remove_from_assigned=self._delete_selected_parts_from_group,
                focused_line_edits=(
                    (
                        self.reference_search_input,
                        lambda: self.search_list_widgets(
                            self.reference_list,
                            self.reference_search_input.text(),
                        ),
                    ),
                    (
                        self.part_search_input,
                        lambda: self.search_list_widgets(
                            self.part_list,
                            self.part_search_input.text(),
                        ),
                    ),
                    (
                        self.group_search_input,
                        lambda: self.search_list_widgets(
                            self.groups_list,
                            self.group_search_input.text(),
                        ),
                    ),
                    (
                        self.part_group_search_input,
                        lambda: self.search_list_widgets(
                            self.part_group_list,
                            self.part_group_search_input.text(),
                        ),
                    ),
                    (self.scope_filter_input, self._apply_scope_filter),
                ),
                error_handler=self.log_and_exit,
                qt_namespace=Qt,
            )

            self.create_group_button.clicked.connect(self.create_group)
            self.rename_group_button.clicked.connect(self.rename_group)
            self.remove_from_group_button.clicked.connect(self.remove_from_group)
            self.delete_group_button.clicked.connect(self.delete_group)

            self.use_grouping_button.clicked.connect(self.use_grouping)
            self.dont_use_grouping_button.clicked.connect(self.dont_use_grouping)
            for list_widget in (
                self.reference_list,
                self.part_list,
                self.groups_list,
                self.part_group_list,
            ):
                list_widget.itemSelectionChanged.connect(self._refresh_selection_summary)
        except Exception as e:
            self.log_and_exit(e)

    def _connect_shift_range_for_list(self, list_widget):
        self._list_selection_utils.connect_shift_range_behavior(list_widget)

    def _handle_list_item_pressed(self, list_widget, item):
        self._list_selection_utils.handle_shift_range_press(list_widget, item)

    def _configure_pane_widget(self, widget, *, min_width=None, min_height=None, expands_vertically=False):
        if widget is None:
            return
        if min_width is not None and hasattr(widget, "setMinimumWidth"):
            widget.setMinimumWidth(min_width)
        if min_height is not None and hasattr(widget, "setMinimumHeight"):
            widget.setMinimumHeight(min_height)
        size_policy_class = getattr(QtWidgets, "QSizePolicy", None)
        policy_enum = getattr(size_policy_class, "Policy", None)
        if size_policy_class is None or policy_enum is None or not hasattr(widget, "setSizePolicy"):
            return
        horizontal_policy = getattr(policy_enum, "Expanding", None)
        vertical_policy = getattr(policy_enum, "Expanding" if expands_vertically else "Preferred", None)
        if horizontal_policy is not None and vertical_policy is not None:
            widget.setSizePolicy(horizontal_policy, vertical_policy)

    def _refresh_selection_summary(self):
        reference_label = self._safe_attr(self, "reference_summary_label")
        group_label = self._safe_attr(self, "group_summary_label")
        selection_label = self._safe_attr(self, "selection_summary_label")
        if reference_label is None and group_label is None and selection_label is None:
            return

        reference_text = "none"
        selected_reference = self._selected_reference_name()
        if selected_reference:
            reference_text = selected_reference
        if reference_label is not None and hasattr(reference_label, "setText"):
            reference_label.setText(f"Reference: {reference_text}")

        selected_group_name = self._selected_group_name() or "none"
        if group_label is not None and hasattr(group_label, "setText"):
            group_label.setText(f"Group: {selected_group_name}")

        part_list = self._safe_attr(self, "part_list")
        part_group_list = self._safe_attr(self, "part_group_list")
        selected_part_count = len(part_list.selectedItems()) if part_list is not None and hasattr(part_list, "selectedItems") else 0
        selected_group_part_count = len(part_group_list.selectedItems()) if part_group_list is not None and hasattr(part_group_list, "selectedItems") else 0
        summary_text = f"Selected parts: {selected_part_count}"
        if selected_group_part_count:
            summary_text += f" | Selected in group: {selected_group_part_count}"
        if selection_label is not None and hasattr(selection_label, "setText"):
            selection_label.setText(summary_text)
        create_button = self._safe_attr(self, "create_group_button")
        if create_button is not None and hasattr(create_button, "setEnabled"):
            create_button.setEnabled(self._has_groupable_selection())

    def read_data_to_df(self):
        """Handle `read_data_to_df` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            initial_filter_query = getattr(self, "_initial_grouping_filter_query", None)
            filter_query = initial_filter_query() if callable(initial_filter_query) else None
            ensure_report_schema(self.db_file)
            self.df = load_grouping_dataframe(read_sql_dataframe, self.db_file, filter_query)
            self._invalidate_grouping_cache()
        except (sqlite3.Error, ValueError, TypeError) as e:
            self.log_and_exit(e)
        except Exception as e:
            self.log_and_exit(e, reraise=True)

    def _initial_grouping_filter_query(self):
        parent = self.parent()
        if parent is None:
            return None
        filter_state = getattr(parent, "filter_state", None)
        if filter_state is not None:
            return build_grouping_scope_query_from_filter_state(filter_state)
        get_filter_query = getattr(parent, "get_filter_query", None)
        if callable(get_filter_query):
            return get_filter_query()
        return None

    @staticmethod
    def _build_grouping_query(filter_query):
        return _build_grouping_query(filter_query)

    def refresh_data(self):
        """Handle `refresh_data` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.read_data_to_df()
            self.add_default_group()
            self._restore_saved_grouping_state()
            self._invalidate_grouping_cache()
            self.populate_list_widgets()
        except Exception as e:
            self.log_and_exit(e, reraise=True)

    def add_default_group(self):
        """Handle `add_default_group` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.df["GROUP"] = self.default_group
            self.df[self.group_color_column] = self.default_group_color
            self.df["GROUP_KEY"] = self._compute_group_key_for_df(self.df)
            self._invalidate_grouping_cache()
        except Exception as e:
            self.log_and_exit(e)

    def _restore_saved_grouping_state(self):
        try:
            parent = self.parent()
            saved_df = getattr(parent, 'df_for_grouping', None) if parent is not None else None
            if not isinstance(saved_df, pd.DataFrame) or saved_df.empty:
                return

            merge_columns = ['GROUP_KEY', 'GROUP']
            if self.group_color_column in saved_df.columns:
                merge_columns.append(self.group_color_column)

            saved_projection = saved_df[merge_columns].drop_duplicates(subset=['GROUP_KEY'], keep='last')
            merged = self.df.drop(columns=['GROUP'], errors='ignore').merge(saved_projection, on='GROUP_KEY', how='left')
            self.df['GROUP'] = merged['GROUP'].fillna(self.default_group)
            if self.group_color_column in merged.columns:
                self.df[self.group_color_column] = merged[self.group_color_column].fillna(self.default_group_color)
            else:
                self.df[self.group_color_column] = self.default_group_color
            self._ensure_group_color_integrity()
            self._invalidate_grouping_cache()
        except Exception as e:
            self.log_and_exit(e)

    @staticmethod
    def _ideal_text_color(background_hex):
        return ui_theme_tokens.ideal_text_color(background_hex)

    @staticmethod
    def _resolve_default_group_color_from_base(base_hex, fallback_hex='#FFFFFF'):
        return ui_theme_tokens.resolve_base_row_background(base_hex or fallback_hex)

    @staticmethod
    def _is_dark_mode_base(base_hex):
        return ui_theme_tokens.is_dark_mode_base(base_hex)

    @staticmethod
    def _clamp_group_color_for_theme(color_hex, dark_mode=False):
        return ui_theme_tokens.clamp_group_color_for_theme(color_hex, dark_mode=dark_mode)

    def _palette_for_current_theme(self, base_palette):
        dark_mode = self._is_dark_mode_base(self.default_group_color)
        return ui_theme_tokens.themed_group_palette(base_palette=base_palette, dark_mode=dark_mode)

    def _resolve_default_group_color(self):
        palette = self.palette() if hasattr(self, 'palette') else None
        base = palette.base().color() if palette is not None and hasattr(palette, 'base') else None
        base_hex = base.name() if base is not None and hasattr(base, 'isValid') and base.isValid() else None
        return ui_theme_tokens.resolve_base_row_background(base_hex)

    def _next_group_color(self):
        used = set(
            self.df.loc[self.df['GROUP'] != self.default_group, self.group_color_column]
            .dropna()
            .astype(str)
            .tolist()
        )
        for color in self.group_palette:
            if color not in used:
                return color

        seed = len(used)
        dark_mode = self._is_dark_mode_base(self.default_group_color)
        return ui_theme_tokens.generate_group_color(seed, dark_mode=dark_mode)

    def _ensure_group_color_integrity(self):
        if self.group_color_column not in self.df.columns:
            self.df[self.group_color_column] = self.default_group_color

        self.df[self.group_color_column] = self.df[self.group_color_column].fillna(self.default_group_color)
        self.df.loc[self.df['GROUP'] == self.default_group, self.group_color_column] = self.default_group_color

        for group_name in self.df['GROUP'].dropna().astype(str).unique():
            if group_name == self.default_group:
                continue
            existing = self.df.loc[self.df['GROUP'] == group_name, self.group_color_column].dropna().astype(str)
            assigned_color = next((value for value in existing if value and value != self.default_group_color), None)
            if assigned_color is None:
                assigned_color = self._next_group_color()
            self.df.loc[self.df['GROUP'] == group_name, self.group_color_column] = assigned_color

    def _group_color_for_row(self, row):
        color = getattr(row, self.group_color_column, self.default_group_color)
        if pd.isna(color) or not str(color).strip():
            return self.default_group_color
        dark_mode = self._is_dark_mode_base(self.default_group_color)
        return ui_theme_tokens.normalize_group_display_color(str(color), dark_mode=dark_mode, fallback=self.default_group_color)

    def _apply_item_color(self, item, color_hex):
        color = QColor(color_hex)
        if not color.isValid():
            color = QColor(self.default_group_color)
        resolved_background = color.name().upper()
        item.setBackground(QBrush(color))
        item.setForeground(QBrush(QColor(self._ideal_text_color(resolved_background))))

    def _apply_list_theme_styles(self):
        highlight_name = ui_theme_tokens.SELECTED_ROW_BACKGROUND_FALLBACK
        for list_widget in (
            getattr(self, 'reference_list', None),
            getattr(self, 'part_list', None),
            getattr(self, 'groups_list', None),
            getattr(self, 'part_group_list', None),
        ):
            if list_widget is None or not hasattr(list_widget, 'setStyleSheet'):
                continue

            palette = list_widget.palette() if hasattr(list_widget, 'palette') else None
            highlight_color = palette.highlight().color() if palette is not None and hasattr(palette, 'highlight') else None
            if highlight_color is not None and hasattr(highlight_color, 'isValid') and highlight_color.isValid():
                highlight_name = highlight_color.name()

            highlight_name = ui_theme_tokens.selected_row_background_override(highlight_name)
            selected_text_color = ui_theme_tokens.selected_text_color(highlight_name)
            list_widget.setStyleSheet(
                "QListWidget::item:selected {"
                f" background-color: {highlight_name};"
                f" color: {selected_text_color};"
                " }"
            )

    def _compute_group_key_for_df(self, df):
        try:
            return _compute_group_key_for_df(df)
        except Exception as e:
            self.log_and_exit(e)

    @staticmethod
    def _display_text(value):
        if value is None:
            return ""

        try:
            if pd.isna(value):
                return ""
        except TypeError:
            pass

        text = str(value).strip()
        if text in {"", "None", "<NA>"}:
            return ""
        return text

    @staticmethod
    def _truthy_text(value):
        text = DataGrouping._display_text(value)
        if not text:
            return False
        return text.lower() not in {"0", "false", "no", "none"}

    @staticmethod
    def _scope_filter_placeholder():
        return _SCOPE_FILTER_PLACEHOLDER

    @staticmethod
    def _row_field_value(row, field_name):
        if hasattr(row, field_name):
            return getattr(row, field_name)
        try:
            return row[field_name]
        except (AttributeError, KeyError, TypeError):
            return None

    @classmethod
    def _first_row_field_value(cls, row, field_names):
        for field_name in field_names:
            value = cls._row_field_value(row, field_name)
            if cls._display_text(value):
                return value
        return None

    @staticmethod
    def _scope_filter_alias_kw():
        try:
            parameters = inspect.signature(parse_filter_expression).parameters
        except (TypeError, ValueError):
            return None

        for name in ("aliases", "field_aliases", "column_aliases"):
            if name in parameters:
                return name
        if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
            return "aliases"
        return None

    @classmethod
    def _scope_filter_field_aliases(cls, columns):
        column_lookup = {str(column).casefold(): str(column) for column in columns}
        aliases = {}
        for alias, candidate_columns in _SCOPE_FILTER_ALIAS_CANDIDATES:
            for candidate_column in candidate_columns:
                resolved_column = column_lookup.get(str(candidate_column).casefold())
                if resolved_column:
                    aliases[alias] = resolved_column
                    break
        return aliases

    @classmethod
    def _normalize_scope_filter_aliases(cls, expression, aliases):
        if not aliases:
            return expression

        alias_lookup = {str(alias).casefold(): str(column) for alias, column in aliases.items()}
        parts = _SCOPE_FILTER_TERM_SPLIT_RE.split(str(expression or ""))
        normalized_parts = []
        for part in parts:
            if _SCOPE_FILTER_TERM_SPLIT_RE.fullmatch(part or ""):
                normalized_parts.append(part)
                continue

            match = _SCOPE_FILTER_FIELD_RE.match(part or "")
            if match is None:
                normalized_parts.append(part)
                continue

            requested_field = match.group("field").strip()
            resolved_field = alias_lookup.get(requested_field.casefold())
            if not resolved_field:
                normalized_parts.append(part)
                continue

            normalized_parts.append(
                f"{match.group('leading')}{resolved_field}{match.group('operator')}{part[match.end():]}"
            )
        return "".join(normalized_parts)

    @classmethod
    def _parse_scope_filter_expression(cls, expression, columns):
        aliases = cls._scope_filter_field_aliases(columns)
        alias_kw = cls._scope_filter_alias_kw()
        if alias_kw:
            return parse_filter_expression(expression, columns, **{alias_kw: aliases})
        normalized_expression = cls._normalize_scope_filter_aliases(expression, aliases)
        return parse_filter_expression(normalized_expression, columns)

    def _status_display_text(self, row):
        status_code = self._display_text(self._row_field_value(row, 'STATUS_CODE'))
        has_nok = self._row_field_value(row, 'HAS_NOK')
        nok_count = self._display_text(self._row_field_value(row, 'NOK_COUNT'))

        if status_code:
            status_text = status_code.upper()
        elif has_nok is not None and self._display_text(has_nok) != "":
            status_text = "NOK" if self._truthy_text(has_nok) else "OK"
        elif nok_count and nok_count not in {"0", "0.0"}:
            status_text = "NOK"
        else:
            status_text = ""

        if status_text and nok_count and nok_count not in {"0", "0.0"}:
            return f"{status_text} ({nok_count})"
        return status_text

    def _part_display_label(self, row):
        tokens = []
        sample_number = self._display_text(self._row_field_value(row, 'SAMPLE_NUMBER'))
        if sample_number:
            tokens.append(f"Sample: {sample_number}")

        date_value = self._display_text(self._row_field_value(row, 'DATE'))
        if date_value:
            tokens.append(f"Date: {date_value}")

        part_name = self._display_text(self._row_field_value(row, 'PART_NAME'))
        if part_name:
            tokens.append(f"Part: {part_name}")

        supplier_name = self._display_text(
            self._first_row_field_value(row, ('SUPPLIER', 'Supplier', 'supplier', 'SUPPLIER_NAME'))
        )
        if supplier_name:
            tokens.append(f"Supplier: {supplier_name}")

        revision = self._display_text(self._row_field_value(row, 'REVISION'))
        if revision:
            tokens.append(f"Rev: {revision}")

        template_variant = self._display_text(self._row_field_value(row, 'TEMPLATE_VARIANT'))
        if template_variant:
            tokens.append(f"Variant: {template_variant}")

        status_text = self._status_display_text(row)
        if status_text:
            tokens.append(f"Status: {status_text}")

        operator_name = self._display_text(self._row_field_value(row, 'OPERATOR_NAME'))
        if operator_name:
            tokens.append(f"Op: {operator_name}")

        filename = self._display_text(self._row_field_value(row, 'FILENAME'))
        if filename:
            tokens.append(f"File: {filename}")

        row_count = self._display_text(self._row_field_value(row, 'ROW_COUNT'))
        if row_count and row_count not in {"1", "1.0"}:
            tokens.append(f"Rows: {row_count}")

        return " | ".join(tokens)

    def _scope_filter_text(self):
        scope_filter_input = self._safe_attr(self, "scope_filter_input")
        if scope_filter_input is None or not hasattr(scope_filter_input, "text"):
            return ""
        return str(scope_filter_input.text() or "").strip()

    def _invalidate_grouping_cache(self, *, filtered=True, full=True):
        if filtered:
            self._cached_filtered_grouping_dataframe = None
            self._cached_grouping_row_index = None
        if full:
            self._cached_full_grouping_row_index = None

    def _apply_scope_filter(self):
        try:
            self._applied_scope_filter_text = self._scope_filter_text()
            self._invalidate_grouping_cache(filtered=True, full=False)
            self.populate_list_widgets()
        except Exception as e:
            self.log_and_exit(e)

    def _filtered_grouping_dataframe(self):
        cached = getattr(self, "_cached_filtered_grouping_dataframe", None)
        if isinstance(cached, pd.DataFrame):
            return cached
        df = self.df if isinstance(self.df, pd.DataFrame) else pd.DataFrame()
        expression = str(getattr(self, "_applied_scope_filter_text", "") or "").strip()
        summary_label = self._safe_attr(self, "scope_filter_summary_label")
        if not expression:
            if summary_label is not None and hasattr(summary_label, "setText"):
                summary_label.setText(f"Scope: all rows ({len(df.index)} rows)")
            self._cached_filtered_grouping_dataframe = df
            return df
        try:
            parsed = self._parse_scope_filter_expression(expression, df.columns)
            filtered = apply_filter_specs(df, parsed.specs, match_mode=parsed.match_mode)
        except (KeyError, TypeError, ValueError) as exc:
            if summary_label is not None and hasattr(summary_label, "setText"):
                summary_label.setText(f"Scope: invalid filter ({exc})")
            filtered = df.iloc[0:0].copy()
            self._cached_filtered_grouping_dataframe = filtered
            return filtered
        if summary_label is not None and hasattr(summary_label, "setText"):
            summary_label.setText(f"Scope: {len(filtered.index)} of {len(df.index)} rows")
        self._cached_filtered_grouping_dataframe = filtered
        return filtered

    def _current_grouping_row_index(self):
        cached = getattr(self, "_cached_grouping_row_index", None)
        if isinstance(cached, pd.DataFrame):
            return cached
        row_index = build_grouping_row_index(
            self._filtered_grouping_dataframe(),
            group_color_column=self.group_color_column,
        )
        self._cached_grouping_row_index = row_index
        return row_index

    def _current_full_grouping_row_index(self):
        cached = getattr(self, "_cached_full_grouping_row_index", None)
        if isinstance(cached, pd.DataFrame):
            return cached
        df = self.df if isinstance(self.df, pd.DataFrame) else pd.DataFrame()
        row_index = build_grouping_row_index(
            df,
            group_color_column=self.group_color_column,
        )
        self._cached_full_grouping_row_index = row_index
        return row_index

    def _cached_grouping_row_index_for_selection(self, *, filtered=True):
        cache_name = "_cached_grouping_row_index" if filtered else "_cached_full_grouping_row_index"
        cached = getattr(self, cache_name, None)
        if isinstance(cached, pd.DataFrame):
            return cached
        if isinstance(getattr(self, "df", None), pd.DataFrame):
            return self._current_grouping_row_index() if filtered else self._current_full_grouping_row_index()
        return None

    def _grouping_row_index(self, *, selected_reference=None, selected_group=None, row_index=None):
        if row_index is None:
            rows_df = self._current_grouping_row_index()
        else:
            rows_df = row_index.copy()
        if rows_df is None or rows_df.empty:
            return rows_df
        if selected_reference:
            rows_df = rows_df[rows_df['REFERENCE'].astype(str) == str(selected_reference)]
        if selected_group:
            rows_df = rows_df[rows_df['GROUP'].astype(str) == str(selected_group)]
        return rows_df

    def _add_list_limit_marker(self, list_widget, total_rows):
        remaining = int(total_rows) - _GROUPING_LIST_PREVIEW_LIMIT
        if remaining <= 0:
            return
        item = QListWidgetItem(f"... {remaining} more matching row(s). Narrow the filter/search.")
        item.setData(Qt.ItemDataRole.UserRole, None)
        list_widget.addItem(item)

    def _populate_part_list(self, selected_reference=None, *, row_index=None):
        rows_df = self._grouping_row_index(selected_reference=selected_reference, row_index=row_index)

        self._apply_list_theme_styles()

        self.part_list.clear()
        total_rows = int(len(rows_df.index)) if isinstance(rows_df, pd.DataFrame) else 0
        rows_df = rows_df.head(_GROUPING_LIST_PREVIEW_LIMIT)
        for row in rows_df.itertuples(index=False):
            item = QListWidgetItem(self._part_display_label(row))
            item.setData(Qt.ItemDataRole.UserRole, row.GROUP_KEY)
            self._apply_item_color(item, self._group_color_for_row(row))
            self.part_list.addItem(item)
        self._add_list_limit_marker(self.part_list, total_rows)

    def _populate_part_group_list(self, selected_group=None, *, row_index=None):
        rows_df = self._grouping_row_index(selected_group=selected_group, row_index=row_index)

        self._apply_list_theme_styles()

        self.part_group_list.clear()
        total_rows = int(len(rows_df.index)) if isinstance(rows_df, pd.DataFrame) else 0
        rows_df = rows_df.head(_GROUPING_LIST_PREVIEW_LIMIT)
        for row in rows_df.itertuples(index=False):
            item = QListWidgetItem(self._part_display_label(row))
            item.setData(Qt.ItemDataRole.UserRole, row.GROUP_KEY)
            self._apply_item_color(item, self._group_color_for_row(row))
            self.part_group_list.addItem(item)
        self._add_list_limit_marker(self.part_group_list, total_rows)

    @staticmethod
    def _group_display_label(group_name, sample_size, *, display_index=None, default_group=None):
        group_name = str(group_name)
        if default_group is not None and group_name == str(default_group):
            return f"{group_name} (n={sample_size})"
        if display_index is not None:
            return f"{group_name} [{int(display_index)}] (n={sample_size})"
        return f"{group_name} (n={sample_size})"

    @staticmethod
    def _reference_display_label(reference_name, sample_size):
        return f"{reference_name} (n={sample_size})"

    def _selected_group_name(self):
        groups_list = self._safe_attr(self, "groups_list")
        if groups_list is None or not hasattr(groups_list, "currentItem"):
            return None

        selected = groups_list.currentItem()
        if selected is None:
            return None

        item_data_role = getattr(Qt, "ItemDataRole", None)
        user_role = getattr(item_data_role, "UserRole", None)
        canonical_name = selected.data(user_role) if user_role is not None and hasattr(selected, "data") else None
        if canonical_name:
            return str(canonical_name)

        display_name = selected.text()
        return self._group_display_to_name.get(display_name, display_name)

    def _selected_reference_name(self):
        reference_list = self._safe_attr(self, 'reference_list')
        if reference_list is None or not hasattr(reference_list, 'currentItem'):
            return None

        selected = reference_list.currentItem()
        if selected is None:
            return None

        item_data_role = getattr(Qt, "ItemDataRole", None)
        user_role = getattr(item_data_role, "UserRole", None)
        canonical_name = selected.data(user_role) if user_role is not None and hasattr(selected, "data") else None
        if canonical_name:
            return str(canonical_name)

        display_name = selected.text()
        reference_display_to_name = getattr(self, "_reference_display_to_name", {})
        return reference_display_to_name.get(display_name, display_name)

    def _reassign_group_keys_to_default(self, selected_part_keys, preferred_group_name=None, preferred_reference_name=None):
        did_reassign = reassign_group_keys_to_default(
            self.df,
            selected_part_keys=selected_part_keys,
            default_group=self.default_group,
            group_color_column=self.group_color_column,
            default_group_color=self.default_group_color,
        )
        if did_reassign:
            self._invalidate_grouping_cache()

        try:
            self.populate_list_widgets(
                preferred_group_name=preferred_group_name,
                preferred_reference_name=preferred_reference_name,
            )
        except TypeError:
            # Compatibility for tests/stubs that override populate_list_widgets
            # with the historical single-parameter signature.
            self.populate_list_widgets(preferred_group_name=preferred_group_name)
        self.remove_from_group_button.setDisabled(True)
        return did_reassign

    def populate_list_widgets(self, preferred_group_name=None, preferred_reference_name=None):
        """Handle `populate_list_widgets` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self._apply_list_theme_styles()
            self._ensure_group_color_integrity()
            row_index = self._grouping_row_index()
            group_row_index = self._current_full_grouping_row_index()
            unique_groups = group_row_index["GROUP"].unique()
            self._group_display_to_name = {}
            self._reference_display_to_name = {}

            # Populate reference_list
            self.reference_list.clear()
            reference_counts = (
                row_index.groupby("REFERENCE", sort=False, dropna=False)["GROUP_KEY"]
                .nunique()
                .reset_index(name="sample_size")
            )
            unique_references = list(map(str, reference_counts["REFERENCE"].tolist()))
            for record in reference_counts.head(_GROUPING_LIST_PREVIEW_LIMIT).itertuples(index=False):
                reference_name = str(record.REFERENCE)
                display_label = self._reference_display_label(reference_name, int(record.sample_size))
                item = QListWidgetItem(display_label)
                item.setData(Qt.ItemDataRole.UserRole, reference_name)
                self._reference_display_to_name[display_label] = reference_name
                self.reference_list.addItem(item)
            self._add_list_limit_marker(self.reference_list, len(reference_counts.index))

            # Select the first item in the reference_list by default
            if self.reference_list.count() > 0:
                preferred_reference_index = 0
                if preferred_reference_name in unique_references:
                    preferred_reference_index = unique_references.index(preferred_reference_name)
                if preferred_reference_index >= self.reference_list.count():
                    preferred_reference_index = 0
                self.reference_list.setCurrentRow(preferred_reference_index)

            # Use clear and addItems for the rest of the lists
            selected_reference = self._selected_reference_name()
            try:
                self._populate_part_list(selected_reference, row_index=row_index)
            except TypeError:
                self._populate_part_list(selected_reference)

            self.all_parts_list.clear()
            if 'SAMPLE_NUMBER' in row_index.columns:
                sample_counts = row_index.groupby("SAMPLE_NUMBER", sort=False, dropna=False)["GROUP_KEY"].nunique()
                self.all_parts_list.addItems(
                    f"{sample_number} (n={int(sample_size)})"
                    for sample_number, sample_size in sample_counts.head(_GROUPING_LIST_PREVIEW_LIMIT).items()
                )
                self._add_list_limit_marker(self.all_parts_list, len(sample_counts.index))

            group_names = list(map(str, unique_groups))
            self.groups_list.clear()
            non_default_group_index = 0
            for group_name in group_names:
                sample_size = int(group_row_index[group_row_index['GROUP'] == group_name]['GROUP_KEY'].nunique())
                display_index = None
                if group_name != self.default_group:
                    non_default_group_index += 1
                    display_index = non_default_group_index
                display_label = self._group_display_label(
                    group_name,
                    sample_size,
                    display_index=display_index,
                    default_group=self.default_group,
                )
                item = QListWidgetItem(display_label)
                item.setData(Qt.ItemDataRole.UserRole, group_name)
                self._group_display_to_name[display_label] = group_name
                group_color = self.default_group_color
                if group_name != self.default_group:
                    group_rows = group_row_index[group_row_index['GROUP'] == group_name]
                    if not group_rows.empty:
                        group_color = str(group_rows[self.group_color_column].iloc[-1])
                self._apply_item_color(item, group_color)
                self.groups_list.addItem(item)

            # Select the first item in the groups_list by default
            if self.groups_list.count() > 0:
                preferred_group_index = 0
                if preferred_group_name in group_names:
                    preferred_group_index = group_names.index(preferred_group_name)
                self.groups_list.setCurrentRow(preferred_group_index)
            selected_group = self._selected_group_name()
            try:
                self._populate_part_group_list(selected_group, row_index=group_row_index)
            except TypeError:
                self._populate_part_group_list(selected_group)
            self._refresh_selection_summary()
        except Exception as e:
            self.log_and_exit(e)

    def search_list_widgets(self, list_widget, search_text):
        """Handle `search_list_widgets` for `DataGrouping`.

        Args:
            list_widget (object): Method input value.
            search_text (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self._list_selection_utils.preserve_selection_during_filter(
                list_widget,
                search_text,
                canonical_text_getter=lambda item: item.data(Qt.ItemDataRole.UserRole),
            )
        except Exception as e:
            self.log_and_exit(e)

    def on_reference_selection_changed(self):
        """Handle `on_reference_selection_changed` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            selected_reference = self._selected_reference_name()
            row_index = self._cached_grouping_row_index_for_selection(filtered=True)
            try:
                if row_index is None:
                    self._populate_part_list(selected_reference)
                else:
                    self._populate_part_list(selected_reference, row_index=row_index)
            except TypeError:
                self._populate_part_list(selected_reference)
            self.create_group_button.setEnabled(self._has_groupable_selection())
            self._refresh_selection_summary()
        except Exception as e:
            self.log_and_exit(e)

    def on_part_selection_changed(self):
        """Handle `on_part_selection_changed` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.create_group_button.setEnabled(self._has_groupable_selection())
            self._refresh_selection_summary()
        except Exception as e:
            self.log_and_exit(e)

    def on_part_item_double_clicked(self, item):
        """Open create-group flow when a part row is double-clicked."""

        try:
            if item is None:
                return
            self.create_group()
        except Exception as e:
            self.log_and_exit(e)

    def on_reference_item_double_clicked(self, item):
        """Keep reference double-clicks navigation-only."""

        try:
            return
        except Exception as e:
            self.log_and_exit(e)

    def on_group_selection_changed(self):
        """Handle `on_group_selection_changed` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            selected_group_name = self._selected_group_name()
            row_index = self._cached_grouping_row_index_for_selection(filtered=False)
            try:
                if row_index is None:
                    self._populate_part_group_list(selected_group_name)
                else:
                    self._populate_part_group_list(selected_group_name, row_index=row_index)
            except TypeError:
                self._populate_part_group_list(selected_group_name)

            selected_group = self.groups_list.currentItem() is not None
            is_default_group = selected_group_name == self.default_group
            self.rename_group_button.setEnabled(selected_group)
            self.delete_group_button.setEnabled(selected_group and not is_default_group)

            selected_part_group = self.part_group_list.currentItem() is not None
            self.remove_from_group_button.setEnabled(selected_group and not is_default_group and selected_part_group)
            self._refresh_selection_summary()
        except Exception as e:
            self.log_and_exit(e)

    def on_group_item_double_clicked(self, item):
        """Open rename flow when a group is double-clicked."""

        try:
            if item is None:
                return
            self.rename_group()
        except Exception as e:
            self.log_and_exit(e)

    def on_part_group_selection_changed(self):
        """Handle `on_part_group_selection_changed` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            selected_part_group = self.part_group_list.currentItem() is not None
            selected_group_name = self._selected_group_name()
            self.remove_from_group_button.setEnabled(selected_part_group and selected_group_name != self.default_group)
            self.create_group_button.setEnabled(self._has_groupable_selection())
            self._refresh_selection_summary()
        except Exception as e:
            self.log_and_exit(e)

    def _selected_part_keys_from_list(self, list_widget):
        if list_widget is None or not hasattr(list_widget, "selectedItems"):
            return []
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in list_widget.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        ]

    def _selected_groupable_part_keys(self):
        part_keys = self._selected_part_keys_from_list(self._safe_attr(self, "part_list"))
        group_part_keys = self._selected_part_keys_from_list(self._safe_attr(self, "part_group_list"))
        if self._list_or_viewport_has_focus(self._safe_attr(self, "part_group_list")) and group_part_keys:
            return group_part_keys
        if part_keys:
            return part_keys
        return group_part_keys

    def _has_groupable_selection(self):
        return bool(self._selected_groupable_part_keys())

    def create_group(self, initial_group_name=""):
        """Handle `create_group` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            selected_reference = self._selected_reference_name()
            target_group_keys = self._selected_groupable_part_keys()
            if not target_group_keys:
                return

            default_name = (initial_group_name or "").strip()
            if not default_name:
                selected_group = (self._selected_group_name() or "").strip()
                if selected_group and selected_group != self.default_group:
                    default_name = selected_group
            new_group_name, ok_pressed = QInputDialog.getText(
                self,
                "New group",
                "Enter group name:",
                text=default_name,
            )
            new_group_name = (new_group_name or "").strip()

            if ok_pressed and target_group_keys and new_group_name:
                group_exists = bool((self.df['GROUP'] == new_group_name).any())
                assigned_color = self._next_group_color() if not group_exists else self.df.loc[self.df['GROUP'] == new_group_name, self.group_color_column].iloc[-1]
                # Update the dataframe with the new group information
                self.df.loc[
                    self.df['GROUP_KEY'].isin(target_group_keys),
                    'GROUP'
                ] = new_group_name
                self.df.loc[
                    self.df['GROUP_KEY'].isin(target_group_keys),
                    self.group_color_column
                ] = assigned_color
                self._invalidate_grouping_cache()

            preferred_group_name = new_group_name if ok_pressed and target_group_keys and new_group_name else None
            try:
                self.populate_list_widgets(
                    preferred_group_name=preferred_group_name,
                    preferred_reference_name=selected_reference,
                )
            except TypeError:
                self.populate_list_widgets()
            self.remove_from_group_button.setDisabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def rename_group(self):
        """Handle `rename_group` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            selected_group = self._selected_group_name()
            new_group_name, ok_pressed = QInputDialog.getText(self, "Rename group", f"Enter new name for '{selected_group}':")

            if ok_pressed and selected_group and new_group_name:
                existing_color = self.df.loc[self.df['GROUP'] == selected_group, self.group_color_column].iloc[-1]
                # Update the dataframe with the new group name
                self.df.loc[self.df['GROUP'] == selected_group, 'GROUP'] = new_group_name
                self.df.loc[self.df['GROUP'] == new_group_name, self.group_color_column] = existing_color
                if selected_group == self.default_group:
                    self.default_group = str(new_group_name)
                    default_color = getattr(self, 'default_group_color', existing_color)
                    self.df.loc[self.df['GROUP'] == self.default_group, self.group_color_column] = default_color
                self._invalidate_grouping_cache()

            self.populate_list_widgets()
            self.remove_from_group_button.setDisabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def remove_from_group(self):
        """Handle `remove_from_group` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self._delete_selected_parts_from_group()
        except Exception as e:
            self.log_and_exit(e)

    def _delete_selected_parts_from_group(self):
        selected_part_keys = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.part_group_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        ]
        selected_group = self._selected_group_name()
        selected_reference = self._selected_reference_name()

        if selected_group is None or not selected_part_keys:
            return False

        return self._reassign_group_keys_to_default(
            selected_part_keys,
            preferred_group_name=selected_group,
            preferred_reference_name=selected_reference,
        )

    def _delete_selected_parts_from_part_list(self):
        selected_part_keys = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.part_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        ]
        return self._reassign_group_keys_to_default(
            selected_part_keys,
            preferred_group_name=self._selected_group_name(),
            preferred_reference_name=self._selected_reference_name(),
        )

    @staticmethod
    def _list_or_viewport_has_focus(list_widget):
        if list_widget is None:
            return False
        if hasattr(list_widget, "hasFocus") and list_widget.hasFocus():
            return True
        if hasattr(list_widget, "viewport") and list_widget.viewport() is not None:
            return bool(list_widget.viewport().hasFocus())
        return False

    def _create_group_from_selected_reference(self):
        return None

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for list-driven grouping workflows."""

        shortcut_handler = getattr(self, "_grouping_shortcuts", None)
        if shortcut_handler is None:
            shortcut_handler = GroupingShortcutBindings(
                source_list=getattr(self, "part_list", None),
                reference_list=getattr(self, "reference_list", None),
                groups_list=getattr(self, "groups_list", None),
                assigned_list=getattr(self, "part_group_list", None),
                create_group=getattr(self, "create_group", None),
                rename_group=getattr(self, "rename_group", None),
                delete_group=getattr(self, "delete_group", None),
                remove_from_source=getattr(self, "_delete_selected_parts_from_part_list", None),
                remove_from_assigned=getattr(self, "_delete_selected_parts_from_group", None),
                focused_line_edits=(
                    (
                        getattr(self, "reference_search_input", None),
                        lambda: self.search_list_widgets(
                            self.reference_list,
                            self.reference_search_input.text(),
                        ),
                    ),
                    (
                        getattr(self, "part_search_input", None),
                        lambda: self.search_list_widgets(
                            self.part_list,
                            self.part_search_input.text(),
                        ),
                    ),
                    (
                        getattr(self, "group_search_input", None),
                        lambda: self.search_list_widgets(
                            self.groups_list,
                            self.group_search_input.text(),
                        ),
                    ),
                    (
                        getattr(self, "part_group_search_input", None),
                        lambda: self.search_list_widgets(
                            self.part_group_list,
                            self.part_group_search_input.text(),
                        ),
                    ),
                    (getattr(self, "scope_filter_input", None), getattr(self, "_apply_scope_filter", None)),
                ),
                error_handler=getattr(self, "log_and_exit", None),
                qt_namespace=Qt,
            )
        if shortcut_handler.handle_key_press(event):
            return

        super().keyPressEvent(event)

    def delete_group(self):
        """Handle `delete_group` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            # Get the selected group
            selected_group = self._selected_group_name()
            if selected_group == self.default_group:
                return

            # Create a QMessageBox with the Question icon
            confirmation = QMessageBox(QMessageBox.Icon.Question, 'Confirm Deletion', f"Are you sure you want to delete group '{selected_group}'?")

            # Add buttons to the QMessageBox
            confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

            # Execute the QMessageBox and check the result
            result = confirmation.exec()

            if result == QMessageBox.StandardButton.Yes and selected_group is not None:
                # Update the dataframe with the default group value for the selected group
                self.df.loc[self.df['GROUP'] == selected_group, 'GROUP'] = self.default_group
                self.df.loc[self.df['GROUP'] == self.default_group, self.group_color_column] = self.default_group_color
                self._invalidate_grouping_cache()

            # Repopulate the list widgets after updating the dataframe
            self.populate_list_widgets()
            self.remove_from_group_button.setDisabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def use_grouping(self):
        """Handle `use_grouping` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.hide()
            set_default_group_label(self.df, self.default_group)
            self.parent().set_df_for_grouping(self.df)
            self.parent().set_grouping_applied(True)
        except Exception as e:
            self.log_and_exit(e)

    def dont_use_grouping(self):
        """Handle `dont_use_grouping` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.hide()
            self.parent().set_df_for_grouping(None)
            self.parent().set_grouping_applied(False)
        except Exception as e:
            self.log_and_exit(e)

    def log_and_exit(self, exception, *, reraise=False):
        """Handle `log_and_exit` for `DataGrouping`.

        Args:
            exception (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        caller = inspect.stack()[1].function
        if hasattr(custom_logger, "handle_exception") and hasattr(custom_logger, "LOG_ONLY"):
            custom_logger.handle_exception(
                exception,
                behavior=custom_logger.LOG_ONLY,
                logger_name=__name__,
                context=f"DataGrouping.{caller}",
                reraise=reraise,
            )
            return
        if reraise:
            raise exception
