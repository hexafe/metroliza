"""Export dialog UI, export option builders, and completion message helpers."""

from metroliza.shared.progress_status import build_three_line_status
from metroliza.ui.filter_dialog import FilterDialog
from metroliza.ui.data_grouping import DataGrouping
import metroliza.shared.custom_logger as custom_logger
from metroliza.exporting.export_dialog_service import (
    build_export_completion_message,
    build_export_directory_link_line as build_export_directory_link_line,
    build_export_folder_link_line as build_export_folder_link_line,
    build_export_options_payload as build_export_options_payload,
    build_validated_export_request,
)
from metroliza.exporting.export_preset_utils import (
    build_export_options_for_preset,
    get_export_preset_id_for_label,
    get_export_preset_ids,
    get_export_preset_label,
    load_export_dialog_config,
    migrate_export_dialog_config,
    save_export_dialog_config,
)
from metroliza.charts.dashboard_visual_options import (
    dashboard_visual_group_names_from_grouping_frame,
    dashboard_visual_settings_summary,
    dashboard_visual_swatch_palette,
    load_dashboard_visual_settings,
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
)
import html
import inspect
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
try:
    from metroliza.ui.worker_progress_dialog import (
        create_delayed_worker_progress_dialog as create_worker_progress_dialog,
    )
except ImportError:  # pragma: no cover - compatibility with lightweight test stubs.
    from metroliza.ui.worker_progress_dialog import create_worker_progress_dialog
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.reports.report_query_service import build_measurement_export_query
from metroliza.shared.filter_state import NOT_APPLIED_LABEL, summarize_filter_state
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    info_button,
    path_field,
    section_label,
    separator,
    set_status_variant,
    status_chip,
    update_path_field,
)


_URL_PATTERN = re.compile(r"((?:https?|file)://[^\s]+)")
DEFAULT_FILTER_QUERY = build_measurement_export_query()


def create_export_data_thread(export_request):
    """Create the export worker only when an export actually starts."""
    from metroliza.exporting.export_data_thread import ExportDataThread

    return ExportDataThread(export_request=export_request)


def _reject_progress_dialog_as_terminal(dialog) -> None:
    """Dismiss a worker progress dialog after the worker has already stopped."""
    reject_as_terminal = getattr(dialog, "reject_as_terminal", None)
    if callable(reject_as_terminal):
        reject_as_terminal()
        return
    request_terminal_close = getattr(dialog, "request_terminal_close", None)
    if callable(request_terminal_close):
        request_terminal_close()
    dialog.reject()


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
        configure_window_size(self, minimum=(700, 430), initial=(760, 700))

        self.db_file = db_file
        self.excel_file = ""
        self.filter_query = DEFAULT_FILTER_QUERY
        self.filter_state = None
        self.df_for_grouping = None

        self.filter_window = None
        self.grouping_window = None
        self.export_thread = None
        self.export_error_message = None
        self._cancel_requested = False
        self._grouping_applied = False
        self.config_path = Path.home() / '.metroliza' / '.export_dialog_config.json'
        self.config = self._load_dialog_config()
        self.dashboard_visual_settings = load_dashboard_visual_settings()

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
            self._sync_html_dashboard_only_state()
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

            self.select_filter_label = QLabel(NOT_APPLIED_LABEL)
            self.select_filter_label.setToolTip("Optional export filters for AX, reference, header, or date range.")
            self.filter_button = QPushButton("Edit...")
            self.filter_button.clicked.connect(self.open_filter_window)
            self.filter_button.setToolTip("Edit the optional export filters.")
            self.clear_filter_button = QPushButton("Clear filters")
            self.clear_filter_button.clicked.connect(self.clear_filters)
            self.clear_filter_button.setToolTip("Reset all export filters to the default unfiltered state.")

            self.select_group_label = QLabel("Not applied")
            self.select_group_label.setToolTip("Optional group assignments for grouped export workflows.")
            self.group_button = QPushButton("Edit...")
            self.group_button.clicked.connect(self.open_grouping_window)
            self.group_button.setToolTip("Edit the optional grouping assignments.")
            self.clear_group_button = QPushButton("Clear grouping")
            self.clear_group_button.clicked.connect(self.clear_grouping)
            self.clear_group_button.setToolTip("Reset optional grouping assignments.")

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
            self.path_readiness_label = status_chip("", "warning")

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
                "Extended plots: includes additional summary plots and statistics sheets.\n"
                "HTML dashboard only: creates the browser dashboard without an .xlsx workbook."
            )
            self.preset_combobox.setToolTip(self.preset_label.toolTip())

            self.export_target_label = QLabel("Additional outputs:")
            self.include_google_sheets_checkbox = QCheckBox("Google Sheets")
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
            self.generate_html_dashboard_checkbox.stateChanged.connect(
                lambda _state: self._sync_dashboard_visual_controls()
            )
            self.dashboard_visuals_label = QLabel("Dashboard style:")
            self.dashboard_visuals_summary_label = status_chip("", "neutral")
            self.dashboard_visuals_button = QPushButton("Change...")
            self.dashboard_visuals_button.setToolTip(
                "Adjust HTML dashboard colors, markers, selected-element opacity, and reference/stat lines."
            )
            self.dashboard_visuals_button.clicked.connect(self.open_dashboard_visual_options)

            self.include_industrial_context_checkbox = QCheckBox("Industrial context")
            self.include_industrial_context_checkbox.setChecked(False)
            industrial_context_tooltip = (
                "Append cached production context from accepted local links to the measurement "
                "export and add a context worksheet when linked records exist."
            )
            self.include_industrial_context_checkbox.setToolTip(industrial_context_tooltip)
            self.industrial_context_info_button = self._build_info_button(industrial_context_tooltip)

            # Add dropdown list for chart type
            self.export_type_label = QLabel("Chart type:")
            self.export_type_combobox = QComboBox()
            self.export_type_combobox.addItem("Line")
            self.export_type_combobox.addItem("Scatter")
            self.export_type_combobox.setCurrentText("Line")
            chart_type_hint = (
                "Line charts keep sample numbers visible. "
                "Scatter charts number exported parts sequentially from 1."
            )
            self.export_type_label.setToolTip(chart_type_hint)
            self.export_type_combobox.setToolTip(chart_type_hint)

            # Add dropdown list for chart type
            self.sort_measurements_label = QLabel("Sort by:")
            self.sort_measurements_combobox = QComboBox()
            self.sort_measurements_combobox.addItem("Date")
            self.sort_measurements_combobox.addItem("Sample #")
            self.sort_measurements_combobox.setCurrentText("Date")
            self.sort_measurements_label.setToolTip("Use this menu to select how data should be sorted - by date or measurement or sample number")
            self.sort_measurements_combobox.setToolTip("Use this menu to select how data should be sorted - by date or measurement or sample number")

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

            # Normalize advanced numeric fields only when editing is finished.
            self.violin_plot_min_samplesize.editingFinished.connect(self.validate_violin_plot_min_samplesize_input)
            self.summary_plot_scale.editingFinished.connect(self.validate_plot_scale_input)

            # Add a QCheckBox for "Hide OK results?"
            self.hide_ok_results_checkbox = QCheckBox("Hide OK results")
            self.hide_ok_results_checkbox.setChecked(False)
            self.hide_ok_results_checkbox.setToolTip(
                "When enabled, columns that contain only OK results are hidden from the workbook, not deleted."
            )

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

            self.preset_output_section_label = section_label("Preset and output")
            self.filters_grouping_section_label = section_label("Filters and grouping")
            self.chart_analysis_section_label = section_label("Chart settings")
            self.optional_outputs_section_label = section_label("Optional outputs")
            self.advanced_section_label = section_label("Advanced")

            self._set_compact_row_label_widths()
            self._sync_html_dashboard_only_state()
            self._sync_dashboard_visual_controls()
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
            content_layout.setColumnStretch(2, 0)
            content_layout.setColumnStretch(3, 0)

            row = 0
            content_layout.addWidget(self.preset_output_section_label, row, 0, 1, 4)
            row += 1
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
            content_layout.addWidget(self.path_readiness_label, row, 0, 1, 4)

            row += 1
            content_layout.addWidget(separator(), row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.filters_grouping_section_label, row, 0, 1, 4)

            row += 1
            content_layout.addWidget(QLabel("Filters:"), row, 0)
            content_layout.addWidget(self.select_filter_label, row, 1)
            content_layout.addWidget(self.filter_button, row, 2)
            content_layout.addWidget(self.clear_filter_button, row, 3)

            row += 1
            content_layout.addWidget(QLabel("Grouping:"), row, 0)
            content_layout.addWidget(self.select_group_label, row, 1)
            content_layout.addWidget(self.group_button, row, 2)
            content_layout.addWidget(self.clear_group_button, row, 3)

            row += 1
            content_layout.addWidget(separator(), row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.chart_analysis_section_label, row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.export_type_label, row, 0)
            content_layout.addWidget(self.export_type_combobox, row, 1)
            content_layout.addWidget(self.sort_measurements_label, row, 2)
            content_layout.addWidget(self.sort_measurements_combobox, row, 3)

            row += 1
            content_layout.addWidget(separator(), row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.optional_outputs_section_label, row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.export_target_label, row, 0)
            optional_outputs_widget = QWidget()
            optional_outputs_layout = QGridLayout(optional_outputs_widget)
            optional_outputs_layout.setContentsMargins(0, 0, 0, 0)
            optional_outputs_layout.setHorizontalSpacing(6)
            optional_outputs_layout.setVerticalSpacing(4)
            optional_outputs_layout.addWidget(self.include_google_sheets_checkbox, 0, 0)
            optional_outputs_layout.addWidget(self.google_sheets_info_button, 0, 1)
            optional_outputs_layout.addWidget(self.generate_html_dashboard_checkbox, 0, 2)
            optional_outputs_layout.addWidget(self.html_dashboard_info_button, 0, 3)
            optional_outputs_layout.addWidget(self.dashboard_visuals_label, 1, 2)
            optional_outputs_layout.addWidget(self.dashboard_visuals_summary_label, 1, 3)
            optional_outputs_layout.addWidget(self.dashboard_visuals_button, 1, 4)
            optional_outputs_layout.addWidget(self.include_industrial_context_checkbox, 1, 0)
            optional_outputs_layout.addWidget(self.industrial_context_info_button, 1, 1)
            optional_outputs_layout.setColumnStretch(6, 1)
            content_layout.addWidget(optional_outputs_widget, row, 1, 1, 3)

            row += 1
            content_layout.addWidget(self.advanced_section_label, row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.advanced_toggle_button, row, 0, 1, 4)

            row += 1
            content_layout.addWidget(self.advanced_options_container, row, 0, 1, 4)
            content_layout.setRowStretch(row + 1, 1)

            self.content_scroll_area = QScrollArea()
            self.content_scroll_area.setWidgetResizable(True)
            self.content_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
            apply_metroliza_theme(self)

            self.setTabOrder(self.preset_combobox, self.select_db_button)
            self.setTabOrder(self.select_db_button, self.select_excel_button)
            self.setTabOrder(self.select_excel_button, self.filter_button)
            self.setTabOrder(self.filter_button, self.clear_filter_button)
            self.setTabOrder(self.clear_filter_button, self.group_button)
            self.setTabOrder(self.group_button, self.clear_group_button)
            self.setTabOrder(self.clear_group_button, self.export_type_combobox)
            self.setTabOrder(self.export_type_combobox, self.sort_measurements_combobox)
            self.setTabOrder(self.sort_measurements_combobox, self.include_google_sheets_checkbox)
            self.setTabOrder(self.include_google_sheets_checkbox, self.generate_html_dashboard_checkbox)
            self.setTabOrder(self.generate_html_dashboard_checkbox, self.dashboard_visuals_button)
            self.setTabOrder(self.dashboard_visuals_button, self.include_industrial_context_checkbox)
            self.setTabOrder(self.include_industrial_context_checkbox, self.advanced_toggle_button)
            self.setTabOrder(self.advanced_toggle_button, self.violin_plot_min_samplesize)
            self.setTabOrder(self.violin_plot_min_samplesize, self.summary_plot_scale)
            self.setTabOrder(self.summary_plot_scale, self.hide_ok_results_checkbox)
            self.setTabOrder(self.hide_ok_results_checkbox, self.close_button)
            self.setTabOrder(self.close_button, self.export_button)
            self._configure_accessibility()
        except Exception as e:
            self.log_and_exit(e)

    def _configure_accessibility(self):
        configure_accessibility(self.preset_combobox, name="Export preset")
        configure_accessibility(self.select_db_button, name="Select export database")
        configure_accessibility(self.select_excel_button, name="Select output workbook")
        configure_accessibility(self.filter_button, name="Edit export filters")
        configure_accessibility(self.clear_filter_button, name="Clear export filters")
        configure_accessibility(self.group_button, name="Edit export grouping")
        configure_accessibility(self.clear_group_button, name="Clear export grouping")
        configure_accessibility(self.export_type_combobox, name="Export chart type")
        configure_accessibility(self.sort_measurements_combobox, name="Export sort order")
        configure_accessibility(self.include_google_sheets_checkbox, name="Create Google Sheets output")
        configure_accessibility(self.generate_html_dashboard_checkbox, name="Create HTML dashboard")
        configure_accessibility(self.dashboard_visuals_button, name="Edit dashboard visuals")
        configure_accessibility(self.include_industrial_context_checkbox, name="Include industrial context")
        configure_accessibility(self.advanced_toggle_button, name="Show advanced export options")
        configure_accessibility(self.violin_plot_min_samplesize, name="Violin plot minimum sample count")
        configure_accessibility(self.summary_plot_scale, name="Summary plot Y limit scale")
        configure_accessibility(self.hide_ok_results_checkbox, name="Hide OK-only result columns")
        configure_accessibility(self.close_button, name="Close export dialog")
        configure_accessibility(self.export_button, name="Start export")

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
        return path_field(value)

    def _set_path_field_value(self, field, value, *, empty_text="None selected"):
        if hasattr(field, "setToolTip"):
            update_path_field(field, value, empty_text=empty_text)
            return
        text = str(value or "").strip()
        if hasattr(field, "setText"):
            field.setText(text if text else empty_text)

    def _build_info_button(self, tooltip_text):
        return info_button(tooltip_text, name="Export option information")

    def _set_compact_row_label_widths(self):
        for label in (
            self.preset_label,
            self.select_db_label,
            self.select_excel_label,
            self.export_type_label,
            self.sort_measurements_label,
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
        size_hint = self.sizeHint()
        content_width = 0
        if hasattr(self, "content_widget") and self.content_widget is not None:
            content_width = self.content_widget.minimumSizeHint().width()
        desired_width = max(720, content_width + 44, size_hint.width())
        initial_width = min(desired_width, 900)
        initial_height = min(max(560, size_hint.height()), 860)
        minimum_width = min(max(700, content_width + 28), 900)
        available = self._available_geometry()
        if available is not None and hasattr(available, "width"):
            bounded_width = max(540, available.width() - 40)
            minimum_width = min(minimum_width, bounded_width)
            initial_width = min(initial_width, bounded_width)
        configure_window_size(
            self,
            minimum=(minimum_width, 430),
            initial=(initial_width, initial_height),
            screen_margin=40,
        )

    def _update_export_button_enabled_state(self):
        if not hasattr(self, "export_button"):
            return
        has_database = bool(str(self.db_file or "").strip())
        has_output = bool(str(self.excel_file or "").strip())
        self.export_button.setEnabled(has_database and has_output)
        self._refresh_path_readiness_state(has_database=has_database, has_output=has_output)

    def _selected_preset_options(self):
        combobox = getattr(self, "preset_combobox", None)
        selected_label = combobox.currentText() if combobox is not None else ""
        selected_preset = get_export_preset_id_for_label(selected_label)
        return build_export_options_for_preset(selected_preset)

    def _is_html_dashboard_only(self):
        return self._selected_preset_options().get("export_target") == "html_dashboard"

    def _grouping_is_applied(self):
        if bool(getattr(self, "_grouping_applied", False)):
            return True
        label = getattr(self, "select_group_label", None)
        label_text = ""
        if label is not None and hasattr(label, "text"):
            label_text = str(label.text() or "")
        elif label is not None and hasattr(label, "value"):
            label_text = str(label.value or "")
        return label_text.strip().lower() == "applied"

    def _coerce_output_path_for_mode(self):
        if not str(getattr(self, "excel_file", "") or "").strip():
            return
        path = Path(str(self.excel_file))
        if self._is_html_dashboard_only():
            if path.suffix.lower() != ".html":
                stem = path.stem
                if not stem.endswith("_dashboard"):
                    stem = f"{stem}_dashboard"
                self.excel_file = path.with_name(f"{stem}.html")
        elif path.suffix.lower() == ".html":
            stem = path.stem
            if stem.endswith("_dashboard"):
                stem = stem[: -len("_dashboard")]
            self.excel_file = path.with_name(f"{stem or 'export'}.xlsx")
        if hasattr(self, "excel_file_text_label"):
            self._set_path_field_value(self.excel_file_text_label, self.excel_file)

    def _sync_html_dashboard_only_state(self, _checked=None):
        html_only = self._is_html_dashboard_only()
        grouped = self._grouping_is_applied()
        if hasattr(self, "generate_html_dashboard_checkbox"):
            if html_only or grouped:
                self.generate_html_dashboard_checkbox.setChecked(True)
            elif (
                hasattr(self.generate_html_dashboard_checkbox, "isEnabled")
                and not self.generate_html_dashboard_checkbox.isEnabled()
            ):
                self.generate_html_dashboard_checkbox.setChecked(False)
            if hasattr(self.generate_html_dashboard_checkbox, "setEnabled"):
                self.generate_html_dashboard_checkbox.setEnabled(not (html_only or grouped))
            tooltip = (
                "Grouped exports include Group Analysis in the HTML dashboard."
                if grouped and not html_only
                else "Create a local HTML sidecar for browser-based chart review next to the workbook."
            )
            self.generate_html_dashboard_checkbox.setToolTip(tooltip)
        if hasattr(self, "include_google_sheets_checkbox"):
            if html_only:
                self.include_google_sheets_checkbox.setChecked(False)
            if hasattr(self.include_google_sheets_checkbox, "setEnabled"):
                self.include_google_sheets_checkbox.setEnabled(not html_only)
        if hasattr(self, "select_excel_label"):
            self.select_excel_label.setText("Dashboard file:" if html_only else "Excel file:")
            self.select_excel_label.setToolTip(
                "Choose where the standalone HTML dashboard will be written."
                if html_only
                else "Choose where the exported workbook will be written."
            )
        if hasattr(self, "select_excel_button"):
            self.select_excel_button.setToolTip(self.select_excel_label.toolTip())
        self._coerce_output_path_for_mode()
        self._sync_dashboard_visual_controls()
        self._update_export_button_enabled_state()

    def _refresh_path_readiness_state(self, *, has_database=None, has_output=None):
        label = getattr(self, "path_readiness_label", None)
        if label is None:
            return
        if has_database is None:
            has_database = bool(str(self.db_file or "").strip())
        if has_output is None:
            has_output = bool(str(self.excel_file or "").strip())

        output_label = "HTML dashboard" if self._is_html_dashboard_only() else "output workbook"
        if has_database and has_output:
            label.setText(f"Database and {output_label} selected. Ready for export.")
            set_status_variant(label, "success")
            return
        if has_database:
            label.setText(f"Select an {output_label} path to enable export.")
            set_status_variant(label, "warning")
            return
        if has_output:
            label.setText("Select a database file to enable export.")
            set_status_variant(label, "warning")
            return
        label.setText(f"Select both a database file and {output_label} path to enable export.")
        set_status_variant(label, "warning")

    def _show_database_required_warning(self, action_name):
        QMessageBox.information(
            self,
            "Database required",
            f"Select a database file before you {action_name}.",
        )

    def validate_violin_plot_min_samplesize_input(self):
        try:
            user_input = self.violin_plot_min_samplesize.text()
            try:
                input_value = int(user_input)
                if input_value < 2:
                    input_value = 2
            except ValueError:
                input_value = 6
            if self.violin_plot_min_samplesize.text() != str(input_value):
                self.violin_plot_min_samplesize.setText(str(input_value))
        except Exception as e:
            self.log_and_exit(e)

    def validate_plot_scale_input(self):
        try:
            user_input = self.summary_plot_scale.text()
            try:
                input_value = int(user_input)
                if input_value <= 0:
                    input_value = 0
            except ValueError:
                input_value = 0
            if self.summary_plot_scale.text() != str(input_value):
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
        self.filter_state = None
        self.df_for_grouping = None
        self._refresh_filter_state_summary()
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

    def set_filter_state(self, filter_state):
        try:
            self.filter_state = filter_state
            self._refresh_filter_state_summary()
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

    def set_filter_applied(self, filter_state=None):
        try:
            if filter_state is not None:
                self.filter_state = filter_state
            self._refresh_filter_state_summary()
        except Exception as e:
            self.log_and_exit(e)

    def _refresh_filter_state_summary(self):
        summary_label, details = summarize_filter_state(self.filter_state)
        if hasattr(self.select_filter_label, "setText"):
            self.select_filter_label.setText(summary_label)
        if hasattr(self.select_filter_label, "setToolTip"):
            self.select_filter_label.setToolTip(details)

    def clear_filters(self):
        try:
            self.filter_query = DEFAULT_FILTER_QUERY
            self.filter_state = None
            self._refresh_filter_state_summary()
            self._discard_child_dialog('filter_window')
        except Exception as e:
            self.log_and_exit(e)

    def clear_grouping(self):
        try:
            self.df_for_grouping = None
            self.set_grouping_applied(False)
            self._discard_child_dialog('grouping_window')
        except Exception as e:
            self.log_and_exit(e)

    def set_grouping_applied(self, applied):
        try:
            self._grouping_applied = bool(applied)
            if applied:
                self.select_group_label.setText("Applied")
            else:
                self.select_group_label.setText("Not applied")
            self._sync_html_dashboard_only_state()
        except Exception as e:
            self.log_and_exit(e)

    def select_excel_file(self):
        """Prompt for an output path and avoid immediate name collisions."""
        try:
            html_only = self._is_html_dashboard_only()
            if str(self.db_file or "").strip():
                default_name = str(Path(str(self.db_file)).with_suffix(""))
                if html_only:
                    default_name = f"{default_name}_dashboard.html"
                elif not default_name.endswith(".xlsx"):
                    default_name += ".xlsx"
                file_path = Path(default_name)
            else:
                file_path = Path.home() / ("export_dashboard.html" if html_only else "export.xlsx")
            base_name = file_path.stem
            suffix = file_path.suffix
            directory = file_path.parent

            counter = 1
            while file_path.exists():
                file_path = directory / f"{base_name}_{counter}{suffix}"
                counter += 1

            dialog_title = "Select an HTML dashboard file" if html_only else "Select an Excel file"
            file_filter = "HTML dashboard (*.html);;All files (*)" if html_only else "Excel workbook (*.xlsx);;All files (*)"
            filename, _ = QFileDialog.getSaveFileName(self, dialog_title, str(file_path), file_filter)

            if filename:
                file_path = Path(filename)
                logger.info("Selected export output file: %s", file_path)
                self.excel_file = file_path
                self._coerce_output_path_for_mode()
                self._set_path_field_value(self.excel_file_text_label, self.excel_file)
                self._update_export_button_enabled_state()
        except Exception as e:
            self.log_and_exit(e)

    def show_loading_screen(self):
        """Validate inputs, persist options, and hand work to the export thread."""
        try:
            self._refresh_metadata_enrichment_notice()
            violin_input = self.violin_plot_min_samplesize.text() or "6"
            summary_scale_input = self.summary_plot_scale.text() or "0"

            selected_preset = get_export_preset_id_for_label(self.preset_combobox.currentText())
            try:
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
                    generate_html_dashboard=(
                        self.generate_html_dashboard_checkbox.isChecked()
                        or self._is_html_dashboard_only()
                        or self._grouping_is_applied()
                    ),
                    include_industrial_context=(
                        self.include_industrial_context_checkbox.isChecked()
                        if hasattr(self, "include_industrial_context_checkbox")
                        else False
                    ),
                    filter_query=self.filter_query,
                    grouping_df=self.df_for_grouping,
                    group_analysis_level=self._selected_group_analysis_level(),
                    group_analysis_scope=self._selected_group_analysis_scope(),
                    dashboard_visual_settings=getattr(self, "dashboard_visual_settings", None),
                )
            except ValueError as validation_error:
                QMessageBox.warning(self, "Export validation failed", str(validation_error))
                return

            # Normalize user-visible values after validation/coercion.
            output_path = export_request.paths.excel_file or export_request.paths.html_dashboard_file
            self.excel_file = Path(output_path)
            if hasattr(self, "excel_file_text_label"):
                self._set_path_field_value(self.excel_file_text_label, self.excel_file)
            self.violin_plot_min_samplesize.setText(str(export_request.options.violin_plot_min_samplesize))
            self.summary_plot_scale.setText(str(export_request.options.summary_plot_scale))

            self.config['selected_preset'] = selected_preset
            save_export_dialog_config(self.config_path, self.config)

            self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif = create_worker_progress_dialog(
                self,
                window_title="Exporting data...",
                initial_status_text=build_three_line_status("Exporting data...", "Preparing export thread", "ETA --"),
                on_cancel=self.stop_exporting,
            )

            # Disable the export button before the worker starts.
            self.export_button.setDisabled(True)

            # Start the exporting thread with validated options
            self._cancel_requested = False
            self._export_terminal_handled = False
            self.export_thread = create_export_data_thread(export_request)
            self.export_thread.update_label.connect(self.loading_label.setText)
            self.export_thread.update_progress.connect(self.loading_bar.setValue)
            self.export_thread.error_occurred.connect(self.on_export_error)
            completion_signal = getattr(self.export_thread, 'completed', self.export_thread.finished)
            completion_signal.connect(self.on_export_finished)
            self.export_thread.finished.connect(self.on_export_thread_stopped)
            self.export_thread.canceled.connect(self.on_export_canceled)
            self.export_thread.start()
            self.loading_dialog.show()
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
            _reject_progress_dialog_as_terminal(self.loading_dialog)
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
            self._export_terminal_handled = True
            QMessageBox.information(self, "Export canceled", "Cancel confirmed. Data exporting has been canceled")
            _reject_progress_dialog_as_terminal(self.loading_dialog)
            self.export_button.setEnabled(True)
            self._cancel_requested = False
            self._set_loading_cancel_enabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def on_export_finished(self):
        """Finalize export flow with success/error messaging and UI reset."""
        try:
            self._export_terminal_handled = True
            if self.export_error_message:
                QMessageBox.warning(self, "Export failed", self.export_error_message)
            else:
                export_target = getattr(self.export_thread, 'export_target', 'excel_xlsx')
                completion_metadata = getattr(self.export_thread, 'completion_metadata', {})
                result_path = (
                    completion_metadata.get('html_dashboard_path')
                    if export_target == 'html_dashboard'
                    else self.excel_file
                )
                level, title, message = build_export_completion_message(
                    excel_file=result_path,
                    export_target=export_target,
                    completion_metadata=completion_metadata,
                )

                try:
                    reveal_path = None if export_target == 'html_dashboard' else self.excel_file
                    show_export_result_message(self, level, title, message, excel_file=reveal_path)
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

    def on_export_thread_stopped(self):
        """Restore export UI when the worker stops without a success/cancel signal."""
        try:
            if getattr(self, '_export_terminal_handled', False):
                return
            if self.export_error_message:
                self.on_export_finished()
                return
            if getattr(self, '_cancel_requested', False):
                self.on_export_canceled()
                return
            if getattr(self, 'loading_dialog', None) is not None:
                self.loading_dialog.accept()
            self.export_button.setEnabled(True)
            self._cancel_requested = False
            self._set_loading_cancel_enabled(True)
        except Exception as e:
            self.log_and_exit(e)

    def log_and_exit(self, exception):
        caller = inspect.stack()[1].function
        _log_exception(exception, context=f"ExportDialog.{caller}", reraise=False)

    def _selected_export_target(self):
        if self._is_html_dashboard_only():
            return 'html_dashboard'
        if self.include_google_sheets_checkbox.isChecked():
            return 'google_sheets_drive_convert'
        return 'excel_xlsx'

    def _dashboard_visuals_enabled(self):
        if self._is_html_dashboard_only():
            return True
        if self._grouping_is_applied():
            return True
        checkbox = getattr(self, "generate_html_dashboard_checkbox", None)
        return bool(checkbox is not None and checkbox.isChecked())

    def _sync_dashboard_visual_controls(self):
        if not hasattr(self, "dashboard_visuals_button"):
            return
        enabled = self._dashboard_visuals_enabled()
        for widget in (
            getattr(self, "dashboard_visuals_label", None),
            self.dashboard_visuals_summary_label,
            self.dashboard_visuals_button,
        ):
            if widget is None:
                continue
            widget.setVisible(enabled)
            widget.setEnabled(enabled)
        self.dashboard_visuals_button.setToolTip(
            "Adjust HTML dashboard colors, markers, selected-element opacity, and reference/stat lines."
            if enabled
            else "Enable HTML dashboard output to adjust dashboard visuals."
        )
        settings = getattr(self, "dashboard_visual_settings", None)
        summary = dashboard_visual_settings_summary(settings)
        palette = dashboard_visual_swatch_palette(settings, count=6)
        self.dashboard_visuals_summary_label.setText(summary)
        summary_tooltip = " ".join(palette)
        if not enabled:
            summary_tooltip = (
                "HTML dashboard output is currently off. Saved visual settings will be used "
                f"when it is enabled. Palette: {summary_tooltip}"
            )
        self.dashboard_visuals_summary_label.setToolTip(summary_tooltip)

    def open_dashboard_visual_options(self):
        try:
            from metroliza.ui.dashboard_visual_options_dialog import DashboardVisualOptionsDialog

            dialog = DashboardVisualOptionsDialog(
                self,
                settings=getattr(self, "dashboard_visual_settings", None),
                preview_group_names=dashboard_visual_group_names_from_grouping_frame(
                    getattr(self, "df_for_grouping", None)
                ),
            )
            if dialog.exec():
                self.dashboard_visual_settings = dialog.visual_settings()
                self._sync_dashboard_visual_controls()
        except Exception as exc:
            QMessageBox.warning(self, "Dashboard visuals", f"Could not open dashboard visuals: {exc}")

    def _selected_group_analysis_level(self):
        return "standard" if self._grouping_is_applied() else "off"

    def _selected_group_analysis_scope(self):
        return "auto"
