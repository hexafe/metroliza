from PyQt6.QtCore import Qt, pyqtSlot, QThread, pyqtSignal, QTemporaryFile, QSize
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QPushButton,
    QFileDialog,
    QListWidget,
    QMessageBox,
    QHBoxLayout,
    QProgressBar,
    QLabel,
)
from pathlib import Path
import pandas as pd
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell
from modules.excel_sheet_utils import unique_sheet_name
from modules.csv_summary_utils import (
    compute_column_summary_stats,
    load_csv_with_fallbacks,
    resolve_default_data_columns,
)
import base64
from modules import Base64EncodedFiles


class FilterDialog(QDialog):
    def __init__(self, parent, column_names):
        super().__init__(parent)

        self.setWindowTitle("Filter Columns")
        self.setGeometry(200, 200, 500, 150)

        self.column_names = column_names
        self.selected_indexes = column_names[:1]
        self.selected_data_columns = column_names[1:]

        # Initialize the layout
        main_layout = QVBoxLayout()

        # Create horizontal layout for the list widgets
        horizontal_layout = QHBoxLayout()

        # Add the list widgets for indexes and data columns
        self.index_list_widget = QListWidget()
        self.data_list_widget = QListWidget()

        # Set the selection mode to multi-selection
        self.index_list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.data_list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)

        # Add the list widgets to the horizontal layout
        horizontal_layout.addWidget(self.index_list_widget)
        horizontal_layout.addWidget(self.data_list_widget)

        # Populate the list widgets with column names
        self.index_list_widget.addItem("SELECT DEFAULT (FIRST COLUMN)")
        self.index_list_widget.addItems(column_names)
        self.data_list_widget.addItem("SELECT ALL")
        self.data_list_widget.addItems(column_names)

        # Add the horizontal layout to the main layout
        main_layout.addLayout(horizontal_layout)

        # Add OK button
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)

        # Add the OK button to the layout
        main_layout.addWidget(ok_button)

        # Set the layout for the dialog
        self.setLayout(main_layout)

        # Select the default filter initially
        self.select_default_filter()

    def select_default_filter(self):
        # Select the first item in INDEX list as default
        self.index_list_widget.setCurrentRow(0)

        # Select the first item in DATA list as default
        self.data_list_widget.setCurrentRow(0)

    def get_selected_columns(self):
        # Get the selected indexes and data columns
        self.selected_indexes = [item.text() for item in self.index_list_widget.selectedItems()]
        self.selected_data_columns = [item.text() for item in self.data_list_widget.selectedItems()]

        # Return the first column if "SELECT DEFAULT (FIRST COLUMN)" is selected
        if "SELECT DEFAULT (FIRST COLUMN)" in self.selected_indexes:
            self.selected_indexes = self.column_names[:1]

        # Return all columns except the ones selected in INDEX if "SELECT ALL" is selected
        if "SELECT ALL" in self.selected_data_columns:
            self.selected_data_columns = [column for column in self.column_names if column not in self.selected_indexes]
            if "SELECT ALL" in self.selected_data_columns:
                self.selected_data_columns.remove("SELECT ALL")

        # Return the selected columns
        return self.selected_indexes, self.selected_data_columns


class DataProcessingThread(QThread):
    progress_signal = pyqtSignal(int)

    def __init__(self, selected_indexes, selected_data_columns, input_file, output_file, data_frame, csv_config=None):
        super().__init__()
        self.selected_indexes = selected_indexes
        self.selected_data_columns = selected_data_columns
        self.input_file = input_file
        self.output_file = output_file
        self.data_frame = data_frame
        self.canceled = False
        self.csv_config = csv_config or {}

    def write_summary_data(self, worksheet, data_column, selected_data):
        col = selected_data.shape[1]

        worksheet.write(0, col + 2, 'NOM')
        nom = 0
        worksheet.write(0, col + 3, nom)

        worksheet.write(1, col + 2, 'USL')
        USL = 0
        worksheet.write(1, col + 3, USL)
        USL = nom + USL
        USL_cell = xl_rowcol_to_cell(1, col + 3, row_abs=True, col_abs=True)

        worksheet.write(2, col + 2, 'LSL')
        LSL = 0
        worksheet.write(2, col + 3, LSL)
        LSL = nom + LSL
        LSL_cell = xl_rowcol_to_cell(2, col + 3, row_abs=True, col_abs=True)

        worksheet.write(3, col + 2, 'MIN')
        min_formula = f"=ROUND(MIN({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1}), 3)"
        worksheet.write_formula(3, col + 3, min_formula)

        worksheet.write(4, col + 2, 'AVG')
        avg_formula = f"=ROUND(AVERAGE({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1}), 3)"
        worksheet.write_formula(4, col + 3, avg_formula)

        worksheet.write(5, col + 2, 'MAX')
        max_formula = f"=ROUND(MAX({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1}), 3)"
        worksheet.write_formula(5, col + 3, max_formula)

        worksheet.write(6, col + 2, 'STD')
        std_formula = f"=ROUND(STDEV({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1}), 3)"
        worksheet.write_formula(6, col + 3, std_formula)

        worksheet.write(7, col + 2, 'Cp')
        summary_col = xl_col_to_name(col + 3)
        USL_formula = f"({summary_col}1 + {summary_col}2)"
        LSL_formula = f"({summary_col}1 + {summary_col}3)"
        sigma_formula = f"({summary_col}7)"
        cp_formula = f"ROUND(({USL_formula} - {LSL_formula})/(6 * {sigma_formula}), 3)"
        worksheet.write_formula(7, col + 3, cp_formula)

        worksheet.write(8, col + 2, 'Cpk')
        average_formula = f"({summary_col}5)"
        cpk_formula = f"ROUND(MIN( ({USL_formula} - {average_formula})/(3 * {sigma_formula}), ({average_formula} - {LSL_formula})/(3 * {sigma_formula}) ), 3)"
        worksheet.write_formula(8, col + 3, cpk_formula)

        worksheet.write(9, col + 2, "Sample size")
        count_formula = f"=COUNT({xl_col_to_name(col-1)}2:{xl_col_to_name(col-1)}{len(selected_data[data_column]) + 1})"
        worksheet.write_formula(9, col + 3, count_formula)

        return col, USL_cell, LSL_cell

    def apply_conditional_formatting(self, worksheet, selected_data, data_column, col, USL_cell, LSL_cell, writer):
        # Define the format for conditional formatting (highlight cells in red)
        red_format = writer.book.add_format({'bg_color': 'red', 'font_color': 'white', 'align': 'center', 'valign': 'vcenter', 'right': 1, 'num_format': '#,##0.000'})

        # Apply conditional formatting to highlight cells greater than USL in red
        worksheet.conditional_format(1, col - 1, len(selected_data[data_column]), col - 1,
                                    {'type': 'cell', 'criteria': '>', 'value': USL_cell, 'format': red_format})

        # Apply conditional formatting to highlight cells lower than LSL in red
        worksheet.conditional_format(1, col - 1, len(selected_data[data_column]), col - 1,
                                    {'type': 'cell', 'criteria': '<', 'value': LSL_cell, 'format': red_format})

    def add_xy_chart(self, worksheet, data_column, col, selected_data, writer, sheet_name):
        # Create an XY chart object
        chart = writer.book.add_chart({'type': 'scatter'})

        # Add data to the chart with the specified x and y ranges
        num_rows = len(selected_data[data_column])
        x_range = f"={sheet_name}!${xl_col_to_name(0)}$2:${xl_col_to_name(0)}${num_rows + 1}"
        y_range = f"={sheet_name}!${xl_col_to_name(col - 1)}$2:${xl_col_to_name(col - 1)}${num_rows + 1}"

        # Add the series to the chart
        chart.add_series({
            'name': data_column,
            'categories': x_range,
            'values': y_range,
        })

        # Configure the chart properties
        chart.set_title({'name': f'{sheet_name}'})
        chart.set_x_axis({
            # 'name': 'Date',
            # 'date_axis': True,
            'min': 0,
            'max': num_rows + 1,
        })
        chart.set_y_axis({
            'name': f'{sheet_name}',
            'major_gridlines': {
                'visible': False,
            }
        })

        chart.set_legend({'position': 'none'})

        # Insert the chart into the worksheet.
        worksheet.insert_chart(12, col + 5, chart)


    def write_overview_sheet(self, writer, overview_rows):
        overview_df = pd.DataFrame(overview_rows)
        if overview_df.empty:
            return
        overview_df.to_excel(writer, sheet_name='CSV_SUMMARY', index=False)

    def run(self):
        # Perform the data processing and save to the Excel file here

        if self.selected_indexes and self.selected_data_columns:
            try:
                # Create an Excel writer with the selected output file
                writer = pd.ExcelWriter(self.output_file, engine='xlsxwriter')

                # Calculate the total number of filtered data columns
                total_filtered_columns = len(self.selected_data_columns)
                used_sheet_names = set()

                num_format = writer.book.add_format({'align': 'center', 'valign': 'vcenter', 'num_format': '#,##0.000'})

                overview_rows = []

                # Update the progress bar for each selected data column
                for i, data_column in enumerate(self.selected_data_columns):
                    # Check if the processing has been canceled
                    if self.canceled:
                        break

                    # Create a new DataFrame with the selected data column and indexes
                    selected_data = self.data_frame[self.selected_indexes + [data_column]].copy()

                    selected_data.loc[:, data_column] = pd.to_numeric(selected_data[data_column], errors='coerce')
                    selected_data = selected_data.dropna(subset=[data_column])
                    if selected_data.empty:
                        progress_percentage = int((i + 1) * 100 / total_filtered_columns)
                        self.progress_signal.emit(progress_percentage)
                        continue

                    # Write the data to a new sheet with a safe unique name
                    sheet_name = unique_sheet_name(data_column, used_sheet_names)
                    selected_data.to_excel(writer, sheet_name=sheet_name, index=False)

                    worksheet = writer.sheets[sheet_name]

                    col, USL_cell, LSL_cell = self.write_summary_data(worksheet, data_column, selected_data)
                    
                    # Set the number format for the data column
                    worksheet.set_column(col, col, None, num_format)

                    self.apply_conditional_formatting(worksheet, selected_data, data_column, col, USL_cell, LSL_cell, writer)

                    self.add_xy_chart(worksheet, data_column, col, selected_data, writer, sheet_name)

                    stats = compute_column_summary_stats(selected_data[data_column])
                    overview_rows.append({
                        'column': data_column,
                        'sheet_name': sheet_name,
                        'sample_size': stats['sample_size'],
                        'min': stats['min'],
                        'avg': stats['avg'],
                        'max': stats['max'],
                        'std': stats['std'],
                        'cp': stats['cp'],
                        'cpk': stats['cpk'],
                    })

                    # Calculate the progress percentage and emit the progress signal
                    progress_percentage = int((i + 1) * 100 / total_filtered_columns)
                    self.progress_signal.emit(progress_percentage)

                self.write_overview_sheet(writer, overview_rows)

                # Save the Excel file
                writer.close()

            except Exception as e:
                print("Error during data processing:", e)
                self.canceled = True

        else:
            print("No data selected for processing.")

    def cancel(self):
        self.canceled = True


class CSVSummaryDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowTitle("CSV Summary")
        self.setGeometry(200, 200, 300, 150)

        self.input_file = ""
        self.output_file = ""
        self.data_frame = None  # Store the loaded DataFrame
        self.column_names = []
        self.selected_indexes = []
        self.selected_data_columns = []
        self.csv_config = {}

        # Initialize the layout
        layout = QVBoxLayout()

        # Add the buttons to the layout
        self.input_button = QPushButton("Select input file (CSV)")
        self.filter_button = QPushButton("Filter columns (optional)")
        self.output_button = QPushButton("Select output file (xlsx)")
        self.start_button = QPushButton("START")  # Add the START button
        layout.addWidget(self.input_button)
        layout.addWidget(self.filter_button)
        layout.addWidget(self.output_button)
        layout.addWidget(self.start_button)  # Add the START button to the layout

        # Connect the buttons to their respective functions
        self.input_button.clicked.connect(self.handle_input_button)
        self.filter_button.clicked.connect(self.handle_filter_button)
        self.output_button.clicked.connect(self.handle_output_button)
        self.start_button.clicked.connect(self.handle_start_button)  # Connect the START button

        # Initially, disable the FILTER, OUTPUT, and START buttons
        self.filter_button.setEnabled(False)
        self.output_button.setEnabled(False)
        self.start_button.setEnabled(False)

        # Set the layout for the dialog
        self.setLayout(layout)

    # Define functions for button clicks
    def handle_input_button(self):
        options = QFileDialog.Option.ReadOnly
        filename, _ = QFileDialog.getOpenFileName(self, "Select input file (CSV)", "", "CSV Files (*.csv);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".csv"):
                filename += ".csv"
            print("Selected input file:", filename)
            self.input_file = filename
            # Enable the FILTER and OUTPUT buttons after the input file is selected
            self.filter_button.setEnabled(True)
            self.output_button.setEnabled(True)

            # Load CSV with delimiter/decimal fallbacks.
            try:
                self.data_frame, self.csv_config = load_csv_with_fallbacks(filename)
            except Exception as exc:
                QMessageBox.critical(self, 'CSV load failed', f'Could not load CSV file.\n\n{exc}')
                self.filter_button.setEnabled(False)
                self.output_button.setEnabled(False)
                self.start_button.setEnabled(False)
                return

            self.column_names = self.data_frame.columns.tolist()
            self.selected_indexes = self.column_names[:1]
            self.selected_data_columns = resolve_default_data_columns(self.data_frame, self.selected_indexes)

    def handle_filter_button(self):
        print("FILTER button clicked")

        # Open the FilterDialog and pass the column names to it
        if self.data_frame is not None:
            filter_dialog = FilterDialog(self, self.column_names)

            if filter_dialog.exec() == QDialog.DialogCode.Accepted:
                self.selected_indexes, self.selected_data_columns = filter_dialog.get_selected_columns()

                # Use the selected_indexes and selected_data_columns for further processing
                if self.selected_indexes:
                    print("Selected Indexes:", self.selected_indexes)
                if self.selected_data_columns:
                    print("Selected Data Columns:", self.selected_data_columns)
        else:
            QMessageBox.warning(self, "Warning", "No data loaded. Please select an input file first.")

    def handle_output_button(self):
        # options = QFileDialog.Option.DontUseNativeDialog
        default_name = self.input_file[:-4]
        if not default_name.endswith(".xlsx"):
            default_name += ".xlsx"

        file_path = Path(default_name)
        base_name = file_path.stem
        suffix = file_path.suffix
        directory = file_path.parent

        counter = 1
        while file_path.exists():
            file_path = directory / f"{base_name}_{counter}{suffix}"
            counter += 1

        filename, _ = QFileDialog.getSaveFileName(self, "Select output file (xlsx)", str(file_path),
                                                "Excel Files (*.xlsx);;All Files (*)")#, options=options)

        if filename:
            print("Selected output file:", filename)
            self.output_file = filename
            # Enable the START button after the output file is selected
            self.start_button.setEnabled(True)

    @pyqtSlot()
    def show_loading_screen(self):
        # Create a custom QDialog for the loading screen
        self.loading_dialog = QDialog(self, Qt.WindowType.WindowTitleHint)
        self.loading_dialog.setWindowTitle("Processing...")
        self.loading_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.loading_dialog.setFixedSize(400, 300)

        # Create a QLabel to display the loading GIF
        loading_gif_label = QLabel(self.loading_dialog)
        loading_gif_label.setFixedSize(200, 200)
        loading_gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Load the loading.gif from a file, create a QMovie from it, and set it to the label
        loading_gif_decoded = base64.b64decode(Base64EncodedFiles.encoded_loading_gif)

        # Create temporary file and save encoded loading gif to it
        temp_file = QTemporaryFile()
        temp_file.setAutoRemove(False)
        temp_file_name = ""
        if temp_file.open():
            temp_file.write(loading_gif_decoded)
            temp_file.close()
            temp_file_name = temp_file.fileName()

        # Create the QMovie using the temporary file name
        loading_gif = QMovie(temp_file_name)
        loading_gif.setScaledSize(QSize(200, 200))
        loading_gif_label.setMovie(loading_gif)
        loading_gif.start()

        # Create the loading label and progress bar as instance variables
        self.loading_label = QLabel("Processing data...", self.loading_dialog)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.loading_bar = QProgressBar(self.loading_dialog)
        self.loading_bar.setValue(0)
        self.loading_bar.setFixedSize(380, 20)
        self.loading_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Create a layout for the dialog and add the loading GIF, loading label, and progress bar to it
        layout = QVBoxLayout(self.loading_dialog)
        layout.addWidget(loading_gif_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.loading_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.loading_bar, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Create and add the Cancel button to the layout
        cancel_button = QPushButton("Cancel", self.loading_dialog)
        cancel_button.clicked.connect(self.stop_data_processing_and_close_loading)
        layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Start the data processing in a separate thread
        self.worker_thread = DataProcessingThread(
            self.selected_indexes,
            self.selected_data_columns,
            self.input_file,
            self.output_file,
            self.data_frame,
            self.csv_config,
        )
        # Connect the progress signal to the update_progress_bar slot
        self.worker_thread.progress_signal.connect(self.update_progress_bar)
        self.worker_thread.finished.connect(self.on_data_processing_finished)
        self.worker_thread.start()

        # Show the loading dialog
        self.loading_dialog.show()

    def update_progress_bar(self, value):
        # Update the progress bar value
        self.loading_bar.setValue(value)

    def stop_data_processing_and_close_loading(self):
        if self.worker_thread:
            # Stop the data processing thread if it exists
            self.worker_thread.cancel()

    @pyqtSlot()
    def on_data_processing_finished(self):
        # Data processing is complete or canceled

        if self.worker_thread.canceled:
            # Show a message box to inform the user that processing has been canceled
            QMessageBox.information(self, "Processing canceled", "Processing has been canceled")
        else:
            # Show a message box to inform the user that processing is complete
            QMessageBox.information(self, "Processing complete", f"Data saved to {self.output_file}!")

        # Close the loading dialog
        self.loading_dialog.close()

        # Reset the worker thread
        self.worker_thread = None

    def handle_start_button(self):
        # Perform the desired action when the START button is clicked
        # You can access the input_file, output_file, and data_frame variables here for further processing

        if self.data_frame is not None:
            # Show the loading screen and progress bar
            self.show_loading_screen()
        else:
            print("No data loaded. Please select an input file first.")
