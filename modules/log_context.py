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
    return OperationLoggerAdapter(base_logger, {"operation_id": operation_id})


def build_parse_log_extra(*, source_path, total_files=None, parsed_count=None, cancel_flag=False):
    return {
        "source_path": str(source_path),
        "total_files": total_files,
        "parsed_count": parsed_count,
        "cancel_flag": bool(cancel_flag),
    }


def build_export_log_extra(*, export_target, output_path, stage, fallback_reason=""):
    return {
        "export_target": str(export_target),
        "output_path": str(output_path),
        "stage": str(stage),
        "fallback_reason": str(fallback_reason or ""),
    }


def build_google_conversion_log_extra(*, file_ref="", error_class="", outcome=""):
    return {
        "file_ref": str(file_ref or ""),
        "error_class": str(error_class or ""),
        "outcome": str(outcome or ""),
    }
