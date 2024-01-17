from modules import base64_encoded_files
from modules.ExportDataThread import ExportDataThread
from modules.FilterDialog import FilterDialog
from modules.DataGrouping import DataGrouping
from modules.CustomLogger import CustomLogger
from PyQt5.QtCore import QSize, QTemporaryFile, Qt
from PyQt5.QtGui import QMovie
from PyQt5.QtWidgets import(
    QDialog,
    QFileDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QComboBox,
    QCheckBox,
)
import base64
from pathlib import Path


class ExportDialog(QDialog):
    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        
        self.setWindowTitle("Export")
        self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 300, 150)

        self.db_file = db_file
        self.excel_file = ""
        self.filter_query = """
                SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL", 
                    MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS, 
                    MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE, 
                    REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE, REPORTS.SAMPLE_NUMBER 
                FROM MEASUREMENTS
                JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
                WHERE 1=1
                """
        self.df_for_grouping = None
        
        self.filter_window = None
        self.grouping_window = None

        self.init_widgets()
        self.init_layout()

    def init_widgets(self):
        try:
            """Initialize the widgets"""
            self.select_db_label = QLabel("Select a database file:")
            self.select_db_button = QPushButton("Browse")
            self.select_db_button.clicked.connect(self.select_db_file)
            self.select_db_label.setToolTip("Use this button to select the database from which the results will be exported to an Excel file")
            self.select_db_button.setToolTip("Use this button to select the database from which the results will be exported to an Excel file")

            self.select_filter_label = QLabel("Select filters (optional): not applied")
            self.filter_button = QPushButton("Filter")
            self.filter_button.clicked.connect(self.open_filter_window)
            self.filter_button.setToolTip("Use this button to filter data from the database")
            
            self.select_group_label = QLabel("Group data (optional): not applied")
            self.group_button = QPushButton("Group")
            self.group_button.clicked.connect(self.open_grouping_window)
            self.group_button.setToolTip("Use this button to group data")

            self.select_excel_label = QLabel("Select an excel file:")
            self.select_excel_button = QPushButton("Browse")
            self.select_excel_button.clicked.connect(self.select_excel_file)
            self.select_excel_label.setToolTip("Use this button to select the Excel file to which the data will be saved")
            self.select_excel_button.setToolTip("Use this button to select the Excel file to which the data will be saved")

            self.export_button = QPushButton("Export")
            self.export_button.setDisabled(True)
            self.export_button.clicked.connect(self.show_loading_screen)
            self.export_button.setToolTip("Start exporting")

            self.spacer = QLabel(" ")

            if self.db_file:
                self.database_text_label = QLabel(self.db_file)
                self.select_excel_button.setEnabled(True)
                self.group_button.setEnabled(True)
                self.filter_button.setEnabled(True)
            else:
                self.database_text_label = QLabel("None selected")
                self.filter_button.setDisabled(True)
                self.group_button.setDisabled(True)
                self.select_excel_button.setDisabled(True)

            if self.excel_file:
                self.excel_file_text_label = QLabel(self.excel_file)
                self.export_button.setEnabled(True)
            else:
                self.excel_file_text_label = QLabel("None selected")
                self.export_button.setEnabled(False)
                
            # Add dropdown list for chart type
            self.export_type_label = QLabel("Chart type:")
            self.export_type_combobox = QComboBox()
            self.export_type_combobox.addItem("Line")
            self.export_type_combobox.addItem("Scatter")
            self.export_type_combobox.setCurrentText("Line")
            self.export_type_label.setToolTip(
                "Use this menu to select the type of charts in Excel sheets\n"
                "On line chart samples numbers are visible\n"
                "On scatter chart parts are numbered sequentially from 1"
            )
            self.export_type_combobox.setToolTip(
                "Use this menu to select the type of charts in Excel sheets\n"
                "On line chart samples numbers are visible\n"
                "On scatter chart parts are numbered sequentially from 1"
            )
            
            # Add dropdown list for chart type
            self.sort_measurements_label = QLabel("Sort measurements by:")
            self.sort_measurements_combobox = QComboBox()
            self.sort_measurements_combobox.addItem("Date")
            self.sort_measurements_combobox.addItem("Sample #")
            self.sort_measurements_combobox.setCurrentText("Date")
            self.sort_measurements_label.setToolTip("Use this menu to select how data should be sorted - by date or measurement or sample number")
            self.sort_measurements_combobox.setToolTip("Use this menu to select how data should be sorted - by date or measurement or sample number")
            
            # Add textbox to set min samplesize for violin plot
            self.violin_plot_min_samplesize_label = QLabel("Min samplesize to generate violin plot instead of scatter: ")
            self.violin_plot_min_samplesize = QLineEdit()
            self.violin_plot_min_samplesize.setPlaceholderText('Min: 2, Default: 6')
            self.violin_plot_min_samplesize_label.setToolTip(
                "Works only if you choose 'Generate summary sheet' option!\n"
                "Use this menu to select how many measurements are required "
                "to generate violin chart instead of scatter"
            )
            self.violin_plot_min_samplesize.setToolTip(
                "Works only if you choose 'Generate summary sheet' option!\n"
                "Use this menu to select how many measurements are required "
                "to generate violin chart instead of scatter"
            )
            
            # Add textbox to set scale for y-axis
            self.summary_plot_scale_label = QLabel("Increase the limits on the y-axis by as many times: ")
            self.summary_plot_scale = QLineEdit()
            self.summary_plot_scale.setPlaceholderText('Default: 0')
            self.summary_plot_scale_label.setToolTip(
                "Works only if you choose 'Generate summary sheet' option!\n"
                "For instance, if you choose 0 (default), limits will be based on the minimum, maximum, and tolerance limits.\n"
                "If you choose 1, it will also add a 'buffer' to the minimum and maximum y-axis limits, resulting in a range that is three times larger."
            )
            self.summary_plot_scale.setToolTip(
                "Works only if you choose 'Generate summary sheet' option!\n"
                "For instance, if you choose 0 (default), limits will be based on the minimum, maximum, and tolerance limits.\n"
                "If you choose 1, it will also add a 'buffer' to the minimum and maximum y-axis limits, resulting in a range that is three times larger."
            )
            
            # Connect textChanged signal to validate_input function
            self.violin_plot_min_samplesize.textChanged.connect(self.validate_violin_plot_min_samplesize_input)
            self.summary_plot_scale.textChanged.connect(self.validate_plot_scale_input)
            
            # Add a QCheckBox for "Hide OK results?"
            self.hide_ok_results_checkbox = QCheckBox("Hide OK results?")
            self.hide_ok_results_checkbox.setChecked(False)
            self.hide_ok_results_checkbox.setToolTip("When enabled, only OK results will be visible (columns with OK results will be hidden, not deleted)")
            
            # Add a QCheckBox for "Generate summary sheet?"
            self.generate_summary_sheet_checkbox = QCheckBox("Generate summary sheet?")
            self.generate_summary_sheet_checkbox.setChecked(False)
            self.generate_summary_sheet_checkbox.setToolTip(
                "When enabled, additional sheets will be created for each reference with additional graphs (grouped scatter/violin, histograms with basic statistics)"
            )
        except Exception as e:
            self.log_and_exit(e)

    def init_layout(self):
        try:
            """Initialize the layout"""
            self.layout = QGridLayout()

            self.layout.addWidget(self.select_db_label, 0, 0)
            self.layout.addWidget(self.database_text_label, 1, 0)
            self.layout.addWidget(self.select_db_button, 2, 0, 1, 2)
            self.layout.addWidget(self.spacer, 3, 0)

            self.layout.addWidget(self.select_excel_label, 4, 0)
            self.layout.addWidget(self.excel_file_text_label, 5, 0)
            self.layout.addWidget(self.select_excel_button, 6, 0, 1, 2)
            self.layout.addWidget(self.spacer, 7, 0)

            self.layout.addWidget(self.select_filter_label, 8, 0)
            self.layout.addWidget(self.filter_button, 9, 0, 1, 2)
            self.layout.addWidget(self.spacer, 10, 0)
            
            self.layout.addWidget(self.select_group_label, 11, 0)
            self.layout.addWidget(self.group_button, 12, 0, 1, 2)
            self.layout.addWidget(self.spacer, 13, 0)

            self.layout.addWidget(self.export_button, 14, 0, 1, 2)

            self.layout.addWidget(self.export_type_label, 15, 0)
            self.layout.addWidget(self.export_type_combobox, 15, 1)
            
            self.layout.addWidget(self.sort_measurements_label, 16, 0)
            self.layout.addWidget(self.sort_measurements_combobox, 16, 1)
            
            self.layout.addWidget(self.violin_plot_min_samplesize_label, 17, 0)
            self.layout.addWidget(self.violin_plot_min_samplesize, 17, 1)
            
            self.layout.addWidget(self.summary_plot_scale_label, 18, 0)
            self.layout.addWidget(self.summary_plot_scale, 18, 1)
            
            self.layout.addWidget(self.hide_ok_results_checkbox, 19, 0)
            
            self.layout.addWidget(self.generate_summary_sheet_checkbox, 19, 1)
            
            self.setLayout(self.layout)
        except Exception as e:
            self.log_and_exit(e)
        
    def validate_violin_plot_min_samplesize_input(self):
        try:
            # Get user input
            user_input = self.violin_plot_min_samplesize.text()

            # Validate if input is an integer and >= 2
            try:
                input_value = int(user_input)
                if input_value < 2:
                    input_value = 2
            except ValueError:
                # Replace non-integer input with default value
                input_value = 6

            # Update the textbox with the validated value
            self.violin_plot_min_samplesize.setText(str(input_value))
        except Exception as e:
            self.log_and_exit(e)
            
    def validate_plot_scale_input(self):
        try:
            # Get user input
            user_input = self.summary_plot_scale.text()

            # Validate if input is a float > 0
            try:
                input_value = float(user_input)
                if input_value <= 0:
                    input_value = 0
            except ValueError:
                # Replace non-number with default value
                input_value = 0

            # Update the textbox with the validated value
            self.summary_plot_scale.setText(str(input_value))
        except Exception as e:
            self.log_and_exit(e)

    def select_db_file(self):
        try:
            """Open a file dialog to select a database file"""
            filename, _ = QFileDialog.getOpenFileName(self, "Select a database file", "",
                                                    "SQLite database (*.db);;All files (*)")
            if filename:
                if not filename.endswith(".db"):
                    filename += ".db"
                print(f"{filename=}")
                self.db_file = filename
                self.database_text_label.setText(filename)
                self.select_excel_button.setEnabled(True)
                self.filter_button.setEnabled(True)
                self.group_button.setEnabled(True)
                self.parent().set_db_file(filename)
        except Exception as e:
            self.log_and_exit(e)

    def open_filter_window(self):
        try:
            # Check if export dialog is already open or visible
            if not self.filter_window:
                # Create a new export dialog if not already existing or visible
                self.filter_window = FilterDialog(self, db_file=self.db_file)
            if not self.filter_window.isVisible():
                self.filter_window.show()

            # Raise the export dialog to the top and activate it
            self.filter_window.raise_()
            self.filter_window.activateWindow()
        except Exception as e:
            self.log_and_exit(e)
            
    def open_grouping_window(self):
        try:
            # Check if grouping dialog is already open or visible
            if not self.grouping_window:
                # Create a new grouping dialog if not already existing or visible
                self.grouping_window = DataGrouping(self, db_file=self.db_file)
            if not self.grouping_window.isVisible():
                self.grouping_window.show()

            # Raise the grouping dialog to the top and activate it
            self.grouping_window.raise_()
            self.grouping_window.activateWindow()
        except Exception as e:
            self.log_and_exit(e)
            
    def set_filter_query(self, query):
        try:
            self.filter_query = query
        except Exception as e:
            self.log_and_exit(e)
            
    def set_df_for_grouping(self, df):
        try:
            self.df_for_grouping = df
        except Exception as e:
            self.log_and_exit(e)
    
    def get_filter_query(self):
        try:
            return self.filter_query
        except Exception as e:
            self.log_and_exit(e)
            
    def set_filter_applied(self):
        try:
            # Update filter label in export window
            self.select_filter_label.setText("Select filters (optional): applied")
        except Exception as e:
            self.log_and_exit(e)
    
    def set_grouping_applied(self, applied):
        try:
            # Update filter label in export window
            if applied:
                self.select_group_label.setText("Group data (optional): applied")
            else:
                self.select_group_label.setText("Group data (optional): not applied")
        except Exception as e:
            self.log_and_exit(e)

    def select_excel_file(self):
        try:
            """Open a file dialog to select an excel file"""
            default_name = self.db_file[:-3]
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

            filename, _ = QFileDialog.getSaveFileName(self, "Select an Excel file", str(file_path),
                                                    "Excel workbook (*.xlsx);;All files (*)")#, options=options)

            if filename:
                file_path = Path(filename)
                print(f"{file_path=}")
                self.excel_file = file_path
                self.excel_file_text_label.setText(str(file_path))
                self.export_button.setEnabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def show_loading_screen(self):
        try:
            # Create the progress dialog
            self.loading_dialog = QDialog(self, Qt.WindowTitleHint)
            self.loading_dialog.setWindowTitle("Exporting data...")
            self.loading_dialog.setWindowModality(Qt.ApplicationModal)
            self.loading_dialog.setFixedSize(400, 300)

            # Create a QLabel to display the loading GIF
            loading_gif_label = QLabel(self.loading_dialog)
            loading_gif_label.setFixedSize(200, 200)
            loading_gif_label.setAlignment(Qt.AlignCenter)

            # Load the loading.gif from a file, create a QMovie from it, and set it to the label
            loading_gif_decoded = base64.b64decode(base64_encoded_files.encoded_loading_gif)

            # Create temporary file and save encoded loading gif to it
            temp_file = QTemporaryFile()
            temp_file.setAutoRemove(False)
            temp_file_name = ""
            if temp_file.open():
                temp_file.write(loading_gif_decoded)
                temp_file.close()
                temp_file_name = temp_file.fileName()

            # Create the QMovie using the temporary file name
            self.loading_gif = QMovie(temp_file_name)
            self.loading_gif.setScaledSize(QSize(200, 200))
            loading_gif_label.setMovie(self.loading_gif)
            self.loading_gif.start()

            # Create the loading label and progress bar
            self.loading_label = QLabel("Exporting data...", self.loading_dialog)
            self.loading_label.setAlignment(Qt.AlignCenter)

            self.loading_bar = QProgressBar(self.loading_dialog)
            self.loading_bar.setValue(0)
            self.loading_bar.setFixedSize(380, 20)
            self.loading_bar.setAlignment(Qt.AlignCenter)

            # Create a layout for the progress dialog and add the loading GIF, loading label, and progress bar to it
            layout = QVBoxLayout(self.loading_dialog)
            layout.addWidget(loading_gif_label, alignment=Qt.AlignHCenter)
            layout.addWidget(self.loading_label, alignment=Qt.AlignHCenter)
            layout.addWidget(self.loading_bar, alignment=Qt.AlignHCenter)

            # Create and add the Cancel button to the layout
            cancel_button = QPushButton("Cancel", self.loading_dialog)
            cancel_button.clicked.connect(self.stop_exporting)
            layout.addWidget(cancel_button, alignment=Qt.AlignHCenter)

            # Disable the export button and show the progress dialog
            self.export_button.setDisabled(True)
            self.loading_dialog.show()

            # Get the selected chart type
            selected_export_type = self.export_type_combobox.currentText()
            
            # Get the selected sorting parameter
            selected_sorting_parameter = self.sort_measurements_combobox.currentText()
            
            # Get the min samplesize for violin plot
            if not self.violin_plot_min_samplesize.text():
                self.violin_plot_min_samplesize.setText(str(6))
            if int(self.violin_plot_min_samplesize.text()) < 2:
                self.violin_plot_min_samplesize.setText(str(2))
            violin_plot_min_samplesize = int(self.violin_plot_min_samplesize.text())
            
            if not self.summary_plot_scale.text():
                self.summary_plot_scale.setText(str(0))
            if float(self.summary_plot_scale.text()) <= 0:
                self.summary_plot_scale.setText(str(0))
            summary_plot_scale = float(self.summary_plot_scale.text())
            
            # Get the state of the "Hide OK results?" checkbox
            hide_ok_results = self.hide_ok_results_checkbox.isChecked()
            
            # Get the state of the "Generate summary sheet?" checkbox
            generate_summary_sheet = self.generate_summary_sheet_checkbox.isChecked()

            # Start the exporting thread with the selected chart type
            self.export_thread = ExportDataThread(
                self.db_file,
                self.excel_file,
                self.filter_query,
                self.df_for_grouping,
                selected_export_type,
                selected_sorting_parameter,
                violin_plot_min_samplesize,
                summary_plot_scale,
                hide_ok_results,
                generate_summary_sheet,
            )
            self.export_thread.update_label.connect(self.loading_label.setText)
            self.export_thread.update_progress.connect(self.loading_bar.setValue)
            self.export_thread.finished.connect(self.on_export_finished)
            self.export_thread.start()
        except Exception as e:
            self.log_and_exit(e)

    def stop_exporting(self):
        try:
            # Stop the exporting thread
            self.export_thread.quit()

            # Check if the thread is still running and wait for it to finish
            if self.export_thread.isRunning():
                print("Export thread still running, waiting...")
                # TODO: remove terminate after changing way of export to line by line or something that can be stopped
                self.export_thread.terminate()
                self.export_thread.wait()
                print("Export thread closed successfully!")

            # Show a message box to inform the user that exporting has been cancelled
            QMessageBox.information(self, "Export canceled", "Data exporting has been canceled")

            self.loading_dialog.reject()
            self.close()
        except Exception as e:
            self.log_and_exit(e)

    def on_export_finished(self):
        try:
            # Show a message box to inform the user that exporting is complete
            QMessageBox.information(self, "Export successful", f"Data exported successfully to {self.excel_file}!")

            # Close the loading dialog
            self.loading_dialog.accept()

            # Re-enable the export button
            self.export_button.setEnabled(True)

            # Close the exporting dialog
            self.accept()
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        CustomLogger(exception)
