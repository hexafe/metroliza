"""Export dialog UI, export option builders, and completion message helpers."""

from modules.progress_status import build_three_line_status
from modules.export_data_thread import ExportDataThread
from modules.filter_dialog import FilterDialog
from modules.data_grouping import DataGrouping
from modules.custom_logger import CustomLogger
from modules.export_dialog_service import (
    build_export_completion_message,
    build_export_directory_link_line as build_export_directory_link_line,
    build_export_folder_link_line as build_export_folder_link_line,
    build_export_options_payload as build_export_options_payload,
    build_validated_export_request,
)
from modules.export_preset_utils import (
    build_export_options_for_preset,
    get_export_preset_id_for_label,
    get_export_preset_ids,
    get_export_preset_label,
    load_export_dialog_config,
    migrate_export_dialog_config,
    save_export_dialog_config,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import(
    QDialog,
    QFileDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QComboBox,
    QCheckBox,
    QHBoxLayout,
    QWidget,
)
import html
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from modules.worker_progress_dialog import create_worker_progress_dialog, set_worker_progress_dialog_cancel_state
from modules import ui_theme_tokens


_URL_PATTERN = re.compile(r"((?:https?|file)://[^\s]+)")


def format_message_with_clickable_links(message):
    """Convert plain-text message into rich text with clickable URLs."""
    safe_message = html.escape(str(message or ""))
    linked_message = _URL_PATTERN.sub(r'<a href="\1">\1</a>', safe_message)
    return linked_message.replace("\n", "<br>")


def handle_export_result_link(parent, url, excel_file=None):
    """Handle message-box link activation, revealing exported file when selected."""
    try:
        parsed = QUrl(str(url or ""))
    except Exception:
        parsed = QUrl()

    if parsed.isValid() and parsed.scheme() == 'file' and excel_file:
        try:
            clicked_path = Path(parsed.toLocalFile()).resolve(strict=False)
            exported_path = Path(str(excel_file)).resolve(strict=False)
            if clicked_path == exported_path:
                reveal_file_in_explorer(excel_file)
                return
        except Exception:
            pass

    QDesktopServices.openUrl(parsed if parsed.isValid() else QUrl(str(url or "")))


def show_export_result_message(parent, level, title, message, excel_file=None):
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

    message_label = dialog.findChild(QLabel, 'qt_msgbox_label') if hasattr(dialog, 'findChild') else None
    if message_label and hasattr(message_label, 'setOpenExternalLinks'):
        message_label.setOpenExternalLinks(False)
        if hasattr(message_label, 'linkActivated'):
            message_label.linkActivated.connect(lambda link: _open_export_result_link(parent, link, excel_file))

    dialog.exec()


def _open_export_result_link(parent, link, excel_file):
    try:
        handle_export_result_link(parent, link, excel_file=excel_file)
    except Exception as exc:
        try:
            QMessageBox.warning(
                parent,
                "Unable to open file location",
                f"Could not open the export location for {excel_file}.\n{exc}",
            )
        except Exception:
            logger.exception("Failed to show warning for export link activation failure.")


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
    """Dialog that gathers export settings and runs export work in a thread.

    Key state includes selected database/output files, optional filter/grouping
    selections, and persisted preset preferences stored in a user config file.
    """

    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        
        self.setWindowTitle("Export")
        self.setStyleSheet(ui_theme_tokens.dialog_shell_style())
        if parent is not None and hasattr(parent, "windowIcon"):
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
        self._cancel_requested = False
        self.config_path = Path.home() / '.metroliza' / '.export_dialog_config.json'
        self.config = self._load_dialog_config()

        self.init_widgets()
        self.init_layout()

    def _load_dialog_config(self):
        """Load and migrate persisted dialog settings from disk.

        Returns:
            dict: Configuration dictionary with at least a preset selection.
        """
        try:
            config = load_export_dialog_config(self.config_path)
            migrated, changed = migrate_export_dialog_config(config)
            if changed:
                save_export_dialog_config(self.config_path, migrated)
            return migrated
        except Exception:
            return {'selected_preset': 'fast_diagnostics'}

    def _save_dialog_config(self):
        """Persist currently selected preset to the user config file."""
        try:
            selected_label = self.preset_combobox.currentText()
            selected_preset = get_export_preset_id_for_label(selected_label)
            self.config['selected_preset'] = selected_preset
            save_export_dialog_config(self.config_path, self.config)
        except Exception as e:
            self.log_and_exit(e)

    def apply_selected_preset(self):
        """Apply the selected preset values to export controls and save them."""
        try:
            selected_preset = get_export_preset_id_for_label(self.preset_combobox.currentText())
            preset_options = build_export_options_for_preset(selected_preset)
            self.export_type_combobox.setCurrentText(preset_options['export_type'].title())
            self.sort_measurements_combobox.setCurrentText('Date' if preset_options['sorting_parameter'] == 'date' else 'Sample #')
            self.violin_plot_min_samplesize.setText(str(preset_options['violin_plot_min_samplesize']))
            self.summary_plot_scale.setText(str(preset_options['summary_plot_scale']))
            self.hide_ok_results_checkbox.setChecked(bool(preset_options['hide_ok_results']))
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

            self.select_filter_label = QLabel("Filters: none")
            self.filter_button = QPushButton("Set filters")
            self.filter_button.clicked.connect(self.open_filter_window)
            self.filter_button.setToolTip("Use this button to filter data from the database")
            
            self.select_group_label = QLabel("Grouping: none")
            self.group_button = QPushButton("Manage groups")
            self.group_button.clicked.connect(self.open_grouping_window)
            self.group_button.setToolTip("Use this button to group data")

            self.select_excel_label = QLabel("Select an excel file:")
            self.select_excel_button = QPushButton("Browse")
            self.select_excel_button.clicked.connect(self.select_excel_file)
            self.select_excel_label.setToolTip("Use this button to select the Excel file to which the data will be saved")
            self.select_excel_button.setToolTip("Use this button to select the Excel file to which the data will be saved")

            self.export_button = QPushButton("Export report")
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
            self.preset_label.setToolTip(
                "Main plots: exports core charts only.\n"
                "Extended plots: includes additional summary plots and statistics sheets."
            )
            self.preset_combobox.setToolTip(self.preset_label.toolTip())

            self.export_target_label = QLabel("Google Sheets export:")
            self.include_google_sheets_checkbox = QCheckBox(
                "Also create Google Sheets version (Excel file is always kept locally)"
            )
            self.include_google_sheets_checkbox.setChecked(False)
            self.google_sheets_note_label = QLabel(
                "Note: A local .xlsx is always created. Google Sheets conversion is optional and may look slightly different from Excel."
            )
            self.google_sheets_note_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_HELPER))
            self.google_sheets_note_label.setWordWrap(True)
            self.export_target_label.setToolTip(
                "Excel (.xlsx) is always generated.\n"
                "Enable this option to also upload and convert the workbook to Google Sheets."
            )
            self.include_google_sheets_checkbox.setToolTip(
                "Excel (.xlsx) is always generated.\n"
                "Enable this option to also upload and convert the workbook to Google Sheets."
            )
            self.google_sheets_note_label.setToolTip(
                "Excel (.xlsx) is always generated locally.\n"
                "Google Sheets conversion can have minor fidelity differences."
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

            self.group_analysis_level_label = QLabel("Group analysis level:")
            self.group_analysis_level_combobox = QComboBox()
            self.group_analysis_level_combobox.addItem("Off")
            self.group_analysis_level_combobox.addItem("Light")
            self.group_analysis_level_combobox.addItem("Standard")
            self.group_analysis_level_label.setToolTip(
                "Controls workbook-level Group Analysis output.\n"
                "Off: disabled.\n"
                "Light: compact statistical report + Diagnostics.\n"
                "Standard: Light plus additional supported plots."
            )
            self.group_analysis_level_combobox.setToolTip(self.group_analysis_level_label.toolTip())
            self.group_analysis_level_combobox.currentTextChanged.connect(lambda _: self._update_group_analysis_scope_enabled_state())

            self.group_analysis_scope_label = QLabel("Group analysis scope:")
            self.group_analysis_scope_combobox = QComboBox()
            self.group_analysis_scope_combobox.addItem("Auto")
            self.group_analysis_scope_combobox.addItem("Single-reference")
            self.group_analysis_scope_combobox.addItem("Multi-reference")
            self.group_analysis_scope_label.setToolTip(
                "Choose how Group Analysis resolves references.\n"
                "Auto uses filtered grouped rows.\n"
                "Single-reference and Multi-reference force scope checks."
            )
            self.group_analysis_scope_combobox.setToolTip(self.group_analysis_scope_label.toolTip())
            self._update_group_analysis_scope_enabled_state()
            
            # Add textbox to set min samplesize for violin plot
            self.violin_plot_min_samplesize_label = QLabel("Min samplesize to generate violin plot instead of scatter: ")
            self.violin_plot_min_samplesize = QLineEdit()
            self.violin_plot_min_samplesize.setPlaceholderText('Min: 2, Default: 6')
            self.violin_plot_min_samplesize_label.setToolTip(
                "Minimum sample count before violin plots are used in Extended plots."
            )
            self.violin_plot_min_samplesize.setToolTip(
                "Minimum sample count before violin plots are used in Extended plots."
            )
            
            # Add textbox to set scale for y-axis
            self.summary_plot_scale_label = QLabel("Increase the limits on the y-axis by as many times: ")
            self.summary_plot_scale = QLineEdit()
            self.summary_plot_scale.setPlaceholderText('Default: 0')
            self.summary_plot_scale_label.setToolTip(
                "Scale factor for expanding summary-plot y-axis limits in Extended plots; 0 keeps automatic limits."
            )
            self.summary_plot_scale.setToolTip(
                "Scale factor for expanding summary-plot y-axis limits in Extended plots; 0 keeps automatic limits."
            )
            
            # Connect textChanged signal to validate_input function
            self.violin_plot_min_samplesize.textChanged.connect(self.validate_violin_plot_min_samplesize_input)
            self.summary_plot_scale.textChanged.connect(self.validate_plot_scale_input)
            
            # Hide passing columns in measurement sheets
            self.hide_ok_results_checkbox = QCheckBox("Hide columns that contain only in-tolerance (OK) results")
            self.hide_ok_results_checkbox.setChecked(False)
            self.hide_ok_results_checkbox.setToolTip(
                "Enable to hide measurement columns where every value passes tolerance (OK).\n"
                "The data is still kept in the workbook and can be unhidden later."
            )

            self.advanced_details_toggle = QCheckBox("Show formatting details")
            self.advanced_details_toggle.setChecked(False)
            self.advanced_details_toggle.setToolTip("Show or hide less-used workbook formatting options.")

            self.advanced_options_toggle = QCheckBox("Show advanced options")
            self.advanced_options_toggle.setChecked(False)
            self.advanced_options_toggle.setToolTip("Show or hide optional export profile and analysis controls.")

            self.scope_help_label = QLabel(
                "Review the current export scope (filters and grouping)."
            )
            self.scope_help_label.setWordWrap(True)
            self.scope_help_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_HELPER))

            self.destination_help_label = QLabel(
                "Review source/destination files and optional Google Sheets output."
            )
            self.destination_help_label.setWordWrap(True)
            self.destination_help_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_HELPER))

            self.advanced_options_help_label = QLabel(
                "Optional settings for profile, chart behavior, and workbook formatting."
            )
            self.advanced_options_help_label.setWordWrap(True)
            self.advanced_options_help_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_HELPER))
            
            self.advanced_options_layout = QVBoxLayout()
            self.advanced_options_layout.setContentsMargins(0, 0, 0, 0)
            self.advanced_options_layout.setSpacing(6)
            self.advanced_options_layout.addWidget(self.violin_plot_min_samplesize_label)
            self.advanced_options_layout.addWidget(self.violin_plot_min_samplesize)
            self.advanced_options_layout.addWidget(self.summary_plot_scale_label)
            self.advanced_options_layout.addWidget(self.summary_plot_scale)
            self.advanced_options_layout.addWidget(self.hide_ok_results_checkbox)

            self.advanced_details_widget = QWidget()
            self.advanced_details_widget.setLayout(self.advanced_options_layout)
            self.advanced_details_widget.setVisible(False)
            self.advanced_details_toggle.toggled.connect(self.advanced_details_widget.setVisible)

            self.close_button = QPushButton("Cancel")
            self.close_button.clicked.connect(self.reject)

            self._apply_shared_theme_styles()
            self.apply_selected_preset()
        except Exception as e:
            self.log_and_exit(e)

    def _apply_shared_theme_styles(self):
        button_map = {
            self.export_button: 'primary',
            self.close_button: 'tertiary',
            self.select_db_button: 'secondary',
            self.filter_button: 'secondary',
            self.group_button: 'secondary',
            self.select_excel_button: 'secondary',
        }
        for button, variant in button_map.items():
            button.setStyleSheet(ui_theme_tokens.button_style(variant))

        input_style = ui_theme_tokens.input_style()
        for widget in (
            self.preset_combobox,
            self.export_type_combobox,
            self.sort_measurements_combobox,
            self.group_analysis_level_combobox,
            self.group_analysis_scope_combobox,
            self.violin_plot_min_samplesize,
            self.summary_plot_scale,
        ):
            widget.setStyleSheet(input_style)

        info_style = ui_theme_tokens.typography_style('body', ui_theme_tokens.COLOR_TEXT_SECONDARY)
        for label in (
            self.select_filter_label,
            self.select_group_label,
            self.database_text_label,
            self.excel_file_text_label,
        ):
            label.setStyleSheet(info_style)

    def init_layout(self):
        try:
            """Initialize the layout"""
            self.layout = QVBoxLayout()
            self.layout.setSpacing(ui_theme_tokens.SPACE_12)

            def build_section_widget(title, content_layout):
                section_widget = QWidget()
                section_widget.setStyleSheet(ui_theme_tokens.panel_style(card=True).replace("QFrame", "QWidget"))
                section_layout = QVBoxLayout(section_widget)
                section_layout.setContentsMargins(
                    ui_theme_tokens.SPACE_12,
                    ui_theme_tokens.SPACE_12,
                    ui_theme_tokens.SPACE_12,
                    ui_theme_tokens.SPACE_12,
                )
                section_layout.setSpacing(ui_theme_tokens.SPACE_8)

                section_title = QLabel(title)
                section_title.setStyleSheet(ui_theme_tokens.typography_style("section", ui_theme_tokens.COLOR_TEXT_PRIMARY))
                section_layout.addWidget(section_title)
                section_layout.addLayout(content_layout)
                return section_widget

            scope_layout = QGridLayout()
            scope_layout.setContentsMargins(0, 0, 0, 0)
            scope_layout.setHorizontalSpacing(ui_theme_tokens.SPACE_8)
            scope_layout.setVerticalSpacing(4)
            scope_layout.addWidget(self.scope_help_label, 0, 0, 1, 2)
            scope_layout.addWidget(self.select_filter_label, 1, 0)
            scope_layout.addWidget(self.filter_button, 1, 1)
            scope_layout.addWidget(self.select_group_label, 2, 0)
            scope_layout.addWidget(self.group_button, 2, 1)

            destination_layout = QGridLayout()
            destination_layout.setContentsMargins(0, 0, 0, 0)
            destination_layout.setVerticalSpacing(6)
            destination_layout.addWidget(self.destination_help_label, 0, 0, 1, 2)
            destination_layout.addWidget(self.select_db_label, 1, 0)
            destination_layout.addWidget(self.select_db_button, 1, 1)
            destination_layout.addWidget(self.database_text_label, 2, 0, 1, 2)
            destination_layout.addWidget(self.select_excel_label, 3, 0)
            destination_layout.addWidget(self.select_excel_button, 3, 1)
            destination_layout.addWidget(self.excel_file_text_label, 4, 0, 1, 2)
            destination_layout.addWidget(self.export_target_label, 5, 0)
            destination_layout.addWidget(self.include_google_sheets_checkbox, 5, 1)
            destination_layout.addWidget(self.google_sheets_note_label, 6, 0, 1, 2)

            report_profile_layout = QGridLayout()
            report_profile_layout.setContentsMargins(0, 0, 0, 0)
            report_profile_layout.setVerticalSpacing(6)
            report_profile_layout.addWidget(self.preset_label, 0, 0)
            preset_selector_layout = QHBoxLayout()
            preset_selector_layout.setContentsMargins(0, 0, 0, 0)
            preset_selector_layout.addWidget(self.preset_combobox)
            report_profile_layout.addLayout(preset_selector_layout, 0, 1)
            report_profile_layout.addWidget(self.export_type_label, 1, 0)
            report_profile_layout.addWidget(self.export_type_combobox, 1, 1)
            report_profile_layout.addWidget(self.sort_measurements_label, 2, 0)
            report_profile_layout.addWidget(self.sort_measurements_combobox, 2, 1)

            advanced_layout = QVBoxLayout()
            advanced_layout.setContentsMargins(0, 0, 0, 0)
            advanced_layout.setSpacing(8)

            advanced_content_layout = QVBoxLayout()
            advanced_content_layout.setContentsMargins(0, 0, 0, 0)
            advanced_content_layout.setSpacing(ui_theme_tokens.SPACE_8)
            advanced_content_layout.addLayout(report_profile_layout)

            group_analysis_layout = QGridLayout()
            group_analysis_layout.setContentsMargins(0, 0, 0, 0)
            group_analysis_layout.setVerticalSpacing(6)
            group_analysis_layout.addWidget(self.group_analysis_level_label, 0, 0)
            group_analysis_layout.addWidget(self.group_analysis_level_combobox, 0, 1)
            group_analysis_layout.addWidget(self.group_analysis_scope_label, 1, 0)
            group_analysis_layout.addWidget(self.group_analysis_scope_combobox, 1, 1)
            advanced_content_layout.addLayout(group_analysis_layout)
            divider = QWidget()
            divider.setFixedHeight(1)
            divider.setStyleSheet(f"background-color: {ui_theme_tokens.COLOR_BORDER_MUTED};")
            advanced_content_layout.addWidget(divider)
            advanced_content_layout.addWidget(self.advanced_details_toggle)
            advanced_content_layout.addWidget(self.advanced_details_widget)

            self.advanced_content_widget = QWidget()
            self.advanced_content_widget.setLayout(advanced_content_layout)
            self.advanced_content_widget.setVisible(False)
            self.advanced_options_toggle.toggled.connect(self.advanced_content_widget.setVisible)

            advanced_layout.addWidget(self.advanced_options_help_label)
            advanced_layout.addWidget(self.advanced_options_toggle)
            advanced_layout.addWidget(self.advanced_content_widget)

            action_layout = QVBoxLayout()
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_help_label = QLabel("Export uses your current scope and destination.")
            action_help_label.setWordWrap(True)
            action_help_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_HELPER))
            action_layout.addWidget(action_help_label)
            action_button_row = QHBoxLayout()
            action_button_row.setContentsMargins(0, 0, 0, 0)
            action_button_row.addWidget(self.close_button)
            action_button_row.addStretch(1)
            action_button_row.addWidget(self.export_button)
            action_layout.addLayout(action_button_row)

            top_row_layout = QGridLayout()
            top_row_layout.setContentsMargins(0, 0, 0, 0)
            top_row_layout.setHorizontalSpacing(ui_theme_tokens.SPACE_12)
            top_row_layout.addWidget(build_section_widget("Scope", scope_layout), 0, 0)
            top_row_layout.addWidget(build_section_widget("Destination", destination_layout), 0, 1)

            self.layout.addLayout(top_row_layout)
            self.layout.addWidget(build_section_widget("Advanced options", advanced_layout))
            self.layout.addWidget(build_section_widget("Action", action_layout))

            self.setLayout(self.layout)

            self.setTabOrder(self.select_db_button, self.select_excel_button)
            self.setTabOrder(self.select_excel_button, self.filter_button)
            self.setTabOrder(self.filter_button, self.group_button)
            self.setTabOrder(self.group_button, self.preset_combobox)
            self.setTabOrder(self.preset_combobox, self.include_google_sheets_checkbox)
            self.setTabOrder(self.include_google_sheets_checkbox, self.export_type_combobox)
            self.setTabOrder(self.export_type_combobox, self.sort_measurements_combobox)
            self.setTabOrder(self.sort_measurements_combobox, self.group_analysis_level_combobox)
            self.setTabOrder(self.group_analysis_level_combobox, self.group_analysis_scope_combobox)
            self.setTabOrder(self.group_analysis_scope_combobox, self.violin_plot_min_samplesize)
            self.setTabOrder(self.violin_plot_min_samplesize, self.summary_plot_scale)
            self.setTabOrder(self.summary_plot_scale, self.hide_ok_results_checkbox)
            self.setTabOrder(self.hide_ok_results_checkbox, self.close_button)
            self.setTabOrder(self.close_button, self.export_button)
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
        """Open or focus the filter dialog while keeping a single dialog instance."""
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
        """Open/focus the grouping dialog and refresh data for reused instances."""
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
            self.select_filter_label.setText("Filters: active")
        except Exception as e:
            self.log_and_exit(e)
    
    def set_grouping_applied(self, applied):
        try:
            # Update filter label in export window
            if applied:
                self.select_group_label.setText("Grouping: active")
            else:
                self.select_group_label.setText("Grouping: none")
        except Exception as e:
            self.log_and_exit(e)

    def select_excel_file(self):
        """Prompt for an output workbook path and avoid immediate name collisions."""
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
        """Validate inputs, persist options, and hand work to the export thread."""
        try:
            self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif = create_worker_progress_dialog(
                self,
                window_title="Exporting data...",
                initial_status_text=build_three_line_status("Exporting data...", "Preparing export thread", "ETA --"),
                on_cancel=self.stop_exporting,
            )

            # Disable the export button and show the progress dialog
            self.export_button.setDisabled(True)
            self.loading_dialog.show()

            violin_input = self.violin_plot_min_samplesize.text() or "6"
            summary_scale_input = self.summary_plot_scale.text() or "0"

            selected_preset = get_export_preset_id_for_label(self.preset_combobox.currentText())
            self.config['selected_preset'] = selected_preset
            save_export_dialog_config(self.config_path, self.config)

            export_request = build_validated_export_request(
                db_file=self.db_file,
                excel_file=self.excel_file,
                selected_preset=selected_preset,
                export_type=self.export_type_combobox.currentText(),
                export_target=self._selected_export_target(),
                sorting_parameter=self.sort_measurements_combobox.currentText(),
                violin_input=violin_input,
                summary_scale_input=summary_scale_input,
                hide_ok_results=self.hide_ok_results_checkbox.isChecked(),
                filter_query=self.filter_query,
                grouping_df=self.df_for_grouping,
                group_analysis_level=self._selected_group_analysis_level(),
                group_analysis_scope=self._selected_group_analysis_scope(),
            )

            # Normalize user-visible values after validation/coercion.
            self.violin_plot_min_samplesize.setText(str(export_request.options.violin_plot_min_samplesize))
            self.summary_plot_scale.setText(str(export_request.options.summary_plot_scale))

            # Start the exporting thread with validated options
            self._cancel_requested = False
            self.export_thread = ExportDataThread(export_request=export_request)
            self.export_thread.update_label.connect(self.loading_label.setText)
            self.export_thread.update_progress.connect(self.loading_bar.setValue)
            self.export_thread.error_occurred.connect(self.on_export_error)
            self.export_thread.finished.connect(self.on_export_finished)
            self.export_thread.canceled.connect(self.on_export_canceled)
            self.export_thread.start()
        except Exception as e:
            self.log_and_exit(e)


    def _set_loading_cancel_enabled(self, enabled):
        if not hasattr(self, 'loading_dialog') or self.loading_dialog is None:
            return
        cancel_label = "Cancel" if enabled else "Canceling..."
        set_worker_progress_dialog_cancel_state(self.loading_dialog, enabled=enabled, label_text=cancel_label)

    def stop_exporting(self):
        """Request cooperative cancelation and keep UI responsive while waiting."""
        try:
            if self.export_thread is not None and self.export_thread.isRunning():
                if self._cancel_requested:
                    return
                self._cancel_requested = True
                self._set_loading_cancel_enabled(False)
                self.export_thread.stop_exporting()
                self.loading_label.setText(build_three_line_status("Cancel requested...", "Waiting for export thread to confirm cancellation", "ETA --"))
                return

            QMessageBox.information(self, "Export canceled", "Cancel confirmed. Data exporting has been canceled")
            self.loading_dialog.reject()
            self.export_button.setEnabled(True)
            self._cancel_requested = False
            self._set_loading_cancel_enabled(True)
        except Exception as e:
            self.log_and_exit(e)


    def on_export_error(self, message):
        """Store export error details for finalization once the worker stops."""
        self.export_error_message = message
        self.loading_label.setText(build_three_line_status("Export failed.", "See error details for context", "ETA --"))

    def on_export_canceled(self):
        """Handle explicit worker cancelation and restore dialog state."""
        try:
            QMessageBox.information(self, "Export canceled", "Cancel confirmed. Data exporting has been canceled")
            self.loading_dialog.reject()
            self.export_button.setEnabled(True)
            self._cancel_requested = False
            self._set_loading_cancel_enabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def on_export_finished(self):
        """Finalize export flow with success/error messaging and UI reset."""
        try:
            if self.export_error_message:
                QMessageBox.warning(self, "Export failed", self.export_error_message)
            else:
                level, title, message = build_export_completion_message(
                    excel_file=self.excel_file,
                    export_target=getattr(self.export_thread, 'export_target', 'excel_xlsx'),
                    completion_metadata=getattr(self.export_thread, 'completion_metadata', {}),
                )

                try:
                    show_export_result_message(self, level, title, message, excel_file=self.excel_file)
                except Exception:
                    logger.exception("Failed to show rich export completion dialog; falling back to basic message box.")
                    QMessageBox.information(
                        self,
                        "Export successful",
                        f"Data exported successfully to {self.excel_file}.",
                    )

            # Close the loading dialog
            self.loading_dialog.accept()
            self._cancel_requested = False
            self._set_loading_cancel_enabled(True)
        except Exception as e:
            self.log_and_exit(e)
        finally:
            # Re-enable actions after completion flow and clear transient error state.
            self.export_button.setEnabled(True)
            self.export_error_message = None
            
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)

    def _selected_export_target(self):
        if self.include_google_sheets_checkbox.isChecked():
            return 'google_sheets_drive_convert'
        return 'excel_xlsx'

    def _selected_group_analysis_level(self):
        combobox = getattr(self, "group_analysis_level_combobox", None)
        if combobox is None:
            return "off"
        return combobox.currentText().strip().lower()

    def _selected_group_analysis_scope(self):
        combobox = getattr(self, "group_analysis_scope_combobox", None)
        if combobox is None:
            return "auto"
        return combobox.currentText().strip().lower()

    def _update_group_analysis_scope_enabled_state(self):
        level = self._selected_group_analysis_level()
        enabled = level != "off"
        if hasattr(self, "group_analysis_scope_combobox"):
            self.group_analysis_scope_combobox.setEnabled(enabled)
        if hasattr(self, "group_analysis_scope_label"):
            self.group_analysis_scope_label.setEnabled(enabled)
