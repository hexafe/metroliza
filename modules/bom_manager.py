from PyQt6.QtWidgets import (
    QMainWindow,
    QLabel,
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QComboBox,
)
from PyQt6.QtCore import Qt

from modules.db import connect_sqlite, execute_select_with_columns


class BOMManager(QMainWindow):
    def __init__(self, database_path='bom.db'):
        super().__init__()
        self.setWindowTitle("BOM Manager")
        self.setGeometry(200, 200, 600, 400)
        self.database_path = database_path

        # Create a connection to the SQLite database
        self.conn = connect_sqlite(database_path)

        # Create the BOM table if it doesn't exist
        self.create_bom_table()

        # Create the main widget and layout
        self.main_widget = QWidget(self)
        self.setCentralWidget(self.main_widget)
        self.layout = QVBoxLayout(self.main_widget)

        # Create the input widgets
        self.create_input_widgets()

        # Create the parent combo box
        self.create_parent_combo_box()

        # Create the buttons
        self.create_buttons()

        # Create the table to display the BOM
        self.create_bom_table_widget()

        # Create the save button
        self.create_save_button()

        # Track whether a row is being modified
        self.modifying_row = False
        self.selected_entry_id = None

    def _execute_write(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()
        return cursor

    def _execute_read(self, query, params=()):
        rows, _ = execute_select_with_columns(self.database_path, query, params)
        return rows

    def create_bom_table(self):
        # Create a BOM table in the database if it doesn't exist
        self._execute_write('''CREATE TABLE IF NOT EXISTS bom (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            product_reference TEXT,
                            description TEXT,
                            part_reference TEXT,
                            part_description TEXT,
                            parent_id INTEGER,
                            FOREIGN KEY (parent_id) REFERENCES bom(id)
                        )''')

    def create_input_widgets(self):
        # Create the input widgets
        self.product_reference_label = QLabel("Product Reference:")
        self.product_reference_input = QLineEdit()
        self.description_label = QLabel("Description:")
        self.description_input = QLineEdit()
        self.part_reference_label = QLabel("Part Reference:")
        self.part_reference_input = QLineEdit()
        self.part_description_label = QLabel("Part Description:")
        self.part_description_input = QLineEdit()

        # Add the input widgets to the layout
        self.layout.addWidget(self.product_reference_label)
        self.layout.addWidget(self.product_reference_input)
        self.layout.addWidget(self.description_label)
        self.layout.addWidget(self.description_input)
        self.layout.addWidget(self.part_reference_label)
        self.layout.addWidget(self.part_reference_input)
        self.layout.addWidget(self.part_description_label)
        self.layout.addWidget(self.part_description_input)

    def create_parent_combo_box(self):
        # Create the parent combo box
        self.parent_label = QLabel("Parent Entry:")
        self.parent_combo_box = QComboBox()
        self.populate_parent_combo_box()

        # Add the parent combo box to the layout
        self.layout.addWidget(self.parent_label)
        self.layout.addWidget(self.parent_combo_box)

    def create_buttons(self):
        # Create the buttons
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self.add_bom_entry)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_bom_entry)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_inputs)

        # Add the buttons to the layout
        self.layout.addWidget(self.add_button)
        self.layout.addWidget(self.delete_button)
        self.layout.addWidget(self.clear_button)

    def create_bom_table_widget(self):
        # Create the table to display the BOM
        self.bom_table = QTableWidget()
        self.bom_table.setColumnCount(5)
        self.bom_table.setHorizontalHeaderLabels(
        ['Product Reference', 'Description', 'Part Reference', 'Part Description', 'Parent Reference']
        )
        self.bom_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.bom_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.bom_table.cellDoubleClicked.connect(self.modify_bom_entry)
        # Add the BOM table widget to the layout
        self.layout.addWidget(self.bom_table)

    def create_save_button(self):
        # Create the save button
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_modified_bom_entry)
        self.save_button.setEnabled(False)  # Initially disabled

        # Add the save button to the layout
        self.layout.addWidget(self.save_button)

    def refresh_table(self):
        # Clear the table
        self.bom_table.setRowCount(0)
        self.populate_parent_combo_box()

        # Retrieve the BOM entries from the database
        bom_entries = self._execute_read("SELECT * FROM bom")

        # Populate the table with the BOM entries
        for row_data in bom_entries:
            entry_id, product_reference, description, part_reference, part_description, parent_id = row_data

            # Create a new row in the table
            row_num = self.bom_table.rowCount()
            self.bom_table.insertRow(row_num)

            # Set the item data for each column in the row
            item_product_reference = QTableWidgetItem(product_reference)
            item_product_reference.setData(Qt.UserRole, row_data)
            item_description = QTableWidgetItem(description)
            item_description.setData(Qt.UserRole, row_data)
            item_part_reference = QTableWidgetItem(part_reference)
            item_part_reference.setData(Qt.UserRole, row_data)
            item_part_description = QTableWidgetItem(part_description)
            item_part_description.setData(Qt.UserRole, row_data)
            item_parent_reference = QTableWidgetItem(self.get_parent_reference(parent_id))
            item_parent_reference.setData(Qt.UserRole, row_data)

            self.bom_table.setItem(row_num, 0, item_product_reference)
            self.bom_table.setItem(row_num, 1, item_description)
            self.bom_table.setItem(row_num, 2, item_part_reference)
            self.bom_table.setItem(row_num, 3, item_part_description)
            self.bom_table.setItem(row_num, 4, item_parent_reference)

    def get_parent_reference(self, parent_id):
        # Retrieve the parent reference based on the parent_id
        parent_rows = self._execute_read("SELECT part_reference FROM bom WHERE id = ?", (parent_id,))
        if parent_rows:
            return parent_rows[0][0]
        else:
            return "None"

    def get_bom_entries(self):
        # Retrieve the BOM entries from the database
        bom_entries = self._execute_read("SELECT id, product_reference FROM bom")

        # Format the entries as strings for the combo box
        entries = []
        for entry in bom_entries:
            entry_id = entry[0]
            product_reference = entry[1]
            entries.append(f"{entry_id} - {product_reference}")

        return entries

    def populate_parent_combo_box(self):
        self.parent_combo_box.clear()
        for entry_id, product_reference in self._execute_read("SELECT id, product_reference FROM bom"):
            self.parent_combo_box.addItem(f"{entry_id} - {product_reference}", entry_id)

    def find_parent_index_by_id(self, parent_id):
        if parent_id is None:
            return -1

        for index in range(self.parent_combo_box.count()):
            if self.parent_combo_box.itemData(index, Qt.ItemDataRole.UserRole) == parent_id:
                return index

        return -1

    def add_bom_entry(self):
        product_reference = self.product_reference_input.text()
        description = self.description_input.text()
        part_reference = self.part_reference_input.text()
        part_description = self.part_description_input.text()
        parent_id = self.parent_combo_box.currentData(Qt.ItemDataRole.UserRole)

        # Insert the BOM entry into the database
        self._execute_write(
            "INSERT INTO bom (product_reference, description, part_reference, part_description, parent_id) VALUES (?, ?, ?, ?, ?)",
            (product_reference, description, part_reference, part_description, parent_id)
        )

        # Refresh the table and clear the input fields
        self.refresh_table()
        self.clear_inputs()

    def save_modified_bom_entry(self):
        # Get the modified data from the input fields
        product_reference = self.product_reference_input.text()
        description = self.description_input.text()
        part_reference = self.part_reference_input.text()
        part_description = self.part_description_input.text()
        parent_id = self.parent_combo_box.currentData(Qt.ItemDataRole.UserRole)

        # Update the modified BOM entry in the database
        self._execute_write(
            "UPDATE bom SET product_reference = ?, description = ?, part_reference = ?, part_description = ?, parent_id = ? WHERE id = ?",
            (product_reference, description, part_reference, part_description, parent_id, self.selected_entry_id)
        )

        # Refresh the table, clear the input fields, and reset the state
        self.refresh_table()
        self.clear_inputs()
        self.save_button.setEnabled(False)
        self.modifying_row = False
        self.selected_entry_id = None

    def delete_bom_entry(self):
        selected_rows = self.bom_table.selectedItems()

        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select a row to delete.")
            return

        # Confirm the deletion with the user
        confirm_dialog = QMessageBox.question(self, "Confirm Deletion", "Are you sure you want to delete the selected row(s)?",
                                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm_dialog == QMessageBox.StandardButton.Yes:
            # Delete the selected BOM entries from the database
            cursor = self.conn.cursor()
            for item in selected_rows:
                row = item.row()
                entry_id = self.bom_table.item(row, 0).data(Qt.UserRole)[0]
                cursor.execute("DELETE FROM bom WHERE id = ?", (entry_id,))
            self.conn.commit()

            # Refresh the table and clear the input fields
            self.refresh_table()
            self.clear_inputs()

    def clear_inputs(self):
        # Clear the input fields
        self.product_reference_input.clear()
        self.description_input.clear()
        self.part_reference_input.clear()
        self.part_description_input.clear()
        self.parent_combo_box.setCurrentIndex(0)

    def modify_bom_entry(self, row, column):
        # Get the data of the selected row
        selected_data = self.bom_table.item(row, 0).data(Qt.UserRole)
        if selected_data:
            self.modifying_row = True
            self.selected_entry_id = selected_data[0]

            # Set the input fields with the selected data
            self.product_reference_input.setText(selected_data[1])
            self.description_input.setText(selected_data[2])
            self.part_reference_input.setText(selected_data[3])
            self.part_description_input.setText(selected_data[4])

            # Set the selected parent in the combo box
            parent_index = self.find_parent_index_by_id(selected_data[5])
            self.parent_combo_box.setCurrentIndex(parent_index)

            # Enable the save button
            self.save_button.setEnabled(True)

    def closeEvent(self, event):
        # Close the database connection when the application is closed
        self.conn.close()
