from modules import base64_encoded_files
from modules.ParseReportsThread import ParseReportsThread
from PyQt5.QtCore import QSize, QTemporaryFile, Qt, pyqtSlot
from PyQt5.QtGui import QMovie
from PyQt5.QtWidgets import QDialog, QFileDialog, QGridLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout


import base64


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
        self.directory_label = QLabel("Select a directory:")
        self.directory_button = QPushButton("Browse")
        self.directory_button.clicked.connect(self.select_directory)

        self.database_label = QLabel("Select a database file:")
        self.database_button = QPushButton("Browse")
        self.database_button.clicked.connect(self.select_database)

        self.parse_button = QPushButton("Parse reports")
        self.parse_button.clicked.connect(self.show_loading_screen)
        self.parse_button.setEnabled(False)

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
        # Open a dialog to select a directory
        directory = QFileDialog.getExistingDirectory(self, "Select directory")
        if directory:
            print(f"{directory=}")
            self.directory = directory
            self.directory_text_label.setText(directory)
            self.database_button.setEnabled(True)
            self.parent().set_directory(directory)

            if self.db_file and self.directory:
                self.parse_button.setEnabled(True)
            else:
                self.parse_button.setEnabled(False)

    @pyqtSlot()
    def select_database(self):
        # Open a dialog to select a database file
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        default_name = self.directory # + "/" + [part for part in self.directory.split("/") if part][-1]
        if not default_name.endswith(".db"):
                default_name += ".db"
        filename, _ = QFileDialog.getSaveFileName(self, "Select database", f"{default_name}",
                                                  "SQLite3 database (*.db);;All Files (*)", options=options)
        if filename:
            if not filename.endswith(".db"):
                filename += ".db"
            print(f"{filename=}")
            self.db_file = filename
            self.database_text_label.setText(filename)
            self.parent().set_db_file(filename)

            if self.db_file and self.directory:
                self.parse_button.setEnabled(True)
            else:
                self.parse_button.setEnabled(False)

    @pyqtSlot()
    def show_loading_screen(self):
        # Create the progress dialog
        self.loading_dialog = QDialog(self, Qt.WindowTitleHint)
        self.loading_dialog.setWindowTitle("Parsing reports...")
        self.loading_dialog.setWindowModality(Qt.ApplicationModal)
        self.loading_dialog.setFixedSize(400, 300)

        # Create a QLabel to display the loading GIF
        loading_gif_label = QLabel(self.loading_dialog)
        loading_gif_label.setFixedSize(200, 200)
        loading_gif_label.setAlignment(Qt.AlignCenter)

        # Load the loading.gif from a file, create a QMovie from it, and set it to the label
        loading_gif_decoded = base64.b64decode(base64_encoded_files.encoded_loading_gif)

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
        self.loading_label.setAlignment(Qt.AlignCenter)

        self.loading_bar = QProgressBar(self.loading_dialog)
        self.loading_bar.setValue(0)
        self.loading_bar.setFixedSize(380, 20)
        self.loading_bar.setAlignment(Qt.AlignCenter)

        # Create a layout for the progress dialog and add the loading GIF, loading label, and progress bar to it
        layout = QVBoxLayout(self.loading_dialog)
        layout.addWidget(loading_gif_label, alignment=Qt.AlignHCenter)
        layout.addWidget(self.loading_label, alignment=Qt.AlignHCenter)
        layout.addWidget(self.loading_bar, alignment=Qt.AlignHCenter)

        # Create and add the Cancel button to the layout
        cancel_button = QPushButton("Cancel", self.loading_dialog)
        cancel_button.clicked.connect(self.stop_parsing)
        layout.addWidget(cancel_button, alignment=Qt.AlignHCenter)

        # Disable the parse button and show the progress dialog
        self.parse_button.setEnabled(False)
        self.loading_dialog.show()

        # Start the parsing thread
        self.parse_thread = ParseReportsThread(self.directory, self.db_file)
        self.parse_thread.update_label.connect(self.loading_label.setText)
        self.parse_thread.update_progress.connect(self.loading_bar.setValue)
        self.parse_thread.finished.connect(self.on_parse_finished)
        self.parse_thread.start()

    @pyqtSlot()
    def stop_parsing(self):
        # Stop the parsing thread
        self.parsing_canceled = True
        self.parse_thread.stop_parsing()
        self.parse_thread.quit()

        # Check if the thread is still running and wait for it to finish
        if self.parse_thread.isRunning():
            print("Parsing thread still running, waiting...")
            self.parse_thread.wait()
            print("Parsing thread closed successfully!")

        # Close the main dialog
        # self.close()

    @pyqtSlot()
    def on_parse_finished(self):
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
        