from modules.CustomLogger import CustomLogger
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import(
    QAbstractItemView,
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
import hashlib
import sqlite3
import pandas as pd


class DataGrouping(QDialog):
    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        self.setWindowTitle("Data grouping")
        self.setWindowIcon(parent.windowIcon())
        self.setModal(True)
        
        self.db_file = db_file
        self.df = None
        self.default_group = "POPULATION"
        
        self.setup_ui()
        
        self.read_data_to_df()
        self.add_default_group()
        self.populate_list_widgets()

    def setup_ui(self):
        try:
            self.create_widgets()
            self.arrange_layout()
            self.connect_signals()
        except Exception as e:
            self.log_and_exit(e)

    def create_widgets(self):
        try:
            # Create labels and list widgets for each column to be filtered
            self.reference_label = QLabel("REFERENCE:")
            self.reference_list = QListWidget()

            self.part_label = QLabel("PART #:")
            self.part_list = QListWidget()
            self.part_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
            self.all_parts_list = QListWidget()
            self.all_parts_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
            
            self.groups_label = QLabel("GROUPS:")
            self.groups_list = QListWidget()
            
            self.part_group_label = QLabel("PART IN SELECTED GROUP:")
            self.part_group_list = QListWidget()
            self.part_group_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

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
        try:
            self.layout = QGridLayout(self)

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
                            widget.setFixedWidth(200) if column == 0 else widget.setFixedWidth(200)

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
        try:
            self.reference_search_input.textChanged.connect(lambda: self.search_list_widgets(self.reference_list, self.reference_search_input.text()))
            self.part_search_input.textChanged.connect(lambda: self.search_list_widgets(self.part_list, self.part_search_input.text()))
            self.group_search_input.textChanged.connect(lambda: self.search_list_widgets(self.groups_list, self.group_search_input.text()))
            self.part_group_search_input.textChanged.connect(lambda: self.search_list_widgets(self.part_group_list, self.part_group_search_input.text()))
            
            # Connect the itemSelectionChanged signal of the "REFERENCE" list to the on_reference_selection_changed method
            self.reference_list.itemSelectionChanged.connect(self.on_reference_selection_changed)
            
            # Connect the itemSelectionChanged signal of the "GROUPS" list to the on_group_selection_changed method
            self.groups_list.itemSelectionChanged.connect(self.on_group_selection_changed)
            
            # Connect the itemSelectionChanged signal of the "PART #" list to the on_part_selection_changed method
            self.part_list.itemSelectionChanged.connect(self.on_part_selection_changed)
            
            # Connect the itemSelectionChanged signal of the "PART IN SELECTED GROUP" list to the on_part_group_selection_changed method
            self.part_group_list.itemSelectionChanged.connect(self.on_part_group_selection_changed)

            self.create_group_button.clicked.connect(self.create_group)
            self.rename_group_button.clicked.connect(self.rename_group)
            self.remove_from_group_button.clicked.connect(self.remove_from_group)
            self.delete_group_button.clicked.connect(self.delete_group)
            
            self.use_grouping_button.clicked.connect(self.use_grouping)
            self.dont_use_grouping_button.clicked.connect(self.dont_use_grouping)
        except Exception as e:
            self.log_and_exit(e)
            
    def read_data_to_df(self):
        try:
            query = "SELECT REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER FROM REPORTS"
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                self.df = pd.read_sql_query(query, cursor.connection)
        except Exception as e:
            self.log_and_exit(e)
            
    def add_default_group(self):
        try:
            self.df["GROUP"] = self.default_group
            self.df["GROUP_KEY"] = self._compute_group_key_for_df(self.df)
        except Exception as e:
            self.log_and_exit(e)

    def _compute_group_key_for_df(self, df):
        try:
            key_columns = ['REFERENCE', 'FILELOC', 'FILENAME', 'DATE', 'SAMPLE_NUMBER']
            raw_key = df[key_columns].fillna('').astype(str).agg('|'.join, axis=1)
            return raw_key.apply(lambda value: hashlib.sha1(value.encode('utf-8')).hexdigest())
        except Exception as e:
            self.log_and_exit(e)

    def _part_display_label(self, row):
        sample = str(row['SAMPLE_NUMBER'])
        date = str(row['DATE']) if pd.notna(row['DATE']) else ''
        filename = str(row['FILENAME']) if pd.notna(row['FILENAME']) else ''
        return f"{sample} | {date} | {filename}"

    def _populate_part_list(self, selected_reference=None):
        rows_df = self.df if not selected_reference else self.df[self.df['REFERENCE'] == selected_reference]
        rows_df = rows_df.drop_duplicates(subset=['GROUP_KEY'])

        self.part_list.clear()
        for _, row in rows_df.iterrows():
            item = QListWidgetItem(self._part_display_label(row))
            item.setData(Qt.ItemDataRole.UserRole, row['GROUP_KEY'])
            self.part_list.addItem(item)

    def _populate_part_group_list(self, selected_group=None):
        rows_df = self.df if not selected_group else self.df[self.df['GROUP'] == selected_group]
        rows_df = rows_df.drop_duplicates(subset=['GROUP_KEY'])

        self.part_group_list.clear()
        for _, row in rows_df.iterrows():
            item = QListWidgetItem(self._part_display_label(row))
            item.setData(Qt.ItemDataRole.UserRole, row['GROUP_KEY'])
            self.part_group_list.addItem(item)
            
    def populate_list_widgets(self):
        try:
            unique_references = self.df["REFERENCE"].unique()
            unique_groups = self.df["GROUP"].unique()

            # Populate reference_list
            self.reference_list.clear()
            self.reference_list.addItems(map(str, unique_references))
            
            # Select the first item in the reference_list by default
            if self.reference_list.count() > 0:
                self.reference_list.setCurrentRow(0)

            # Use clear and addItems for the rest of the lists
            selected_reference = self.reference_list.currentItem().text() if self.reference_list.currentItem() else None
            self._populate_part_list(selected_reference)

            self.all_parts_list.clear()
            self.all_parts_list.addItems(map(str, self.df['SAMPLE_NUMBER'].astype(str).unique()))

            self.groups_list.clear()
            self.groups_list.addItems(map(str, unique_groups))
            
            # Select the first item in the groups_list by default
            if self.groups_list.count() > 0:
                self.groups_list.setCurrentRow(0)
            selected_group = self.groups_list.currentItem().text() if self.groups_list.currentItem() else None
            self._populate_part_group_list(selected_group)
        except Exception as e:
            self.log_and_exit(e)

    def search_list_widgets(self, list_widget, search_text):
        try:
            selected_items = list_widget.selectedItems()
            list_widget.clearSelection()

            if not search_text:
                for row in range(list_widget.count()):
                    item = list_widget.item(row)
                    item.setHidden(False)
                for item in selected_items:
                    item.setSelected(True)
                return

            search_text = search_text.lower()

            for row in range(list_widget.count()):
                item = list_widget.item(row)
                item_text = item.text().lower()
                if search_text in item_text:
                    item.setHidden(False)
                else:
                    item.setHidden(True)

            for item in selected_items:
                item.setSelected(True)
        except Exception as e:
            self.log_and_exit(e)
            
    def on_reference_selection_changed(self):
        try:
            selected_reference = self.reference_list.currentItem().text() if self.reference_list.currentItem() else None
            self._populate_part_list(selected_reference)
            self.create_group_button.setDisabled(True)
        except Exception as e:
            self.log_and_exit(e)
    
    def on_part_selection_changed(self):
        try:
            selected_part = self.part_list.currentItem() is not None
            self.create_group_button.setEnabled(selected_part)
        except Exception as e:
            self.log_and_exit(e)
    
    def on_group_selection_changed(self):
        try:
            selected_group_name = self.groups_list.currentItem().text() if self.groups_list.currentItem() else None
            self._populate_part_group_list(selected_group_name)

            selected_group = self.groups_list.currentItem() is not None
            self.rename_group_button.setEnabled(selected_group)
            self.delete_group_button.setEnabled(selected_group)
        except Exception as e:
            self.log_and_exit(e)
            
    def on_part_group_selection_changed(self):
        try:
            selected_part_group = self.part_group_list.currentItem() is not None
            self.remove_from_group_button.setEnabled(selected_part_group)
        except Exception as e:
            self.log_and_exit(e)
            
    def create_group(self):
        try:
            # Get the selected items from the list widgets
            selected_part_keys = [item.data(Qt.ItemDataRole.UserRole) for item in self.part_list.selectedItems()]
            new_group_name, ok_pressed = QInputDialog.getText(self, "New group", "Enter group name:")

            if ok_pressed and selected_part_keys:
                # Update the dataframe with the new group information
                self.df.loc[
                    self.df['GROUP_KEY'].isin(selected_part_keys),
                    'GROUP'
                ] = new_group_name
                
            self.populate_list_widgets()
            self.remove_from_group_button.setDisabled(True)
        except Exception as e:
            self.log_and_exit(e)
            
    def rename_group(self):
        try:
            selected_group = self.groups_list.currentItem().text()
            new_group_name, ok_pressed = QInputDialog.getText(self, "Rename group", f"Enter new name for '{selected_group}':")

            if ok_pressed and selected_group and new_group_name:
                # Update the dataframe with the new group name
                self.df.loc[self.df['GROUP'] == selected_group, 'GROUP'] = new_group_name
                
            self.populate_list_widgets()
            self.remove_from_group_button.setDisabled(True)
        except Exception as e:
            self.log_and_exit(e)
            
    def remove_from_group(self):
        try:
            selected_group = self.groups_list.currentItem().text() if self.groups_list.currentItem() else None
            selected_part_keys = [item.data(Qt.ItemDataRole.UserRole) for item in self.part_group_list.selectedItems()]

            if selected_group and selected_part_keys:
                # Update the dataframe with the default group information for selected rows only
                self.df.loc[
                    (self.df['GROUP'] == selected_group) &
                    (self.df['GROUP_KEY'].isin(selected_part_keys)),
                    'GROUP'
                ] = self.default_group

                # Repopulate the list widgets after updating the dataframe
                self.populate_list_widgets()
                self.remove_from_group_button.setDisabled(True)
        except Exception as e:
            self.log_and_exit(e)
            
    def delete_group(self):
        try:
            # Get the selected group
            selected_group = self.groups_list.currentItem().text()

            # Create a QMessageBox with the Question icon
            confirmation = QMessageBox(QMessageBox.Icon.Question, 'Confirm Deletion', f"Are you sure you want to delete group '{selected_group}'?")

            # Add buttons to the QMessageBox
            confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            # Execute the QMessageBox and check the result
            result = confirmation.exec()

            if result == QMessageBox.StandardButton.Yes and selected_group:
                # Update the dataframe with the default group value for the selected group
                self.df.loc[self.df['GROUP'] == selected_group, 'GROUP'] = self.default_group
            
            # Repopulate the list widgets after updating the dataframe
            self.populate_list_widgets()
            self.remove_from_group_button.setDisabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def use_grouping(self):
        try:
            self.hide()
            self.parent().set_df_for_grouping(self.df)
            self.parent().set_grouping_applied(True)
        except Exception as e:
            self.log_and_exit(e)
            
    def dont_use_grouping(self):
        try:
            self.hide()
            self.parent().set_df_for_grouping(None)
            self.parent().set_grouping_applied(False)
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
