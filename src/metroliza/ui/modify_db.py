"""Dialog for bulk and targeted metadata edits in the SQLite database."""

from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
import PyQt6.QtCore as QtCore
from PyQt6.QtCore import QTimer, Qt
import PyQt6.QtWidgets as QtWidgets
import logging
import sqlite3
from metroliza.shared.custom_logger import CustomLogger
from metroliza.reports.db import (
    execute_select_with_columns,
    quote_identifier,
)
from metroliza.reports.report_edit_service import (
    LEGACY_MEASUREMENT_FIELD_COLUMNS as EDIT_SERVICE_LEGACY_MEASUREMENT_FIELDS,
    LEGACY_REPORT_FIELD_COLUMNS as EDIT_SERVICE_LEGACY_REPORT_FIELDS,
    ReportEditService,
)
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.modify_db_records import (
    FILTER_DEBOUNCE_MS,
    RecordBusyBanner,
    RecordLoadThread,
    RecordRows,
    RecordTableModel,
    RecordTableSlot,
    RecordTableView,
    cancel_load_thread,
    display_value,
    load_record_rows,
    start_load_thread,
)
from metroliza.reports.report_repository import ReportRepository
from metroliza.reports.report_schema import ensure_report_schema
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_dialog_button_roles,
    configure_table,
    configure_window_size,
)


logger = logging.getLogger(__name__)
QItemSelection = getattr(QtCore, "QItemSelection", None)
QItemSelectionModel = getattr(QtCore, "QItemSelectionModel", None)


class ModifyDB(QDialog):
    """Provide table-based editing for selected report metadata fields.

    The first tab keeps the legacy global value normalization behavior. The
    record tabs load report and measurement rows and apply changed fields
    through the repository API when available.
    """

    REPORT_RECORD_COLUMNS = (
        {"label": "REPORT_ID", "field": "report_id", "source": "report_id", "editable": False, "key": True},
        {"label": "REFERENCE", "field": "reference", "source": "reference", "editable": True},
        {"label": "DATE", "field": "report_date", "source": "report_date", "editable": True},
        {"label": "TIME", "field": "report_time", "source": "report_time", "editable": True},
        {"label": "PART_NAME", "field": "part_name", "source": "part_name", "editable": True},
        {"label": "REVISION", "field": "revision", "source": "revision", "editable": True},
        {"label": "SAMPLE_NUMBER", "field": "sample_number", "source": "sample_number", "editable": True},
        {"label": "OPERATOR_NAME", "field": "operator_name", "source": "operator_name", "editable": True},
        {"label": "COMMENT", "field": "comment", "source": "comment", "editable": True},
        {"label": "FILENAME", "field": "file_name", "source": "file_name", "editable": False},
        {"label": "TEMPLATE_VARIANT", "field": "template_variant", "source": "template_variant", "editable": False},
    )

    MEASUREMENT_RECORD_COLUMNS = (
        {"label": "MEASUREMENT_ID", "field": "measurement_id", "source": "measurement_id", "editable": False, "key": True},
        {"label": "REPORT_ID", "field": "report_id", "source": "report_id", "editable": False},
        {"label": "HEADER", "field": "header", "source": "header", "editable": True},
        {"label": "SECTION_NAME", "field": "section_name", "source": "section_name", "editable": True},
        {"label": "FEATURE_LABEL", "field": "feature_label", "source": "feature_label", "editable": True},
        {"label": "CHARACTERISTIC_NAME", "field": "characteristic_name", "source": "characteristic_name", "editable": True},
        {
            "label": "CHARACTERISTIC_FAMILY",
            "field": "characteristic_family",
            "source": "characteristic_family",
            "editable": True,
        },
        {"label": "DESCRIPTION", "field": "description", "source": "description", "editable": True},
        {"label": "AX", "field": "ax", "source": "ax", "editable": True},
        {"label": "NOM", "field": "nominal", "source": "nominal", "editable": True, "value_type": "float"},
        {"label": "+TOL", "field": "tol_plus", "source": "tol_plus", "editable": True, "value_type": "float"},
        {"label": "-TOL", "field": "tol_minus", "source": "tol_minus", "editable": True, "value_type": "float"},
        {"label": "BONUS", "field": "bonus", "source": "bonus", "editable": True, "value_type": "float"},
        {"label": "MEAS", "field": "meas", "source": "meas", "editable": True, "value_type": "float"},
        {"label": "DEV", "field": "dev", "source": "dev", "editable": True, "value_type": "float"},
        {"label": "OUTTOL", "field": "outtol", "source": "outtol", "editable": True, "value_type": "float"},
        {"label": "STATUS_CODE", "field": "status_code", "source": "status_code", "editable": True},
    )

    MEASUREMENT_TABLE_COLUMNS = tuple(
        {**column, "source": "id"} if column["field"] == "measurement_id" else column
        for column in MEASUREMENT_RECORD_COLUMNS
    )

    LEGACY_REPORT_RECORD_COLUMNS = (
        {"label": "REPORT_ID", "field": "report_id", "source": "ID", "editable": False, "key": True},
        {"label": "REFERENCE", "field": "reference", "source": "REFERENCE", "editable": True},
        {"label": "DATE", "field": "report_date", "source": "DATE", "editable": True},
        {"label": "SAMPLE_NUMBER", "field": "sample_number", "source": "SAMPLE_NUMBER", "editable": True},
        {"label": "FILELOC", "field": "fileloc", "source": "FILELOC", "editable": False},
        {"label": "FILENAME", "field": "filename", "source": "FILENAME", "editable": False},
    )

    LEGACY_MEASUREMENT_RECORD_COLUMNS = (
        {"label": "MEASUREMENT_ID", "field": "measurement_id", "source": "ID", "editable": False, "key": True},
        {"label": "REPORT_ID", "field": "report_id", "source": "REPORT_ID", "editable": False},
        {"label": "HEADER", "field": "header", "source": "HEADER", "editable": True},
        {"label": "AX", "field": "ax", "source": "AX", "editable": True},
        {"label": "NOM", "field": "nominal", "source": "NOM", "editable": True, "value_type": "float"},
        {"label": "+TOL", "field": "tol_plus", "source": "+TOL", "editable": True, "value_type": "float"},
        {"label": "-TOL", "field": "tol_minus", "source": "-TOL", "editable": True, "value_type": "float"},
        {"label": "BONUS", "field": "bonus", "source": "BONUS", "editable": True, "value_type": "float"},
        {"label": "MEAS", "field": "meas", "source": "MEAS", "editable": True, "value_type": "float"},
        {"label": "DEV", "field": "dev", "source": "DEV", "editable": True, "value_type": "float"},
        {"label": "OUTTOL", "field": "outtol", "source": "OUTTOL", "editable": True, "value_type": "float"},
    )

    LEGACY_REPORT_FIELD_COLUMNS = EDIT_SERVICE_LEGACY_REPORT_FIELDS
    LEGACY_MEASUREMENT_FIELD_COLUMNS = EDIT_SERVICE_LEGACY_MEASUREMENT_FIELDS

    def __init__(self, parent=None, db_file="", *, modal=True):
        super().__init__(parent)
        self.setWindowTitle("Modify database")
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())
        configure_window_size(self, minimum=(860, 540), initial=(1100, 650))
        self.setModal(modal)

        self.db_file = db_file
        self.database_change_allowed = None
        self.undo_data = {}
        self._last_clicked_row_by_table = {}
        self._record_slots = []
        self._storage_flavor = "current"
        self._changes_committed = False
        self._discard_confirmed = False

        self.setup_ui()

    @staticmethod
    def _multi_selection_mode():
        selection_mode_enum = getattr(getattr(QtWidgets, "QAbstractItemView", None), "SelectionMode", None)
        return getattr(selection_mode_enum, "MultiSelection", 2)

    @staticmethod
    def _select_rows_behavior():
        selection_behavior_enum = getattr(getattr(QtWidgets, "QAbstractItemView", None), "SelectionBehavior", None)
        return getattr(selection_behavior_enum, "SelectRows", 1)

    @staticmethod
    def _keyboard_modifiers():
        app_cls = getattr(QtWidgets, "QApplication", None)
        if app_cls is None or not hasattr(app_cls, "keyboardModifiers"):
            return 0
        return app_cls.keyboardModifiers()

    @staticmethod
    def _shift_modifier_flag():
        keyboard_modifier_enum = getattr(Qt, "KeyboardModifier", None)
        return getattr(keyboard_modifier_enum, "ShiftModifier", 0)

    def setup_ui(self):
        try:
            self.create_widgets()
            self.arrange_layout()
            self.connect_signals()
            apply_metroliza_theme(self)
            if self.db_file:
                self.populate_tables()
        except Exception as e:
            self.log_and_exit(e)

    def create_widgets(self):
        try:
            self.reference_filter_edit = QtWidgets.QLineEdit()
            self.reference_filter_edit.setPlaceholderText("Search references")
            self.reference_table = self._create_normalize_table()

            self.part_number_filter_edit = QtWidgets.QLineEdit()
            self.part_number_filter_edit.setPlaceholderText("Search sample numbers")
            self.part_number_table = self._create_normalize_table()

            self.header_filter_edit = QtWidgets.QLineEdit()
            self.header_filter_edit.setPlaceholderText("Search headers")
            self.header_table = self._create_normalize_table()

            self.tab_widget = QtWidgets.QTabWidget()
            self.normalize_tab = QtWidgets.QWidget()
            self.normalize_tab_widget = QtWidgets.QTabWidget()
            self.report_records_tab = QtWidgets.QWidget()
            self.measurement_rows_tab = QtWidgets.QWidget()

            self.report_filter_edit = QtWidgets.QLineEdit()
            self.report_filter_edit.setPlaceholderText("Filter report records")
            self.report_records_table = self._create_record_table()
            self.report_busy_banner = RecordBusyBanner("Loading report records...")

            self.measurement_filter_edit = QtWidgets.QLineEdit()
            self.measurement_filter_edit.setPlaceholderText("Filter measurement rows")
            self.measurement_records_table = self._create_record_table()
            self.measurement_busy_banner = RecordBusyBanner("Loading measurement rows...")
            self._record_slots = [
                self._create_record_slot(
                    "report", self.report_records_tab, self.report_records_table,
                    self.report_filter_edit, self.report_busy_banner,
                ),
                self._create_record_slot(
                    "measurement", self.measurement_rows_tab, self.measurement_records_table,
                    self.measurement_filter_edit, self.measurement_busy_banner,
                ),
            ]

            # Create buttons for Select DB file, Apply changes, Undo, and Cancel
            self.select_db_button = QPushButton("Select DB file")
            self.apply_button = QPushButton("Apply changes")
            if not self.db_file:
                self.apply_button.setEnabled(False)
            self.undo_button = QPushButton("Undo last change")
            self.cancel_button = QPushButton("Cancel")
            configure_dialog_button_roles(
                primary=self.apply_button,
                secondary=(self.select_db_button,),
                quiet=(self.cancel_button,),
            )
        except Exception as e:
            self.log_and_exit(e)

    def _create_record_table(self):
        table = RecordTableView()
        table.setSelectionMode(self._multi_selection_mode())
        table.setSelectionBehavior(self._select_rows_behavior())
        table.set_record_model(RecordTableModel())
        return table

    def _create_record_slot(self, kind, tab, table, filter_edit, banner):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(FILTER_DEBOUNCE_MS)
        return RecordTableSlot(
            kind=kind, tab=tab, view=table, filter_edit=filter_edit, banner=banner, filter_timer=timer
        )

    def _create_normalize_table(self):
        table = QTableWidget()
        table.setSelectionMode(self._multi_selection_mode())
        table.setSelectionBehavior(self._select_rows_behavior())
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Original value", "New value", "Occurrences"])
        self._configure_normalize_table(table)
        return table

    @staticmethod
    def _configure_normalize_table(table):
        configure_table(table, stretch_column=1, resize_to_contents=(2,), min_height=220)
        header = table.horizontalHeader() if hasattr(table, "horizontalHeader") else None
        resize_mode_enum = getattr(getattr(QtWidgets, "QHeaderView", None), "ResizeMode", None)
        stretch_mode = getattr(resize_mode_enum, "Stretch", None)
        resize_to_contents_mode = getattr(resize_mode_enum, "ResizeToContents", None)
        if header is None or stretch_mode is None or resize_to_contents_mode is None:
            return
        header.setSectionResizeMode(0, stretch_mode)
        header.setSectionResizeMode(1, stretch_mode)
        header.setSectionResizeMode(2, resize_to_contents_mode)

    def arrange_layout(self):
        try:
            layout = QGridLayout(self)
            attach_help_menu_to_layout(layout, self, [("Modify Database manual", 'modify_database')])
            if hasattr(layout, "setContentsMargins"):
                layout.setContentsMargins(14, 14, 14, 14)
            if hasattr(layout, "setHorizontalSpacing"):
                layout.setHorizontalSpacing(10)
            if hasattr(layout, "setVerticalSpacing"):
                layout.setVerticalSpacing(8)

            normalize_layout = QtWidgets.QVBoxLayout(self.normalize_tab)
            normalize_layout.addWidget(self.normalize_tab_widget)
            self._add_normalize_field_tab("REFERENCE", self.reference_filter_edit, self.reference_table)
            self._add_normalize_field_tab("SAMPLE NUMBER", self.part_number_filter_edit, self.part_number_table)
            self._add_normalize_field_tab("HEADER", self.header_filter_edit, self.header_table)

            report_layout = QtWidgets.QVBoxLayout(self.report_records_tab)
            report_layout.addWidget(self.report_filter_edit)
            report_layout.addWidget(self.report_busy_banner)
            report_layout.addWidget(self.report_records_table)

            measurement_layout = QtWidgets.QVBoxLayout(self.measurement_rows_tab)
            measurement_layout.addWidget(self.measurement_filter_edit)
            measurement_layout.addWidget(self.measurement_busy_banner)
            measurement_layout.addWidget(self.measurement_records_table)

            self.tab_widget.addTab(self.normalize_tab, "Normalize values")
            self.tab_widget.addTab(self.report_records_tab, "Report records")
            self.tab_widget.addTab(self.measurement_rows_tab, "Measurement rows")

            layout.addWidget(self.tab_widget, 0, 0, 1, 3)

            footer_layout = QHBoxLayout()
            if hasattr(footer_layout, "setSpacing"):
                footer_layout.setSpacing(8)
            footer_layout.addWidget(self.select_db_button)
            footer_layout.addStretch(1)
            footer_layout.addWidget(self.cancel_button)
            footer_layout.addSpacing(10)
            footer_layout.addWidget(self.apply_button)
            # Undo remains non-primary until editing behavior is revisited.
            # footer_layout.addWidget(self.undo_button)
            layout.addLayout(footer_layout, 1, 0, 1, 3)

            self.show()
        except Exception as e:
            self.log_and_exit(e)

    def _add_normalize_field_tab(self, title, search_edit, table):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(search_edit)
        layout.addWidget(table)
        self.normalize_tab_widget.addTab(tab, title)

    def connect_signals(self):
        try:
            # Connect signals for button clicks or list item selection if needed
            self.select_db_button.clicked.connect(self.select_db_file)
            self.apply_button.clicked.connect(self.confirm_and_apply_changes)
            self.undo_button.clicked.connect(self.undo_last_change)
            self.cancel_button.clicked.connect(self.cancel_changes)

            self._connect_shift_range_for_table(self.reference_table)
            self._connect_shift_range_for_table(self.part_number_table)
            self._connect_shift_range_for_table(self.header_table)
            self._connect_shift_range_for_table(self.report_records_table)
            self._connect_shift_range_for_table(self.measurement_records_table)
            self.tab_widget.currentChanged.connect(self._on_main_tab_changed)
            for slot in self._record_slots:
                slot.filter_edit.textChanged.connect(lambda _text, timer=slot.filter_timer: timer.start())
                slot.filter_timer.timeout.connect(lambda slot=slot: self._apply_record_filter(slot))
            self.reference_filter_edit.textChanged.connect(
                lambda text: self._filter_table_rows(self.reference_table, text)
            )
            self.part_number_filter_edit.textChanged.connect(
                lambda text: self._filter_table_rows(self.part_number_table, text)
            )
            self.header_filter_edit.textChanged.connect(
                lambda text: self._filter_table_rows(self.header_table, text)
            )
        except Exception as e:
            self.log_and_exit(e)

    def _connect_shift_range_for_table(self, table_widget):
        table_widget.cellPressed.connect(
            lambda row, column, tw=table_widget: self._handle_table_cell_pressed(tw, row, column)
        )

    def _handle_table_cell_pressed(self, table_widget, row, column):
        del column
        previous_row = self._last_clicked_row_by_table.get(table_widget)
        keyboard_modifiers = self._keyboard_modifiers()
        shift_modifier_flag = self._shift_modifier_flag()
        is_shift_pressed = (
            bool(keyboard_modifiers & shift_modifier_flag)
            if shift_modifier_flag
            else bool(keyboard_modifiers)
        )

        if is_shift_pressed and previous_row is not None:
            start_row = min(previous_row, row)
            end_row = max(previous_row, row)
            selection_model = table_widget.selectionModel()
            table_model = table_widget.model()
            last_column = max(table_widget.columnCount() - 1, 0)

            selection_flag_enum = getattr(QItemSelectionModel, "SelectionFlag", None)
            select_flag = getattr(selection_flag_enum, "Select", 0)
            rows_flag = getattr(selection_flag_enum, "Rows", 0)
            selection_flags = select_flag | rows_flag

            if QItemSelection is not None and QItemSelectionModel is not None:
                selection = QItemSelection(
                    table_model.index(start_row, 0),
                    table_model.index(end_row, last_column),
                )
                selection_model.select(selection, selection_flags)
                selection_model.select(table_model.index(previous_row, 0), selection_flags)
            else:
                for selected_row in range(start_row, end_row + 1):
                    selection_model.select(table_model.index(selected_row, 0), selection_flags)

            table_widget.setCurrentCell(row, 0)
            return

        self._last_clicked_row_by_table[table_widget] = row

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._handle_bulk_rename_shortcut():
                event.accept()
                return

        super().keyPressEvent(event)

    def _handle_bulk_rename_shortcut(self):
        target_table = self._focused_table_widget()
        if target_table is None:
            return False

        selected_rows = sorted({index.row() for index in target_table.selectionModel().selectedRows()})
        if not selected_rows:
            return False

        edit_column = self._normalize_table_edit_column(target_table)
        current_row = target_table.currentRow() if hasattr(target_table, "currentRow") else selected_rows[0]
        suggested_item = target_table.item(current_row, edit_column)
        current_item = target_table.currentItem()
        if suggested_item is None:
            suggested_item = current_item
        suggested_value = suggested_item.text() if suggested_item is not None else ""
        new_value, is_confirmed = QtWidgets.QInputDialog.getText(
            self,
            "Rename selected items",
            f"Enter new value for {len(selected_rows)} selected item(s):",
            text=suggested_value,
        )
        if not is_confirmed:
            return True

        normalized_value = str(new_value)
        for row in selected_rows:
            item = target_table.item(row, edit_column)
            if item is not None:
                item.setText(normalized_value)

        return True

    def _focused_table_widget(self):
        app_cls = getattr(QtWidgets, "QApplication", None)
        focused_widget = app_cls.focusWidget() if app_cls is not None and hasattr(app_cls, "focusWidget") else None
        table_widgets = (self.reference_table, self.part_number_table, self.header_table)

        for table_widget in table_widgets:
            if focused_widget is table_widget or table_widget.isAncestorOf(focused_widget):
                return table_widget

        for table_widget in table_widgets:
            if table_widget.hasFocus() or table_widget.viewport().hasFocus():
                return table_widget

        return None

    def select_db_file(self):
        """Select a database file and load editable values into each table."""
        try:
            if self.database_change_allowed is not None and not self.database_change_allowed():
                return
            if self.has_pending_changes() and not self._confirm_discard_changes(
                "Choose another database"
            ):
                return
            """Open a file dialog to select a database file"""
            filename, _ = QFileDialog.getOpenFileName(
                self, "Select a database file", "", "SQLite database (*.db);;All files (*)"
            )
            if filename:
                if self.database_change_allowed is not None and not self.database_change_allowed():
                    return
                if not filename.endswith(".db"):
                    filename += ".db"
                logger.info("Selected DB file: %s", filename)
                self.db_file = filename
                self.populate_tables()
                self.apply_button.setEnabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def populate_tables(self):
        """Refresh the normalization tables and reset the lazily loaded record tables."""
        try:
            # Clear existing items in table widgets and undo data
            self.reference_table.clearContents()
            self.part_number_table.clearContents()
            self.header_table.clearContents()
            self._reset_record_tables()
            self.undo_data.clear()
            self._changes_committed = False
            self._discard_confirmed = False
            self._prepare_database_for_loading()

            reference_source = ("REPORTS", "REFERENCE") if self._uses_legacy_schema() else ("report_metadata", "reference")
            sample_number_source = (
                ("REPORTS", "SAMPLE_NUMBER") if self._uses_legacy_schema() else ("report_metadata", "sample_number")
            )
            header_source = ("MEASUREMENTS", "HEADER") if self._uses_legacy_schema() else ("report_measurements", "header")

            self.populate_table(self.reference_table, self._distinct_value_counts(*reference_source))
            self.populate_table(self.part_number_table, self._distinct_value_counts(*sample_number_source))
            self.populate_table(self.header_table, self._distinct_value_counts(*header_source))

            # Report/measurement records load the first time their tab is shown.
            self._load_visible_record_table()
        except Exception as e:
            self.log_and_exit(e)

    def _prepare_database_for_loading(self):
        """Resolve current vs legacy storage before querying schema-specific tables."""
        if not self.db_file:
            return

        has_current_metadata = bool(self._source_columns("report_metadata"))
        has_legacy_reports = bool(self._source_columns("REPORTS"))
        has_legacy_measurements = bool(self._source_columns("MEASUREMENTS"))

        if has_legacy_reports and has_legacy_measurements and not has_current_metadata:
            self._storage_flavor = "legacy"
            return

        self._storage_flavor = "current"
        ensure_report_schema(self.db_file)

    def _uses_legacy_schema(self):
        return self._storage_flavor == "legacy"

    def _distinct_value_counts(self, source_name, column_name):
        available_columns = self._source_columns(source_name)
        if column_name.lower() not in available_columns:
            return []

        quoted_column = self._quote_identifier(column_name)
        quoted_source = self._quote_identifier(source_name)
        rows, _columns = execute_select_with_columns(
            self.db_file,
            f"""
            SELECT {quoted_column}, COUNT(*) AS occurrences
            FROM {quoted_source}
            WHERE {quoted_column} IS NOT NULL
            GROUP BY {quoted_column}
            ORDER BY {quoted_column};
            """,
        )
        return rows

    def populate_table(self, table, values):
        table.setRowCount(len(values))
        self.undo_data[table] = {}
        for i, value in enumerate(values):
            original_value = str(value[0])
            occurrences = value[1] if len(value) > 1 else ""
            original_item = self._record_table_item(original_value, editable=False)
            new_item = self._record_table_item(original_value, editable=True)
            count_item = self._record_table_item(occurrences, editable=False)
            new_item.setData(Qt.ItemDataRole.UserRole, original_value)
            table.setItem(i, 0, original_item)
            table.setItem(i, 1, new_item)
            table.setItem(i, 2, count_item)
            self.undo_data[table][i] = original_value

        self._configure_normalize_table(table)

    def _plan_report_records(self):
        """Return ``(specs, query)`` for the report-level rows of the overview view."""
        available_columns = self._source_columns("vw_report_overview")
        specs = self._available_specs(self.REPORT_RECORD_COLUMNS, available_columns)
        if not specs:
            return [], ""

        select_exprs = self._select_exprs_for_specs(specs)
        order_by = " ORDER BY report_id" if "report_id" in available_columns else ""
        return specs, f"SELECT {', '.join(select_exprs)} FROM vw_report_overview{order_by};"

    def _plan_measurement_records(self):
        """Return ``(specs, query)`` for measurement rows keyed by measurement id when exposed."""
        view_columns = self._source_columns("vw_measurement_export")
        use_export_view = "measurement_id" in view_columns
        if use_export_view:
            source_name = "vw_measurement_export"
            available_columns = view_columns
            specs = self._available_specs(self.MEASUREMENT_RECORD_COLUMNS, available_columns)
            order_by = " ORDER BY report_id, measurement_id"
        else:
            source_name = "report_measurements"
            available_columns = self._source_columns(source_name)
            specs = self._available_specs(self.MEASUREMENT_TABLE_COLUMNS, available_columns)
            order_by = " ORDER BY report_id, id"

        if not specs:
            return [], ""

        select_exprs = self._select_exprs_for_specs(specs)
        quoted_source = self._quote_identifier(source_name)
        return specs, f"SELECT {', '.join(select_exprs)} FROM {quoted_source}{order_by};"

    def _plan_legacy_report_records(self):
        available_columns = self._source_columns("REPORTS")
        specs = self._available_specs(self.LEGACY_REPORT_RECORD_COLUMNS, available_columns)
        if not specs:
            return [], ""

        select_exprs = self._select_exprs_for_specs(specs)
        order_by = " ORDER BY ID" if "id" in available_columns else ""
        return specs, f"SELECT {', '.join(select_exprs)} FROM REPORTS{order_by};"

    def _plan_legacy_measurement_records(self):
        available_columns = self._source_columns("MEASUREMENTS")
        specs = self._available_specs(self.LEGACY_MEASUREMENT_RECORD_COLUMNS, available_columns)
        if not specs:
            return [], ""

        select_exprs = self._select_exprs_for_specs(specs)
        order_by_parts = [column for column in ("REPORT_ID", "ID") if column.lower() in available_columns]
        order_by = f" ORDER BY {', '.join(order_by_parts)}" if order_by_parts else ""
        return specs, f"SELECT {', '.join(select_exprs)} FROM MEASUREMENTS{order_by};"

    def _record_load_plan(self, kind):
        legacy = self._uses_legacy_schema()
        if kind == "report":
            return self._plan_legacy_report_records() if legacy else self._plan_report_records()
        return self._plan_legacy_measurement_records() if legacy else self._plan_measurement_records()

    def _reset_record_tables(self):
        """Drop loaded record rows and pending fetches; the next tab visit reloads them."""
        for slot in self._record_slots:
            self._cancel_record_load(slot)
            slot.state = "idle"
            slot.view.set_record_model(RecordTableModel())
            self._last_clicked_row_by_table.pop(slot.view, None)

    def _on_main_tab_changed(self, _index):
        try:
            self._load_visible_record_table()
        except Exception as e:
            self.log_and_exit(e)

    def _load_visible_record_table(self):
        """Start loading the record table whose tab is showing, if it has not loaded yet."""
        if not self.db_file:
            return
        current_tab = self.tab_widget.currentWidget()
        for slot in self._record_slots:
            if slot.tab is current_tab and slot.state == "idle":
                self._start_record_load(slot)

    def _start_record_load(self, slot):
        specs, query = self._record_load_plan(slot.kind)
        if not specs:
            self._install_record_rows(slot, specs, RecordRows([], []))
            return

        slot.generation += 1
        slot.state = "loading"
        slot.pending_specs = specs
        slot.banner.setVisible(True)
        thread = RecordLoadThread(slot.kind, slot.generation, self.db_file, query, specs)
        thread.loaded.connect(self._on_record_rows_loaded)
        thread.failed.connect(self._on_record_load_failed)
        slot.thread = thread
        start_load_thread(thread)

    def _slot_for_kind(self, kind):
        return next((slot for slot in self._record_slots if slot.kind == kind), None)

    def _current_record_slot(self, kind, generation):
        """Return the slot a worker result belongs to, or ``None`` when it is stale."""
        slot = self._slot_for_kind(kind)
        if slot is None or generation != slot.generation or slot.state != "loading":
            return None
        return slot

    def _on_record_rows_loaded(self, kind, generation, rows):
        slot = self._current_record_slot(kind, generation)
        if slot is None:
            return
        try:
            slot.thread = None
            self._install_record_rows(slot, slot.pending_specs or [], rows)
        except Exception as e:
            self.log_and_exit(e)

    def _on_record_load_failed(self, kind, generation, error):
        slot = self._current_record_slot(kind, generation)
        if slot is None:
            return
        slot.thread = None
        slot.state = "idle"
        slot.banner.setVisible(False)
        self.log_and_exit(error)

    def _cancel_record_load(self, slot, *, wait_ms=3000):
        """Ignore any in-flight fetch for ``slot`` and give its worker a bounded time to stop."""
        slot.generation += 1
        thread, slot.thread = slot.thread, None
        if slot.state == "loading":
            slot.state = "idle"
        slot.banner.setVisible(False)
        cancel_load_thread(thread, wait_ms=wait_ms)

    def ensure_record_tables_loaded(self):
        """Load every record table that is still empty and wait for the rows (blocking)."""
        try:
            if not self.db_file:
                return
            for slot in self._record_slots:
                if slot.state != "loaded":
                    self._cancel_record_load(slot)
                    self._load_record_table_now(slot)
        except Exception as e:
            self.log_and_exit(e)

    def _load_record_table_now(self, slot):
        specs, query = self._record_load_plan(slot.kind)
        rows = load_record_rows(self.db_file, query, specs) if specs else RecordRows([], [])
        self._install_record_rows(slot, specs, rows)

    def _install_record_rows(self, slot, specs, record_rows):
        model = RecordTableModel(specs, record_rows.rows, record_rows.haystack)
        model.set_filter_text(slot.filter_edit.text())
        slot.view.set_record_model(model)
        self._configure_record_table(slot.view, specs)
        self._last_clicked_row_by_table.pop(slot.view, None)
        slot.state = "loaded"
        slot.pending_specs = None
        slot.banner.setVisible(False)

    def _apply_record_filter(self, slot):
        try:
            slot.filter_timer.stop()
            model = slot.view.model()
            if model is not None:
                model.set_filter_text(slot.filter_edit.text())
                self._last_clicked_row_by_table.pop(slot.view, None)
        except Exception as e:
            self.log_and_exit(e)

    def flush_record_filters(self):
        """Apply any record filter still waiting for its debounce interval."""
        for slot in self._record_slots:
            if slot.filter_timer.isActive():
                self._apply_record_filter(slot)

    def _shutdown_record_loading(self):
        for slot in getattr(self, "_record_slots", ()):
            slot.filter_timer.stop()
            self._cancel_record_load(slot)

    def _source_columns(self, source_name):
        try:
            quoted_source = self._quote_identifier(source_name)
            _rows, columns = execute_select_with_columns(
                self.db_file,
                f"SELECT * FROM {quoted_source} LIMIT 0;",
            )
            return {column.lower() for column in columns}
        except sqlite3.Error:
            return set()

    def _available_specs(self, specs, available_columns):
        return [spec for spec in specs if spec["source"].lower() in available_columns]

    def _select_exprs_for_specs(self, specs):
        expressions = []
        for spec in specs:
            source = spec["source"]
            field = spec["field"]
            quoted_source = self._quote_identifier(source)
            if source.lower() == field.lower():
                expressions.append(quoted_source)
            else:
                expressions.append(f"{quoted_source} AS {self._quote_identifier(field)}")
        return expressions

    @staticmethod
    def _quote_identifier(identifier):
        return quote_identifier(identifier)

    @staticmethod
    def _configure_record_table(table, specs):
        key_columns = tuple(index for index, spec in enumerate(specs) if spec.get("key"))
        preferred_stretch_fields = (
            "comment",
            "description",
            "characteristic_name",
            "feature_label",
            "section_name",
            "header",
            "reference",
            "part_name",
        )
        stretch_column = 0
        for candidate_field in preferred_stretch_fields:
            for index, spec in enumerate(specs):
                if spec.get("field") == candidate_field:
                    stretch_column = index
                    break
            else:
                continue
            break
        configure_table(
            table,
            stretch_column=stretch_column,
            resize_to_contents=key_columns,
            min_height=260,
        )

    def _record_table_item(self, value, *, editable):
        item = QTableWidgetItem(self._display_value(value))
        item.setData(Qt.ItemDataRole.UserRole, value)
        if not editable and hasattr(item, "flags") and hasattr(item, "setFlags"):
            item_flag_enum = getattr(Qt, "ItemFlag", None)
            item_is_editable = getattr(item_flag_enum, "ItemIsEditable", None)
            if item_is_editable is not None:
                item.setFlags(item.flags() & ~item_is_editable)
        return item

    @staticmethod
    def _display_value(value):
        return display_value(value)

    def _filter_table_rows(self, table, text):
        normalized_text = str(text).lower()
        for row in range(table.rowCount()):
            row_matches = not normalized_text
            for column in range(table.columnCount()):
                item = table.item(row, column)
                if item is not None and normalized_text in item.text().lower():
                    row_matches = True
                    break
            if hasattr(table, "setRowHidden"):
                table.setRowHidden(row, not row_matches)

    def confirm_and_apply_changes(self):
        """Show pending edits and apply them only after user confirmation."""
        try:
            modifications_text = self.collect_modifications()
            confirmation_dialog = QMessageBox(self)
            confirmation_dialog.setIcon(QMessageBox.Icon.Question)
            confirmation_dialog.setText(
                "The following modifications will be applied:\n\n" + modifications_text
            )
            confirmation_dialog.setWindowTitle("Confirm changes")
            confirmation_dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)

            if confirmation_dialog.exec() == QMessageBox.StandardButton.Ok:
                self.apply_changes()
        except Exception as e:
            self.log_and_exit(e)

    def collect_modifications(self):
        """Collect a user-facing summary of all modified rows across tables."""
        modifications = []

        # Collect modifications for reference table
        reference_modifications = self.collect_table_modifications(self.reference_table, "References")
        if reference_modifications:
            modifications.append(reference_modifications)

        # Collect modifications for part number table
        part_number_modifications = self.collect_table_modifications(self.part_number_table, "Part numbers")
        if part_number_modifications:
            modifications.append(part_number_modifications)

        # Collect modifications for header table
        header_modifications = self.collect_table_modifications(self.header_table, "Headers")
        if header_modifications:
            modifications.append(header_modifications)

        report_modifications = self.collect_record_table_modifications(
            self.report_records_table,
            "Report records",
            "report_id",
        )
        if report_modifications:
            modifications.append(report_modifications)

        measurement_modifications = self.collect_record_table_modifications(
            self.measurement_records_table,
            "Measurement rows",
            "measurement_id",
        )
        if measurement_modifications:
            modifications.append(measurement_modifications)

        return "\n".join(modifications)

    @staticmethod
    def _summary_value(value):
        if value is None:
            return "NULL"
        text = str(value)
        return f'"{text}"'

    def collect_table_modifications(self, table, table_name):
        """Build a per-table change list using original values stored in UserRole."""
        lines = []
        edit_column = self._normalize_table_edit_column(table)

        for i in range(table.rowCount()):
            item = table.item(i, edit_column)
            if item is None:
                continue
            old_value = item.data(Qt.ItemDataRole.UserRole)
            new_value = str(item.text())
            occurrences_item = table.item(i, 2) if table.columnCount() > 2 else None
            occurrence_count = occurrences_item.text() if occurrences_item is not None else ""

            if old_value != new_value:
                line = (
                    f"{table_name}: {self._summary_value(old_value)} -> "
                    f"{self._summary_value(new_value)}"
                )
                if occurrence_count:
                    line += f" (occurrences: {occurrence_count})"
                lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def _record_model(table):
        """Return the record model behind a record table, or ``None`` when nothing is loaded."""
        model = table.model() if hasattr(table, "model") else None
        return model if isinstance(model, RecordTableModel) else None

    def collect_record_table_modifications(self, table, table_name, key_field):
        """Build a summary of changed targeted record fields."""
        updates = self.collect_record_table_updates(table, key_field)
        if not updates:
            return ""

        model = self._record_model(table)
        specs = model.specs
        editable_fields = {spec["field"]: spec for spec in specs if spec.get("editable")}
        key_column = self._column_index_for_field(specs, key_field)
        first_rows = model.first_rows_by_key(
            key_column, {record_id for record_id, _fields in updates}, self._coerce_record_id
        )

        lines = []
        for record_id, fields in updates:
            for field_name, new_value in fields.items():
                spec = editable_fields.get(field_name)
                if spec is None:
                    continue
                old_value = self._original_value_for_record_field(model, first_rows, record_id, field_name)
                lines.append(
                    f"{table_name}.{spec['label']}: "
                    f"{self._summary_value(old_value)} -> {self._summary_value(new_value)} "
                    f"({key_field.upper()}={record_id})"
                )

        if not lines:
            return ""
        return "\n".join(lines)

    def _original_value_for_record_field(self, model, first_rows, record_id, field_name):
        value_column = self._column_index_for_field(model.specs, field_name)
        source_row = first_rows.get(record_id)
        if value_column is None or source_row is None:
            return None
        return model.original_value(source_row, value_column)

    def apply_changes(self):
        """Collect table edits and delegate persistence to the report edit service."""
        try:
            normalization_changes = {
                "reference": self.collect_normalization_value_changes(self.reference_table),
                "sample_number": self.collect_normalization_value_changes(self.part_number_table),
                "header": self.collect_normalization_value_changes(self.header_table),
            }
            report_updates = self.collect_report_record_updates()
            measurement_updates = self.collect_measurement_record_updates()

            if not any(normalization_changes.values()) and not report_updates and not measurement_updates:
                QMessageBox.information(self, "No changes", "No changes were detected.")
                return

            self._create_report_edit_service().apply_changes(
                storage_flavor=self._storage_flavor,
                normalization_changes=normalization_changes,
                report_updates=report_updates,
                measurement_updates=measurement_updates,
            )

            # Display a message box with confirmation
            QMessageBox.information(self, "Changes applied", "Changes have been applied successfully.")

            # Close the dialog
            self._changes_committed = True
            self.close()
        except Exception as e:
            self.log_and_exit(e)

    def _apply_update_statements(self, cursor, statements):
        ReportEditService.apply_update_statements(cursor, statements)

    def build_update_statements(self, table_widget, table_name, column_name):
        """Compatibility wrapper for normalization statement tests and callers."""
        return ReportEditService.build_value_update_statements(
            table_name,
            column_name,
            ModifyDB.collect_normalization_value_changes(table_widget),
        )

    @staticmethod
    def collect_normalization_value_changes(table_widget):
        """Collect changed normalized values without owning persistence SQL."""
        changes = []
        edit_column = ModifyDB._normalize_table_edit_column(table_widget)
        for row in range(table_widget.rowCount()):
            item = table_widget.item(row, edit_column)
            if item is None:
                continue
            new_value = str(item.text())
            old_value = str(item.data(Qt.ItemDataRole.UserRole))

            if new_value != old_value:
                changes.append((new_value, old_value))

        return changes

    def _build_legacy_record_update_statements(self, report_updates, measurement_updates):
        return ReportEditService.build_legacy_record_update_statements(
            report_updates,
            measurement_updates,
        )

    def _build_legacy_update_statements(self, table_name, key_column, field_columns, updates):
        return ReportEditService._build_legacy_update_statements(
            table_name,
            key_column,
            field_columns,
            updates,
        )

    @staticmethod
    def _normalize_table_edit_column(table_widget):
        try:
            return 1 if table_widget.columnCount() > 1 else 0
        except AttributeError:
            return 0

    def collect_report_record_updates(self):
        return self.collect_record_table_updates(self.report_records_table, "report_id")

    def collect_measurement_record_updates(self):
        return self.collect_record_table_updates(self.measurement_records_table, "measurement_id")

    def collect_record_table_updates(self, table, key_field):
        """Collect changed editable cells as targeted repository update payloads."""
        model = self._record_model(table)
        if model is None:
            return []
        specs = model.specs
        key_column = self._column_index_for_field(specs, key_field)
        if key_column is None:
            return []

        updates = []
        for source_row, edits in model.edited_rows():
            record_id = self._coerce_record_id(model.original_text(source_row, key_column))
            if record_id is None:
                continue

            fields = {}
            for column_index, new_text in edits.items():
                spec = specs[column_index]
                if not spec.get("editable") or new_text == model.original_text(source_row, column_index):
                    continue
                fields[spec["field"]] = self._coerce_record_value(new_text, spec.get("value_type"))

            if fields:
                updates.append((record_id, fields))

        return updates

    @staticmethod
    def _column_index_for_field(specs, field_name):
        for index, spec in enumerate(specs):
            if spec["field"] == field_name:
                return index
        return None

    @staticmethod
    def _coerce_record_id(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_record_value(value, value_type):
        if value == "":
            return None
        if value_type == "float":
            try:
                return float(value)
            except (TypeError, ValueError):
                return value
        return value

    def _create_report_repository(self):
        return ReportRepository(self.db_file)

    def _create_report_edit_service(self):
        return ReportEditService(
            self.db_file,
            repository_factory=lambda _database: self._create_report_repository(),
        )

    def _validate_record_update_methods(self, repository, report_updates, measurement_updates):
        ReportEditService.validate_record_update_methods(
            repository,
            report_updates,
            measurement_updates,
        )

    def apply_record_updates(self, repository, report_updates, measurement_updates):
        ReportEditService.apply_record_updates(
            repository,
            report_updates,
            measurement_updates,
        )

    def undo_last_change(self):
        try:
            if self.undo_data:
                for table, changes in self.undo_data.items():
                    if changes:
                        # Get the current row index
                        current_row_index = table.currentRow()

                        # Check if there's a change at the current row
                        if current_row_index in changes:
                            original_value = changes[current_row_index]
                            # Set the current change back to its original value
                            table.item(current_row_index, 0).setText(original_value)
                            # Remove the current change from undo_data
                            del changes[current_row_index]

                QMessageBox.information(self, "Undo", "Last change has been undone.")
        except Exception as e:
            self.log_and_exit(e)

    def cancel_changes(self):
        self.close()

    def has_pending_changes(self) -> bool:
        """Return whether the editor contains unapplied table changes."""

        if not hasattr(self, "reference_table"):
            return False
        return bool(self.collect_modifications().strip())

    def _confirm_discard_changes(self, action: str = "Close editor") -> bool:
        choice = QMessageBox.question(
            self,
            "Unapplied database changes",
            f"{action} and discard the unapplied table changes?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return choice == QMessageBox.StandardButton.Discard

    def done(self, result) -> None:
        """Stop record fetches before the dialog hides so no worker outlives its owner."""

        self._shutdown_record_loading()
        super().done(result)

    def reject(self) -> None:
        """Route Escape through the same dirty-state guard as the Close button."""

        if (
            not self._changes_committed
            and not self._discard_confirmed
            and self.has_pending_changes()
            and not self._confirm_discard_changes()
        ):
            return
        self._discard_confirmed = True
        super().reject()

    def closeEvent(self, event) -> None:
        if (
            not self._changes_committed
            and not self._discard_confirmed
            and self.has_pending_changes()
            and not self._confirm_discard_changes()
        ):
            event.ignore()
            return
        self._discard_confirmed = True
        super().closeEvent(event)

    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
