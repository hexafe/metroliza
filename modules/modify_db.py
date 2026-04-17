"""Dialog for bulk and targeted metadata edits in the SQLite database."""

from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
import PyQt6.QtCore as QtCore
from PyQt6.QtCore import Qt
import PyQt6.QtWidgets as QtWidgets
import logging
from modules.custom_logger import CustomLogger
from modules.db import execute_select_with_columns, run_transaction_with_retry
from modules.help_menu import attach_help_menu_to_layout
from modules.report_repository import ReportRepository


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

    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        self.setWindowTitle("Modify database")
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 1100, 650)
        self.setModal(True)

        self.db_file = db_file
        self.undo_data = {}
        self._last_clicked_row_by_table = {}
        self._record_specs_by_table = {}

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
            if self.db_file:
                self.populate_tables()
        except Exception as e:
            self.log_and_exit(e)

    def create_widgets(self):
        try:
            # Create table widgets for REFERENCE, PART NUMBER, and HEADER
            self.reference_table = QTableWidget()
            self.reference_table.setSelectionMode(self._multi_selection_mode())
            self.reference_table.setSelectionBehavior(self._select_rows_behavior())
            self.reference_table.setColumnCount(1)
            self.reference_table.setHorizontalHeaderLabels(["REFERENCE"])
            self.reference_table.setColumnWidth(0, 200)

            self.part_number_table = QTableWidget()
            self.part_number_table.setSelectionMode(self._multi_selection_mode())
            self.part_number_table.setSelectionBehavior(self._select_rows_behavior())
            self.part_number_table.setColumnCount(1)
            self.part_number_table.setHorizontalHeaderLabels(["SAMPLE NUMBER"])
            self.part_number_table.setColumnWidth(0, 200)

            self.header_table = QTableWidget()
            self.header_table.setSelectionMode(self._multi_selection_mode())
            self.header_table.setSelectionBehavior(self._select_rows_behavior())
            self.header_table.setColumnCount(1)
            self.header_table.setHorizontalHeaderLabels(["HEADER"])
            self.header_table.setColumnWidth(0, 200)

            self.tab_widget = QtWidgets.QTabWidget()
            self.normalize_tab = QtWidgets.QWidget()
            self.report_records_tab = QtWidgets.QWidget()
            self.measurement_rows_tab = QtWidgets.QWidget()

            self.report_filter_edit = QtWidgets.QLineEdit()
            self.report_filter_edit.setPlaceholderText("Filter report records")
            self.report_records_table = QTableWidget()
            self.report_records_table.setSelectionMode(self._multi_selection_mode())
            self.report_records_table.setSelectionBehavior(self._select_rows_behavior())

            self.measurement_filter_edit = QtWidgets.QLineEdit()
            self.measurement_filter_edit.setPlaceholderText("Filter measurement rows")
            self.measurement_records_table = QTableWidget()
            self.measurement_records_table.setSelectionMode(self._multi_selection_mode())
            self.measurement_records_table.setSelectionBehavior(self._select_rows_behavior())

            # Create buttons for Select DB file, Apply changes, Undo, and Cancel
            self.select_db_button = QPushButton("Select DB file")
            self.apply_button = QPushButton("Apply changes")
            if not self.db_file:
                self.apply_button.setEnabled(False)
            self.undo_button = QPushButton("Undo last change")
            self.cancel_button = QPushButton("Cancel")
        except Exception as e:
            self.log_and_exit(e)

    def arrange_layout(self):
        try:
            layout = QGridLayout(self)
            attach_help_menu_to_layout(layout, self, [("Modify Database manual", 'modify_database')])

            normalize_layout = QGridLayout(self.normalize_tab)
            normalize_layout.addWidget(self.reference_table, 0, 0)
            normalize_layout.addWidget(self.part_number_table, 0, 1)
            normalize_layout.addWidget(self.header_table, 0, 2)

            report_layout = QtWidgets.QVBoxLayout(self.report_records_tab)
            report_layout.addWidget(self.report_filter_edit)
            report_layout.addWidget(self.report_records_table)

            measurement_layout = QtWidgets.QVBoxLayout(self.measurement_rows_tab)
            measurement_layout.addWidget(self.measurement_filter_edit)
            measurement_layout.addWidget(self.measurement_records_table)

            self.tab_widget.addTab(self.normalize_tab, "Normalize values")
            self.tab_widget.addTab(self.report_records_tab, "Report records")
            self.tab_widget.addTab(self.measurement_rows_tab, "Measurement rows")

            layout.addWidget(self.tab_widget, 0, 0, 1, 3)
            layout.addWidget(self.select_db_button, 1, 0, 1, 3)
            layout.addWidget(self.apply_button, 2, 0, 1, 1)
            # layout.addWidget(self.undo_button, 2, 1, 1, 1) #to be re-added after undo functionality correction
            layout.addWidget(self.cancel_button, 2, 2, 1, 1)

            self.show()
        except Exception as e:
            self.log_and_exit(e)

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
            self.report_filter_edit.textChanged.connect(
                lambda text: self._filter_table_rows(self.report_records_table, text)
            )
            self.measurement_filter_edit.textChanged.connect(
                lambda text: self._filter_table_rows(self.measurement_records_table, text)
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

        current_item = target_table.currentItem()
        suggested_value = current_item.text() if current_item is not None else ""
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
            item = target_table.item(row, 0)
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
            """Open a file dialog to select a database file"""
            filename, _ = QFileDialog.getOpenFileName(
                self, "Select a database file", "", "SQLite database (*.db);;All files (*)"
            )
            if filename:
                if not filename.endswith(".db"):
                    filename += ".db"
                logger.info("Selected DB file: %s", filename)
                self.db_file = filename
                self.populate_tables()
                self.apply_button.setEnabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def populate_tables(self):
        """Refresh all editor tables from the currently selected database."""
        try:
            # Clear existing items in table widgets and undo data
            self.reference_table.clearContents()
            self.part_number_table.clearContents()
            self.header_table.clearContents()
            self.report_records_table.clearContents()
            self.measurement_records_table.clearContents()
            self.undo_data.clear()
            self._record_specs_by_table.clear()

            reference_values, _ = execute_select_with_columns(
                self.db_file,
                "SELECT DISTINCT reference FROM report_metadata WHERE reference IS NOT NULL ORDER BY reference;",
            )
            self.populate_table(self.reference_table, reference_values)

            part_number_values, _ = execute_select_with_columns(
                self.db_file,
                "SELECT DISTINCT sample_number FROM report_metadata WHERE sample_number IS NOT NULL ORDER BY sample_number;",
            )
            self.populate_table(self.part_number_table, part_number_values)

            header_values, _ = execute_select_with_columns(
                self.db_file,
                "SELECT DISTINCT header FROM report_measurements WHERE header IS NOT NULL ORDER BY header;",
            )
            self.populate_table(self.header_table, header_values)
            self.populate_report_records_table()
            self.populate_measurement_records_table()
        except Exception as e:
            self.log_and_exit(e)

    def populate_table(self, table, values):
        table.setRowCount(len(values))
        self.undo_data[table] = {}
        for i, value in enumerate(values):
            item = QTableWidgetItem(str(value[0]))
            item.setData(Qt.ItemDataRole.UserRole, str(value[0]))
            table.setItem(i, 0, item)
            self.undo_data[table][i] = str(value[0])

    def populate_report_records_table(self):
        """Load report-level rows from the overview view into an editable table."""
        available_columns = self._source_columns("vw_report_overview")
        specs = self._available_specs(self.REPORT_RECORD_COLUMNS, available_columns)
        if not specs:
            self._populate_record_table(self.report_records_table, [], [], [])
            return

        select_exprs = self._select_exprs_for_specs(specs)
        order_by = " ORDER BY report_id" if "report_id" in available_columns else ""
        rows, columns = execute_select_with_columns(
            self.db_file,
            f"SELECT {', '.join(select_exprs)} FROM vw_report_overview{order_by};",
        )
        self._populate_record_table(self.report_records_table, specs, rows, columns)

    def populate_measurement_records_table(self):
        """Load measurement rows keyed by measurement id when the source exposes it."""
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
            self._populate_record_table(self.measurement_records_table, [], [], [])
            return

        select_exprs = self._select_exprs_for_specs(specs)
        rows, columns = execute_select_with_columns(
            self.db_file,
            f"SELECT {', '.join(select_exprs)} FROM {source_name}{order_by};",
        )
        self._populate_record_table(self.measurement_records_table, specs, rows, columns)

    def _source_columns(self, source_name):
        try:
            _rows, columns = execute_select_with_columns(self.db_file, f"SELECT * FROM {source_name} LIMIT 0;")
            return {column.lower() for column in columns}
        except Exception:
            return set()

    def _available_specs(self, specs, available_columns):
        return [spec for spec in specs if spec["source"].lower() in available_columns]

    def _select_exprs_for_specs(self, specs):
        expressions = []
        for spec in specs:
            source = spec["source"]
            field = spec["field"]
            if source == field:
                expressions.append(source)
            else:
                expressions.append(f"{source} AS {field}")
        return expressions

    def _populate_record_table(self, table, specs, rows, columns):
        table.setColumnCount(len(specs))
        table.setHorizontalHeaderLabels([spec["label"] for spec in specs])
        table.setRowCount(len(rows))
        self._record_specs_by_table[table] = list(specs)

        column_indexes = {column.lower(): index for index, column in enumerate(columns)}
        for row_index, row_values in enumerate(rows):
            for column_index, spec in enumerate(specs):
                value_index = column_indexes.get(spec["field"].lower())
                value = row_values[value_index] if value_index is not None else None
                item = self._record_table_item(value, editable=spec.get("editable", False))
                table.setItem(row_index, column_index, item)

        if hasattr(table, "resizeColumnsToContents"):
            table.resizeColumnsToContents()

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
        return "" if value is None else str(value)

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
        modifications_text = ""

        # Collect modifications for reference table
        reference_modifications = self.collect_table_modifications(self.reference_table, "References")
        if reference_modifications:
            modifications_text += reference_modifications + "\n"

        # Collect modifications for part number table
        part_number_modifications = self.collect_table_modifications(self.part_number_table, "Part numbers")
        if part_number_modifications:
            modifications_text += part_number_modifications + "\n"

        # Collect modifications for header table
        header_modifications = self.collect_table_modifications(self.header_table, "Headers")
        if header_modifications:
            modifications_text += header_modifications + "\n"

        report_modifications = self.collect_record_table_modifications(
            self.report_records_table,
            "Report records",
            "report_id",
        )
        if report_modifications:
            modifications_text += report_modifications + "\n"

        measurement_modifications = self.collect_record_table_modifications(
            self.measurement_records_table,
            "Measurement rows",
            "measurement_id",
        )
        if measurement_modifications:
            modifications_text += measurement_modifications + "\n"

        return modifications_text

    def collect_table_modifications(self, table, table_name):
        """Build a per-table change list using original values stored in UserRole."""
        modifications_text = ""

        for i in range(table.rowCount()):
            old_value = str(table.item(i, 0).data(Qt.ItemDataRole.UserRole))
            new_value = str(table.item(i, 0).text())

            if old_value != new_value:
                modifications_text += f"{old_value} → {new_value}\n"

        if modifications_text:
            modifications_text = f"{table_name}:\n{modifications_text}"

        return modifications_text

    def collect_record_table_modifications(self, table, table_name, key_field):
        """Build a summary of changed targeted record fields."""
        updates = self.collect_record_table_updates(table, key_field)
        if not updates:
            return ""

        lines = []
        specs = self._record_specs_by_table.get(table, [])
        editable_specs = [spec for spec in specs if spec.get("editable")]
        for record_id, fields in updates:
            for field_name, new_value in fields.items():
                spec = next((candidate for candidate in editable_specs if candidate["field"] == field_name), None)
                if spec is None:
                    continue
                old_value = self._original_value_for_record_field(table, key_field, record_id, field_name)
                lines.append(
                    f"{key_field.upper()} {record_id} {spec['label']}: "
                    f"{self._display_value(old_value)} → {self._display_value(new_value)}"
                )

        if not lines:
            return ""
        return f"{table_name}:\n" + "\n".join(lines) + "\n"

    def _original_value_for_record_field(self, table, key_field, record_id, field_name):
        specs = self._record_specs_by_table.get(table, [])
        key_column = self._column_index_for_field(specs, key_field)
        value_column = self._column_index_for_field(specs, field_name)
        if key_column is None or value_column is None:
            return None

        for row in range(table.rowCount()):
            key_item = table.item(row, key_column)
            if key_item is None:
                continue
            if self._coerce_record_id(key_item.text()) != record_id:
                continue
            item = table.item(row, value_column)
            return item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return None

    def apply_changes(self):
        """Apply collected UPDATE statements in a single retried transaction."""
        try:
            statements = []
            statements.extend(self.build_update_statements(self.reference_table, "report_metadata", "reference"))
            statements.extend(self.build_update_statements(self.part_number_table, "report_metadata", "sample_number"))
            statements.extend(self.build_update_statements(self.header_table, "report_measurements", "header"))
            report_updates = self.collect_report_record_updates()
            measurement_updates = self.collect_measurement_record_updates()

            if not statements and not report_updates and not measurement_updates:
                QMessageBox.information(self, "No changes", "No changes were detected.")
                return

            repository = None
            if report_updates or measurement_updates:
                repository = self._create_report_repository()
                self._validate_record_update_methods(repository, report_updates, measurement_updates)

            if statements:
                run_transaction_with_retry(
                    self.db_file,
                    lambda cursor: self._apply_update_statements(cursor, statements),
                )

            if report_updates or measurement_updates:
                self.apply_record_updates(repository, report_updates, measurement_updates)

            # Display a message box with confirmation
            QMessageBox.information(self, "Changes applied", "Changes have been applied successfully.")

            # Close the dialog
            self.close()
        except Exception as e:
            self.log_and_exit(e)


    def _apply_update_statements(self, cursor, statements):
        for query, params in statements:
            cursor.execute(query, params)

    def build_update_statements(self, table_widget, table_name, column_name):
        """Build SQL UPDATE statements for rows modified in the given table."""
        statements = []
        for row in range(table_widget.rowCount()):
            new_value = str(table_widget.item(row, 0).text())
            old_value = str(table_widget.item(row, 0).data(Qt.ItemDataRole.UserRole))

            if new_value != old_value:
                query = f"UPDATE {table_name} SET {column_name} = ? WHERE {column_name} = ?"
                statements.append((query, (new_value, old_value)))

        return statements

    def collect_report_record_updates(self):
        return self.collect_record_table_updates(self.report_records_table, "report_id")

    def collect_measurement_record_updates(self):
        return self.collect_record_table_updates(self.measurement_records_table, "measurement_id")

    def collect_record_table_updates(self, table, key_field):
        """Collect changed editable cells as targeted repository update payloads."""
        specs = self._record_specs_by_table.get(table, [])
        key_column = self._column_index_for_field(specs, key_field)
        if key_column is None:
            return []

        updates = []
        for row in range(table.rowCount()):
            key_item = table.item(row, key_column)
            if key_item is None:
                continue
            record_id = self._coerce_record_id(key_item.text())
            if record_id is None:
                continue

            fields = {}
            for column_index, spec in enumerate(specs):
                if not spec.get("editable"):
                    continue
                item = table.item(row, column_index)
                if item is None:
                    continue
                original_value = item.data(Qt.ItemDataRole.UserRole)
                new_text = str(item.text())
                if new_text == self._display_value(original_value):
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

    def _validate_record_update_methods(self, repository, report_updates, measurement_updates):
        missing_methods = []
        if report_updates and not hasattr(repository, "update_report_metadata_fields"):
            missing_methods.append("update_report_metadata_fields")
        if measurement_updates and not hasattr(repository, "update_measurement_fields"):
            missing_methods.append("update_measurement_fields")
        if missing_methods:
            raise RuntimeError(
                "ReportRepository does not provide required targeted update API(s): "
                + ", ".join(missing_methods)
            )

    def apply_record_updates(self, repository, report_updates, measurement_updates):
        self._validate_record_update_methods(repository, report_updates, measurement_updates)
        for report_id, fields in report_updates:
            repository.update_report_metadata_fields(report_id, fields)
        for measurement_id, fields in measurement_updates:
            repository.update_measurement_fields(measurement_id, fields)

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

    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
