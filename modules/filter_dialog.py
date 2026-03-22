from modules.custom_logger import CustomLogger
from modules.db import execute_with_retry
from modules.list_selection_utils import ListSelectionUtils
from modules import ui_theme_tokens
from modules.help_menu import attach_help_menu_to_layout
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


class FilterDialog(QDialog):
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

        self.setup_ui()

    @staticmethod
    def _multi_selection_mode():
        selection_mode_enum = getattr(getattr(QtWidgets, "QAbstractItemView", None), "SelectionMode", None)
        return getattr(selection_mode_enum, "MultiSelection", 2)

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
            
            self.selected_headers_label = QLabel("SELECTED HEADERS:")
            self.selected_headers_list = QListWidget()
            self.selected_headers_list.setSelectionMode(self._multi_selection_mode())

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

            # Create separate QLineEdit widgets for searching in each list widget
            self.ax_search_input = QLineEdit()
            self.ax_search_input.setPlaceholderText("Search AX...")
            self.reference_search_input = QLineEdit()
            self.reference_search_input.setPlaceholderText("Search REFERENCE...")
            self.header_search_input = QLineEdit()
            self.header_search_input.setPlaceholderText("Search HEADER...")

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
            self.layout = QGridLayout(self)
            attach_help_menu_to_layout(self.layout, self, [("Filtering manual", 'export_filtering')])
            self.layout.addWidget(self.ax_label, 0, 0)
            self.layout.addWidget(self.ax_search_input, 1, 0)
            self.layout.addWidget(self.ax_list, 2, 0)

            self.layout.addWidget(self.reference_label, 0, 1)
            self.layout.addWidget(self.reference_search_input, 1, 1)
            self.layout.addWidget(self.reference_list, 2, 1)

            self.layout.addWidget(self.header_label, 0, 2)
            self.layout.addWidget(self.header_search_input, 1, 2)
            self.layout.addWidget(self.header_list, 2, 2)

            self.layout.addWidget(self.selected_headers_label, 0, 3)
            self.layout.addWidget(self.selected_headers_list, 2, 3)

            self.layout.addWidget(self.date_from_label, 3, 0)
            self.layout.addWidget(self.date_from_calendar, 3, 1)

            self.layout.addWidget(self.date_to_label, 4, 0)
            self.layout.addWidget(self.date_to_calendar, 4, 1)

            for row in range(self.layout.rowCount()):
                for column in range(self.layout.columnCount()):
                    item = self.layout.itemAtPosition(row, column)
                    if item is not None:
                        widget = item.widget()
                        if widget is not None:
                            widget.setFixedWidth(150) if column == 0 else widget.setFixedWidth(150)

            self.layout.addWidget(self.select_beginning_button, 3, 2)
            self.layout.addWidget(self.select_today_button, 4, 2)
            self.layout.addWidget(self.apply_button, 6, 0, 1, 3)

            self.show()
        except Exception as e:
            self.log_and_exit(e)
            
    def connect_signals(self):
        try:
            self.ax_search_input.textChanged.connect(lambda: self.search_list_widgets(self.ax_list, self.ax_search_input.text()))
            self.header_search_input.textChanged.connect(lambda: self.search_list_widgets(self.header_list, self.header_search_input.text()))
            self.reference_search_input.textChanged.connect(lambda: self.search_list_widgets(self.reference_list, self.reference_search_input.text()))
            
            # Connect the itemSelectionChanged signal of the "HEADER" list to the update_selected_headers method
            self.header_list.itemSelectionChanged.connect(self.update_selected_headers)

            self._connect_shift_range_for_list(self.ax_list)
            self._connect_shift_range_for_list(self.reference_list)
            self._connect_shift_range_for_list(self.header_list)
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
            ax_values = execute_with_retry(self.db_file, "SELECT DISTINCT AX FROM MEASUREMENTS;")
            for value in ax_values:
                item = QListWidgetItem(value[0])
                self.ax_list.addItem(item)

            header_values = execute_with_retry(self.db_file, "SELECT DISTINCT HEADER FROM MEASUREMENTS;")
            for value in header_values:
                header_item = QListWidgetItem(value[0])
                all_headers_item = QListWidgetItem(value[0])
                self.header_list.addItem(header_item)
                self.all_headers_list.addItem(all_headers_item)

            reference_values = execute_with_retry(self.db_file, "SELECT DISTINCT REFERENCE FROM REPORTS;")
            for value in reference_values:
                item = QListWidgetItem(value[0])
                self.reference_list.addItem(item)

            self.reference_list.itemSelectionChanged.connect(self.on_reference_selection_changed)
        except Exception as e:
            self.log_and_exit(e)

    def search_list_widgets(self, list_widget, search_text):
        try:
            self._list_selection_utils.preserve_selection_during_filter(list_widget, search_text)
        except Exception as e:
            self.log_and_exit(e)

    def on_reference_selection_changed(self):
        try:
            selected_references = [item.text() for item in self.reference_list.selectedItems()]
            self.header_list.clear()

            if selected_references and "SELECT ALL" not in selected_references:
                reference_values = "','".join(selected_references)
                query = f"""
                    SELECT DISTINCT HEADER FROM MEASUREMENTS 
                    JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID 
                    WHERE REFERENCE IN (SELECT REFERENCE FROM REPORTS WHERE REFERENCE IN ('{reference_values}'));
                    """
                header_values = execute_with_retry(self.db_file, query)
                for value in header_values:
                    item = QListWidgetItem(value[0])
                    self.header_list.addItem(item)
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
            date_from = self.date_from_calendar.date().toString("yyyy-MM-dd")
            date_to = self.date_to_calendar.date().toString("yyyy-MM-dd")

            # Construct the filter query based on the selected values
            query = """
                SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL", 
                    MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS, 
                    MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE, 
                    REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE, REPORTS.SAMPLE_NUMBER 
                FROM MEASUREMENTS
                JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
                WHERE 1=1
                """

            if ax_selected_items and "SELECT ALL" not in ax_selected_items:
                ax_values = "','".join(ax_selected_items)
                query += f" AND MEASUREMENTS.AX IN ('{ax_values}')"

            if header_selected_items and "SELECT ALL" not in header_selected_items:
                header_values = "','".join(header_selected_items)
                query += f" AND MEASUREMENTS.HEADER IN ('{header_values}')"

            if reference_selected_items and "SELECT ALL" not in reference_selected_items:
                reference_values = "','".join(reference_selected_items)
                query += f" AND REPORTS.REFERENCE IN ('{reference_values}')"

            if date_from:
                query += f" AND REPORTS.DATE >= '{date_from}'"

            if date_to:
                query += f" AND REPORTS.DATE <= '{date_to}'"

            self.filter_query = query
            self.parent().set_filter_query(self.filter_query)
            self.parent().set_filter_applied()

            # Hide the filter window
            self.hide()
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
