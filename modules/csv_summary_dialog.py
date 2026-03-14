"""CSV summary export dialogs and worker thread for workbook generation."""

from pathlib import Path
import logging
import re

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from modules import ui_theme_tokens
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


logger = logging.getLogger(__name__)

class FilterDialog(QDialog):
    """Select index and data columns for CSV summary processing.

    The dialog supports convenient defaults via special rows for first-column
    index selection and selecting all non-index data columns.
    """

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
        self._apply_list_theme_styles()
        self.select_default_filter()

    def _apply_list_theme_styles(self):
        highlight_name = ui_theme_tokens.SELECTED_ROW_BACKGROUND_FALLBACK
        for list_widget in (self.index_list_widget, self.data_list_widget):
            palette = list_widget.palette() if hasattr(list_widget, 'palette') else None
            highlight_color = palette.highlight().color() if palette is not None and hasattr(palette, 'highlight') else None
            if highlight_color is not None and hasattr(highlight_color, 'isValid') and highlight_color.isValid():
                highlight_name = highlight_color.name()

            highlight_name = ui_theme_tokens.selected_row_background_override(highlight_name)
            selected_text_color = ui_theme_tokens.selected_text_color(highlight_name)
            list_widget.setStyleSheet(
                "QListWidget::item:selected {"
                f" background-color: {highlight_name};"
                f" color: {selected_text_color};"
                " }"
            )

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
        self.setGeometry(220, 220, 700, 380)
        self.data_columns = data_columns

        layout = QVBoxLayout()
        self.table = QTableWidget(len(data_columns), 4, self)
        self.table.setHorizontalHeaderLabels(["Column", "NOM", "USL", "LSL"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)

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
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

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
        self.setGeometry(200, 200, 300, 150)

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

        # Initialize the layout
        layout = QVBoxLayout()

        # Add the buttons to the layout
        self.input_button = QPushButton("Select input file (CSV)")
        self.filter_button = QPushButton("Filter columns (optional)")
        self.spec_limits_button = QPushButton("Set spec limits (optional)")
        self.clear_presets_button = QPushButton("Clear saved presets (optional)")
        self.include_extended_plots = QCheckBox("Include histogram and boxplot charts")
        self.summary_only_checkbox = QCheckBox("Summary-only mode (skip per-column sheets/charts)")
        self.output_button = QPushButton("Select output file (xlsx)")
        self.start_button = QPushButton("START")  # Add the START button
        layout.addWidget(self.input_button)
        layout.addWidget(self.filter_button)
        layout.addWidget(self.spec_limits_button)
        layout.addWidget(self.clear_presets_button)
        layout.addWidget(self.include_extended_plots)
        layout.addWidget(self.summary_only_checkbox)
        layout.addWidget(self.output_button)
        layout.addWidget(self.start_button)  # Add the START button to the layout

        # Connect the buttons to their respective functions
        self.input_button.clicked.connect(self.handle_input_button)
        self.filter_button.clicked.connect(self.handle_filter_button)
        self.spec_limits_button.clicked.connect(self.handle_spec_limits_button)
        self.clear_presets_button.clicked.connect(self.handle_clear_presets_button)
        self.output_button.clicked.connect(self.handle_output_button)
        self.start_button.clicked.connect(self.handle_start_button)  # Connect the START button

        self.include_extended_plots.setChecked(True)
        self.summary_only_checkbox.setChecked(False)

        # Initially, disable the FILTER, OUTPUT, and START buttons
        self.filter_button.setEnabled(False)
        self.spec_limits_button.setEnabled(False)
        self.output_button.setEnabled(False)
        self.start_button.setEnabled(False)

        # Set the layout for the dialog
        self.setLayout(layout)

        self.preset_path = Path.home() / '.metroliza' / '.csv_summary_presets.json'

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

    # Define functions for button clicks
    def handle_input_button(self):
        """Select an input CSV, load it, and restore matching preset values."""
        options = QFileDialog.Option.ReadOnly
        filename, _ = QFileDialog.getOpenFileName(self, "Select input file (CSV)", "", "CSV Files (*.csv);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".csv"):
                filename += ".csv"
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
                self.filter_button.setEnabled(False)
                self.spec_limits_button.setEnabled(False)
                self.output_button.setEnabled(False)
                self.start_button.setEnabled(False)
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
        else:
            QMessageBox.warning(self, "Warning", "No data loaded. Please select an input file first.")

    def handle_spec_limits_button(self):
        """Open spec-limits editor and store normalized per-column values."""
        if not self.selected_data_columns:
            QMessageBox.information(self, "No data columns", "Select input/filter columns before setting spec limits.")
            return

        spec_dialog = SpecLimitsDialog(self, self.selected_data_columns, self.column_spec_limits)
        if spec_dialog.exec() == QDialog.DialogCode.Accepted:
            self.column_spec_limits = spec_dialog.get_limits()

    def handle_clear_presets_button(self):
        """Clear all saved CSV presets after explicit user confirmation."""
        if not self.preset_path.exists():
            QMessageBox.information(self, "No presets", "No saved CSV presets were found.")
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
            logger.info("Selected output Excel file: %s", filename)
            self.output_file = filename
            # Enable the START button after the output file is selected
            self.start_button.setEnabled(True)

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
        self.worker_thread.status_signal.connect(self.loading_label.setText)
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

    @pyqtSlot()
    def on_data_processing_finished(self):
        """Handle completion feedback for both canceled and successful runs."""
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
        # Perform the desired action when the START button is clicked
        # You can access the input_file, output_file, and data_frame variables here for further processing

        if self.data_frame is not None:
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
            # Show the loading screen and progress bar
            self.show_loading_screen()
        else:
            logger.warning("Start requested without loaded data frame.")
