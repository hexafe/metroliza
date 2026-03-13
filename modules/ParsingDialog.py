"""Parsing dialog for selecting input sources and running report ingestion."""

from modules.progress_status import build_three_line_status
from modules.parse_reports_thread import ParseReportsThread
from modules.custom_logger import CustomLogger
from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
import logging
from modules.contracts import ParseRequest, validate_parse_request
from modules.worker_progress_dialog import create_worker_progress_dialog
from modules import ui_theme_tokens
import shutil


logger = logging.getLogger(__name__)


class ParsingDialog(QDialog):
    """Collect parse inputs and coordinate parsing thread lifecycle.

    The dialog tracks selected source/database paths and handles cancellation,
    error propagation, and completion feedback from the worker thread.
    """

    def __init__(self, parent=None, directory=None, db_file=None):
        super().__init__(parent)

        self.section_spacing = ui_theme_tokens.SPACE_12
        self.section_content_spacing = ui_theme_tokens.SPACE_8

        # Set the window title and geometry
        self.setWindowTitle("Parsing")
        self.setStyleSheet(ui_theme_tokens.dialog_shell_style())
        self.setGeometry(100, 100, 300, 150)

        # Initialize variables
        self.directory = directory
        self.db_file = db_file

        # Initialize the widgets
        self.directory_label = QLabel("Select a source (directory or archive file):")
        self.directory_label.setStyleSheet(ui_theme_tokens.typography_style("section", ui_theme_tokens.COLOR_TEXT_PRIMARY))
        self.directory_help_label = QLabel("Step 1: Choose the folder with reports or a supported archive to ingest.")
        self.directory_help_label.setWordWrap(True)
        self.directory_help_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_SECONDARY))
        self.directory_button = QPushButton("Browse")
        self.directory_button.clicked.connect(self.select_directory)
        self.directory_label.setToolTip("Use this button to select a folder with PDF reports or a supported archive directly")
        self.directory_button.setToolTip("Use this button to select a folder with PDF reports or a supported archive directly")

        self.database_label = QLabel("Select a database file:")
        self.database_label.setStyleSheet(ui_theme_tokens.typography_style("section", ui_theme_tokens.COLOR_TEXT_PRIMARY))
        self.database_help_label = QLabel("Step 2: Choose where parsed report data should be stored.")
        self.database_help_label.setWordWrap(True)
        self.database_help_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_SECONDARY))
        self.database_button = QPushButton("Browse")
        self.database_button.clicked.connect(self.select_database)
        self.database_label.setToolTip("Use this button to select the database to which to save the results from PDF files")
        self.database_button.setToolTip("Use this button to select the database to which to save the results from PDF files")

        self.parse_button = QPushButton("Parse reports")
        self.parse_button.clicked.connect(self.show_loading_screen)
        self.parse_button.setStyleSheet(ui_theme_tokens.button_style("primary"))
        self.parse_button.setDefault(True)
        self.parse_button.setAutoDefault(True)
        self.parse_button.setToolTip("Use this button to start reading data from PDF files and writing to the database")
        self.action_help_label = QLabel()
        self.action_help_label.setWordWrap(True)
        self.action_help_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_SECONDARY))

        if self.directory:
            self.directory_text_label = QLabel(self.directory)
        else:
            self.directory_text_label = QLabel("None selected")
        self.directory_text_label.setStyleSheet(ui_theme_tokens.typography_style("body", ui_theme_tokens.COLOR_TEXT_PRIMARY))

        if self.db_file:
            self.database_text_label = QLabel(self.db_file)
        else:
            self.database_text_label = QLabel("None selected")
        self.database_text_label.setStyleSheet(ui_theme_tokens.typography_style("body", ui_theme_tokens.COLOR_TEXT_PRIMARY))

        self.directory_button.setStyleSheet(ui_theme_tokens.button_style("secondary"))
        self.database_button.setStyleSheet(ui_theme_tokens.button_style("secondary"))

        # Initialize thread and flag
        self.parse_thread = None
        self.parsing_canceled = False
        self.parse_error_message = None

        # Initialize the layout
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(
            ui_theme_tokens.SPACE_16,
            ui_theme_tokens.SPACE_16,
            ui_theme_tokens.SPACE_16,
            ui_theme_tokens.SPACE_16,
        )
        self.layout.setSpacing(self.section_spacing)
        self.layout.addWidget(self._build_source_section())
        self.layout.addWidget(self._build_database_section())
        self.layout.addWidget(self._build_action_section())

        self.setLayout(self.layout)
        self._refresh_ui_state()

    def _build_source_section(self):
        section_layout = QGridLayout()
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setVerticalSpacing(self.section_content_spacing)
        section_layout.addWidget(self.directory_help_label, 0, 0)
        section_layout.addWidget(self.directory_label, 1, 0)
        section_layout.addWidget(self.directory_text_label, 2, 0)
        section_layout.addWidget(self.directory_button, 3, 0)
        return self._build_section_widget("Step 1 — Source", section_layout)

    def _build_database_section(self):
        section_layout = QGridLayout()
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setVerticalSpacing(self.section_content_spacing)
        section_layout.addWidget(self.database_help_label, 0, 0)
        section_layout.addWidget(self.database_label, 1, 0)
        section_layout.addWidget(self.database_text_label, 2, 0)
        section_layout.addWidget(self.database_button, 3, 0)
        return self._build_section_widget("Step 2 — Database", section_layout)

    def _build_action_section(self):
        section_layout = QVBoxLayout()
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(self.section_content_spacing)
        section_layout.addWidget(self.action_help_label)
        section_layout.addWidget(self.parse_button)
        return self._build_section_widget("Step 3 — Action", section_layout)

    def _build_section_widget(self, title, content_layout):
        container = QFrame(self)
        container.setStyleSheet(ui_theme_tokens.panel_style(card=True))
        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            ui_theme_tokens.SPACE_12,
            ui_theme_tokens.SPACE_12,
            ui_theme_tokens.SPACE_12,
            ui_theme_tokens.SPACE_12,
        )
        layout.setSpacing(ui_theme_tokens.SPACE_8)

        title_label = QLabel(title)
        title_label.setStyleSheet(ui_theme_tokens.typography_style("section", ui_theme_tokens.COLOR_TEXT_PRIMARY))
        layout.addWidget(title_label)

        separator = QFrame(container)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"color: {ui_theme_tokens.COLOR_BORDER_MUTED};")
        layout.addWidget(separator)
        layout.addLayout(content_layout)
        return container

    def _refresh_ui_state(self):
        has_source = bool(self.directory)
        has_database = bool(self.db_file)
        self.database_button.setEnabled(has_source)
        self.parse_button.setEnabled(has_source and has_database)

        if not has_source:
            self.action_help_label.setText("Step 3: Choose a source first, then choose a database to enable parsing.")
            self.parse_button.setToolTip("Select a source first")
        elif not has_database:
            self.action_help_label.setText("Step 3: Choose a database file to enable parsing.")
            self.parse_button.setToolTip("Select a database file to enable parsing")
        else:
            self.action_help_label.setText("Step 3: Parse reports to ingest data into the selected database.")
            self.parse_button.setToolTip("Start reading report data and writing it to the selected database")

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

                archive_patterns = sorted({f"*{ext}" for _, extensions, _ in shutil.get_unpack_formats() for ext in extensions})
                archive_filter = "Supported archives (" + " ".join(archive_patterns) + ")" if archive_patterns else "All Files (*)"
                selected_source, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select archive",
                    "",
                    f"{archive_filter};;All Files (*)",
                )

            if selected_source:
                logger.info("Selected parse source: %s", selected_source)
                self.directory = selected_source
                self.directory_text_label.setText(selected_source)
                self.parent().set_directory(selected_source)
                self._refresh_ui_state()
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
                self.database_text_label.setText(filename)
                self.parent().set_db_file(filename)
                self._refresh_ui_state()
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

            # Disable the parse button and show the progress dialog
            self.parse_button.setEnabled(False)
            self.loading_dialog.show()

            request = validate_parse_request(ParseRequest(source_directory=self.directory, db_file=self.db_file))

            # Start the parsing thread
            self.parse_thread = ParseReportsThread(request)
            self.parse_thread.update_label.connect(self.loading_label.setText)
            self.parse_thread.update_progress.connect(self.loading_bar.setValue)
            self.parse_thread.error_occurred.connect(self.on_parse_error)
            self.parse_thread.finished.connect(self.on_parse_finished)
            self.parse_thread.start()
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


    @pyqtSlot(str)
    def on_parse_error(self, message):
        """Capture parse errors for final summary when the worker finishes."""
        self.parse_error_message = message
        self.loading_label.setText(build_three_line_status("Parsing failed.", "See error details for context", "ETA --"))

    @pyqtSlot()
    def on_parse_finished(self):
        """Handle parse completion, including cancellation and error paths."""
        try:
            if self.parse_error_message:
                QMessageBox.warning(self, "Parsing failed", self.parse_error_message)
            elif self.parsing_canceled:
                # Show a message box to inform the user that parsing has been canceled
                QMessageBox.information(self, "Parsing canceled", "Parsing has been canceled")
            else:
                # Show a message box to inform the user that parsing is complete
                QMessageBox.information(self, "Parsing successful", f"Measurements data saved to {self.db_file}!")

            # Close the loading dialog
            self.loading_dialog.accept()

            # Re-enable the parse button
            self.parse_button.setEnabled(True)

            # Reset parse state flags
            self.parsing_canceled = False
            self.parse_error_message = None

            # Close the parsing dialog
            self.accept()
        except Exception as e:
            self.log_and_exit(e)
        
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
