import logging
from typing import Any, Literal

from metroliza.shared.logging_utils import redact_log_text, summarize_exception


LogBehavior = Literal["log_only", "log_and_dialog"]
LOG_ONLY: LogBehavior = "log_only"
LOG_AND_DIALOG: LogBehavior = "log_and_dialog"
logger = logging.getLogger(__name__)


def log_exception(
    exception: BaseException,
    *,
    logger_name: str | None = None,
    context: object = "operation",
) -> None:
    """Log an exception with traceback and operation context, without UI side effects."""
    active_logger = logging.getLogger(logger_name) if logger_name else logger
    safe_context = redact_log_text(context)
    safe_structure = summarize_exception(exception)
    active_logger.error(
        "Unhandled exception during %s; %s",
        safe_context,
        safe_structure,
    )


def notify_user(*, message: str, title: str = "Error", parent: Any = None) -> None:
    """Show a user-facing error notification dialog."""
    try:
        from PyQt6.QtWidgets import QMessageBox
    except (ImportError, OSError, RuntimeError) as exc:
        log_exception(
            exc,
            context="Could not show error dialog because Qt failed to import",
        )
        return

    QMessageBox.information(parent, title, message)


def handle_exception(
    exception: BaseException,
    *,
    behavior: LogBehavior = LOG_AND_DIALOG,
    logger_name: str | None = None,
    context: object = "operation",
    dialog_title: str = "Error",
    dialog_message: str = (
        "An error occurred.\nPlease check the log file for more information.\n"
        "(or just contact the author :P)"
    ),
    dialog_parent: Any = None,
    reraise: bool = True,
) -> None:
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
        exception: BaseException,
        reraise: bool = True,
        *,
        behavior: LogBehavior = LOG_AND_DIALOG,
        logger_name: str | None = None,
        context: object = "operation",
        dialog_title: str = "Error",
        dialog_message: str = (
            "An error occurred.\nPlease check the log file for more information.\n"
            "(or just contact the author :P)"
        ),
        dialog_parent: Any = None,
    ) -> None:
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

    def log_and_exit(self) -> None:
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
