"""Dialog for bulk editing selected reference fields in the SQLite database."""

from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QItemSelection, QItemSelectionModel
import PyQt6.QtWidgets as QtWidgets
import logging
from modules.CustomLogger import CustomLogger
from modules.db import execute_select_with_columns, run_transaction_with_retry
from modules import ui_theme_tokens


logger = logging.getLogger(__name__)


class ModifyDB(QDialog):
    """Provide table-based editing for key text fields in REPORTS/MEASUREMENTS.

    The dialog loads distinct values from the database, lets users update them
    in-place, and commits all detected changes in one transaction.
    """

    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        self.setWindowTitle("Review and Rename Data")
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 640, 480)
        self.setModal(True)

        self.db_file = db_file
        self.undo_data = {}
        self._last_clicked_row_by_table = {}

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

    def setup_ui(self):
        try:
            self.create_widgets()
            self.arrange_layout()
            self.connect_signals()
        except Exception as e:
            self.log_and_exit(e)

    def create_widgets(self):
        try:
            label_cls = getattr(QtWidgets, "QLabel", None)
            self.dialog_title_label = label_cls("Review and Rename Data") if label_cls is not None else None
            if self.dialog_title_label is not None and hasattr(self.dialog_title_label, "setStyleSheet"):
                self.dialog_title_label.setStyleSheet(ui_theme_tokens.typography_style("page", ui_theme_tokens.COLOR_TEXT_PRIMARY))

            subtitle_text = (
                "Review distinct values across Reference, Sample number, and Header, then rename as needed. "
                "You can batch-rename selected rows with Enter and confirm all changes before they are saved."
            )
            self.dialog_subtitle_label = label_cls(subtitle_text) if label_cls is not None else None
            if self.dialog_subtitle_label is not None and hasattr(self.dialog_subtitle_label, "setWordWrap"):
                self.dialog_subtitle_label.setWordWrap(True)

            # Create table widgets for REFERENCE, PART NUMBER, and HEADER
            self.reference_table = QTableWidget()
            self.reference_table.setSelectionMode(self._multi_selection_mode())
            self.reference_table.setSelectionBehavior(self._select_rows_behavior())
            self.reference_table.setColumnCount(1)
            self.reference_table.setHorizontalHeaderLabels(["Reference"])
            self.reference_table.setColumnWidth(0, 200)

            self.part_number_table = QTableWidget()
            self.part_number_table.setSelectionMode(self._multi_selection_mode())
            self.part_number_table.setSelectionBehavior(self._select_rows_behavior())
            self.part_number_table.setColumnCount(1)
            self.part_number_table.setHorizontalHeaderLabels(["Sample number"])
            self.part_number_table.setColumnWidth(0, 200)

            self.header_table = QTableWidget()
            self.header_table.setSelectionMode(self._multi_selection_mode())
            self.header_table.setSelectionBehavior(self._select_rows_behavior())
            self.header_table.setColumnCount(1)
            self.header_table.setHorizontalHeaderLabels(["Header"])
            self.header_table.setColumnWidth(0, 200)

            helper_text = "Tip: Choose a database file first to load values for review."
            self.helper_text_label = label_cls(helper_text) if label_cls is not None else None
            if self.helper_text_label is not None and hasattr(self.helper_text_label, "setWordWrap"):
                self.helper_text_label.setWordWrap(True)

            # Create buttons for Select DB file, Apply changes, Undo, and Cancel
            self.select_db_button = QPushButton("Choose database file")
            self.apply_button = QPushButton("Review and apply changes")
            if not self.db_file:
                self.apply_button.setEnabled(False)
            self.undo_button = QPushButton("Undo last change")
            self.cancel_button = QPushButton("Close")
            self._apply_action_button_styles()
        except Exception as e:
            self.log_and_exit(e)

    def arrange_layout(self):
        try:
            layout = QGridLayout(self)
            layout.setHorizontalSpacing(ui_theme_tokens.SPACE_12)
            layout.setVerticalSpacing(ui_theme_tokens.SPACE_8)

            # Add table widgets and buttons to the layout
            row_offset = 0
            if self.dialog_title_label is not None:
                layout.addWidget(self.dialog_title_label, row_offset, 0, 1, 3)
                row_offset += 1
            if self.dialog_subtitle_label is not None:
                layout.addWidget(self.dialog_subtitle_label, row_offset, 0, 1, 3)
                row_offset += 1

            layout.addWidget(self.reference_table, row_offset, 0)
            layout.addWidget(self.part_number_table, row_offset, 1)
            layout.addWidget(self.header_table, row_offset, 2)
            row_offset += 1
            if self.helper_text_label is not None:
                layout.addWidget(self.helper_text_label, row_offset, 0, 1, 3)
                row_offset += 1
            layout.addWidget(self.select_db_button, row_offset, 0, 1, 3)
            row_offset += 1
            layout.addWidget(self.apply_button, row_offset, 0, 1, 1)
            # layout.addWidget(self.undo_button, 3, 1, 1, 1) #to be re-added after undo functionality correction
            layout.addWidget(self.cancel_button, row_offset, 2, 1, 1)

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
        except Exception as e:
            self.log_and_exit(e)

    def _apply_action_button_styles(self):
        self.apply_button.setStyleSheet(ui_theme_tokens.button_style('primary'))
        self.select_db_button.setStyleSheet(ui_theme_tokens.button_style('secondary'))
        self.undo_button.setStyleSheet(ui_theme_tokens.button_style('tertiary'))
        self.cancel_button.setStyleSheet(ui_theme_tokens.button_style('secondary'))

        table_style = ui_theme_tokens.table_style(cell_padding=ui_theme_tokens.SPACE_8)
        self.reference_table.setStyleSheet(table_style)
        self.part_number_table.setStyleSheet(table_style)
        self.header_table.setStyleSheet(table_style)

    def _connect_shift_range_for_table(self, table_widget):
        table_widget.cellPressed.connect(
            lambda row, column, tw=table_widget: self._handle_table_cell_pressed(tw, row, column)
        )

    def _handle_table_cell_pressed(self, table_widget, row, column):
        del column
        previous_row = self._last_clicked_row_by_table.get(table_widget)
        is_shift_pressed = bool(self._keyboard_modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if is_shift_pressed and previous_row is not None:
            start_row = min(previous_row, row)
            end_row = max(previous_row, row)
            selection_model = table_widget.selectionModel()
            table_model = table_widget.model()
            last_column = max(table_widget.columnCount() - 1, 0)

            selection = QItemSelection(
                table_model.index(start_row, 0),
                table_model.index(end_row, last_column),
            )
            selection_flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
            selection_model.select(selection, selection_flags)
            selection_model.select(table_model.index(previous_row, 0), selection_flags)
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
            self.undo_data.clear()

            reference_values, _ = execute_select_with_columns(
                self.db_file,
                "SELECT DISTINCT REFERENCE FROM REPORTS;",
            )
            self.populate_table(self.reference_table, reference_values)

            part_number_values, _ = execute_select_with_columns(
                self.db_file,
                "SELECT DISTINCT SAMPLE_NUMBER FROM REPORTS;",
            )
            self.populate_table(self.part_number_table, part_number_values)

            header_values, _ = execute_select_with_columns(
                self.db_file,
                "SELECT DISTINCT HEADER FROM MEASUREMENTS;",
            )
            self.populate_table(self.header_table, header_values)
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

    def apply_changes(self):
        """Apply collected UPDATE statements in a single retried transaction."""
        try:
            statements = []
            statements.extend(self.build_update_statements(self.reference_table, "REPORTS", "REFERENCE"))
            statements.extend(self.build_update_statements(self.part_number_table, "REPORTS", "SAMPLE_NUMBER"))
            statements.extend(self.build_update_statements(self.header_table, "MEASUREMENTS", "HEADER"))

            if not statements:
                QMessageBox.information(self, "No changes", "No changes were detected.")
                return

            run_transaction_with_retry(
                self.db_file,
                lambda cursor: self._apply_update_statements(cursor, statements),
            )

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
