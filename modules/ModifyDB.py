from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from modules.CustomLogger import CustomLogger
from modules.db import connect_sqlite, execute_select_with_columns


class ModifyDB(QDialog):
    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        self.setWindowTitle("Modify database")
        self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 640, 480)
        self.setModal(True)

        self.db_file = db_file
        self.undo_data = {}

        self.setup_ui()

    def setup_ui(self):
        try:
            self.create_widgets()
            self.arrange_layout()
            self.connect_signals()
        except Exception as e:
            self.log_and_exit(e)

    def create_widgets(self):
        try:
            # Create table widgets for REFERENCE, PART NUMBER, and HEADER
            self.reference_table = QTableWidget()
            self.reference_table.setColumnCount(1)
            self.reference_table.setHorizontalHeaderLabels(["REFERENCE"])
            self.reference_table.setColumnWidth(0, 200)

            self.part_number_table = QTableWidget()
            self.part_number_table.setColumnCount(1)
            self.part_number_table.setHorizontalHeaderLabels(["SAMPLE NUMBER"])
            self.part_number_table.setColumnWidth(0, 200)

            self.header_table = QTableWidget()
            self.header_table.setColumnCount(1)
            self.header_table.setHorizontalHeaderLabels(["HEADER"])
            self.header_table.setColumnWidth(0, 200)

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

            # Add table widgets and buttons to the layout
            layout.addWidget(self.reference_table, 0, 0)
            layout.addWidget(self.part_number_table, 0, 1)
            layout.addWidget(self.header_table, 0, 2)
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
        except Exception as e:
            self.log_and_exit(e)

    def select_db_file(self):
        try:
            """Open a file dialog to select a database file"""
            filename, _ = QFileDialog.getOpenFileName(
                self, "Select a database file", "", "SQLite database (*.db);;All files (*)"
            )
            if filename:
                if not filename.endswith(".db"):
                    filename += ".db"
                print(f"Selected DB file: {filename}")
                self.db_file = filename
                self.populate_tables()
                self.apply_button.setEnabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def populate_tables(self):
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
        try:
            with connect_sqlite(self.db_file) as conn:
                cursor = conn.cursor()

                # Update reference values
                self.update_table_values(cursor, conn, self.reference_table, "REPORTS", "REFERENCE")

                # Update part number values
                self.update_table_values(cursor, conn, self.part_number_table, "REPORTS", "SAMPLE_NUMBER")

                # Update header values
                self.update_table_values(cursor, conn, self.header_table, "MEASUREMENTS", "HEADER")

            # Display a message box with confirmation
            QMessageBox.information(self, "Changes applied", "Changes have been applied successfully.")

            # Close the dialog
            self.close()
        except Exception as e:
            self.log_and_exit(e)

    def update_table_values(self, cursor, conn, table_widget, table_name, column_name):
        for row in range(table_widget.rowCount()):
            new_value = str(table_widget.item(row, 0).text())
            old_value = str(table_widget.item(row, 0).data(Qt.ItemDataRole.UserRole))

            if new_value != old_value:
                query = f"UPDATE {table_name} SET {column_name} = ? WHERE {column_name} = ?"
                cursor.execute(query, (new_value, old_value))
                conn.commit()

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
