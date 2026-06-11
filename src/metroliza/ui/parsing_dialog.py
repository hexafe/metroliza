"""Parsing dialog for selecting input sources and running report ingestion."""

from metroliza.shared.progress_status import build_three_line_status
from metroliza.parsing.parse_reports_thread import ParseReportsThread
from metroliza.shared.custom_logger import CustomLogger
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
)
import logging
from metroliza.shared.parse_contracts import ParseRequest, validate_parse_request
try:
    from metroliza.ui.worker_progress_dialog import (
        create_delayed_worker_progress_dialog as create_worker_progress_dialog,
    )
except ImportError:  # pragma: no cover - compatibility with lightweight test stubs.
    from metroliza.ui.worker_progress_dialog import create_worker_progress_dialog
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    path_field,
    section_label,
    secondary_label,
    set_status_variant,
    status_chip,
    update_path_field,
)
import shutil


logger = logging.getLogger(__name__)

_METADATA_MODE_FAST = "fast"
_METADATA_MODE_FAST_THEN_ENRICH = "fast_then_enrich"
_METADATA_MODE_COMPLETE = "complete"
_METADATA_MODE_REQUEST_FIELDS = {
    _METADATA_MODE_FAST: ("light", False),
    _METADATA_MODE_FAST_THEN_ENRICH: ("light", False),
    _METADATA_MODE_COMPLETE: ("complete", False),
}


class ParsingDialog(QDialog):
    """Collect parse inputs and coordinate parsing thread lifecycle.

    The dialog tracks selected source/database paths and handles cancellation,
    error propagation, and completion feedback from the worker thread.
    """

    metadata_enrichment_requested = pyqtSignal(str)

    def __init__(self, parent=None, directory=None, db_file=None):
        super().__init__(parent)

        # Set the window title and geometry
        self.setWindowTitle("Parsing")
        configure_window_size(self, minimum=(520, 300), initial=(620, 360))

        # Initialize variables
        self.directory = directory
        self.db_file = db_file

        # Initialize the widgets
        self.source_section_label = section_label("Source")
        self.directory_label = QLabel("Reports directory or archive:")
        self.directory_button = QPushButton("Browse folder")
        self.directory_button.clicked.connect(self.select_directory)
        self.archive_button = QPushButton("Browse archive")
        self.archive_button.clicked.connect(self.select_archive)
        self.directory_label.setToolTip("Folder with PDF reports, or a supported archive file.")
        self.directory_button.setToolTip("Choose a folder with PDF reports.")
        self.archive_button.setToolTip("Choose a supported archive file with PDF reports.")

        self.database_section_label = section_label("Destination")
        self.database_label = QLabel("Database file:")
        self.database_button = QPushButton("Browse")
        self.database_button.clicked.connect(self.select_database)
        self.database_label.setToolTip("SQLite database that will receive parsed measurements.")
        self.database_button.setToolTip("Choose or create the SQLite database for parsed measurements.")

        self.import_section_label = section_label("Import behavior")
        self.metadata_mode_label = QLabel("Metadata mode:")
        self.metadata_mode_combo = QComboBox()
        fast_tooltip = (
            "Light metadata skips OCR fallback and uses filename or embedded text metadata. "
            "Use this for the fastest import."
        )
        enrich_tooltip = (
            "Import quickly with light metadata first, then run a visible OCR metadata enrichment pass."
        )
        complete_tooltip = (
            "Run OCR fallback during import for stronger header metadata coverage. "
            "This is slower on large imports."
        )
        self.metadata_mode_combo.addItem("Fast import - light metadata, no OCR", _METADATA_MODE_FAST)
        self.metadata_mode_combo.setItemData(0, fast_tooltip, Qt.ItemDataRole.ToolTipRole)
        self.metadata_mode_combo.addItem(
            "Fast import, then enrich metadata",
            _METADATA_MODE_FAST_THEN_ENRICH,
        )
        self.metadata_mode_combo.setItemData(1, enrich_tooltip, Qt.ItemDataRole.ToolTipRole)
        self.metadata_mode_combo.addItem("Complete import - OCR during parsing", _METADATA_MODE_COMPLETE)
        self.metadata_mode_combo.setItemData(2, complete_tooltip, Qt.ItemDataRole.ToolTipRole)
        self.metadata_mode_combo.setCurrentIndex(self.metadata_mode_combo.findData(_METADATA_MODE_FAST))
        self.metadata_mode_label.setToolTip(f"{fast_tooltip} {enrich_tooltip} {complete_tooltip}")
        self.metadata_mode_combo.setToolTip(f"{fast_tooltip} {enrich_tooltip} {complete_tooltip}")

        self.parse_button = QPushButton("Parse reports")
        self.parse_button.clicked.connect(self.show_loading_screen)
        self.parse_button.setEnabled(False)
        self.parse_button.setToolTip("Use this button to start reading data from PDF files and writing to the database")
        if hasattr(self.parse_button, "setDefault"):
            self.parse_button.setDefault(True)

        self.readiness_label = status_chip("Select a source and database to enable parsing.", "warning")

        self.mode_guidance_label = secondary_label(
            "Fast import stays light by default. OCR metadata can run after import or during complete import."
        )

        if self.directory:
            self.directory_text_label = path_field(self.directory)
            self.database_button.setEnabled(True)
        else:
            self.directory_text_label = path_field("")
            self.database_button.setEnabled(False)

        if self.db_file:
            self.database_text_label = path_field(self.db_file)
            if self.directory:
                self.parse_button.setEnabled(True)
        else:
            self.database_text_label = path_field("")
            self.parse_button.setEnabled(False)

        # Initialize thread and flag
        self.parse_thread = None
        self.parsing_canceled = False
        self.parse_error_message = None
        self._pending_modeless_metadata_enrichment = False

        # Initialize the layout
        self.layout = QGridLayout()
        try:
            attach_help_menu_to_layout(self.layout, self, [("Parsing manual", 'parsing')])
        except TypeError:
            # Parent-none safety tests install lightweight Qt stubs after the
            # help-menu module may already be imported with real Qt classes.
            pass
        if hasattr(self.layout, "setContentsMargins"):
            self.layout.setContentsMargins(14, 14, 14, 14)
        if hasattr(self.layout, "setHorizontalSpacing"):
            self.layout.setHorizontalSpacing(10)
        if hasattr(self.layout, "setVerticalSpacing"):
            self.layout.setVerticalSpacing(8)
        if hasattr(self.layout, "setColumnStretch"):
            self.layout.setColumnStretch(1, 1)

        row = 0
        self.layout.addWidget(self.source_section_label, row, 0, 1, 4)
        row += 1
        self.layout.addWidget(self.directory_label, row, 0)
        self.layout.addWidget(self.directory_text_label, row, 1)
        self.layout.addWidget(self.directory_button, row, 2)
        self.layout.addWidget(self.archive_button, row, 3)

        row += 1
        self.layout.addWidget(self.database_section_label, row, 0, 1, 4)
        row += 1
        self.layout.addWidget(self.database_label, row, 0)
        self.layout.addWidget(self.database_text_label, row, 1)
        self.layout.addWidget(self.database_button, row, 2)

        row += 1
        self.layout.addWidget(self.import_section_label, row, 0, 1, 4)
        row += 1
        self.layout.addWidget(self.metadata_mode_label, row, 0)
        self.layout.addWidget(self.metadata_mode_combo, row, 1, 1, 3)
        row += 1
        self.layout.addWidget(self.mode_guidance_label, row, 0, 1, 4)

        row += 1
        self.layout.addWidget(self.readiness_label, row, 0, 1, 4)
        row += 1
        self.layout.addWidget(self.parse_button, row, 3)

        self.setLayout(self.layout)
        self._sync_readiness_state()
        configure_accessibility(self.directory_button, name="Browse parse source")
        configure_accessibility(self.archive_button, name="Browse parse archive source")
        configure_accessibility(self.database_button, name="Browse parse database")
        configure_accessibility(self.metadata_mode_combo, name="Metadata mode")
        configure_accessibility(self.parse_button, name="Parse reports")
        apply_metroliza_theme(self)

    def _selected_metadata_request_fields(self):
        selected_mode = self.metadata_mode_combo.currentData() or _METADATA_MODE_FAST
        return _METADATA_MODE_REQUEST_FIELDS.get(selected_mode, _METADATA_MODE_REQUEST_FIELDS[_METADATA_MODE_FAST])

    @staticmethod
    def _archive_extension_set():
        return {ext.lower() for _, extensions, _ in shutil.get_unpack_formats() for ext in extensions}

    @staticmethod
    def _archive_file_filter():
        archive_patterns = sorted({
            f"*{ext}"
            for _, extensions, _ in shutil.get_unpack_formats()
            for ext in extensions
        })
        if not archive_patterns:
            return "All Files (*)"
        return "Supported archives (" + " ".join(archive_patterns) + ")"

    def _selected_metadata_mode(self):
        return self.metadata_mode_combo.currentData() or _METADATA_MODE_FAST

    def _source_is_archive(self):
        if not self.directory:
            return False
        return str(self.directory).lower().endswith(tuple(self._archive_extension_set()))

    def _build_parse_request_fields(self):
        selected_mode = self._selected_metadata_mode()
        metadata_parsing_mode, run_background_metadata_enrichment = _METADATA_MODE_REQUEST_FIELDS.get(
            selected_mode,
            _METADATA_MODE_REQUEST_FIELDS[_METADATA_MODE_FAST],
        )
        request_modeless_enrichment = selected_mode == _METADATA_MODE_FAST_THEN_ENRICH

        if request_modeless_enrichment and self._source_is_archive():
            # Archive imports are unpacked into a temporary directory owned by
            # ParseReportsThread. Modeless enrichment would run after cleanup,
            # so archive fast-then-enrich intentionally keeps enrichment inside
            # the parser thread while those extracted files still exist.
            run_background_metadata_enrichment = True
            request_modeless_enrichment = False

        return metadata_parsing_mode, run_background_metadata_enrichment, request_modeless_enrichment

    def _sync_readiness_state(self):
        is_ready = bool(self.directory and self.db_file)
        self.parse_button.setEnabled(is_ready)
        if is_ready:
            self.readiness_label.setText("Ready to parse selected reports into the database.")
            set_status_variant(self.readiness_label, "success")
        elif self.directory:
            self.readiness_label.setText("Select or create a database before parsing.")
            set_status_variant(self.readiness_label, "warning")
        else:
            self.readiness_label.setText("Select a source and database to enable parsing.")
            set_status_variant(self.readiness_label, "warning")

    def _set_parse_source(self, selected_source):
        if not selected_source:
            return
        logger.info("Selected parse source: %s", selected_source)
        self.directory = selected_source
        update_path_field(self.directory_text_label, selected_source)
        self.database_button.setEnabled(True)
        if self.parent() is not None and hasattr(self.parent(), "set_directory"):
            self.parent().set_directory(selected_source)
        self._sync_readiness_state()

    @pyqtSlot()
    def select_directory(self):
        """Choose a parse source, with a fallback path for archive selection."""
        try:
            # Open a dialog to select a directory first.
            selected_source = QFileDialog.getExistingDirectory(self, "Select directory")
            if not selected_source:
                choose_archive = QMessageBox.question(
                    self,
                    "No directory selected",
                    "No directory was selected. Do you want to choose an archive file instead?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if choose_archive != QMessageBox.StandardButton.Yes:
                    return

                selected_source, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select archive",
                    "",
                    f"{self._archive_file_filter()};;All Files (*)",
                )

            self._set_parse_source(selected_source)
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def select_archive(self):
        """Choose an archive parse source directly without first opening folder selection."""
        try:
            selected_source, _ = QFileDialog.getOpenFileName(
                self,
                "Select archive",
                "",
                f"{self._archive_file_filter()};;All Files (*)",
            )
            self._set_parse_source(selected_source)
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def select_database(self):
        """Select or create the destination database and update parent state."""
        try:
            # Open a dialog to select a database file
            # options = QFileDialog.Options()
            # options |= QFileDialog.DontUseNativeDialog
            default_name = self.directory # + "/" + [part for part in self.directory.split("/") if part][-1]
            if not default_name.endswith(".db"):
                    default_name += ".db"
            filename, _ = QFileDialog.getSaveFileName(self, "Select database", f"{default_name}",
                                                    "SQLite3 database (*.db);;All Files (*)")#, options=options)
            if filename:
                if not filename.endswith(".db"):
                    filename += ".db"
                logger.info("Selected parse database file: %s", filename)
                self.db_file = filename
                update_path_field(self.database_text_label, filename)
                if self.parent() is not None and hasattr(self.parent(), "set_db_file"):
                    self.parent().set_db_file(filename)

                self._sync_readiness_state()
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def show_loading_screen(self):
        """Validate parse request and hand processing to the parser thread."""
        try:
            self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif = create_worker_progress_dialog(
                self,
                window_title="Parsing reports...",
                initial_status_text=build_three_line_status("Parsing files...", "Preparing parser thread", "ETA --"),
                on_cancel=self.stop_parsing,
            )

            # Disable the parse button before the worker starts.
            self.parse_button.setEnabled(False)
            self.parsing_canceled = False
            self.parse_error_message = None

            (
                metadata_parsing_mode,
                run_background_metadata_enrichment,
                self._pending_modeless_metadata_enrichment,
            ) = self._build_parse_request_fields()
            request = validate_parse_request(
                ParseRequest(
                    source_directory=self.directory,
                    db_file=self.db_file,
                    metadata_parsing_mode=metadata_parsing_mode,
                    run_background_metadata_enrichment=run_background_metadata_enrichment,
                )
            )

            # Start the parsing thread
            self.parse_thread = ParseReportsThread(request)
            self.parse_thread.update_label.connect(self.loading_label.setText)
            self.parse_thread.update_progress.connect(self.loading_bar.setValue)
            self.parse_thread.error_occurred.connect(self.on_parse_error)
            self.parse_thread.finished.connect(self.on_parse_finished)
            self.parse_thread.start()
            self.loading_dialog.show()
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def stop_parsing(self):
        """Request cooperative parser cancellation without blocking the UI."""
        try:
            # Request cooperative cancellation and return immediately to keep UI responsive
            self.parsing_canceled = True
            if self.parse_thread is not None and self.parse_thread.isRunning():
                self.parse_thread.stop_parsing()
                self.loading_label.setText(build_three_line_status("Canceling parsing...", "Waiting for parser thread to stop", "ETA --"))
        except Exception as e:
            self.log_and_exit(e)


    @staticmethod
    def _report_file_label(count):
        return "report file" if count == 1 else "report files"

    def _build_parse_completion_feedback(self):
        result = getattr(self.parse_thread, "last_parse_result", None)
        if result is None:
            return (
                "info",
                "Parsing successful",
                f"Measurements data saved to {self.db_file}!",
            )

        total_files = max(0, int(getattr(result, "total_files", 0) or 0))
        parsed_files = max(0, int(getattr(result, "parsed_files", 0) or 0))
        failed_files = max(0, int(getattr(result, "failed_files", 0) or 0))

        if total_files == 0:
            return (
                "info",
                "No reports parsed",
                (
                    "No supported report files were found in the selected source. "
                    f"Nothing was written to {self.db_file}."
                ),
            )

        if failed_files and parsed_files == 0:
            return (
                "warning",
                "No reports parsed",
                (
                    f"Metroliza found {total_files} {self._report_file_label(total_files)}, "
                    f"but none were saved to {self.db_file}. "
                    f"{failed_files} {self._report_file_label(failed_files)} could not be parsed. "
                    "Review the log for details, then check the report format and retry."
                ),
            )

        if failed_files:
            return (
                "warning",
                "Parsing completed with warnings",
                (
                    f"{parsed_files} of {total_files} {self._report_file_label(total_files)} "
                    f"completed successfully and are available in {self.db_file}. "
                    f"{failed_files} {self._report_file_label(failed_files)} could not be parsed. "
                    "Skipped files are listed in the log."
                ),
            )

        return (
            "info",
            "Parsing successful",
            f"Measurements data saved to {self.db_file}!",
        )


    @pyqtSlot(str)
    def on_parse_error(self, message):
        """Capture parse errors for final summary when the worker finishes."""
        self.parse_error_message = message
        self.loading_label.setText(build_three_line_status("Parsing failed.", "See error details for context", "ETA --"))

    @pyqtSlot()
    def on_parse_finished(self):
        """Handle parse completion, including cancellation and error paths."""
        try:
            should_request_modeless_enrichment = (
                not self.parse_error_message
                and not self.parsing_canceled
                and self._pending_modeless_metadata_enrichment
            )
            if self.parse_error_message:
                QMessageBox.warning(self, "Parsing failed", self.parse_error_message)
            elif self.parsing_canceled:
                # Show a message box to inform the user that parsing has been canceled
                QMessageBox.information(self, "Parsing canceled", "Parsing has been canceled")
            elif not should_request_modeless_enrichment:
                # Show a message box to inform the user that parsing is complete
                severity, title, message = self._build_parse_completion_feedback()
                if severity == "warning":
                    QMessageBox.warning(self, title, message)
                else:
                    QMessageBox.information(self, title, message)

            # Close the loading dialog
            self.loading_dialog.accept()

            # Re-enable the parse button
            self.parse_button.setEnabled(True)

            # Reset parse state flags
            self.parsing_canceled = False
            self.parse_error_message = None
            self._pending_modeless_metadata_enrichment = False

            if should_request_modeless_enrichment:
                parent = self.parent()
                if parent is not None and hasattr(parent, "set_db_file"):
                    parent.set_db_file(self.db_file)

            # Close the parsing dialog
            self.accept()

            if should_request_modeless_enrichment:
                self.metadata_enrichment_requested.emit(self.db_file)
        except Exception as e:
            self.log_and_exit(e)

    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
