"""Typed, centrally-derived export artifact and stage outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Mapping


class ExportRunStatus(str, Enum):
    COMPLETE = "complete"
    COMPLETE_WITH_OMISSIONS = "complete_with_omissions"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportArtifactStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    OMITTED = "omitted"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ExportArtifactResult:
    artifact_id: str
    label: str
    status: ExportArtifactStatus
    required: bool
    location: str = ""
    public_message: str = ""
    diagnostic_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExportStageResult:
    stage_id: str
    label: str
    status: ExportArtifactStatus
    public_message: str = ""
    diagnostic_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExportRunResult:
    status: ExportRunStatus
    artifacts: tuple[ExportArtifactResult, ...]
    stages: tuple[ExportStageResult, ...]
    diagnostics: tuple[str, ...] = ()

    @property
    def level(self) -> str:
        if self.status is ExportRunStatus.FAILED:
            return "error"
        if self.status in {
            ExportRunStatus.COMPLETE_WITH_OMISSIONS,
            ExportRunStatus.CANCELLED,
        }:
            return "warning"
        return "info"

    @property
    def title(self) -> str:
        return {
            ExportRunStatus.COMPLETE: "Export complete",
            ExportRunStatus.COMPLETE_WITH_OMISSIONS: "Export complete with omissions",
            ExportRunStatus.FAILED: "Export failed",
            ExportRunStatus.CANCELLED: "Export cancelled",
        }[self.status]


def _text_values(values) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, Mapping)):
        values = (values,)
    else:
        try:
            values = tuple(values)
        except TypeError:
            values = (values,)
    normalized = []
    for value in values:
        text = str(value).strip()
        if text:
            normalized.append(text)
    return tuple(normalized)


def _detail_values(values) -> tuple[object, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, Mapping)):
        values = (values,)
    else:
        try:
            values = tuple(values)
        except TypeError:
            values = (values,)
    return tuple(value for value in values if value is not None)


def _display_path(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return raw


_SAFE_DIAGNOSTIC_VALUE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_FAILURE_TYPE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b")
_SAFE_RENDERED_FAILURE_TYPES = frozenset(
    {
        "ArithmeticError",
        "AssertionError",
        "AttributeError",
        "ConnectionError",
        "DataError",
        "DatabaseError",
        "EOFError",
        "ExportError",
        "FileExistsError",
        "FileNotFoundError",
        "ImportError",
        "IndexError",
        "IntegrityError",
        "KeyError",
        "LookupError",
        "MemoryError",
        "NameError",
        "NotImplementedError",
        "OSError",
        "OperationalError",
        "OverflowError",
        "PermissionError",
        "ReadError",
        "RuntimeError",
        "TimeoutError",
        "TypeError",
        "UnicodeError",
        "ValueError",
        "ZeroDivisionError",
    }
)
_KNOWN_DIAGNOSTIC_ID = re.compile(
    r"^(?:terminal_failure|summary_chart-\d+|dashboard-\d+|"
    r"google_conversion-\d+|google_fallback|diagnostic-\d+)$"
)
_SAFE_DETAIL_KEYS = {
    "chart": "chart",
    "code": "code",
    "diagnostic_id": "code",
    "error_code": "code",
    "stage": "stage",
}


def _safe_diagnostic_value(value) -> str:
    text = str(value or "").strip()
    return text if _SAFE_DIAGNOSTIC_VALUE.fullmatch(text) else ""


def _failure_type(value, *, default: str = "") -> str:
    if isinstance(value, Mapping):
        for key in ("exception_class", "error_class", "exception_type", "error_type"):
            candidate = _safe_diagnostic_value(value.get(key))
            if candidate and _FAILURE_TYPE.fullmatch(candidate):
                return candidate
    return default


def _safe_diagnostic_attributes(value, *, default_failure_type: str = "") -> tuple[str, ...]:
    attributes: list[str] = []
    failure_type = _failure_type(value, default=default_failure_type)
    if failure_type:
        attributes.append(f"failure_type={failure_type}")
    if isinstance(value, Mapping):
        for source_key, display_key in _SAFE_DETAIL_KEYS.items():
            safe_value = _safe_diagnostic_value(value.get(source_key))
            if safe_value:
                attributes.append(f"{display_key}={safe_value}")
    return tuple(dict.fromkeys(attributes))


def _safe_diagnostic_line(
    diagnostic_id: str,
    value,
    *,
    default_failure_type: str = "",
) -> str:
    attributes = _safe_diagnostic_attributes(
        value,
        default_failure_type=default_failure_type,
    )
    payload = "; ".join((*attributes, "detail=redacted"))
    return f"{diagnostic_id}: {payload}"


def _diagnostic_lines(metadata, *, terminal_failure: str) -> tuple[str, ...]:
    lines: list[str] = []
    if terminal_failure.strip():
        lines.append(
            _safe_diagnostic_line(
                "terminal_failure",
                terminal_failure,
                default_failure_type="ExportError",
            )
        )

    detail_groups = (
        (
            "summary_chart",
            metadata.get("summary_sheet_warning_details", ()),
            metadata.get("summary_sheet_warnings", ()),
        ),
        (
            "dashboard",
            metadata.get("html_dashboard_warning_details", ()),
            metadata.get("html_dashboard_warnings", ()),
        ),
        (
            "google_conversion",
            metadata.get("conversion_warning_details", ()),
            metadata.get("conversion_warnings", ()),
        ),
    )
    for group_name, detail_values, warning_values in detail_groups:
        details = _detail_values(detail_values)
        warnings = _detail_values(warning_values)
        for offset in range(max(len(details), len(warnings))):
            value = details[offset] if offset < len(details) else warnings[offset]
            lines.append(_safe_diagnostic_line(f"{group_name}-{offset + 1}", value))

    fallback_message = str(metadata.get("fallback_message", "")).strip()
    if fallback_message:
        lines.append(_safe_diagnostic_line("google_fallback", fallback_message))
    return tuple(dict.fromkeys(lines))


def sanitize_export_diagnostics(value) -> str:
    """Return diagnostics safe for an on-screen details pane or clipboard.

    Only stable diagnostic identifiers, exception types, and small enumerated
    attributes survive.  Raw exception messages, URLs, DSNs, credentials, and
    report values are intentionally never copied into the UI boundary.
    """

    safe_lines: list[str] = []
    for index, raw_line in enumerate(str(value or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        prefix, separator, payload = line.partition(":")
        diagnostic_id = prefix.strip() if separator else ""
        if not _KNOWN_DIAGNOSTIC_ID.fullmatch(diagnostic_id):
            diagnostic_id = f"diagnostic-{index}"
            payload = line
        payload = payload.strip()

        attributes: list[str] = []
        failure_type_match = re.search(
            r"(?:^|;\s*)failure_type=([A-Za-z_][A-Za-z0-9_]*)\s*(?:;|$)",
            payload,
        )
        failure_type = failure_type_match.group(1) if failure_type_match else ""
        if failure_type in _SAFE_RENDERED_FAILURE_TYPES:
            attributes.append(f"failure_type={failure_type}")
        elif diagnostic_id == "terminal_failure":
            attributes.append("failure_type=ExportError")
        for key, safe_value in re.findall(
            r"\b(chart|code|stage)=([A-Za-z0-9_.-]{1,80})\b",
            payload,
        ):
            attributes.append(f"{key}={safe_value}")
        safe_lines.append(
            f"{diagnostic_id}: "
            + "; ".join((*dict.fromkeys(attributes), "detail=redacted"))
        )
    return "\n".join(safe_lines)


def _cancelled_export_result(
    metadata,
    *,
    target: str,
    workbook_path: str,
    workbook_requested: bool,
    summary_requested: bool,
    dashboard_requested: bool,
    google_requested: bool,
    terminal_failure: str,
) -> ExportRunResult:
    artifacts: list[ExportArtifactResult] = []
    stages: list[ExportStageResult] = []
    local_outcome = str(metadata.get("local_export_outcome", ""))
    local_completed = local_outcome in {"completed", "completed_with_warnings"}

    if workbook_requested:
        if local_completed and workbook_path:
            _append_workbook_outcome(
                artifacts,
                stages,
                workbook_path=workbook_path,
                local_completed=True,
                terminal_failure="",
            )
        else:
            _append_cancelled_outcome(
                artifacts,
                stages,
                artifact_id="workbook",
                artifact_label="Workbook",
                stage_id="local_export",
                stage_label="Local workbook export",
                required=True,
            )
    if summary_requested:
        if local_completed:
            _append_summary_outcome(
                artifacts,
                stages,
                _text_values(metadata.get("summary_sheet_warnings", ())),
            )
        else:
            _append_cancelled_outcome(
                artifacts,
                stages,
                artifact_id="summary_charts",
                artifact_label="Summary charts",
                stage_id="summary_charts",
                stage_label="Summary chart generation",
                required=False,
            )
    if dashboard_requested:
        dashboard_path = _display_path(metadata.get("html_dashboard_path"))
        dashboard_warnings = _text_values(metadata.get("html_dashboard_warnings", ()))
        if dashboard_path or dashboard_warnings:
            _append_dashboard_outcome(
                artifacts,
                stages,
                path=dashboard_path,
                warnings=dashboard_warnings,
                required=target == "html_dashboard",
            )
        else:
            _append_cancelled_outcome(
                artifacts,
                stages,
                artifact_id="html_dashboard",
                artifact_label="HTML dashboard",
                stage_id="html_dashboard",
                stage_label="HTML dashboard generation",
                required=target == "html_dashboard",
            )
    if google_requested:
        converted_url = str(metadata.get("converted_url", "")).strip()
        conversion_warnings = _text_values(metadata.get("conversion_warnings", ()))
        fallback_message = str(metadata.get("fallback_message", "")).strip()
        if converted_url or conversion_warnings or fallback_message:
            _append_google_outcome(
                artifacts,
                stages,
                url=converted_url,
                warnings=conversion_warnings,
                fallback=fallback_message,
            )
        else:
            _append_cancelled_outcome(
                artifacts,
                stages,
                artifact_id="google_sheet",
                artifact_label="Google Sheet",
                stage_id="google_conversion",
                stage_label="Google Sheets conversion",
                required=False,
            )

    stages.append(
        ExportStageResult(
            stage_id="export",
            label="Export",
            status=ExportArtifactStatus.CANCELLED,
            public_message="The export stopped after cancellation was confirmed.",
        )
    )
    return ExportRunResult(
        status=ExportRunStatus.CANCELLED,
        artifacts=tuple(artifacts),
        stages=tuple(stages),
        diagnostics=_diagnostic_lines(metadata, terminal_failure=terminal_failure),
    )


def _append_cancelled_outcome(
    artifacts,
    stages,
    *,
    artifact_id: str,
    artifact_label: str,
    stage_id: str,
    stage_label: str,
    required: bool,
) -> None:
    message = "Not completed because the export was cancelled."
    artifacts.append(
        ExportArtifactResult(
            artifact_id=artifact_id,
            label=artifact_label,
            status=ExportArtifactStatus.CANCELLED,
            required=required,
            public_message=message,
        )
    )
    stages.append(
        ExportStageResult(
            stage_id=stage_id,
            label=stage_label,
            status=ExportArtifactStatus.CANCELLED,
            public_message=message,
        )
    )


def _append_workbook_outcome(
    artifacts,
    stages,
    *,
    workbook_path: str,
    local_completed: bool,
    terminal_failure: str,
) -> None:
    status = (
        ExportArtifactStatus.FAILED
        if terminal_failure or not local_completed or not workbook_path
        else ExportArtifactStatus.COMPLETE
    )
    message = (
        "Required workbook was not completed."
        if status is ExportArtifactStatus.FAILED
        else ""
    )
    artifacts.append(
        ExportArtifactResult(
            artifact_id="workbook",
            label="Workbook",
            status=status,
            required=True,
            location=workbook_path if status is ExportArtifactStatus.COMPLETE else "",
            public_message=message,
            diagnostic_ids=("terminal_failure",) if terminal_failure else (),
        )
    )
    stages.append(
        ExportStageResult(
            stage_id="local_export",
            label="Local workbook export",
            status=status,
            public_message=message,
        )
    )


def _append_summary_outcome(artifacts, stages, warnings: tuple[str, ...]) -> None:
    status = ExportArtifactStatus.PARTIAL if warnings else ExportArtifactStatus.COMPLETE
    message = (
        "Some summary charts could not be generated; remaining charts and workbook data "
        "are available."
        if warnings
        else ""
    )
    diagnostic_ids = tuple(f"summary_chart-{index}" for index in range(1, len(warnings) + 1))
    artifacts.append(
        ExportArtifactResult(
            artifact_id="summary_charts",
            label="Summary charts",
            status=status,
            required=False,
            public_message=message,
            diagnostic_ids=diagnostic_ids,
        )
    )
    stages.append(
        ExportStageResult(
            stage_id="summary_charts",
            label="Summary chart generation",
            status=status,
            public_message=message,
            diagnostic_ids=diagnostic_ids,
        )
    )


def _dashboard_status(path: str, warnings: tuple[str, ...], *, required: bool):
    if path and not warnings:
        return ExportArtifactStatus.COMPLETE, ""
    if required:
        return ExportArtifactStatus.FAILED, "Required HTML dashboard was not completed."
    return (
        ExportArtifactStatus.OMITTED,
        "HTML dashboard could not be generated; the workbook is available.",
    )


def _append_dashboard_outcome(
    artifacts,
    stages,
    *,
    path: str,
    warnings: tuple[str, ...],
    required: bool,
) -> None:
    status, message = _dashboard_status(path, warnings, required=required)
    diagnostic_ids = tuple(f"dashboard-{index}" for index in range(1, len(warnings) + 1))
    artifacts.append(
        ExportArtifactResult(
            artifact_id="html_dashboard",
            label="HTML dashboard",
            status=status,
            required=required,
            location=path if status is ExportArtifactStatus.COMPLETE else "",
            public_message=message,
            diagnostic_ids=diagnostic_ids,
        )
    )
    stages.append(
        ExportStageResult(
            stage_id="html_dashboard",
            label="HTML dashboard generation",
            status=status,
            public_message=message,
            diagnostic_ids=diagnostic_ids,
        )
    )


def _google_status(url: str, warnings: tuple[str, ...], fallback: str):
    if url and not warnings and not fallback:
        return ExportArtifactStatus.COMPLETE, ""
    if url:
        return (
            ExportArtifactStatus.PARTIAL,
            "Google Sheet was created with conversion warnings; the local workbook is also "
            "available.",
        )
    return (
        ExportArtifactStatus.OMITTED,
        "Google Sheets conversion was not completed; the local workbook is available.",
    )


def _append_google_outcome(
    artifacts,
    stages,
    *,
    url: str,
    warnings: tuple[str, ...],
    fallback: str,
) -> None:
    status, message = _google_status(url, warnings, fallback)
    diagnostic_ids = tuple(
        f"google_conversion-{index}" for index in range(1, len(warnings) + 1)
    )
    artifacts.append(
        ExportArtifactResult(
            artifact_id="google_sheet",
            label="Google Sheet",
            status=status,
            required=False,
            location=url,
            public_message=message,
            diagnostic_ids=diagnostic_ids,
        )
    )
    stages.append(
        ExportStageResult(
            stage_id="google_conversion",
            label="Google Sheets conversion",
            status=status,
            public_message=message,
            diagnostic_ids=diagnostic_ids,
        )
    )


def _run_status(artifacts, *, terminal_failure: str) -> ExportRunStatus:
    if terminal_failure or any(
        artifact.required and artifact.status is ExportArtifactStatus.FAILED
        for artifact in artifacts
    ):
        return ExportRunStatus.FAILED
    omission_statuses = {
        ExportArtifactStatus.PARTIAL,
        ExportArtifactStatus.OMITTED,
        ExportArtifactStatus.FAILED,
    }
    if any(artifact.status in omission_statuses for artifact in artifacts):
        return ExportRunStatus.COMPLETE_WITH_OMISSIONS
    return ExportRunStatus.COMPLETE


def _cancel_embedded_export_result(
    result: ExportRunResult,
    metadata,
    *,
    terminal_failure: str,
) -> ExportRunResult:
    stages = list(result.stages)
    if not any(stage.stage_id == "export" and stage.status is ExportArtifactStatus.CANCELLED for stage in stages):
        stages.append(
            ExportStageResult(
                stage_id="export",
                label="Export",
                status=ExportArtifactStatus.CANCELLED,
                public_message="The export stopped after cancellation was confirmed.",
            )
        )
    diagnostics = sanitize_export_diagnostics(
        "\n".join((*result.diagnostics, *_diagnostic_lines(metadata, terminal_failure=terminal_failure)))
    )
    return ExportRunResult(
        status=ExportRunStatus.CANCELLED,
        artifacts=result.artifacts,
        stages=tuple(stages),
        diagnostics=tuple(diagnostics.splitlines()),
    )


def derive_export_run_result(
    *,
    excel_file,
    export_target: str,
    completion_metadata,
    cancelled: bool = False,
    terminal_failure: str = "",
) -> ExportRunResult:
    """Derive one terminal result from every requested export artifact."""

    metadata = dict(completion_metadata or {})
    embedded = metadata.get("export_run_result")
    if isinstance(embedded, ExportRunResult) and not cancelled and not terminal_failure:
        return embedded
    if isinstance(embedded, ExportRunResult) and cancelled:
        return _cancel_embedded_export_result(
            embedded,
            metadata,
            terminal_failure=terminal_failure,
        )

    target = str(export_target or "excel_xlsx")
    workbook_requested = target != "html_dashboard"
    dashboard_requested = bool(
        target == "html_dashboard"
        or metadata.get("html_dashboard_requested")
        or metadata.get("html_dashboard_path")
        or metadata.get("html_dashboard_warnings")
    )
    google_requested = target == "google_sheets_drive_convert"
    summary_requested = bool(
        metadata.get("summary_sheet_requested") or metadata.get("summary_sheet_warnings")
    )
    if cancelled:
        return _cancelled_export_result(
            metadata,
            target=target,
            workbook_path=_display_path(metadata.get("local_xlsx_path") or excel_file),
            workbook_requested=workbook_requested,
            summary_requested=summary_requested,
            dashboard_requested=dashboard_requested,
            google_requested=google_requested,
            terminal_failure=terminal_failure,
        )

    artifacts: list[ExportArtifactResult] = []
    stages: list[ExportStageResult] = []
    if workbook_requested:
        local_outcome = str(metadata.get("local_export_outcome", "completed"))
        _append_workbook_outcome(
            artifacts,
            stages,
            workbook_path=_display_path(metadata.get("local_xlsx_path") or excel_file),
            local_completed=local_outcome in {"completed", "completed_with_warnings"},
            terminal_failure=terminal_failure,
        )
    if summary_requested:
        _append_summary_outcome(
            artifacts,
            stages,
            _text_values(metadata.get("summary_sheet_warnings", ())),
        )
    if dashboard_requested:
        _append_dashboard_outcome(
            artifacts,
            stages,
            path=_display_path(metadata.get("html_dashboard_path")),
            warnings=_text_values(metadata.get("html_dashboard_warnings", ())),
            required=target == "html_dashboard",
        )
    if google_requested:
        _append_google_outcome(
            artifacts,
            stages,
            url=str(metadata.get("converted_url", "")).strip(),
            warnings=_text_values(metadata.get("conversion_warnings", ())),
            fallback=str(metadata.get("fallback_message", "")).strip(),
        )
    return ExportRunResult(
        status=_run_status(artifacts, terminal_failure=terminal_failure),
        artifacts=tuple(artifacts),
        stages=tuple(stages),
        diagnostics=_diagnostic_lines(metadata, terminal_failure=terminal_failure),
    )


def build_export_run_message(result: ExportRunResult) -> tuple[str, str, str]:
    """Build primary UI copy without raw exceptions or local file URIs."""

    opening = {
        ExportRunStatus.COMPLETE: "All requested export outputs are complete.",
        ExportRunStatus.COMPLETE_WITH_OMISSIONS: (
            "The export completed, but some requested outputs were omitted or incomplete."
        ),
        ExportRunStatus.FAILED: "The export did not complete its required output.",
        ExportRunStatus.CANCELLED: "The export was cancelled before all outputs completed.",
    }[result.status]
    lines = [opening]

    completed = [
        artifact
        for artifact in result.artifacts
        if artifact.status in {ExportArtifactStatus.COMPLETE, ExportArtifactStatus.PARTIAL}
        and artifact.location
    ]
    if completed:
        lines.extend(["", "Completed outputs:"])
        lines.extend(f"- {artifact.label}: {artifact.location}" for artifact in completed)

    issues = [artifact for artifact in result.artifacts if artifact.public_message]
    if issues:
        lines.extend(["", "Omissions and required actions:"])
        lines.extend(
            f"- {artifact.label}: {artifact.public_message}"
            for artifact in issues
        )

    if result.diagnostics:
        lines.extend(["", "Technical details are available under Show Details."])
    return result.level, result.title, "\n".join(lines)


def format_export_diagnostics(result: ExportRunResult) -> str:
    """Return copyable technical details kept out of primary completion copy."""

    return sanitize_export_diagnostics("\n".join(result.diagnostics))
