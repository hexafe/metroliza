"""Provide the data-grouping dialog used to curate export grouping presets.

This UI reads report data from SQLite and coordinates with the main window to
store, apply, and clear reference/part grouping assignments.
"""

import inspect
import sqlite3

import modules.custom_logger as custom_logger
from modules.db import read_sql_dataframe
from modules.data_grouping_service import (
    build_grouping_query as _build_grouping_query,
    compute_group_key_for_df as _compute_group_key_for_df,
    load_grouping_dataframe,
    reassign_group_keys_to_default,
)
from modules.list_selection_utils import ListSelectionUtils
from modules import ui_theme_tokens
from modules.help_menu import attach_help_menu_to_layout
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
        self._list_selection_utils = ListSelectionUtils()

        self.setup_ui()
        
        self.read_data_to_df()
        self.add_default_group()
        self._restore_saved_grouping_state()
        self.populate_list_widgets()

    @staticmethod
    def _multi_selection_mode():
        selection_mode_enum = getattr(getattr(QtWidgets, "QAbstractItemView", None), "SelectionMode", None)
        return getattr(selection_mode_enum, "MultiSelection", 2)

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
            self.reference_label = QLabel("REFERENCE:")
            self.reference_list = QListWidget()

            self.part_label = QLabel("PART #:")
            self.part_list = QListWidget()
            self.part_list.setSelectionMode(self._multi_selection_mode())
            self.all_parts_list = QListWidget()
            self.all_parts_list.setSelectionMode(self._multi_selection_mode())
            
            self.groups_label = QLabel("GROUPS:")
            self.groups_list = QListWidget()
            
            self.part_group_label = QLabel("PART IN SELECTED GROUP:")
            self.part_group_list = QListWidget()
            self.part_group_list.setSelectionMode(self._multi_selection_mode())

            # Create separate QLineEdit widgets for searching in each list widget
            self.reference_search_input = QLineEdit()
            self.reference_search_input.setPlaceholderText("Search REFERENCE...")
            self.part_search_input = QLineEdit()
            self.part_search_input.setPlaceholderText("Search PART #...")
            self.group_search_input = QLineEdit()
            self.group_search_input.setPlaceholderText("Search GROUP...")
            self.part_group_search_input = QLineEdit()
            self.part_group_search_input.setPlaceholderText("Search PART IN SELECTED GROUP...")
            
            # Create buttons
            self.create_group_button = QPushButton("Create/add to group")
            self.create_group_button.setDisabled(True)
            self.rename_group_button = QPushButton("Rename selected group")
            self.rename_group_button.setDisabled(True)
            self.remove_from_group_button = QPushButton("Remove from selected group")
            self.remove_from_group_button.setDisabled(True)
            self.delete_group_button = QPushButton("Delete selected group")
            self.delete_group_button.setDisabled(True)
            
            self.use_grouping_button = QPushButton("Use grouping")
            self.dont_use_grouping_button = QPushButton("Do not use grouping")
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

            self.layout.addWidget(self.reference_label, 0, 0)
            self.layout.addWidget(self.reference_search_input, 1, 0)
            self.layout.addWidget(self.reference_list, 2, 0)

            self.layout.addWidget(self.part_label, 0, 1)
            self.layout.addWidget(self.part_search_input, 1, 1)
            self.layout.addWidget(self.part_list, 2, 1)

            self.layout.addWidget(self.groups_label, 0, 2)
            self.layout.addWidget(self.group_search_input, 1, 2)
            self.layout.addWidget(self.groups_list, 2, 2)
            
            self.layout.addWidget(self.part_group_label, 0, 3)
            self.layout.addWidget(self.part_group_search_input, 1, 3)
            self.layout.addWidget(self.part_group_list, 2, 3)

            for row in range(self.layout.rowCount()):
                for column in range(self.layout.columnCount()):
                    item = self.layout.itemAtPosition(row, column)
                    if item is not None:
                        widget = item.widget()
                        if widget is not None:
                            widget.setFixedWidth(200)

            self.layout.addWidget(self.create_group_button, 4, 0, 1, 4)
            self.layout.addWidget(self.rename_group_button, 5, 0, 1, 4)
            self.layout.addWidget(self.remove_from_group_button, 6, 0, 1, 4)
            self.layout.addWidget(self.delete_group_button, 7, 0, 1, 4)

            self.layout.addWidget(self.use_grouping_button, 8, 0, 1, 2)
            self.layout.addWidget(self.dont_use_grouping_button, 8, 2, 1, 2)

            self.show()
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
            self.reference_search_input.textChanged.connect(lambda: self.search_list_widgets(self.reference_list, self.reference_search_input.text()))
            self.part_search_input.textChanged.connect(lambda: self.search_list_widgets(self.part_list, self.part_search_input.text()))
            self.group_search_input.textChanged.connect(lambda: self.search_list_widgets(self.groups_list, self.group_search_input.text()))
            self.part_group_search_input.textChanged.connect(lambda: self.search_list_widgets(self.part_group_list, self.part_group_search_input.text()))
            
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

            self.create_group_button.clicked.connect(self.create_group)
            self.rename_group_button.clicked.connect(self.rename_group)
            self.remove_from_group_button.clicked.connect(self.remove_from_group)
            self.delete_group_button.clicked.connect(self.delete_group)
            
            self.use_grouping_button.clicked.connect(self.use_grouping)
            self.dont_use_grouping_button.clicked.connect(self.dont_use_grouping)
        except Exception as e:
            self.log_and_exit(e)
            
    def _connect_shift_range_for_list(self, list_widget):
        self._list_selection_utils.connect_shift_range_behavior(list_widget)

    def _handle_list_item_pressed(self, list_widget, item):
        self._list_selection_utils.handle_shift_range_press(list_widget, item)

    def read_data_to_df(self):
        """Handle `read_data_to_df` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            filter_query = self.parent().get_filter_query() if self.parent() else None
            self.df = load_grouping_dataframe(read_sql_dataframe, self.db_file, filter_query)
        except (sqlite3.Error, ValueError, TypeError) as e:
            self.log_and_exit(e)
        except Exception as e:
            self.log_and_exit(e, reraise=True)

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

    def _status_display_text(self, row):
        def _field_value(field_name):
            if hasattr(row, field_name):
                return getattr(row, field_name)
            try:
                return row[field_name]
            except (AttributeError, KeyError, TypeError):
                return None

        status_code = self._display_text(_field_value('STATUS_CODE'))
        has_nok = _field_value('HAS_NOK')
        nok_count = self._display_text(_field_value('NOK_COUNT'))

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
        def _field_value(field_name):
            if hasattr(row, field_name):
                return getattr(row, field_name)
            try:
                return row[field_name]
            except (AttributeError, KeyError, TypeError):
                return None

        tokens = []
        sample_number = self._display_text(_field_value('SAMPLE_NUMBER'))
        if sample_number:
            tokens.append(sample_number)

        date_value = self._display_text(_field_value('DATE'))
        if date_value:
            tokens.append(date_value)

        part_name = self._display_text(_field_value('PART_NAME'))
        if part_name:
            tokens.append(f"Part: {part_name}")

        revision = self._display_text(_field_value('REVISION'))
        if revision:
            tokens.append(f"Rev: {revision}")

        template_variant = self._display_text(_field_value('TEMPLATE_VARIANT'))
        if template_variant:
            tokens.append(f"Variant: {template_variant}")

        status_text = self._status_display_text(row)
        if status_text:
            tokens.append(f"Status: {status_text}")

        operator_name = self._display_text(_field_value('OPERATOR_NAME'))
        if operator_name:
            tokens.append(f"Op: {operator_name}")

        filename = self._display_text(_field_value('FILENAME'))
        if filename:
            tokens.append(f"File: {filename}")

        return " | ".join(tokens)

    def _populate_part_list(self, selected_reference=None):
        rows_df = self.df if not selected_reference else self.df[self.df['REFERENCE'] == selected_reference]
        rows_df = rows_df.drop_duplicates(subset=['GROUP_KEY'])

        self._apply_list_theme_styles()

        self.part_list.clear()
        for row in rows_df.itertuples(index=False):
            item = QListWidgetItem(self._part_display_label(row))
            item.setData(Qt.ItemDataRole.UserRole, row.GROUP_KEY)
            self._apply_item_color(item, self._group_color_for_row(row))
            self.part_list.addItem(item)

    def _populate_part_group_list(self, selected_group=None):
        rows_df = self.df if not selected_group else self.df[self.df['GROUP'] == selected_group]
        rows_df = rows_df.drop_duplicates(subset=['GROUP_KEY'])

        self._apply_list_theme_styles()

        self.part_group_list.clear()
        for row in rows_df.itertuples(index=False):
            item = QListWidgetItem(self._part_display_label(row))
            item.setData(Qt.ItemDataRole.UserRole, row.GROUP_KEY)
            self._apply_item_color(item, self._group_color_for_row(row))
            self.part_group_list.addItem(item)

    @staticmethod
    def _group_display_label(group_name, sample_size):
        return f"{group_name} (n={sample_size})"

    def _selected_group_name(self):
        selected = self.groups_list.currentItem()
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
        reference_list = getattr(self, 'reference_list', None)
        if reference_list is None or not hasattr(reference_list, 'currentItem'):
            return None

        selected = reference_list.currentItem()
        if selected is None:
            return None
        return selected.text()

    def _reassign_group_keys_to_default(self, selected_part_keys, preferred_group_name=None, preferred_reference_name=None):
        did_reassign = reassign_group_keys_to_default(
            self.df,
            selected_part_keys=selected_part_keys,
            default_group=self.default_group,
            group_color_column=self.group_color_column,
            default_group_color=self.default_group_color,
        )

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
            unique_references = list(map(str, self.df["REFERENCE"].unique()))
            self._ensure_group_color_integrity()
            unique_groups = self.df["GROUP"].unique()
            self._group_display_to_name = {}

            # Populate reference_list
            self.reference_list.clear()
            self.reference_list.addItems(unique_references)
            
            # Select the first item in the reference_list by default
            if self.reference_list.count() > 0:
                preferred_reference_index = 0
                if preferred_reference_name in unique_references:
                    preferred_reference_index = unique_references.index(preferred_reference_name)
                self.reference_list.setCurrentRow(preferred_reference_index)

            # Use clear and addItems for the rest of the lists
            selected_reference = self.reference_list.currentItem().text() if self.reference_list.currentItem() else None
            self._populate_part_list(selected_reference)

            self.all_parts_list.clear()
            self.all_parts_list.addItems(map(str, self.df['SAMPLE_NUMBER'].astype(str).unique()))

            group_names = list(map(str, unique_groups))
            self.groups_list.clear()
            for group_name in group_names:
                sample_size = int(self.df[self.df['GROUP'] == group_name]['GROUP_KEY'].nunique())
                display_label = self._group_display_label(group_name, sample_size)
                item = QListWidgetItem(display_label)
                item.setData(Qt.ItemDataRole.UserRole, group_name)
                self._group_display_to_name[display_label] = group_name
                group_color = self.default_group_color
                if group_name != self.default_group:
                    group_rows = self.df[self.df['GROUP'] == group_name]
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
            self._populate_part_group_list(selected_group)
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
            selected_reference = self.reference_list.currentItem().text() if self.reference_list.currentItem() else None
            self._populate_part_list(selected_reference)
            has_part_selection = bool(self.part_list.selectedItems()) if hasattr(self.part_list, 'selectedItems') else False
            self.create_group_button.setEnabled(bool(selected_reference) or has_part_selection)
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
            selected_part = bool(self.part_list.selectedItems()) if hasattr(self.part_list, 'selectedItems') else (self.part_list.currentItem() is not None)
            selected_reference = self._selected_reference_name()
            self.create_group_button.setEnabled(selected_part or bool(selected_reference))
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
        """Open create-group flow prefilled with the double-clicked reference."""

        try:
            if item is None:
                return
            self.create_group(initial_group_name=item.text())
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
            self._populate_part_group_list(selected_group_name)

            selected_group = self.groups_list.currentItem() is not None
            is_default_group = selected_group_name == self.default_group
            self.rename_group_button.setEnabled(selected_group)
            self.delete_group_button.setEnabled(selected_group and not is_default_group)

            selected_part_group = self.part_group_list.currentItem() is not None
            self.remove_from_group_button.setEnabled(selected_group and not is_default_group and selected_part_group)
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
        except Exception as e:
            self.log_and_exit(e)
            
    def create_group(self, initial_group_name=""):
        """Handle `create_group` for `DataGrouping`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            # Get the selected items from the list widgets
            selected_part_keys = [item.data(Qt.ItemDataRole.UserRole) for item in self.part_list.selectedItems()]
            if selected_part_keys:
                target_group_keys = selected_part_keys
            else:
                selected_reference = self._selected_reference_name()
                target_group_keys = []
                if selected_reference:
                    target_group_keys = self.df.loc[
                        self.df['REFERENCE'] == selected_reference,
                        'GROUP_KEY',
                    ].dropna().unique().tolist()

            default_name = (initial_group_name or "").strip()
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
        selected_part_keys = [item.data(Qt.ItemDataRole.UserRole) for item in self.part_group_list.selectedItems()]
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
        selected_part_keys = [item.data(Qt.ItemDataRole.UserRole) for item in self.part_list.selectedItems()]
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

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for list-driven grouping workflows."""

        try:
            pressed_key = event.key() if event is not None and hasattr(event, "key") else None
            key_enum = getattr(Qt, "Key", None)
            delete_keys = tuple(
                key
                for key in (
                    getattr(key_enum, "Key_Delete", None),
                    getattr(key_enum, "Key_Backspace", None),
                )
                if key is not None
            )
            enter_keys = tuple(
                key
                for key in (
                    getattr(key_enum, "Key_Return", None),
                    getattr(key_enum, "Key_Enter", None),
                )
                if key is not None
            )

            if pressed_key in enter_keys and self._list_or_viewport_has_focus(self.reference_list):
                selected_reference = self._selected_reference_name()
                if selected_reference:
                    self.create_group(initial_group_name=selected_reference)
                    event.accept()
                    return

            if pressed_key in delete_keys:
                if self._list_or_viewport_has_focus(self.part_list):
                    self._delete_selected_parts_from_part_list()
                    event.accept()
                    return

                if self._list_or_viewport_has_focus(self.part_group_list):
                    self._delete_selected_parts_from_group()
                    event.accept()
                    return

                if self._list_or_viewport_has_focus(self.groups_list):
                    self.delete_group()
                    event.accept()
                    return
        except Exception as e:
            self.log_and_exit(e)

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
