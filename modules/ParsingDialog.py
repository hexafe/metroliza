from modules import Base64EncodedFiles
from modules.ParseReportsThread import ParseReportsThread
from modules.CustomLogger import CustomLogger
from PyQt6.QtCore import QSize, QTemporaryFile, Qt, pyqtSlot
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QDialog, QFileDialog, QGridLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout
import base64
import logging
from modules.contracts import ParseRequest, validate_parse_request
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
            # Create the progress dialog
            self.loading_dialog = QDialog(self, Qt.WindowType.WindowTitleHint)
            self.loading_dialog.setWindowTitle("Parsing reports...")
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
            self.loading_gif = QMovie(temp_file_name)  # Save as an instance variable
            self.loading_gif.setScaledSize(QSize(200, 200))
            loading_gif_label.setMovie(self.loading_gif)
            self.loading_gif.start()

            # Create the loading label and progress bar
            self.loading_label = QLabel("Parsing files...", self.loading_dialog)
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
            cancel_button.clicked.connect(self.stop_parsing)
            layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

            # Disable the parse button and show the progress dialog
            self.parse_button.setEnabled(False)
            self.loading_dialog.show()

            request = validate_parse_request(ParseRequest(source_directory=self.directory, db_file=self.db_file))

            # Start the parsing thread
            self.parse_thread = ParseReportsThread(request)
            self.parse_thread.update_label.connect(self.loading_label.setText)
            self.parse_thread.update_progress.connect(self.loading_bar.setValue)
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
                self.loading_label.setText("Canceling parsing...")
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def on_parse_finished(self):
        try:
            if self.parsing_canceled:
                # Show a message box to inform the user that parsing has been canceled
                QMessageBox.information(self, "Parsing canceled", "Parsing has been canceled")
            else:
                # Show a message box to inform the user that parsing is complete
                QMessageBox.information(self, "Parsing successful", f"Measurements data saved to {self.db_file}!")

            # Close the loading dialog
            self.loading_dialog.accept()

            # Re-enable the parse button
            self.parse_button.setEnabled(True)

            # Reset the parsing canceled flag
            self.parsing_canceled = False

            # Close the parsing dialog
            self.accept()
        except Exception as e:
            self.log_and_exit(e)
        
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
