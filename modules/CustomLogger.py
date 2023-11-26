import logging
from PyQt5.QtWidgets import QMessageBox


class CustomLogger:
    """
    Custom Logger Class:
    Handles logging exceptions and displaying error messages using PyQt5 QMessageBox.
    """

    def __init__(self, exception):
        """
        Initializes the CustomLogger with the provided exception.
        :param exception: The exception to be logged and displayed.
        """
        self.exception = exception
        self.logger_message = "An error occurred: "
        self.error_message = (
            "An error occurred.\nPlease check the log file for more information.\n(or just contact the author :P)"
        )
        self.log_and_exit()

    def log_and_exit(self):
        """
        Logs the exception using the logging module and displays an error message.
        """
        logging.exception(self.logger_message + f"{self.exception}")
        QMessageBox.information(None, "Error", self.error_message)
        raise
