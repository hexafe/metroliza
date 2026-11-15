import logging
from typing import Literal

from metroliza.shared.diagnostic_events import (
    DiagnosticOperation,
    build_exception_diagnostic_event,
)
from metroliza.shared.safe_bugreport import record_handled_exception
from metroliza.shared.safe_bugreport_context import ExceptionSite


# Exact source-owned names only. Caller context, logger suffixes and traceback
# contents must never become fields in the copyable report.
_EXCEPTION_SITES = {
    "app.bootstrap": ExceptionSite.BOOTSTRAP,
    "parsing.parse_reports_thread": ExceptionSite.REPORT_PARSER,
    "parsing.cmm_report_parser": ExceptionSite.REPORT_PARSER,
    "parsing.metadata_enrichment_thread": ExceptionSite.REPORT_PARSER,
    "ui.parsing_dialog": ExceptionSite.REPORT_PARSER,
    "exporting.export_data_thread": ExceptionSite.REPORT_EXPORT,
    "ui.export_dialog": ExceptionSite.EXPORT_DIALOG,
    "ui.filter_dialog": ExceptionSite.EXPORT_DIALOG,
    "ui.data_grouping": ExceptionSite.EXPORT_DIALOG,
    "ui.modify_db": ExceptionSite.DATABASE_EDIT,
    "ui.characteristic_mapping_dialog": ExceptionSite.MAPPING,
}


LOG_ONLY = "log_only"
LOG_AND_DIALOG = "log_and_dialog"
LogBehavior = Literal["log_only", "log_and_dialog"]
logger = logging.getLogger(__name__)


def _exception_site_for_logger(name):
    # Package-relative names classify records without importing those packages.
    prefix = "metroliza."
    if type(name) is not str or not name.startswith(prefix):
        return ExceptionSite.UNKNOWN
    return _EXCEPTION_SITES.get(name[len(prefix):], ExceptionSite.UNKNOWN)


def log_exception(exception, *, logger_name=None, context="operation"):
    """Log closed exception structure without exception- or caller-controlled text."""
    site = _exception_site_for_logger(logger_name)
    record_handled_exception(exception, site=site)
    active_logger = logging.getLogger(logger_name) if logger_name else logger
    active_logger.error(
        build_exception_diagnostic_event(
            exception,
            operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
        )
    )


def notify_user(*, message, title="Error", parent=None):
    """Show a user-facing error notification dialog."""
    try:
        from PyQt6.QtWidgets import QMessageBox
    except (ImportError, OSError, RuntimeError) as exc:
        logger.error(
            build_exception_diagnostic_event(
                exc,
                operation=DiagnosticOperation.QT_DIALOG_IMPORT_FAILURE,
            )
        )
        return

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
