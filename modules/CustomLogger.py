import logging
from PyQt6.QtWidgets import QMessageBox

class CustomLogger:
    """A custom logger class that logs and displays an exception and exits the program."""

    def __init__(self, exception):
        """Initialize the logger with the exception and the messages to show.

        Args:
            exception (Exception): The exception to log and display.
        """
        self.exception = exception
        self.logger_message = "An error occurred: "
        self.error_message = (
            "An error occurred.\nPlease check the log file for more information.\n(or just contact the author :P)"
        )
        self.log_and_exit()

    def log_and_exit(self):
        """Log the exception with the logger message and display the error message in a message box.

        Raises:
            Exception: The original exception that caused the error.
        """
        logging.exception(self.logger_message + f"{self.exception}")
        QMessageBox.information(None, "Error", self.error_message)
        raise self.exception
