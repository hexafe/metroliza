from modules.custom_logger import CustomLogger
from modules.db import execute_with_retry
from modules.list_selection_utils import ListSelectionUtils
from modules import ui_theme_tokens
from modules.help_menu import attach_help_menu_to_layout
from modules.report_query_service import (
    build_distinct_value_query as _build_distinct_value_query,
    build_measurement_filter_query as _build_measurement_filter_query,
)
from PyQt6.QtCore import QDate, Qt
import PyQt6.QtWidgets as QtWidgets
from PyQt6.QtWidgets import(
    QDateEdit,
    QDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)


def build_measurement_filter_query(**kwargs):
    return _build_measurement_filter_query(**kwargs)


def build_distinct_value_query(column_name, *, source_view="vw_measurement_export", filter_query=None):
    return _build_distinct_value_query(column_name, source_view=source_view, filter_query=filter_query)


def ensure_report_schema(database):
    from modules.report_schema import ensure_report_schema as _ensure_report_schema

    return _ensure_report_schema(database)


def _normalize_filter_values(values):
    normalized_values = []
    for value in values or ():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            normalized_values.append(text)
    return normalized_values


def _build_in_clause(column_name, values):
    normalized_values = _normalize_filter_values(values)
    if not normalized_values:
        return None

    escaped_values = []
    for value in normalized_values:
        escaped_values.append("'" + value.replace("'", "''") + "'")
    return f"{column_name} IN ({', '.join(escaped_values)})"


class FilterDialog(QDialog):
    FILTER_SECTIONS = (
        (
            "Measurement",
            (
                ("ax_label", "ax_search_input", "ax_list"),
                ("reference_label", "reference_search_input", "reference_list"),
                ("header_label", "header_search_input", "header_list"),
                ("selected_headers_label", None, "selected_headers_list"),
                ("status_code_label", "status_code_search_input", "status_code_list"),
            ),
        ),
        (
            "Report metadata",
            (
                ("part_name_label", "part_name_search_input", "part_name_list"),
                ("revision_label", "revision_search_input", "revision_list"),
                ("template_variant_label", "template_variant_search_input", "template_variant_list"),
                ("sample_number_label", "sample_number_search_input", "sample_number_list"),
                ("operator_name_label", "operator_name_search_input", "operator_name_list"),
                ("sample_number_kind_label", "sample_number_kind_search_input", "sample_number_kind_list"),
            ),
        ),
        (
            "Source",
            (
                ("filename_label", "filename_search_input", "filename_list"),
                ("parser_id_label", "parser_id_search_input", "parser_id_list"),
                ("template_family_label", "template_family_search_input", "template_family_list"),
            ),
        ),
    )

    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        
        self.setWindowTitle("Data filtering")
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())
        self.setModal(True)
        
        self.db_file = db_file
        if self.parent() is not None and hasattr(self.parent(), "get_filter_query"):
            self.filter_query = self.parent().get_filter_query()
        else:
            self.filter_query = ""

        self._list_selection_utils = ListSelectionUtils()

        try:
            self._ensure_schema_ready()
        except Exception as e:
            self.log_and_exit(e)

        self.setup_ui()

    @staticmethod
    def _multi_selection_mode():
        selection_mode_enum = getattr(getattr(QtWidgets, "QAbstractItemView", None), "SelectionMode", None)
        return getattr(selection_mode_enum, "MultiSelection", 2)

    @classmethod
    def _build_filter_sections(cls):
        return cls.FILTER_SECTIONS

    def _ensure_schema_ready(self):
        if str(self.db_file or "").strip():
            ensure_report_schema(self.db_file)

    def setup_ui(self):
        try:
            self.create_widgets()
            self.arrange_layout()
            self.populate_list_widgets()
            self._apply_list_theme_styles()
            self.connect_signals()
        except Exception as e:
            self.log_and_exit(e)

    def create_widgets(self):
        try:
            # Create labels and list widgets for each column to be filtered
            self.ax_label = QLabel("AX:")
            self.ax_list = QListWidget()
            self.ax_list.setSelectionMode(self._multi_selection_mode())

            self.reference_label = QLabel("REFERENCE:")
            self.reference_list = QListWidget()
            self.reference_list.setSelectionMode(self._multi_selection_mode())

            self.header_label = QLabel("HEADER:")
            self.header_list = QListWidget()
            self.header_list.setSelectionMode(self._multi_selection_mode())
            self.all_headers_list = QListWidget()
            self.all_headers_list.setSelectionMode(self._multi_selection_mode())

            self.part_name_label = QLabel("PART NAME:")
            self.part_name_list = QListWidget()
            self.part_name_list.setSelectionMode(self._multi_selection_mode())

            self.revision_label = QLabel("REVISION:")
            self.revision_list = QListWidget()
            self.revision_list.setSelectionMode(self._multi_selection_mode())

            self.template_variant_label = QLabel("TEMPLATE VARIANT:")
            self.template_variant_list = QListWidget()
            self.template_variant_list.setSelectionMode(self._multi_selection_mode())

            self.sample_number_label = QLabel("SAMPLE NUMBER:")
            self.sample_number_list = QListWidget()
            self.sample_number_list.setSelectionMode(self._multi_selection_mode())

            self.operator_name_label = QLabel("OPERATOR NAME:")
            self.operator_name_list = QListWidget()
            self.operator_name_list.setSelectionMode(self._multi_selection_mode())

            self.sample_number_kind_label = QLabel("SAMPLE NUMBER KIND:")
            self.sample_number_kind_list = QListWidget()
            self.sample_number_kind_list.setSelectionMode(self._multi_selection_mode())

            self.status_code_label = QLabel("STATUS CODE:")
            self.status_code_list = QListWidget()
            self.status_code_list.setSelectionMode(self._multi_selection_mode())

            self.filename_label = QLabel("FILENAME:")
            self.filename_list = QListWidget()
            self.filename_list.setSelectionMode(self._multi_selection_mode())

            self.parser_id_label = QLabel("PARSER ID:")
            self.parser_id_list = QListWidget()
            self.parser_id_list.setSelectionMode(self._multi_selection_mode())

            self.template_family_label = QLabel("TEMPLATE FAMILY:")
            self.template_family_list = QListWidget()
            self.template_family_list.setSelectionMode(self._multi_selection_mode())
            
            self.selected_headers_label = QLabel("SELECTED HEADERS:")
            self.selected_headers_list = QListWidget()
            self.selected_headers_list.setSelectionMode(self._multi_selection_mode())

            self.has_nok_button = QPushButton("HAS NOK ONLY")
            if hasattr(self.has_nok_button, "setCheckable"):
                self.has_nok_button.setCheckable(True)
            if hasattr(self.has_nok_button, "setChecked"):
                self.has_nok_button.setChecked(False)

            self.date_from_label = QLabel("MEASUREMENT DATE FROM:")
            self.date_from_calendar = QDateEdit(calendarPopup=True)
            self.date_from_calendar.setCalendarPopup(True)
            self.date_from_calendar.setDate(QDate(1970, 1, 1))
            self.date_from_calendar.setMinimumWidth(100)

            self.date_to_label = QLabel("MEASUREMENT DATE TO:")
            self.date_to_calendar = QDateEdit(calendarPopup=True)
            self.date_to_calendar.setCalendarPopup(True)
            self.date_to_calendar.setDate(QDate.currentDate())
            self.date_to_calendar.setMinimumWidth(100)

            # Set the default selection for list widgets as "SELECT ALL"
            self.ax_list.addItem("SELECT ALL")
            self.reference_list.addItem("SELECT ALL")
            self.header_list.addItem("SELECT ALL")
            self.all_headers_list.addItem("SELECT ALL")
            self.part_name_list.addItem("SELECT ALL")
            self.revision_list.addItem("SELECT ALL")
            self.template_variant_list.addItem("SELECT ALL")
            self.sample_number_list.addItem("SELECT ALL")
            self.operator_name_list.addItem("SELECT ALL")
            self.sample_number_kind_list.addItem("SELECT ALL")
            self.status_code_list.addItem("SELECT ALL")
            self.filename_list.addItem("SELECT ALL")
            self.parser_id_list.addItem("SELECT ALL")
            self.template_family_list.addItem("SELECT ALL")

            # Create separate QLineEdit widgets for searching in each list widget
            self.ax_search_input = QLineEdit()
            self.ax_search_input.setPlaceholderText("Search AX...")
            self.reference_search_input = QLineEdit()
            self.reference_search_input.setPlaceholderText("Search REFERENCE...")
            self.header_search_input = QLineEdit()
            self.header_search_input.setPlaceholderText("Search HEADER...")
            self.part_name_search_input = QLineEdit()
            self.part_name_search_input.setPlaceholderText("Search PART NAME...")
            self.revision_search_input = QLineEdit()
            self.revision_search_input.setPlaceholderText("Search REVISION...")
            self.template_variant_search_input = QLineEdit()
            self.template_variant_search_input.setPlaceholderText("Search TEMPLATE VARIANT...")
            self.sample_number_search_input = QLineEdit()
            self.sample_number_search_input.setPlaceholderText("Search SAMPLE NUMBER...")
            self.operator_name_search_input = QLineEdit()
            self.operator_name_search_input.setPlaceholderText("Search OPERATOR NAME...")
            self.sample_number_kind_search_input = QLineEdit()
            self.sample_number_kind_search_input.setPlaceholderText("Search SAMPLE NUMBER KIND...")
            self.status_code_search_input = QLineEdit()
            self.status_code_search_input.setPlaceholderText("Search STATUS CODE...")
            self.filename_search_input = QLineEdit()
            self.filename_search_input.setPlaceholderText("Search FILENAME...")
            self.parser_id_search_input = QLineEdit()
            self.parser_id_search_input.setPlaceholderText("Search PARSER ID...")
            self.template_family_search_input = QLineEdit()
            self.template_family_search_input.setPlaceholderText("Search TEMPLATE FAMILY...")

            # Create a button to apply the filters
            self.apply_button = QPushButton("Apply filters")

            # Create a button to select today's date as "date TO"
            self.select_today_button = QPushButton("Select today")

            # Create a button to select the beginning of time
            self.select_beginning_button = QPushButton("Select beginning of time")
        except Exception as e:
            self.log_and_exit(e)

    def arrange_layout(self):
        try:
            self.layout = QtWidgets.QVBoxLayout(self)
            attach_help_menu_to_layout(self.layout, self, [("Filtering manual", 'export_filtering')])
            self.layout.setContentsMargins(10, 10, 10, 10)
            self.layout.setSpacing(8)

            self.filter_scroll_area = QtWidgets.QScrollArea()
            self.filter_scroll_area.setWidgetResizable(True)
            self.filter_scroll_content = QtWidgets.QWidget()
            self.filter_scroll_layout = QtWidgets.QVBoxLayout(self.filter_scroll_content)
            self.filter_scroll_layout.setContentsMargins(0, 0, 0, 0)
            self.filter_scroll_layout.setSpacing(8)

            for title, field_specs in self._build_filter_sections():
                group = QtWidgets.QGroupBox(title)
                group_layout = QGridLayout(group)
                group_layout.setContentsMargins(8, 8, 8, 8)
                group_layout.setHorizontalSpacing(8)
                group_layout.setVerticalSpacing(8)
                self._add_filter_group(group_layout, field_specs, max_columns=3)
                self.filter_scroll_layout.addWidget(group)

            self.filter_scroll_layout.addStretch(1)
            self.filter_scroll_area.setWidget(self.filter_scroll_content)
            self.layout.addWidget(self.filter_scroll_area, 1)
            self._add_filter_footer(self.layout)
            self._apply_window_size_constraints()
        except Exception as e:
            self.log_and_exit(e)

    def _add_filter_group(self, group_layout, field_specs, *, max_columns=3):
        for index, (label_attr, search_attr, list_attr) in enumerate(field_specs):
            row = index // max_columns
            column = index % max_columns
            field_widget = QtWidgets.QWidget()
            field_layout = QtWidgets.QVBoxLayout(field_widget)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)

            field_layout.addWidget(getattr(self, label_attr))
            if search_attr is not None:
                search_widget = getattr(self, search_attr)
                self._set_widget_size_policy(search_widget, min_width=150)
                field_layout.addWidget(search_widget)

            list_widget = getattr(self, list_attr)
            self._set_widget_size_policy(list_widget, min_width=150, min_height=110, expands_vertically=True)
            field_layout.addWidget(list_widget, 1)
            group_layout.addWidget(field_widget, row, column)

        for column in range(max_columns):
            group_layout.setColumnStretch(column, 1)

    def _add_filter_footer(self, parent_layout):
        footer_widget = QtWidgets.QWidget()
        footer_layout = QGridLayout(footer_widget)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setHorizontalSpacing(8)
        footer_layout.setVerticalSpacing(6)

        footer_layout.addWidget(self.date_from_label, 0, 0)
        footer_layout.addWidget(self.date_from_calendar, 0, 1)
        footer_layout.addWidget(self.select_beginning_button, 0, 2)
        footer_layout.addWidget(self.has_nok_button, 0, 3)
        footer_layout.addWidget(self.date_to_label, 1, 0)
        footer_layout.addWidget(self.date_to_calendar, 1, 1)
        footer_layout.addWidget(self.select_today_button, 1, 2)

        action_layout = QtWidgets.QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addStretch(1)
        action_layout.addWidget(self.apply_button)
        footer_layout.addLayout(action_layout, 1, 3)
        footer_layout.setColumnStretch(3, 1)
        parent_layout.addWidget(footer_widget)

    def _set_widget_size_policy(self, widget, *, min_width=None, min_height=None, expands_vertically=False):
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

    def _apply_window_size_constraints(self):
        default_width = 980
        default_height = 720
        app = QtWidgets.QApplication.instance() if hasattr(QtWidgets, "QApplication") else None
        screen = app.primaryScreen() if app is not None and hasattr(app, "primaryScreen") else None
        available = screen.availableGeometry() if screen is not None and hasattr(screen, "availableGeometry") else None
        if available is None:
            self.resize(default_width, default_height)
            return

        width = min(max(default_width, int(available.width() * 0.78)), int(available.width() * 0.96))
        height = min(max(default_height, int(available.height() * 0.78)), int(available.height() * 0.92))
        if hasattr(self, "setMaximumSize"):
            self.setMaximumSize(available.width(), available.height())
        self.resize(width, height)
            
    def connect_signals(self):
        try:
            self.ax_search_input.textChanged.connect(lambda: self.search_list_widgets(self.ax_list, self.ax_search_input.text()))
            self.header_search_input.textChanged.connect(lambda: self.search_list_widgets(self.header_list, self.header_search_input.text()))
            self.reference_search_input.textChanged.connect(lambda: self.search_list_widgets(self.reference_list, self.reference_search_input.text()))
            self.part_name_search_input.textChanged.connect(lambda: self.search_list_widgets(self.part_name_list, self.part_name_search_input.text()))
            self.revision_search_input.textChanged.connect(lambda: self.search_list_widgets(self.revision_list, self.revision_search_input.text()))
            self.template_variant_search_input.textChanged.connect(lambda: self.search_list_widgets(self.template_variant_list, self.template_variant_search_input.text()))
            self.sample_number_search_input.textChanged.connect(lambda: self.search_list_widgets(self.sample_number_list, self.sample_number_search_input.text()))
            self.operator_name_search_input.textChanged.connect(lambda: self.search_list_widgets(self.operator_name_list, self.operator_name_search_input.text()))
            self.sample_number_kind_search_input.textChanged.connect(lambda: self.search_list_widgets(self.sample_number_kind_list, self.sample_number_kind_search_input.text()))
            self.status_code_search_input.textChanged.connect(lambda: self.search_list_widgets(self.status_code_list, self.status_code_search_input.text()))
            self.filename_search_input.textChanged.connect(lambda: self.search_list_widgets(self.filename_list, self.filename_search_input.text()))
            self.parser_id_search_input.textChanged.connect(lambda: self.search_list_widgets(self.parser_id_list, self.parser_id_search_input.text()))
            self.template_family_search_input.textChanged.connect(lambda: self.search_list_widgets(self.template_family_list, self.template_family_search_input.text()))
            
            # Connect the itemSelectionChanged signal of the "HEADER" list to the update_selected_headers method
            self.header_list.itemSelectionChanged.connect(self.update_selected_headers)
            self.reference_list.itemSelectionChanged.connect(self.on_reference_selection_changed)

            self._connect_shift_range_for_list(self.ax_list)
            self._connect_shift_range_for_list(self.reference_list)
            self._connect_shift_range_for_list(self.header_list)
            self._connect_shift_range_for_list(self.part_name_list)
            self._connect_shift_range_for_list(self.revision_list)
            self._connect_shift_range_for_list(self.template_variant_list)
            self._connect_shift_range_for_list(self.sample_number_list)
            self._connect_shift_range_for_list(self.operator_name_list)
            self._connect_shift_range_for_list(self.sample_number_kind_list)
            self._connect_shift_range_for_list(self.status_code_list)
            self._connect_shift_range_for_list(self.filename_list)
            self._connect_shift_range_for_list(self.parser_id_list)
            self._connect_shift_range_for_list(self.template_family_list)
            self._connect_shift_range_for_list(self.selected_headers_list)

            self.select_today_button.clicked.connect(self.select_today_as_date_to)
            self.select_beginning_button.clicked.connect(self.select_beginning_of_time)
            self.apply_button.clicked.connect(self.apply_filters)
        except Exception as e:
            self.log_and_exit(e)


    def _apply_list_theme_styles(self):
        highlight_name = ui_theme_tokens.SELECTED_ROW_BACKGROUND_FALLBACK
        for list_widget in (
            getattr(self, 'ax_list', None),
            getattr(self, 'reference_list', None),
            getattr(self, 'header_list', None),
            getattr(self, 'part_name_list', None),
            getattr(self, 'revision_list', None),
            getattr(self, 'template_variant_list', None),
            getattr(self, 'sample_number_list', None),
            getattr(self, 'operator_name_list', None),
            getattr(self, 'sample_number_kind_list', None),
            getattr(self, 'status_code_list', None),
            getattr(self, 'filename_list', None),
            getattr(self, 'parser_id_list', None),
            getattr(self, 'template_family_list', None),
            getattr(self, 'selected_headers_list', None),
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

    def _connect_shift_range_for_list(self, list_widget):
        self._list_selection_utils.connect_shift_range_behavior(list_widget)

    def _handle_list_item_pressed(self, list_widget, item):
        self._list_selection_utils.handle_shift_range_press(list_widget, item)

    def _delete_selected_headers(self):
        selected_headers = {item.text() for item in self.selected_headers_list.selectedItems()}
        if not selected_headers:
            return False

        for row in range(self.header_list.count()):
            header_item = self.header_list.item(row)
            if header_item is not None and header_item.text() in selected_headers:
                header_item.setSelected(False)

        self.update_selected_headers()
        return True

    def keyPressEvent(self, event):
        try:
            pressed_key = event.key() if event is not None and hasattr(event, "key") else None
            if (
                pressed_key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
                and self.selected_headers_list is not None
                and (
                    self.selected_headers_list.hasFocus()
                    or (
                        hasattr(self.selected_headers_list, "viewport")
                        and self.selected_headers_list.viewport() is not None
                        and self.selected_headers_list.viewport().hasFocus()
                    )
                )
            ):
                self._delete_selected_headers()
                event.accept()
                return
        except Exception as e:
            self.log_and_exit(e)

        super().keyPressEvent(event)

    def populate_list_widgets(self):
        try:
            current_filter_query = self.filter_query
            self._populate_distinct_values(self.ax_list, "AX", filter_query=current_filter_query)
            self._populate_distinct_values(self.header_list, "HEADER", filter_query=current_filter_query)
            self._populate_distinct_values(self.all_headers_list, "HEADER", filter_query=current_filter_query)
            self._populate_distinct_values(self.reference_list, "REFERENCE", source_view="vw_report_overview", filter_query=current_filter_query)
            self._populate_distinct_values(self.part_name_list, "PART_NAME", source_view="vw_report_overview", filter_query=current_filter_query)
            self._populate_distinct_values(self.revision_list, "REVISION", source_view="vw_report_overview", filter_query=current_filter_query)
            self._populate_distinct_values(self.template_variant_list, "TEMPLATE_VARIANT", source_view="vw_report_overview", filter_query=current_filter_query)
            self._populate_distinct_values(self.sample_number_list, "SAMPLE_NUMBER", source_view="vw_report_overview", filter_query=current_filter_query)
            self._populate_distinct_values(self.operator_name_list, "OPERATOR_NAME", source_view="vw_report_overview", filter_query=current_filter_query)
            self._populate_distinct_values(self.sample_number_kind_list, "SAMPLE_NUMBER_KIND", source_view="vw_report_overview", filter_query=current_filter_query)
            self._populate_distinct_values(self.status_code_list, "STATUS_CODE", filter_query=current_filter_query)
            self._populate_distinct_values(self.filename_list, "FILENAME", source_view="vw_report_overview", filter_query=current_filter_query)
            self._populate_distinct_values(self.parser_id_list, "PARSER_ID", source_view="vw_report_overview", filter_query=current_filter_query)
            self._populate_distinct_values(self.template_family_list, "TEMPLATE_FAMILY", source_view="vw_report_overview", filter_query=current_filter_query)
        except Exception as e:
            self.log_and_exit(e)

    def _populate_distinct_values(self, list_widget, column_name, *, source_view="vw_measurement_export", filter_query=None):
        query = build_distinct_value_query(column_name, source_view=source_view, filter_query=filter_query)
        values = execute_with_retry(self.db_file, query)
        list_widget.clear()
        list_widget.addItem("SELECT ALL")
        for value in values:
            item = QListWidgetItem(value[0])
            list_widget.addItem(item)

    def search_list_widgets(self, list_widget, search_text):
        try:
            self._list_selection_utils.preserve_selection_during_filter(list_widget, search_text)
        except Exception as e:
            self.log_and_exit(e)

    def on_reference_selection_changed(self):
        try:
            selected_references = [item.text() for item in self.reference_list.selectedItems()]
            self.header_list.clear()
            self.selected_headers_list.clear()

            if selected_references and "SELECT ALL" not in selected_references:
                filter_query = build_measurement_filter_query(reference_values=selected_references)
                self._populate_distinct_values(self.header_list, "HEADER", filter_query=filter_query)
            else:
                for row in range(self.all_headers_list.count()):
                    item = self.all_headers_list.item(row)
                    self.header_list.addItem(item.text())
        except Exception as e:
            self.log_and_exit(e)
                
    def update_selected_headers(self):
        try:
            # Clear the current items in the "SELECTED HEADERS" list
            self.selected_headers_list.clear()

            # Get selected items from the "HEADER" list
            selected_header_items = [
                self.header_list.item(row)
                for row in range(self.header_list.count())
                if self.header_list.item(row) is not None and self.header_list.item(row).isSelected()
            ]

            # Add the selected headers to the "SELECTED HEADERS" list
            for item in selected_header_items:
                selected_header_item = QListWidgetItem(item.text())
                self.selected_headers_list.addItem(selected_header_item)
        except Exception as e:
            self.log_and_exit(e)

    def select_beginning_of_time(self):
        try:
            beginning_of_time = QDate(1970, 1, 1)
            self.date_from_calendar.setDate(beginning_of_time)
        except Exception as e:
            self.log_and_exit(e)

    def select_today_as_date_to(self):
        try:
            today = QDate.currentDate()
            self.date_to_calendar.setDate(today)
        except Exception as e:
            self.log_and_exit(e)

    def apply_filters(self):
        try:
            # Get the selected values from the list widgets and calendars
            ax_selected_items = [item.text() for item in self.ax_list.selectedItems()]
            header_selected_items = [item.text() for item in self.header_list.selectedItems()]
            reference_selected_items = [item.text() for item in self.reference_list.selectedItems()]
            part_name_selected_items = [item.text() for item in self.part_name_list.selectedItems()]
            revision_selected_items = [item.text() for item in self.revision_list.selectedItems()]
            template_variant_selected_items = [item.text() for item in self.template_variant_list.selectedItems()]
            sample_number_selected_items = [item.text() for item in self.sample_number_list.selectedItems()]
            operator_name_selected_items = [item.text() for item in self.operator_name_list.selectedItems()]
            sample_number_kind_selected_items = [item.text() for item in self.sample_number_kind_list.selectedItems()]
            status_code_selected_items = [item.text() for item in self.status_code_list.selectedItems()]
            filename_selected_items = [item.text() for item in self.filename_list.selectedItems()]
            parser_id_selected_items = [item.text() for item in self.parser_id_list.selectedItems()]
            template_family_selected_items = [item.text() for item in self.template_family_list.selectedItems()]
            has_nok_only = bool(getattr(self.has_nok_button, "isChecked", lambda: False)())
            date_from = self.date_from_calendar.date().toString("yyyy-MM-dd")
            date_to = self.date_to_calendar.date().toString("yyyy-MM-dd")

            query = build_measurement_filter_query(
                ax_values=[] if "SELECT ALL" in ax_selected_items else ax_selected_items,
                header_values=[] if "SELECT ALL" in header_selected_items else header_selected_items,
                reference_values=[] if "SELECT ALL" in reference_selected_items else reference_selected_items,
                part_name_values=[] if "SELECT ALL" in part_name_selected_items else part_name_selected_items,
                revision_values=[] if "SELECT ALL" in revision_selected_items else revision_selected_items,
                template_variant_values=[] if "SELECT ALL" in template_variant_selected_items else template_variant_selected_items,
                sample_number_values=[] if "SELECT ALL" in sample_number_selected_items else sample_number_selected_items,
                operator_name_values=[] if "SELECT ALL" in operator_name_selected_items else operator_name_selected_items,
                sample_number_kind_values=[] if "SELECT ALL" in sample_number_kind_selected_items else sample_number_kind_selected_items,
                status_code_values=[] if "SELECT ALL" in status_code_selected_items else status_code_selected_items,
                filename_values=[] if "SELECT ALL" in filename_selected_items else filename_selected_items,
                parser_id_values=[] if "SELECT ALL" in parser_id_selected_items else parser_id_selected_items,
                template_family_values=[] if "SELECT ALL" in template_family_selected_items else template_family_selected_items,
                has_nok_only=has_nok_only,
                date_from=date_from,
                date_to=date_to,
            )

            self.filter_query = query
            self.parent().set_filter_query(self.filter_query)
            self.parent().set_filter_applied()

            # Hide the filter window
            self.hide()
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
