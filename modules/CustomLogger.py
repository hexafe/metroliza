import logging
from PyQt6.QtWidgets import QMessageBox

class CustomLogger:
    """A custom logger class that logs exceptions and optionally re-raises them."""

    def __init__(self, exception, reraise=True):
        """Initialize the logger with the exception and the messages to show.

        Args:
            exception (Exception): The exception to log and display.
        """
        self.exception = exception
        self.logger_message = "An error occurred: "
        self.reraise = reraise
        self.error_message = (
            "An error occurred.\nPlease check the log file for more information.\n(or just contact the author :P)"
        )
        self.log_and_exit()

    def log_and_exit(self):
        """Log the exception and display a user-facing message.

        Raises:
            Exception: The original exception when ``reraise`` is enabled.
        """
        logging.exception(self.logger_message + f"{self.exception}")
        QMessageBox.information(None, "Error", self.error_message)
        if self.reraise:
            raise self.exception
