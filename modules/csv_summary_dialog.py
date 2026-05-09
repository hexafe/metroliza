"""CSV summary export dialogs and worker thread for workbook generation."""

from pathlib import Path
import logging
import re

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from modules.csv_summary_utils import (
    build_csv_summary_preset_key,
    build_default_plot_toggles,
    estimate_enabled_chart_count,
    load_csv_summary_presets,
    load_csv_with_fallbacks,
    migrate_csv_summary_presets,
    normalize_column_spec_limits,
    normalize_plot_toggles,
    recommend_extended_plots_default,
    resolve_default_data_columns,
    save_csv_summary_presets,
)
from modules.csv_summary_worker import DataProcessingThread
from modules.progress_status import build_three_line_status
from modules.worker_progress_dialog import create_worker_progress_dialog
from modules.help_menu import attach_help_menu_to_layout
from modules.ui_foundation import (
    apply_list_selection_style,
    apply_metroliza_theme,
    configure_accessibility,
    configure_table,
    configure_window_size,
    path_field,
    section_label,
    set_status_variant,
    status_chip,
    update_path_field,
)


logger = logging.getLogger(__name__)

class FilterDialog(QDialog):
    """Select index and data columns for CSV summary processing.

    The dialog supports convenient defaults via special rows for first-column
    index selection and selecting all non-index data columns.
    """

    def __init__(self, parent, column_names):
        super().__init__(parent)

        self.setWindowTitle("Filter Columns")
        configure_window_size(self, minimum=(620, 300), initial=(760, 420))

        self.column_names = column_names
        self.selected_indexes = column_names[:1]
        self.selected_data_columns = column_names[1:]

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)
        attach_help_menu_to_layout(main_layout, self, [("CSV Summary manual", 'csv_summary')])

        main_layout.addWidget(section_label("Column selection"))
        horizontal_layout = QHBoxLayout()
        horizontal_layout.setSpacing(10)

        self.index_list_widget = QListWidget()
        self.data_list_widget = QListWidget()

        self.index_list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.data_list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        apply_list_selection_style(self.index_list_widget)
        apply_list_selection_style(self.data_list_widget)
        configure_accessibility(self.index_list_widget, name="Index columns list")
        configure_accessibility(self.data_list_widget, name="Data columns list")

        horizontal_layout.addWidget(self.index_list_widget)
        horizontal_layout.addWidget(self.data_list_widget)

        self.index_list_widget.addItem("SELECT DEFAULT (FIRST COLUMN)")
        self.index_list_widget.addItems(column_names)
        self.data_list_widget.addItem("SELECT ALL")
        self.data_list_widget.addItems(column_names)

        main_layout.addLayout(horizontal_layout)

        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        if hasattr(ok_button, "setDefault"):
            ok_button.setDefault(True)
        configure_accessibility(ok_button, name="Confirm selected columns")

        main_layout.addWidget(ok_button)

        self.setLayout(main_layout)
        apply_metroliza_theme(self)
        self.select_default_filter()

    def select_default_filter(self):
        # Select the first item in INDEX list as default
        self.index_list_widget.setCurrentRow(0)

        # Select the first item in DATA list as default
        self.data_list_widget.setCurrentRow(0)

    def get_selected_columns(self):
        """Resolve selected list items into explicit index/data column lists."""
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


class SpecLimitsDialog(QDialog):
    """Edit per-column NOM/USL/LSL overrides used in generated summaries."""

    def __init__(self, parent, data_columns, existing_limits):
        super().__init__(parent)
        self.setWindowTitle("Column spec limits")
        configure_window_size(self, minimum=(680, 360), initial=(860, 520))
        self.data_columns = data_columns

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("CSV Summary manual", 'csv_summary')])
        layout.addWidget(section_label("Per-column limits"))
        self.table = QTableWidget(len(data_columns), 4, self)
        self.table.setHorizontalHeaderLabels(["Column", "NOM", "USL", "LSL"])
        configure_table(self.table, stretch_column=0, resize_to_contents=(1, 2, 3), min_height=260)
        configure_accessibility(self.table, name="Spec limits table")

        for row, column_name in enumerate(data_columns):
            self.table.setItem(row, 0, QTableWidgetItem(column_name))
            defaults = existing_limits.get(column_name, {'nom': 0.0, 'usl': 0.0, 'lsl': 0.0})
            self.table.setItem(row, 1, QTableWidgetItem(str(defaults.get('nom', 0.0))))
            self.table.setItem(row, 2, QTableWidgetItem(str(defaults.get('usl', 0.0))))
            self.table.setItem(row, 3, QTableWidgetItem(str(defaults.get('lsl', 0.0))))

        layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        if hasattr(ok_button, "setDefault"):
            ok_button.setDefault(True)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)
        apply_metroliza_theme(self)

    def _cell_to_float(self, row, col):
        item = self.table.item(row, col)
        if item is None:
            return 0.0
        value = (item.text() or "").strip()
        if value == "":
            return 0.0
        try:
            return float(value.replace(',', '.'))
        except ValueError:
            return 0.0

    def get_limits(self):
        """Collect spec-limit values from the table, coercing blanks to 0.0."""
        limits = {}
        for row, column_name in enumerate(self.data_columns):
            limits[column_name] = {
                'nom': self._cell_to_float(row, 1),
                'usl': self._cell_to_float(row, 2),
                'lsl': self._cell_to_float(row, 3),
            }
        return limits



class CSVSummaryDialog(QDialog):
    """Configure CSV summary options and launch background export processing.

    Key state includes loaded CSV data, selected columns, optional spec limits,
    and per-file preset data persisted under the user profile.
    """

    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowTitle("CSV Summary")
        configure_window_size(self, minimum=(760, 460), initial=(900, 620))

        self.input_file = ""
        self.output_file = ""
        self.data_frame = None  # Store the loaded DataFrame
        self.column_names = []
        self.selected_indexes = []
        self.selected_data_columns = []
        self.csv_config = {}
        self.column_spec_limits = {}
        self.plot_toggles = {}
        self.summary_only = False
        self.worker_thread = None

        self.input_label = QLabel("Input CSV:")
        self.input_button = QPushButton("Browse")
        self.input_path_field = path_field("")
        self.input_button.setToolTip("Select the CSV source used for the summary workbook.")

        self.columns_label = QLabel("Selected columns:")
        self.filter_button = QPushButton("Edit...")
        self.columns_status_label = status_chip("No CSV loaded", "warning")
        self.filter_button.setToolTip("Choose index and data columns.")

        self.spec_limits_label = QLabel("Spec limits:")
        self.spec_limits_button = QPushButton("Edit...")
        self.spec_limits_status_label = status_chip("No data columns selected", "warning")
        self.spec_limits_button.setToolTip("Set NOM/USL/LSL values for selected data columns.")

        self.plot_options_label = QLabel("Plot options:")
        self.include_extended_plots = QCheckBox("Include histogram and boxplot charts")
        self.summary_only_checkbox = QCheckBox("Summary-only mode (skip per-column sheets/charts)")
        self.plot_options_status_label = status_chip("Charts enabled for full report.", "neutral")

        self.output_label = QLabel("Output workbook:")
        self.output_button = QPushButton("Browse")
        self.output_path_field = path_field("")
        self.output_button.setToolTip("Choose the target .xlsx file.")

        self.clear_presets_button = QPushButton("Clear saved presets")
        self.clear_presets_button.setToolTip("Remove saved CSV summary presets from your profile.")
        if hasattr(self.clear_presets_button, "setAutoDefault"):
            self.clear_presets_button.setAutoDefault(False)
        if hasattr(self.clear_presets_button, "setDefault"):
            self.clear_presets_button.setDefault(False)
        self.start_button = QPushButton("Create Summary")
        self.start_button.setToolTip("Run CSV summary export in the background.")
        if hasattr(self.start_button, "setDefault"):
            self.start_button.setDefault(True)
        if hasattr(self.start_button, "setAutoDefault"):
            self.start_button.setAutoDefault(True)
        self.start_button.setStyleSheet(
            "QPushButton { font-weight: 600; min-width: 160px; }"
        )
        self.readiness_label = status_chip("Select an input CSV to begin.", "warning")
        self._worker_failed = False

        self.input_button.clicked.connect(self.handle_input_button)
        self.filter_button.clicked.connect(self.handle_filter_button)
        self.spec_limits_button.clicked.connect(self.handle_spec_limits_button)
        self.clear_presets_button.clicked.connect(self.handle_clear_presets_button)
        self.output_button.clicked.connect(self.handle_output_button)
        self.start_button.clicked.connect(self.handle_start_button)
        self.include_extended_plots.stateChanged.connect(self._on_plot_mode_changed)
        self.summary_only_checkbox.stateChanged.connect(self._on_plot_mode_changed)

        self.include_extended_plots.setChecked(True)
        self.summary_only_checkbox.setChecked(False)

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("CSV Summary manual", 'csv_summary')])

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        row = 0
        grid.addWidget(self.input_label, row, 0)
        grid.addWidget(self.input_path_field, row, 1)
        grid.addWidget(self.input_button, row, 2)

        row += 1
        grid.addWidget(self.columns_label, row, 0)
        grid.addWidget(self.columns_status_label, row, 1)
        grid.addWidget(self.filter_button, row, 2)

        row += 1
        grid.addWidget(self.spec_limits_label, row, 0)
        grid.addWidget(self.spec_limits_status_label, row, 1)
        grid.addWidget(self.spec_limits_button, row, 2)

        row += 1
        grid.addWidget(self.plot_options_label, row, 0)
        grid.addWidget(self.plot_options_status_label, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.include_extended_plots, row, 1, 1, 2)
        row += 1
        grid.addWidget(self.summary_only_checkbox, row, 1, 1, 2)

        row += 1
        grid.addWidget(self.output_label, row, 0)
        grid.addWidget(self.output_path_field, row, 1)
        grid.addWidget(self.output_button, row, 2)

        row += 1
        grid.addWidget(self.readiness_label, row, 0, 1, 3)
        layout.addLayout(grid)
        footer_actions = QHBoxLayout()
        footer_actions.setSpacing(10)
        footer_actions.addWidget(self.clear_presets_button)
        footer_actions.addStretch(1)
        footer_actions.addWidget(self.start_button)
        layout.addLayout(footer_actions)
        self.setLayout(layout)
        self.preset_path = Path.home() / '.metroliza' / '.csv_summary_presets.json'
        self._sync_ui_state()
        configure_accessibility(self.input_button, name="Browse CSV input")
        configure_accessibility(self.filter_button, name="Edit CSV columns")
        configure_accessibility(self.spec_limits_button, name="Edit spec limits")
        configure_accessibility(self.output_button, name="Browse summary output")
        configure_accessibility(self.start_button, name="Create CSV summary")
        configure_accessibility(self.clear_presets_button, name="Clear CSV summary presets")
        apply_metroliza_theme(self)

    def _load_presets(self):
        """Load and migrate saved presets from the persistent config file."""
        presets = load_csv_summary_presets(self.preset_path)
        migrated, changed = migrate_csv_summary_presets(presets)
        if changed:
            save_csv_summary_presets(self.preset_path, migrated)
        return migrated

    def _save_presets(self, preset_key, selected_indexes, selected_data_columns, csv_config, column_spec_limits, include_extended_plots, summary_only, plot_toggles):
        """Persist current column/filter/report settings for a preset key."""
        if not preset_key:
            return
        presets = self._load_presets()
        presets[preset_key] = {
            "selected_indexes": list(selected_indexes or []),
            "selected_data_columns": list(selected_data_columns or []),
            "csv_config": csv_config or {},
            "column_spec_limits": normalize_column_spec_limits(selected_data_columns, column_spec_limits),
            "include_extended_plots": bool(include_extended_plots),
            "summary_only": bool(summary_only),
            "plot_toggles": normalize_plot_toggles(selected_data_columns, plot_toggles, full_report=include_extended_plots),
        }
        save_csv_summary_presets(self.preset_path, presets)

    @staticmethod
    def _preset_key_candidates(file_path):
        path = Path(file_path)
        normalized_stem = re.sub(r"\d+", "", path.stem).strip("_- ").lower()
        candidates = [build_csv_summary_preset_key(path)]
        if normalized_stem:
            candidates.append(f"{normalized_stem}.csv")
        return candidates

    def _resolve_preset_for_file(self, file_path):
        """Resolve a preset using canonical and compatibility file-name keys."""
        presets = self._load_presets()
        for key in self._preset_key_candidates(file_path):
            preset = presets.get(key)
            if isinstance(preset, dict):
                return preset
        return {}

    @staticmethod
    def _summarize_column_selection(selected_indexes, selected_data_columns):
        indexes = list(selected_indexes or [])
        data_columns = list(selected_data_columns or [])
        index_text = ", ".join(indexes[:2]) if indexes else "none"
        if len(indexes) > 2:
            index_text += f" (+{len(indexes) - 2})"

        data_text = ", ".join(data_columns[:3]) if data_columns else "none"
        if len(data_columns) > 3:
            data_text += f" (+{len(data_columns) - 3})"
        return f"Index: {index_text} | Data: {data_text}"

    @staticmethod
    def _summarize_spec_limits(column_spec_limits, selected_data_columns):
        selected = list(selected_data_columns or [])
        if not selected:
            return "No data columns selected"

        defaults = {'nom': 0.0, 'usl': 0.0, 'lsl': 0.0}
        custom_count = 0
        for column in selected:
            payload = (column_spec_limits or {}).get(column, defaults)
            normalized = {
                'nom': float(payload.get('nom', 0.0) or 0.0),
                'usl': float(payload.get('usl', 0.0) or 0.0),
                'lsl': float(payload.get('lsl', 0.0) or 0.0),
            }
            if normalized != defaults:
                custom_count += 1
        if custom_count == 0:
            return f"Defaults for {len(selected)} columns"
        return f"Custom limits on {custom_count}/{len(selected)} columns"

    @staticmethod
    def _spec_limit_issues(column_spec_limits, selected_data_columns):
        issues = []
        for column in (selected_data_columns or []):
            limits = (column_spec_limits or {}).get(column, {})
            nom = float(limits.get('nom', 0.0) or 0.0)
            usl = float(limits.get('usl', 0.0) or 0.0)
            lsl = float(limits.get('lsl', 0.0) or 0.0)
            absolute_usl = nom + usl
            absolute_lsl = nom + lsl
            if not (absolute_lsl <= nom <= absolute_usl):
                issues.append(column)
        return issues

    def _sync_ui_state(self):
        has_data_frame = self.data_frame is not None
        has_output_file = bool(self.output_file)
        has_data_columns = bool(self.selected_data_columns)
        limit_issues = self._spec_limit_issues(self.column_spec_limits, self.selected_data_columns)

        self.filter_button.setEnabled(has_data_frame)
        self.spec_limits_button.setEnabled(has_data_frame and has_data_columns)
        self.output_button.setEnabled(has_data_frame)
        self.start_button.setEnabled(has_data_frame and has_output_file and has_data_columns and not limit_issues)

        update_path_field(self.input_path_field, self.input_file)
        update_path_field(self.output_path_field, self.output_file)

        if has_data_frame:
            self.columns_status_label.setText(
                self._summarize_column_selection(self.selected_indexes, self.selected_data_columns)
            )
            set_status_variant(
                self.columns_status_label,
                "success" if has_data_columns else "warning",
            )
        else:
            self.columns_status_label.setText("No CSV loaded")
            set_status_variant(self.columns_status_label, "warning")

        self.spec_limits_status_label.setText(
            self._summarize_spec_limits(self.column_spec_limits, self.selected_data_columns)
        )
        if not has_data_columns:
            set_status_variant(self.spec_limits_status_label, "warning")
        elif limit_issues:
            self.spec_limits_status_label.setText(
                f"Invalid limits for {len(limit_issues)} column(s): {', '.join(limit_issues[:2])}"
                + (f" (+{len(limit_issues) - 2})" if len(limit_issues) > 2 else "")
            )
            set_status_variant(self.spec_limits_status_label, "danger")
        else:
            set_status_variant(self.spec_limits_status_label, "success")

        chart_mode = "disabled" if self.summary_only_checkbox.isChecked() else (
            "enabled" if self.include_extended_plots.isChecked() else "disabled"
        )
        chart_count = estimate_enabled_chart_count(
            self.selected_data_columns,
            self.plot_toggles,
            full_report=self.include_extended_plots.isChecked(),
            summary_only=self.summary_only_checkbox.isChecked(),
        )
        if self.summary_only_checkbox.isChecked():
            self.plot_options_status_label.setText("Summary-only mode: charts disabled.")
            set_status_variant(self.plot_options_status_label, "info")
        elif self.include_extended_plots.isChecked():
            self.plot_options_status_label.setText(f"Charts {chart_mode} ({chart_count} estimated).")
            set_status_variant(self.plot_options_status_label, "neutral")
        else:
            self.plot_options_status_label.setText("Quick-look mode: charts disabled.")
            set_status_variant(self.plot_options_status_label, "neutral")

        if not has_data_frame:
            self.readiness_label.setText("Select an input CSV to begin.")
            set_status_variant(self.readiness_label, "warning")
        elif not has_data_columns:
            self.readiness_label.setText("Select at least one data column before creating a summary.")
            set_status_variant(self.readiness_label, "warning")
        elif limit_issues:
            self.readiness_label.setText("Fix invalid spec limits: expected LSL <= NOM <= USL.")
            set_status_variant(self.readiness_label, "danger")
        elif not has_output_file:
            self.readiness_label.setText("Select an output workbook path to enable Create Summary.")
            set_status_variant(self.readiness_label, "warning")
        else:
            self.readiness_label.setText("Ready to create CSV summary workbook.")
            set_status_variant(self.readiness_label, "success")

    def _on_plot_mode_changed(self, *_args):
        self.plot_toggles = normalize_plot_toggles(
            self.selected_data_columns,
            self.plot_toggles,
            full_report=self.include_extended_plots.isChecked(),
        )
        self._sync_ui_state()

    # Define functions for button clicks
    def handle_input_button(self):
        """Select an input CSV, load it, and restore matching preset values."""
        options = QFileDialog.Option.ReadOnly
        filename, _ = QFileDialog.getOpenFileName(self, "Select input file (CSV)", "", "CSV Files (*.csv);;All Files (*)", options=options)
        if filename:
            if Path(filename).suffix.lower() != ".csv":
                QMessageBox.warning(self, "Invalid input file", "Please select a .csv input file.")
                return
            logger.info("Selected input CSV file: %s", filename)
            self.input_file = filename
            # Enable the FILTER and OUTPUT buttons after the input file is selected
            self.filter_button.setEnabled(True)
            self.spec_limits_button.setEnabled(True)
            self.output_button.setEnabled(True)

            preset = self._resolve_preset_for_file(filename)
            preset_csv_config = preset.get('csv_config', {}) if isinstance(preset, dict) else {}

            # Load CSV with delimiter/decimal fallbacks.
            try:
                self.data_frame, self.csv_config = load_csv_with_fallbacks(filename, preferred_config=preset_csv_config)
            except Exception as exc:
                logger.exception("CSV summary failed to load input file '%s'.", filename)
                QMessageBox.critical(self, 'CSV load failed', f'Could not load CSV file.\n\n{exc}')
                self.data_frame = None
                self.column_names = []
                self.selected_indexes = []
                self.selected_data_columns = []
                self._sync_ui_state()
                return

            self.column_names = self.data_frame.columns.tolist()
            preset_indexes = preset.get('selected_indexes', []) if isinstance(preset, dict) else []
            preset_data_columns = preset.get('selected_data_columns', []) if isinstance(preset, dict) else []

            self.selected_indexes = [col for col in preset_indexes if col in self.column_names] or self.column_names[:1]
            default_data_columns = resolve_default_data_columns(self.data_frame, self.selected_indexes)
            self.selected_data_columns = [col for col in preset_data_columns if col in default_data_columns] or default_data_columns

            if isinstance(preset, dict):
                preset_include_extended_plots = bool(preset.get('include_extended_plots', True))
            else:
                preset_include_extended_plots = recommend_extended_plots_default(self.selected_data_columns)
            self.include_extended_plots.setChecked(preset_include_extended_plots)
            self.summary_only = bool(preset.get('summary_only', False)) if isinstance(preset, dict) else False
            self.summary_only_checkbox.setChecked(self.summary_only)

            preset_spec_limits = preset.get('column_spec_limits', {}) if isinstance(preset, dict) else {}
            self.column_spec_limits = normalize_column_spec_limits(self.selected_data_columns, preset_spec_limits)

            preset_plot_toggles = preset.get('plot_toggles', {}) if isinstance(preset, dict) else {}
            self.plot_toggles = normalize_plot_toggles(
                self.selected_data_columns,
                preset_plot_toggles,
                full_report=self.include_extended_plots.isChecked(),
            )
            self._sync_ui_state()

    def handle_filter_button(self):
        """Open the column picker and guard against empty data selections."""
        logger.debug("FILTER button clicked.")

        # Open the FilterDialog and pass the column names to it
        if self.data_frame is not None:
            filter_dialog = FilterDialog(self, self.column_names)

            if filter_dialog.exec() == QDialog.DialogCode.Accepted:
                self.selected_indexes, self.selected_data_columns = filter_dialog.get_selected_columns()

                # Use the selected_indexes and selected_data_columns for further processing
                if self.selected_indexes:
                    logger.info("Selected index columns: %s", self.selected_indexes)
                if self.selected_data_columns:
                    logger.info("Selected data columns: %s", self.selected_data_columns)
                    self.column_spec_limits = {
                        column: self.column_spec_limits.get(column, {'nom': 0.0, 'usl': 0.0, 'lsl': 0.0})
                        for column in self.selected_data_columns
                    }
                    self.plot_toggles = normalize_plot_toggles(
                        self.selected_data_columns,
                        self.plot_toggles,
                        full_report=self.include_extended_plots.isChecked(),
                    )
                    self._sync_ui_state()

    def handle_spec_limits_button(self):
        """Open spec-limits editor and store normalized per-column values."""
        if not self.selected_data_columns:
            self._sync_ui_state()
            return

        spec_dialog = SpecLimitsDialog(self, self.selected_data_columns, self.column_spec_limits)
        if spec_dialog.exec() == QDialog.DialogCode.Accepted:
            self.column_spec_limits = spec_dialog.get_limits()
            self._sync_ui_state()

    def handle_clear_presets_button(self):
        """Clear all saved CSV presets after explicit user confirmation."""
        if not self.preset_path.exists():
            QMessageBox.information(self, "No presets", "No saved CSV presets were found.")
            return
        reply = QMessageBox.question(
            self,
            "Clear saved presets",
            "Remove all saved CSV Summary presets?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.preset_path.unlink(missing_ok=True)
        QMessageBox.information(self, "Presets cleared", "Saved CSV presets were removed.")

    def handle_output_button(self):
        """Select an output workbook path and enable export start."""
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
            selected_path = Path(filename)
            if selected_path.suffix != ".xlsx":
                selected_path = selected_path.with_suffix(".xlsx")
            logger.info("Selected output Excel file: %s", selected_path)
            self.output_file = str(selected_path)
            self._sync_ui_state()

    @pyqtSlot()
    def show_loading_screen(self):
        """Create progress UI and hand CSV processing to a worker thread."""
        self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif = create_worker_progress_dialog(
            self,
            window_title="Processing...",
            initial_status_text=build_three_line_status("Processing data...", "Preparing CSV summary export", "ETA --"),
            on_cancel=self.stop_data_processing_and_close_loading,
        )

        # Start the data processing in a separate thread
        self.worker_thread = DataProcessingThread(
            self.selected_indexes,
            self.selected_data_columns,
            self.input_file,
            self.output_file,
            self.data_frame,
            self.csv_config,
            self.column_spec_limits,
            self.plot_toggles if self.include_extended_plots.isChecked() else build_default_plot_toggles(self.selected_data_columns, full_report=False),
            summary_only=self.summary_only_checkbox.isChecked(),
        )
        # Connect the progress signal to the update_progress_bar slot
        self.worker_thread.progress_signal.connect(self.update_progress_bar)
        self._worker_failed = False
        self.worker_thread.status_signal.connect(self._on_worker_status_text)
        self.worker_thread.finished.connect(self.on_data_processing_finished)
        self.worker_thread.start()

        # Show the loading dialog
        self.loading_dialog.show()

    def update_progress_bar(self, value):
        # Update the progress bar value
        self.loading_bar.setValue(value)

    def stop_data_processing_and_close_loading(self):
        """Forward cancel requests to the worker thread if it is active."""
        if self.worker_thread:
            # Stop the data processing thread if it exists
            self.worker_thread.cancel()

    def _on_worker_status_text(self, status_text):
        self.loading_label.setText(status_text)
        self._worker_failed = "Processing failed" in (status_text or "")

    @pyqtSlot()
    def on_data_processing_finished(self):
        """Handle completion feedback for both canceled and successful runs."""
        # Data processing is complete or canceled

        if self._worker_failed:
            QMessageBox.critical(
                self,
                "Processing failed",
                "CSV summary export failed. Review the log for details and try again.",
            )
        elif self.worker_thread.canceled:
            # Show a message box to inform the user that processing has been canceled
            QMessageBox.information(self, "Processing canceled", "Processing has been canceled")
        else:
            # Show a message box to inform the user that processing is complete
            QMessageBox.information(self, "Processing complete", f"Data saved to {self.output_file}!")

        # Close the loading dialog
        self.loading_dialog.close()

        # Reset the worker thread
        self.worker_thread = None


    def _show_chart_generation_advisory(self):
        """Warn about heavy chart workloads and offer a faster fallback mode."""
        chart_count = estimate_enabled_chart_count(
            self.selected_data_columns,
            self.plot_toggles,
            full_report=self.include_extended_plots.isChecked(),
            summary_only=self.summary_only_checkbox.isChecked(),
        )
        if chart_count <= 40:
            return

        reply = QMessageBox.question(
            self,
            "Large chart workload detected",
            (
                f"This export is configured to generate about {chart_count} charts.\n\n"
                "This may be slow for large datasets.\n"
                "Would you like to switch to Quick-look mode (disable charts)?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.include_extended_plots.setChecked(False)

    def handle_start_button(self):
        """Persist current settings and start processing when inputs are ready."""
        self._sync_ui_state()
        if not self.start_button.isEnabled():
            logger.warning("Create Summary requested while dialog is not ready.")
            return

        self._show_chart_generation_advisory()

        self._save_presets(
            build_csv_summary_preset_key(self.input_file),
            self.selected_indexes,
            self.selected_data_columns,
            self.csv_config,
            self.column_spec_limits,
            self.include_extended_plots.isChecked(),
            self.summary_only_checkbox.isChecked(),
            self.plot_toggles,
        )
        self.show_loading_screen()
