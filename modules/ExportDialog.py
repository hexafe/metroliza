from modules import Base64EncodedFiles
from modules.ExportDataThread import ExportDataThread
from modules.FilterDialog import FilterDialog
from modules.DataGrouping import DataGrouping
from modules.CustomLogger import CustomLogger
from modules.contracts import AppPaths, ExportOptions, ExportRequest, validate_export_options, validate_paths
from modules.export_preset_utils import (
    build_export_options_for_preset,
    get_export_preset_id_for_label,
    get_export_preset_ids,
    get_export_preset_label,
    load_export_dialog_config,
    migrate_export_dialog_config,
    save_export_dialog_config,
)
from PyQt6.QtCore import QSize, QTemporaryFile, Qt
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import(
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
import html
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path


def build_export_options_payload(selected_preset, export_type, export_target, sorting_parameter, violin_input, summary_scale_input, hide_ok_results, generate_summary_sheet):
    preset_options = build_export_options_for_preset(selected_preset)
    return ExportOptions(
        preset=selected_preset,
        export_type=export_type or preset_options['export_type'],
        export_target=export_target or ExportOptions.export_target,
        sorting_parameter=sorting_parameter or preset_options['sorting_parameter'],
        violin_plot_min_samplesize=int(violin_input if violin_input not in (None, "") else preset_options['violin_plot_min_samplesize']),
        summary_plot_scale=int(summary_scale_input if summary_scale_input not in (None, "") else preset_options['summary_plot_scale']),
        hide_ok_results=bool(hide_ok_results),
        generate_summary_sheet=bool(generate_summary_sheet),
    )


def build_export_completion_message(*, excel_file, export_target, completion_metadata):
    metadata = completion_metadata or {}
    warnings = [str(w) for w in metadata.get('conversion_warnings', []) if str(w).strip()]
    fallback_message = str(metadata.get('fallback_message', '')).strip()
    converted_url = str(metadata.get('converted_url', '')).strip()

    if export_target == 'google_sheets_drive_convert':
        if warnings or fallback_message:
            message_lines = [
                f"Data exported locally to {excel_file}.",
                "Google Sheets conversion was not fully completed.",
            ]
            if converted_url:
                message_lines.append(f"Google Sheet: {converted_url}")
            if fallback_message:
                message_lines.append(fallback_message)
            if warnings:
                message_lines.append("Warnings:")
                message_lines.extend(f"- {warning}" for warning in warnings)
            return 'warning', 'Export completed with Google fallback', "\n".join(message_lines)

        if converted_url:
            message_lines = [
                f"Data exported successfully to {excel_file}.",
                f"Google Sheet: {converted_url}",
            ]
            return 'info', 'Export successful', "\n".join(message_lines)

    return 'info', 'Export successful', f"Data exported successfully to {excel_file}!"


_URL_PATTERN = re.compile(r"(https?://[^\s]+)")


def format_message_with_clickable_links(message):
    """Convert plain-text message into rich text with clickable URLs."""
    safe_message = html.escape(str(message or ""))
    linked_message = _URL_PATTERN.sub(r'<a href="\1">\1</a>', safe_message)
    return linked_message.replace("\n", "<br>")


def show_export_result_message(parent, level, title, message):
    """Display export result message with external links enabled when supported."""
    dialog = QMessageBox(parent)
    icon = QMessageBox.Icon.Warning if level == 'warning' else QMessageBox.Icon.Information
    dialog.setIcon(icon)
    dialog.setWindowTitle(title)
    dialog.setText(format_message_with_clickable_links(message))
    if hasattr(dialog, 'setTextFormat') and hasattr(Qt, 'TextFormat'):
        dialog.setTextFormat(Qt.TextFormat.RichText)
    if hasattr(dialog, 'setTextInteractionFlags') and hasattr(Qt, 'TextInteractionFlag'):
        dialog.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    if hasattr(dialog, 'setStandardButtons'):
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
    dialog.exec()


def reveal_file_in_explorer(file_path):
    """Open OS file explorer and highlight exported file when possible."""
    target_path = Path(file_path)
    if not target_path.exists():
        raise FileNotFoundError(f"Exported file does not exist: {target_path}")

    if sys.platform.startswith('win'):
        # Windows explorer may return 1 even when the folder opens and the file is selected.
        # Treat 0 and 1 as success to avoid showing a false error dialog.
        completed = subprocess.run(["explorer", "/select,", str(target_path)], check=False)
        if completed.returncode not in (0, 1):
            raise subprocess.CalledProcessError(completed.returncode, completed.args)
        return

    if sys.platform == 'darwin':
        subprocess.run(["open", "-R", str(target_path)], check=True)
        return

    folder = target_path.parent
    opener = shutil.which('xdg-open')
    if opener:
        subprocess.run([opener, str(folder)], check=True)
        return
    raise OSError("Unable to open file explorer on this platform.")




logger = logging.getLogger(__name__)


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
        self.export_thread = None
        self.export_error_message = None
        self.config_path = Path.home() / '.metroliza' / '.export_dialog_config.json'
        self.config = self._load_dialog_config()

        self.init_widgets()
        self.init_layout()

    def _load_dialog_config(self):
        try:
            config = load_export_dialog_config(self.config_path)
            migrated, changed = migrate_export_dialog_config(config)
            if changed:
                save_export_dialog_config(self.config_path, migrated)
            return migrated
        except Exception:
            return {'selected_preset': 'fast_diagnostics'}

    def _save_dialog_config(self):
        try:
            selected_label = self.preset_combobox.currentText()
            selected_preset = get_export_preset_id_for_label(selected_label)
            self.config['selected_preset'] = selected_preset
            save_export_dialog_config(self.config_path, self.config)
        except Exception as e:
            self.log_and_exit(e)

    def apply_selected_preset(self):
        try:
            selected_preset = get_export_preset_id_for_label(self.preset_combobox.currentText())
            preset_options = build_export_options_for_preset(selected_preset)
            self.export_type_combobox.setCurrentText(preset_options['export_type'].title())
            self.sort_measurements_combobox.setCurrentText('Date' if preset_options['sorting_parameter'] == 'date' else 'Sample #')
            self.violin_plot_min_samplesize.setText(str(preset_options['violin_plot_min_samplesize']))
            self.summary_plot_scale.setText(str(preset_options['summary_plot_scale']))
            self.hide_ok_results_checkbox.setChecked(bool(preset_options['hide_ok_results']))
            self.generate_summary_sheet_checkbox.setChecked(bool(preset_options['generate_summary_sheet']))
            self._save_dialog_config()
        except Exception as e:
            self.log_and_exit(e)

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
                
            # Export preset selector
            self.preset_label = QLabel("Export preset:")
            self.preset_combobox = QComboBox()
            for preset_id in get_export_preset_ids():
                self.preset_combobox.addItem(get_export_preset_label(preset_id))
            selected_preset = self.config.get('selected_preset', 'fast_diagnostics')
            self.preset_combobox.setCurrentText(get_export_preset_label(selected_preset))
            self.preset_combobox.currentTextChanged.connect(lambda _: self.apply_selected_preset())

            self.export_target_label = QLabel("Google Sheets export:")
            self.include_google_sheets_checkbox = QCheckBox("Include Google Sheets conversion")
            self.include_google_sheets_checkbox.setChecked(False)
            self.export_target_label.setToolTip(
                "Excel (.xlsx) is always generated.\n"
                "Enable this option to also upload and convert the workbook to Google Sheets."
            )
            self.include_google_sheets_checkbox.setToolTip(
                "Excel (.xlsx) is always generated.\n"
                "Enable this option to also upload and convert the workbook to Google Sheets."
            )

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

            self.apply_selected_preset()
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

            self.layout.addWidget(self.preset_label, 15, 0)
            self.layout.addWidget(self.preset_combobox, 15, 1)

            self.layout.addWidget(self.export_target_label, 16, 0)
            self.layout.addWidget(self.include_google_sheets_checkbox, 16, 1)

            self.layout.addWidget(self.export_type_label, 17, 0)
            self.layout.addWidget(self.export_type_combobox, 17, 1)

            self.layout.addWidget(self.sort_measurements_label, 18, 0)
            self.layout.addWidget(self.sort_measurements_combobox, 18, 1)

            self.layout.addWidget(self.violin_plot_min_samplesize_label, 19, 0)
            self.layout.addWidget(self.violin_plot_min_samplesize, 19, 1)

            self.layout.addWidget(self.summary_plot_scale_label, 20, 0)
            self.layout.addWidget(self.summary_plot_scale, 20, 1)

            self.layout.addWidget(self.hide_ok_results_checkbox, 21, 0)

            self.layout.addWidget(self.generate_summary_sheet_checkbox, 21, 1)
            
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
                input_value = int(user_input)
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
                logger.info("Selected database file: %s", filename)
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
            else:
                self.grouping_window.refresh_data()
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
                logger.info("Selected export Excel file: %s", file_path)
                self.excel_file = file_path
                self.excel_file_text_label.setText(str(file_path))
                self.export_button.setEnabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def show_loading_screen(self):
        try:
            # Create the progress dialog
            self.loading_dialog = QDialog(self, Qt.WindowType.WindowTitleHint)
            self.loading_dialog.setWindowTitle("Exporting data...")
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
            self.loading_gif = QMovie(temp_file_name)
            self.loading_gif.setScaledSize(QSize(200, 200))
            loading_gif_label.setMovie(self.loading_gif)
            self.loading_gif.start()

            # Create the loading label and progress bar
            self.loading_label = QLabel("Exporting data...", self.loading_dialog)
            self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.loading_bar = QProgressBar(self.loading_dialog)
            self.loading_bar.setValue(0)
            self.loading_bar.setFixedSize(380, 20)
            self.loading_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Create a layout for the progress dialog and add the loading GIF, loading label, and progress bar to it
            layout = QVBoxLayout(self.loading_dialog)
            layout.addWidget(loading_gif_label, alignment=Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(self.loading_label, alignment=Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(self.loading_bar, alignment=Qt.AlignmentFlag.AlignHCenter)

            # Create and add the Cancel button to the layout
            cancel_button = QPushButton("Cancel", self.loading_dialog)
            cancel_button.clicked.connect(self.stop_exporting)
            layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

            # Disable the export button and show the progress dialog
            self.export_button.setDisabled(True)
            self.loading_dialog.show()

            violin_input = self.violin_plot_min_samplesize.text() or "6"
            summary_scale_input = self.summary_plot_scale.text() or "0"

            selected_preset = get_export_preset_id_for_label(self.preset_combobox.currentText())
            self.config['selected_preset'] = selected_preset
            save_export_dialog_config(self.config_path, self.config)

            options = validate_export_options(
                build_export_options_payload(
                    selected_preset=selected_preset,
                    export_type=self.export_type_combobox.currentText(),
                    export_target=self._selected_export_target(),
                    sorting_parameter=self.sort_measurements_combobox.currentText(),
                    violin_input=violin_input,
                    summary_scale_input=summary_scale_input,
                    hide_ok_results=self.hide_ok_results_checkbox.isChecked(),
                    generate_summary_sheet=self.generate_summary_sheet_checkbox.isChecked(),
                )
            )
            validate_paths(AppPaths(db_file=self.db_file, excel_file=str(self.excel_file)))

            # Normalize user-visible values after validation/coercion.
            self.violin_plot_min_samplesize.setText(str(options.violin_plot_min_samplesize))
            self.summary_plot_scale.setText(str(options.summary_plot_scale))

            export_request = ExportRequest(
                paths=AppPaths(db_file=self.db_file, excel_file=str(self.excel_file)),
                options=options,
                filter_query=self.filter_query,
                grouping_df=self.df_for_grouping,
            )

            # Start the exporting thread with validated options
            self.export_thread = ExportDataThread(export_request=export_request)
            self.export_thread.update_label.connect(self.loading_label.setText)
            self.export_thread.update_progress.connect(self.loading_bar.setValue)
            self.export_thread.error_occurred.connect(self.on_export_error)
            self.export_thread.finished.connect(self.on_export_finished)
            self.export_thread.canceled.connect(self.on_export_canceled)
            self.export_thread.start()
        except Exception as e:
            self.log_and_exit(e)

    def stop_exporting(self):
        try:
            # Request cooperative cancellation and return immediately to avoid blocking the UI thread
            if self.export_thread is not None and self.export_thread.isRunning():
                self.export_thread.stop_exporting()
                self.loading_label.setText("Canceling export...")
                return

            QMessageBox.information(self, "Export canceled", "Data exporting has been canceled")
            self.loading_dialog.reject()
            self.close()
        except Exception as e:
            self.log_and_exit(e)


    def on_export_error(self, message):
        self.export_error_message = message
        self.loading_label.setText("Export failed.")

    def on_export_canceled(self):
        try:
            QMessageBox.information(self, "Export canceled", "Data exporting has been canceled")
            self.loading_dialog.reject()
            self.export_button.setEnabled(True)
            self.close()
        except Exception as e:
            self.log_and_exit(e)

    def on_export_finished(self):
        try:
            if self.export_error_message:
                QMessageBox.warning(self, "Export failed", self.export_error_message)
            else:
                level, title, message = build_export_completion_message(
                    excel_file=self.excel_file,
                    export_target=getattr(self.export_thread, 'export_target', 'excel_xlsx'),
                    completion_metadata=getattr(self.export_thread, 'completion_metadata', {}),
                )

                show_export_result_message(self, level, title, message)

            # Close the loading dialog
            self.loading_dialog.accept()

            # Re-enable the export button
            self.export_button.setEnabled(True)

            exported_file = Path(str(self.excel_file))
            if not self.export_error_message and exported_file.exists():
                open_location = QMessageBox.question(
                    self,
                    "Export completed",
                    "Do you want to open the export location in file explorer?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if open_location == QMessageBox.StandardButton.Yes:
                    try:
                        reveal_file_in_explorer(exported_file)
                    except Exception as e:
                        QMessageBox.warning(self, "Open location failed", f"Could not open export location: {e}")

            self.export_error_message = None

            # Close the exporting dialog
            self.accept()
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)

    def _selected_export_target(self):
        if self.include_google_sheets_checkbox.isChecked():
            return 'google_sheets_drive_convert'
        return 'excel_xlsx'
