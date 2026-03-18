"""Helpers for attaching structured operation context to log records.

This module provides a logger adapter and extra-payload builders used to
standardize metadata fields across parsing, export, and conversion workflows.
"""

import logging


class OperationLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that preserves operation metadata and merges call-site extras."""

    def process(self, msg, kwargs):
        merged_extra = dict(self.extra)
        call_extra = kwargs.get("extra")
        if isinstance(call_extra, dict):
            merged_extra.update(call_extra)
        kwargs["extra"] = merged_extra
        return msg, kwargs


def get_operation_logger(base_logger, operation_id):
    """Create an operation-scoped logger adapter.

    Args:
        base_logger: Underlying logger instance to wrap.
        operation_id: Identifier attached to every emitted record.

    Returns:
        An :class:`OperationLoggerAdapter` that merges operation metadata with
        call-site ``extra`` dictionaries.
    """

    return OperationLoggerAdapter(base_logger, {"operation_id": operation_id})


def build_parse_log_extra(*, source_path, total_files=None, parsed_count=None, cancel_flag=False):
    """Build structured ``extra`` fields for parse-stage logging.

    Args:
        source_path: Input path being parsed.
        total_files: Optional number of files expected.
        parsed_count: Optional number of files parsed so far.
        cancel_flag: Whether cancellation has been requested.

    Returns:
        A dictionary suitable for ``logging.Logger.*(..., extra=...)``.
    """

    return {
        "source_path": str(source_path),
        "total_files": total_files,
        "parsed_count": parsed_count,
        "cancel_flag": bool(cancel_flag),
    }


def build_export_log_extra(*, export_target, output_path, stage, fallback_reason=""):
    """Build structured ``extra`` fields for export-stage logging.

    Args:
        export_target: Destination target identifier.
        output_path: Materialized output path.
        stage: Export stage label.
        fallback_reason: Optional reason describing fallback behavior.

    Returns:
        A dictionary suitable for ``logging.Logger.*(..., extra=...)``.
    """

    return {
        "export_target": str(export_target),
        "output_path": str(output_path),
        "stage": str(stage),
        "fallback_reason": str(fallback_reason or ""),
    }


def build_google_conversion_log_extra(*, file_ref="", error_class="", outcome=""):
    """Build structured ``extra`` fields for Google conversion logging.

    Args:
        file_ref: Optional file reference or identifier.
        error_class: Optional error class name.
        outcome: Optional conversion outcome label.

    Returns:
        A dictionary suitable for ``logging.Logger.*(..., extra=...)``.
    """

    return {
        "file_ref": str(file_ref or ""),
        "error_class": str(error_class or ""),
        "outcome": str(outcome or ""),
    }
