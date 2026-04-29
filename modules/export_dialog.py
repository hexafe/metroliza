"""Export dialog UI, export option builders, and completion message helpers."""

from modules.progress_status import build_three_line_status
from modules.export_data_thread import ExportDataThread
from modules.filter_dialog import FilterDialog
from modules.data_grouping import DataGrouping
import modules.custom_logger as custom_logger
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
    QApplication,
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
    QScrollArea,
    QSizePolicy,
    QToolButton,
)
import html
import inspect
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from modules.worker_progress_dialog import create_worker_progress_dialog
from modules.help_menu import attach_help_menu_to_layout
from modules.report_query_service import build_measurement_export_query


_URL_PATTERN = re.compile(r"((?:https?|file)://[^\s]+)")
DEFAULT_FILTER_QUERY = build_measurement_export_query()


def format_message_with_clickable_links(message):
    """Convert plain-text message into rich text with clickable URLs."""
    safe_message = html.escape(str(message or ""))
    linked_message = _URL_PATTERN.sub(r'<a href="\1">\1</a>', safe_message)
    return linked_message.replace("\n", "<br>")


def handle_export_result_link(parent, url, excel_file=None):
    """Handle message-box link activation, revealing exported file when selected."""
    parsed = QUrl(str(url or ""))

    if parsed.isValid() and parsed.scheme() == 'file' and excel_file:
        try:
            clicked_path = Path(parsed.toLocalFile()).resolve(strict=False)
            exported_path = Path(str(excel_file)).resolve(strict=False)
            if clicked_path == exported_path:
                reveal_file_in_explorer(excel_file)
                return
        except (OSError, ValueError) as exc:
            _log_exception(exc, context="resolve export result link path", reraise=False)

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
    except (OSError, ValueError, RuntimeError) as exc:
        try:
            QMessageBox.warning(
                parent,
                "Unable to open file location",
                f"Could not open the export location for {excel_file}.\n{exc}",
            )
        except (RuntimeError, TypeError) as warning_error:
            _log_exception(warning_error, context="show export link failure warning", reraise=False)
    except Exception as exc:
        _log_exception(exc, context="open export result link", reraise=False)
        raise


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


def _log_exception(exception, *, context, reraise=False):
    if hasattr(custom_logger, "handle_exception") and hasattr(custom_logger, "LOG_ONLY"):
        custom_logger.handle_exception(
            exception,
            behavior=custom_logger.LOG_ONLY,
            logger_name=logger.name,
            context=context,
            reraise=reraise,
        )
        return
    logger.exception("Unhandled exception during %s: %s", context, exception)
    if reraise:
        raise exception


class ExportDialog(QDialog):
    """Dialog that gathers export settings and runs export work in a thread.

    Key state includes selected database/output files, optional filter/grouping
    selections, and persisted preset preferences stored in a user config file.
    """

    def __init__(self, parent=None, db_file=""):
        super().__init__(parent)
        
        self.setWindowTitle("Export")
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 300, 150)

        self.db_file = db_file
        self.excel_file = ""
        self.filter_query = DEFAULT_FILTER_QUERY
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
        except (OSError, ValueError, TypeError):
            return {'selected_preset': 'fast_diagnostics'}
        except Exception as exc:
            _log_exception(exc, context="load export dialog config", reraise=False)
            raise

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
            required_controls = (
                'export_type_combobox',
                'sort_measurements_combobox',
                'violin_plot_min_samplesize',
                'summary_plot_scale',
                'hide_ok_results_checkbox',
            )
            if any(not hasattr(self, control_name) for control_name in required_controls):
                return

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
            self.select_db_label = QLabel("Database file:")
            self.select_db_button = QPushButton("Browse")
            self.select_db_button.clicked.connect(self.select_db_file)
            self.select_db_label.setToolTip("Select the database used as the source for this export.")
            self.select_db_button.setToolTip(self.select_db_label.toolTip())

            self.select_filter_label = QLabel("Not applied")
            self.select_filter_label.setToolTip("Optional export filters for AX, reference, header, or date range.")
            self.filter_button = QPushButton("Edit...")
            self.filter_button.clicked.connect(self.open_filter_window)
            self.filter_button.setToolTip("Edit the optional export filters.")
            
            self.select_group_label = QLabel("Not applied")
            self.select_group_label.setToolTip("Optional group assignments for grouped export workflows.")
            self.group_button = QPushButton("Edit...")
            self.group_button.clicked.connect(self.open_grouping_window)
            self.group_button.setToolTip("Edit the optional grouping assignments.")

            self.select_excel_label = QLabel("Excel file:")
            self.select_excel_button = QPushButton("Browse")
            self.select_excel_button.clicked.connect(self.select_excel_file)
            self.select_excel_label.setToolTip("Choose where the exported workbook will be written.")
            self.select_excel_button.setToolTip(self.select_excel_label.toolTip())

            self.export_button = QPushButton("Export")
            self.export_button.setDisabled(True)
            self.export_button.clicked.connect(self.show_loading_screen)
            self.export_button.setToolTip("Start exporting")
            self.export_button.setDefault(True)

            self.close_button = QPushButton("Close")
            self.close_button.clicked.connect(self.close)
            self.close_button.setToolTip("Close the export window without starting an export.")
            self.metadata_enrichment_notice_label = QLabel(
                "Metadata enrichment is running. Export will use the current database state."
            )
            self.metadata_enrichment_notice_label.setWordWrap(True)
            self.metadata_enrichment_notice_label.setVisible(False)
            self._refresh_metadata_enrichment_notice()

            self.database_text_label = self._build_path_field(self.db_file)
            self.excel_file_text_label = self._build_path_field(self.excel_file)
            self._set_path_field_value(self.database_text_label, self.db_file)
            self._set_path_field_value(self.excel_file_text_label, self.excel_file)

            # Export preset selector
            self.preset_label = QLabel("Preset:")
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

            self.export_target_label = QLabel("Optional outputs:")
            self.include_google_sheets_checkbox = QCheckBox("Google Sheets version")
            self.include_google_sheets_checkbox.setChecked(False)
            google_tooltip = (
                "Keep the local .xlsx workbook and also try to upload and convert it "
                "to Google Sheets."
            )
            self.export_target_label.setToolTip(google_tooltip)
            self.include_google_sheets_checkbox.setToolTip(google_tooltip)
            self.google_sheets_info_button = self._build_info_button(google_tooltip)

            self.html_dashboard_label = QLabel("")
            self.generate_html_dashboard_checkbox = QCheckBox("HTML dashboard")
            self.generate_html_dashboard_checkbox.setChecked(False)
            html_dashboard_tooltip = (
                "Create a local HTML sidecar for browser-based chart review next to the workbook."
            )
            self.html_dashboard_label.setToolTip(html_dashboard_tooltip)
            self.generate_html_dashboard_checkbox.setToolTip(html_dashboard_tooltip)
            self.html_dashboard_info_button = self._build_info_button(html_dashboard_tooltip)

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
            self.sort_measurements_label = QLabel("Sort by:")
            self.sort_measurements_combobox = QComboBox()
            self.sort_measurements_combobox.addItem("Date")
            self.sort_measurements_combobox.addItem("Sample #")
            self.sort_measurements_combobox.setCurrentText("Date")
            self.sort_measurements_label.setToolTip("Use this menu to select how data should be sorted - by date or measurement or sample number")
            self.sort_measurements_combobox.setToolTip("Use this menu to select how data should be sorted - by date or measurement or sample number")

            self.group_analysis_level_label = QLabel("Group analysis:")
            self.group_analysis_level_combobox = QComboBox()
            self.group_analysis_level_combobox.addItem("Off")
            self.group_analysis_level_combobox.addItem("Light")
            self.group_analysis_level_combobox.addItem("Standard")
            self.group_analysis_level_label.setToolTip(
                "Controls whether the canonical Group Analysis worksheet is added.\n"
                "Off: do not add grouped statistical output.\n"
                "Light: add the compact Group Analysis worksheet.\n"
                "Standard: add the same worksheet with additional supported on-sheet plots."
            )
            self.group_analysis_level_combobox.setToolTip(self.group_analysis_level_label.toolTip())
            self.group_analysis_level_combobox.currentTextChanged.connect(lambda _: self._update_group_analysis_scope_enabled_state())

            self.group_analysis_scope_label = QLabel("Scope:")
            self.group_analysis_scope_combobox = QComboBox()
            self.group_analysis_scope_combobox.addItem("Auto")
            self.group_analysis_scope_combobox.addItem("Single-reference")
            self.group_analysis_scope_combobox.addItem("Multi-reference")
            self.group_analysis_scope_label.setToolTip(
                "Choose how the Group Analysis worksheet resolves references.\n"
                "Auto uses the filtered grouped rows.\n"
                "Single-reference and Multi-reference enforce the corresponding scope check for that worksheet."
            )
            self.group_analysis_scope_combobox.setToolTip(self.group_analysis_scope_label.toolTip())
            
            # Add textbox to set min samplesize for violin plot
            self.violin_plot_min_samplesize_label = QLabel("Violin min n:")
            self.violin_plot_min_samplesize = QLineEdit()
            self.violin_plot_min_samplesize.setPlaceholderText('Min: 2, Default: 6')
            self.violin_plot_min_samplesize_label.setToolTip(
                "Minimum sample count before violin plots are used in Extended plots."
            )
            self.violin_plot_min_samplesize.setToolTip(
                "Minimum sample count before violin plots are used in Extended plots."
            )
            self.violin_plot_min_samplesize.setMaximumWidth(96)
            
            # Add textbox to set scale for y-axis
            self.summary_plot_scale_label = QLabel("Y-limit x:")
            self.summary_plot_scale = QLineEdit()
            self.summary_plot_scale.setPlaceholderText('Default: 0')
            self.summary_plot_scale_label.setToolTip(
                "Scale factor for expanding summary-plot y-axis limits in Extended plots; 0 keeps automatic limits."
            )
            self.summary_plot_scale.setToolTip(
                "Scale factor for expanding summary-plot y-axis limits in Extended plots; 0 keeps automatic limits."
            )
            self.summary_plot_scale.setMaximumWidth(96)
            
            # Connect textChanged signal to validate_input function
            self.violin_plot_min_samplesize.textChanged.connect(self.validate_violin_plot_min_samplesize_input)
            self.summary_plot_scale.textChanged.connect(self.validate_plot_scale_input)
            
            # Add a QCheckBox for "Hide OK results?"
            self.hide_ok_results_checkbox = QCheckBox("Hide OK results?")
            self.hide_ok_results_checkbox.setChecked(False)
            self.hide_ok_results_checkbox.setToolTip("When enabled, only OK results will be visible (columns with OK results will be hidden, not deleted)")
            
            self.advanced_options_container = QWidget()
            advanced_options_layout = QGridLayout(self.advanced_options_container)
            advanced_options_layout.setContentsMargins(0, 0, 0, 0)
            advanced_options_layout.setHorizontalSpacing(12)
            advanced_options_layout.setVerticalSpacing(6)
            advanced_options_layout.addWidget(self.violin_plot_min_samplesize_label, 0, 0)
            advanced_options_layout.addWidget(self.violin_plot_min_samplesize, 0, 1)
            advanced_options_layout.addWidget(self.summary_plot_scale_label, 0, 2)
            advanced_options_layout.addWidget(self.summary_plot_scale, 0, 3)
            advanced_options_layout.addWidget(self.hide_ok_results_checkbox, 1, 0, 1, 4)
            self.advanced_options_container.setVisible(False)

            self.advanced_toggle_button = QPushButton("Show advanced options")
            self.advanced_toggle_button.setCheckable(True)
            self.advanced_toggle_button.toggled.connect(self._toggle_advanced_options)
            self.advanced_toggle_button.setToolTip("Show or hide the rarely needed advanced export options.")

            self._set_compact_row_label_widths()
            self._update_group_analysis_scope_enabled_state()
            self._update_export_button_enabled_state()

            self.apply_selected_preset()
        except Exception as e:
            self.log_and_exit(e)

    def init_layout(self):
        try:
            """Initialize the layout"""
            self.layout = QVBoxLayout()
            self.layout.setContentsMargins(8, 8, 8, 8)
            self.layout.setSpacing(8)
            attach_help_menu_to_layout(
                self.layout,
                self,
                [("Export overview manual", 'export_overview'), ("Filtering manual", 'export_filtering'), ("Grouping manual", 'export_grouping')],
            )

            self.content_widget = QWidget()
            content_layout = QGridLayout(self.content_widget)
            content_layout.setContentsMargins(4, 4, 4, 4)
            content_layout.setHorizontalSpacing(12)
            content_layout.setVerticalSpacing(8)
            content_layout.setColumnStretch(1, 1)
            content_layout.setColumnStretch(3, 1)

            row = 0
            content_layout.addWidget(self.preset_label, row, 0)
            content_layout.addWidget(self.preset_combobox, row, 1, 1, 3)

            row += 1
            content_layout.addWidget(self.select_db_label, row, 0)
            content_layout.addWidget(self.database_text_label, row, 1, 1, 2)
            content_layout.addWidget(self.select_db_button, row, 3)

            row += 1
            content_layout.addWidget(self.select_excel_label, row, 0)
            content_layout.addWidget(self.excel_file_text_label, row, 1, 1, 2)
            content_layout.addWidget(self.select_excel_button, row, 3)

            row += 1
            content_layout.addWidget(self._build_separator(), row, 0, 1, 4)

            row += 1
            content_layout.addWidget(QLabel("Filters:"), row, 0)
            content_layout.addWidget(self.select_filter_label, row, 1, 1, 2)
            content_layout.addWidget(self.filter_button, row, 3)

            row += 1
            content_layout.addWidget(QLabel("Grouping:"), row, 0)
            content_layout.addWidget(self.select_group_label, row, 1, 1, 2)
            content_layout.addWidget(self.group_button, row, 3)

            row += 1
            content_layout.addWidget(self._build_separator(), row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.export_type_label, row, 0)
            content_layout.addWidget(self.export_type_combobox, row, 1)
            content_layout.addWidget(self.sort_measurements_label, row, 2)
            content_layout.addWidget(self.sort_measurements_combobox, row, 3)

            row += 1
            content_layout.addWidget(self.group_analysis_level_label, row, 0)
            content_layout.addWidget(self.group_analysis_level_combobox, row, 1)
            content_layout.addWidget(self.group_analysis_scope_label, row, 2)
            content_layout.addWidget(self.group_analysis_scope_combobox, row, 3)

            row += 1
            content_layout.addWidget(self._build_separator(), row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.export_target_label, row, 0)
            optional_outputs_widget = QWidget()
            optional_outputs_layout = QHBoxLayout(optional_outputs_widget)
            optional_outputs_layout.setContentsMargins(0, 0, 0, 0)
            optional_outputs_layout.setSpacing(12)
            optional_outputs_layout.addWidget(self.include_google_sheets_checkbox)
            optional_outputs_layout.addWidget(self.google_sheets_info_button)
            optional_outputs_layout.addSpacing(8)
            optional_outputs_layout.addWidget(self.generate_html_dashboard_checkbox)
            optional_outputs_layout.addWidget(self.html_dashboard_info_button)
            optional_outputs_layout.addStretch(1)
            content_layout.addWidget(optional_outputs_widget, row, 1, 1, 3)

            row += 1
            content_layout.addWidget(self.advanced_toggle_button, row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.advanced_options_container, row, 0, 1, 4)
            content_layout.setRowStretch(row + 1, 1)

            self.content_scroll_area = QScrollArea()
            self.content_scroll_area.setWidgetResizable(True)
            self.content_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.content_scroll_area.setWidget(self.content_widget)
            self.content_scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.layout.addWidget(self.content_scroll_area, 1)
            self.layout.addWidget(self.metadata_enrichment_notice_label)

            footer_layout = QHBoxLayout()
            footer_layout.setContentsMargins(0, 0, 0, 0)
            footer_layout.addStretch(1)
            footer_layout.addWidget(self.close_button)
            footer_layout.addWidget(self.export_button)
            self.layout.addLayout(footer_layout)

            self.setLayout(self.layout)
            self._apply_window_size_constraints()

            self.setTabOrder(self.preset_combobox, self.select_db_button)
            self.setTabOrder(self.select_db_button, self.select_excel_button)
            self.setTabOrder(self.select_excel_button, self.filter_button)
            self.setTabOrder(self.filter_button, self.group_button)
            self.setTabOrder(self.group_button, self.export_type_combobox)
            self.setTabOrder(self.export_type_combobox, self.sort_measurements_combobox)
            self.setTabOrder(self.sort_measurements_combobox, self.group_analysis_level_combobox)
            self.setTabOrder(self.group_analysis_level_combobox, self.group_analysis_scope_combobox)
            self.setTabOrder(self.group_analysis_scope_combobox, self.include_google_sheets_checkbox)
            self.setTabOrder(self.include_google_sheets_checkbox, self.generate_html_dashboard_checkbox)
            self.setTabOrder(self.generate_html_dashboard_checkbox, self.advanced_toggle_button)
            self.setTabOrder(self.advanced_toggle_button, self.violin_plot_min_samplesize)
            self.setTabOrder(self.violin_plot_min_samplesize, self.summary_plot_scale)
            self.setTabOrder(self.summary_plot_scale, self.hide_ok_results_checkbox)
            self.setTabOrder(self.hide_ok_results_checkbox, self.close_button)
            self.setTabOrder(self.close_button, self.export_button)
        except Exception as e:
            self.log_and_exit(e)

    def _refresh_metadata_enrichment_notice(self):
        if not hasattr(self, "metadata_enrichment_notice_label"):
            return False
        parent = self.parent()
        enrichment_active = (
            parent is not None
            and hasattr(parent, "is_metadata_enrichment_active")
            and parent.is_metadata_enrichment_active()
        )
        self.metadata_enrichment_notice_label.setVisible(bool(enrichment_active))
        return bool(enrichment_active)

    def _build_path_field(self, value):
        field = QLineEdit()
        field.setReadOnly(True)
        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._set_path_field_value(field, value)
        return field

    def _set_path_field_value(self, field, value, *, empty_text="None selected"):
        text = str(value or "").strip()
        if hasattr(field, "setText"):
            field.setText(text if text else empty_text)
        if hasattr(field, "setToolTip"):
            field.setToolTip(text if text else "")
        if text and hasattr(field, "setCursorPosition"):
            field.setCursorPosition(0)

    def _build_info_button(self, tooltip_text):
        button = QToolButton()
        button.setText("?")
        button.setAutoRaise(True)
        button.setToolTip(tooltip_text)
        if hasattr(Qt, "FocusPolicy"):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if hasattr(button, "setFixedSize"):
            button.setFixedSize(20, 20)
        return button

    def _build_separator(self):
        separator = QLabel("")
        separator.setStyleSheet("border-top: 1px solid #d7d7d7;")
        separator.setMinimumHeight(1)
        return separator

    def _set_compact_row_label_widths(self):
        for label in (
            self.preset_label,
            self.select_db_label,
            self.select_excel_label,
            self.export_type_label,
            self.sort_measurements_label,
            self.group_analysis_level_label,
            self.group_analysis_scope_label,
            self.export_target_label,
            self.violin_plot_min_samplesize_label,
            self.summary_plot_scale_label,
        ):
            label.setMinimumWidth(120)

    def _toggle_advanced_options(self, expanded):
        self.advanced_options_container.setVisible(bool(expanded))
        self.advanced_toggle_button.setText("Hide advanced options" if expanded else "Show advanced options")
        self._apply_window_size_constraints()

    def _available_geometry(self):
        screen = self.screen() if hasattr(self, "screen") else None
        if screen is None:
            app = QApplication.instance()
            screen = app.primaryScreen() if app is not None and hasattr(app, "primaryScreen") else None
        if screen is None or not hasattr(screen, "availableGeometry"):
            return None
        return screen.availableGeometry()

    def _apply_window_size_constraints(self):
        available_geometry = self._available_geometry()
        if available_geometry is None:
            return
        max_width = max(520, available_geometry.width() - 40)
        max_height = max(420, available_geometry.height() - 40)
        self.setMaximumSize(max_width, max_height)
        size_hint = self.sizeHint()
        self.resize(min(size_hint.width(), max_width), min(size_hint.height(), max_height))

    def _update_export_button_enabled_state(self):
        if not hasattr(self, "export_button"):
            return
        self.export_button.setEnabled(bool(str(self.db_file or "").strip()) and bool(str(self.excel_file or "").strip()))

    def _show_database_required_warning(self, action_name):
        QMessageBox.information(
            self,
            "Database required",
            f"Select a database file before you {action_name}.",
        )

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
                self._update_database_context(filename)
                parent = self.parent() if hasattr(self, "parent") else None
                if parent is not None and hasattr(parent, "set_db_file"):
                    parent.set_db_file(filename)
        except Exception as e:
            self.log_and_exit(e)

    def _discard_child_dialog(self, dialog_name):
        dialog = getattr(self, dialog_name, None)
        if dialog is None:
            return
        if hasattr(dialog, 'close'):
            dialog.close()
        if hasattr(dialog, 'deleteLater'):
            dialog.deleteLater()
        setattr(self, dialog_name, None)

    def _update_database_context(self, db_file):
        self.db_file = db_file
        self._set_path_field_value(self.database_text_label, db_file)

        self.filter_query = DEFAULT_FILTER_QUERY
        self.df_for_grouping = None
        self.select_filter_label.setText("Not applied")
        self.set_grouping_applied(False)
        self._update_export_button_enabled_state()

        self._discard_child_dialog('filter_window')
        self._discard_child_dialog('grouping_window')

    def open_filter_window(self):
        """Open or focus the filter dialog while keeping a single dialog instance."""
        try:
            if not str(self.db_file or "").strip():
                self._show_database_required_warning("edit filters")
                return
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
            if not str(self.db_file or "").strip():
                self._show_database_required_warning("edit grouping")
                return
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
            self.select_filter_label.setText("Applied")
        except Exception as e:
            self.log_and_exit(e)
    
    def set_grouping_applied(self, applied):
        try:
            # Update filter label in export window
            if applied:
                self.select_group_label.setText("Applied")
                if hasattr(self, "group_analysis_level_combobox"):
                    current = self.group_analysis_level_combobox.currentText().strip().lower()
                    if current == "off":
                        self.group_analysis_level_combobox.setCurrentText("Standard")
            else:
                self.select_group_label.setText("Not applied")
                if hasattr(self, "group_analysis_level_combobox"):
                    self.group_analysis_level_combobox.setCurrentText("Off")
        except Exception as e:
            self.log_and_exit(e)

    def select_excel_file(self):
        """Prompt for an output workbook path and avoid immediate name collisions."""
        try:
            """Open a file dialog to select an excel file"""
            if str(self.db_file or "").strip():
                default_name = self.db_file[:-3]
                if not default_name.endswith(".xlsx"):
                    default_name += ".xlsx"
                file_path = Path(default_name)
            else:
                file_path = Path.home() / "export.xlsx"
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
                self._set_path_field_value(self.excel_file_text_label, file_path)
                self._update_export_button_enabled_state()
        except Exception as e:
            self.log_and_exit(e)

    def show_loading_screen(self):
        """Validate inputs, persist options, and hand work to the export thread."""
        try:
            self._refresh_metadata_enrichment_notice()
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
                generate_html_dashboard=self.generate_html_dashboard_checkbox.isChecked(),
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
        if not hasattr(self.loading_dialog, 'findChildren'):
            return
        for button in self.loading_dialog.findChildren(QPushButton):
            text = button.text().strip().lower() if hasattr(button, 'text') else ''
            if text == 'cancel':
                button.setEnabled(bool(enabled))

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
                        title,
                        message,
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
        caller = inspect.stack()[1].function
        _log_exception(exception, context=f"ExportDialog.{caller}", reraise=False)

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
            self.group_analysis_scope_combobox.setVisible(enabled)
            self.group_analysis_scope_combobox.setEnabled(enabled)
        if hasattr(self, "group_analysis_scope_label"):
            self.group_analysis_scope_label.setVisible(enabled)
            self.group_analysis_scope_label.setEnabled(enabled)
        self._apply_window_size_constraints()
