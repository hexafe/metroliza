from modules.progress_status import build_three_line_status
from modules.ParseReportsThread import ParseReportsThread
from modules.CustomLogger import CustomLogger
from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import QDialog, QFileDialog, QGridLayout, QLabel, QMessageBox, QPushButton
import logging
from modules.contracts import ParseRequest, validate_parse_request
from modules.worker_progress_dialog import create_worker_progress_dialog
import shutil


logger = logging.getLogger(__name__)


class ParsingDialog(QDialog):
    def __init__(self, parent=None, directory=None, db_file=None):
        super().__init__(parent)

        # Set the window title and geometry
        self.setWindowTitle("Parsing")
        self.setGeometry(100, 100, 300, 150)

        # Initialize variables
        self.directory = directory
        self.db_file = db_file

        # Initialize the widgets
        self.directory_label = QLabel("Select a source (directory or archive file):")
        self.directory_button = QPushButton("Browse")
        self.directory_button.clicked.connect(self.select_directory)
        self.directory_label.setToolTip("Use this button to select a folder with PDF reports or a supported archive directly")
        self.directory_button.setToolTip("Use this button to select a folder with PDF reports or a supported archive directly")

        self.database_label = QLabel("Select a database file:")
        self.database_button = QPushButton("Browse")
        self.database_button.clicked.connect(self.select_database)
        self.database_label.setToolTip("Use this button to select the database to which to save the results from PDF files")
        self.database_button.setToolTip("Use this button to select the database to which to save the results from PDF files")

        self.parse_button = QPushButton("Parse reports")
        self.parse_button.clicked.connect(self.show_loading_screen)
        self.parse_button.setEnabled(False)
        self.parse_button.setToolTip("Use this button to start reading data from PDF files and writing to the database")

        self.spacer = QLabel(" ")

        if self.directory:
            self.directory_text_label = QLabel(self.directory)
            self.database_button.setEnabled(True)
        else:
            self.directory_text_label = QLabel("None selected")
            self.database_button.setEnabled(False)

        if self.db_file:
            self.database_text_label = QLabel(self.db_file)
            if self.directory:
                self.parse_button.setEnabled(True)
        else:
            self.database_text_label = QLabel("None selected")
            self.parse_button.setEnabled(False)

        # Initialize thread and flag
        self.parse_thread = None
        self.parsing_canceled = False
        self.parse_error_message = None

        # Initialize the layout
        self.layout = QGridLayout()
        self.layout.addWidget(self.directory_label, 0, 0)
        self.layout.addWidget(self.directory_text_label, 1, 0)
        self.layout.addWidget(self.directory_button, 2, 0, 1, 2)
        self.layout.addWidget(self.spacer, 3, 0)

        self.layout.addWidget(self.database_label, 4, 0)
        self.layout.addWidget(self.database_text_label, 5, 0)
        self.layout.addWidget(self.database_button, 6, 0, 1, 2)
        self.layout.addWidget(self.spacer, 7, 0)

        self.layout.addWidget(self.parse_button, 8, 0, 1, 2)

        self.setLayout(self.layout)

    @pyqtSlot()
    def select_directory(self):
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
                self.database_button.setEnabled(True)
                self.parent().set_directory(selected_source)

                if self.db_file and self.directory:
                    self.parse_button.setEnabled(True)
                else:
                    self.parse_button.setEnabled(False)
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def select_database(self):
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

                if self.db_file and self.directory:
                    self.parse_button.setEnabled(True)
                else:
                    self.parse_button.setEnabled(False)
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def show_loading_screen(self):
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
        self.parse_error_message = message
        self.loading_label.setText(build_three_line_status("Parsing failed.", "See error details for context", "ETA --"))

    @pyqtSlot()
    def on_parse_finished(self):
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
