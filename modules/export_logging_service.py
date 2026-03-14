"""Stateless helpers for export-thread structured logging.

These helpers keep logging payload assembly and Google-conversion issue formatting
outside orchestration code so ``ExportDataThread`` can remain focused on flow
control and signal behavior.
"""

from modules.log_context import build_export_log_extra, build_google_conversion_log_extra


def build_export_context(*, export_target, output_path, stage, fallback_reason=""):
    """Build structured export context for thread-stage logging."""

    return build_export_log_extra(
        export_target=export_target,
        output_path=output_path,
        stage=stage,
        fallback_reason=fallback_reason,
    )


def log_export_stage(
    operation_logger,
    message,
    *,
    export_target,
    output_path,
    stage,
    level="info",
    fallback_reason="",
    **extra,
):
    """Emit a structured export-stage log message."""

    log_method = getattr(operation_logger, level)
    log_method(
        message,
        extra=build_export_context(
            export_target=export_target,
            output_path=output_path,
            stage=stage,
            fallback_reason=fallback_reason,
        )
        | extra,
    )


def log_google_issue(
    operation_logger,
    context,
    *,
    output_path,
    export_target,
    fallback_message="",
    warnings=None,
    error=None,
):
    """Emit a normalized warning/error log for Google conversion issues."""

    warning_list = [str(item) for item in (warnings or []) if str(item).strip()]
    details = []
    if fallback_message:
        details.append(f"fallback={fallback_message}")
    if warning_list:
        details.append("warnings=" + " | ".join(warning_list))
    if error is not None:
        details.append(f"error={error}")

    suffix = f" ({'; '.join(details)})" if details else ""
    log_method = operation_logger.error if error is not None else operation_logger.warning
    google_extra = build_google_conversion_log_extra(
        file_ref=output_path,
        error_class=type(error).__name__ if error is not None else "",
        outcome="fallback" if fallback_message else "warning",
    )
    log_method(
        "Google export issue: %s%s",
        context,
        suffix,
        extra=build_export_context(
            export_target=export_target,
            output_path=output_path,
            stage="google_issue",
            fallback_reason=fallback_message,
        )
        | google_extra,
    )
