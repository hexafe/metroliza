import logging
from typing import Literal

from PyQt6.QtWidgets import QMessageBox


LOG_ONLY = "log_only"
LOG_AND_DIALOG = "log_and_dialog"
LogBehavior = Literal["log_only", "log_and_dialog"]
logger = logging.getLogger(__name__)


def log_exception(exception, *, logger_name=None, context="operation"):
    """Log an exception with traceback and operation context, without UI side effects."""
    active_logger = logging.getLogger(logger_name) if logger_name else logger
    active_logger.error(
        "Unhandled exception during %s: %s",
        context,
        exception,
        exc_info=(type(exception), exception, exception.__traceback__),
    )


def notify_user(*, message, title="Error", parent=None):
    """Show a user-facing error notification dialog."""
    QMessageBox.information(parent, title, message)


def handle_exception(
    exception,
    *,
    behavior: LogBehavior = LOG_AND_DIALOG,
    logger_name=None,
    context="operation",
    dialog_title="Error",
    dialog_message=(
        "An error occurred.\nPlease check the log file for more information.\n"
        "(or just contact the author :P)"
    ),
    dialog_parent=None,
    reraise=True,
):
    """Handle an exception with selectable logging and user notification behavior."""
    log_exception(exception, logger_name=logger_name, context=context)

    if behavior == LOG_AND_DIALOG:
        notify_user(message=dialog_message, title=dialog_title, parent=dialog_parent)

    if reraise:
        raise exception


class CustomLogger:
    """A custom logger class that logs exceptions and optionally re-raises them."""

    def __init__(
        self,
        exception,
        reraise=True,
        *,
        behavior: LogBehavior = LOG_AND_DIALOG,
        logger_name=None,
        context="operation",
        dialog_title="Error",
        dialog_message=(
            "An error occurred.\nPlease check the log file for more information.\n"
            "(or just contact the author :P)"
        ),
        dialog_parent=None,
    ):
        """Initialize the logger with the exception and the messages to show.

        Args:
            exception (Exception): The exception to log and display.
        """
        self.exception = exception
        self.reraise = reraise
        self.behavior = behavior
        self.logger_name = logger_name
        self.context = context
        self.dialog_title = dialog_title
        self.error_message = dialog_message
        self.dialog_parent = dialog_parent
        self.log_and_exit()

    def log_and_exit(self):
        """Log the exception and display a user-facing message.

        Raises:
            Exception: The original exception when ``reraise`` is enabled.
        """
        handle_exception(
            self.exception,
            behavior=self.behavior,
            logger_name=self.logger_name,
            context=self.context,
            dialog_title=self.dialog_title,
            dialog_message=self.error_message,
            dialog_parent=self.dialog_parent,
            reraise=self.reraise,
        )
