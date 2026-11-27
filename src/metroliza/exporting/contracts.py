"""Immutable export request contracts and validation entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from metroliza.charts.dashboard_visual_options import normalize_dashboard_visual_settings
from metroliza.exporting.output_publication import OutputConsent, output_paths, validate_sources_outside_outputs
from metroliza.tabular.contracts import (
    GroupingAssignments,
    validate_grouping_df,
)

if TYPE_CHECKING:
    from metroliza.reports.report_typed_filter import ReportTypedFilterScope


@dataclass(frozen=True)
class AppPaths:
    """Filesystem paths required by export workflows."""

    db_file: str
    excel_file: str | None = None
    html_dashboard_file: str | None = None


@dataclass(frozen=True)
class ExportOptions:
    """Configurable export behavior with normalized defaults."""

    preset: str = "fast_diagnostics"
    export_type: str = "line"
    export_target: str = "excel_xlsx"
    backend_target: str = "excel"
    sorting_parameter: str = "date"
    violin_plot_min_samplesize: int = 6
    summary_plot_scale: int = 0
    hide_ok_results: bool = False
    generate_summary_sheet: bool = False
    generate_html_dashboard: bool = False
    include_industrial_context: bool = False
    allow_non_essential_chart_skipping: bool = False
    chart_worker_count: int = 4
    chart_worker_queue_size: int = 4
    group_analysis_level: str = "off"
    group_analysis_scope: str = "auto"
    dashboard_visual_settings: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExportRequest:
    """Top-level immutable export request contract."""

    paths: AppPaths
    options: ExportOptions
    filter_query: str | None = None
    grouping_df: GroupingAssignments | None = None
    replace_outputs: tuple[OutputConsent, ...] = ()
    copy_output_from: str | None = None
    existing_database_identity: tuple[int, int] | None = field(default=None, repr=False)
    approved_source_digests: tuple[str, ...] = field(default=(), repr=False)
    approved_report_ids: tuple[int, ...] = field(default=(), repr=False)
    filter_description: str = field(default="", repr=False)
    application_version: str = ""
    typed_report_scope: ReportTypedFilterScope | None = field(default=None, repr=False)


_ALLOWED_EXPORT_TYPES = {"line", "scatter"}
_ALLOWED_EXPORT_PRESETS = {"fast_diagnostics", "full_report", "html_dashboard_only"}
_ALLOWED_EXPORT_TARGETS = {
    "excel_xlsx",
    "google_sheets_drive_convert",
    "html_dashboard",
}
_ALLOWED_BACKEND_TARGETS = {"excel", "google", "html"}
_BACKEND_TARGET_ALIASES = {"google_sheets": "google", "googlesheets": "google"}
_SAMPLE_SORT_ALIASES = {
    "sample",
    "sample #",
    "sample number",
    "part #",
    "part number",
}
_GROUP_ANALYSIS_LEVEL_ALIASES = {
    "off": "off",
    "light": "light",
    "standard": "standard",
}
_GROUP_ANALYSIS_SCOPE_ALIASES = {
    "auto": "auto",
    "single-reference": "single_reference",
    "single_reference": "single_reference",
    "single reference": "single_reference",
    "multi-reference": "multi_reference",
    "multi_reference": "multi_reference",
    "multi reference": "multi_reference",
}


def validate_export_request(request: ExportRequest) -> ExportRequest:
    """Validate an export request and normalize nested contracts."""

    if not isinstance(request, ExportRequest):
        raise ValueError("Export request must be provided as an ExportRequest instance.")

    validated_options = validate_export_options(request.options)
    validated_paths = validate_paths(request.paths)
    validated_grouping_df = validate_grouping_df(request.grouping_df)

    if request.filter_query is not None and not isinstance(request.filter_query, str):
        raise ValueError("Filter query must be a string when provided.")
    if not isinstance(request.filter_description, str):
        raise ValueError("Filter description must be text.")
    if not isinstance(request.application_version, str):
        raise ValueError("Application version must be text.")
    _validate_approved_source_scope(request)
    if request.typed_report_scope is not None:
        _validate_typed_report_scope(request, validated_paths, validated_options)

    _validate_output_namespace(validated_paths, validated_options)

    return ExportRequest(
        paths=validated_paths,
        options=validated_options,
        filter_query=request.filter_query,
        grouping_df=validated_grouping_df,
        replace_outputs=request.replace_outputs,
        copy_output_from=request.copy_output_from,
        existing_database_identity=request.existing_database_identity,
        approved_source_digests=request.approved_source_digests,
        approved_report_ids=request.approved_report_ids,
        filter_description=(request.typed_report_scope.describe()[:2000] if request.typed_report_scope is not None
                            else request.filter_description.strip()[:2000]),
        application_version=request.application_version.strip()[:64],
        typed_report_scope=request.typed_report_scope,
    )


def _validate_typed_report_scope(request, paths, options):
    from metroliza.reports.report_typed_filter import REPORT_TYPED_FILTER_MODE_HINT, ReportTypedFilterScope

    scope = request.typed_report_scope
    if type(scope) is not ReportTypedFilterScope:
        raise ValueError("Invalid typed report filter scope.")
    if (request.filter_query is not None or request.grouping_df is not None
            or request.existing_database_identity is not None or options.preset != "fast_diagnostics"
            or options.export_target != "excel_xlsx" or options.backend_target != "excel"
            or options.generate_html_dashboard or options.include_industrial_context
            or options.group_analysis_level != "off"):
        raise ValueError(REPORT_TYPED_FILTER_MODE_HINT)
    scope.require_current_database(paths.db_file)


def _validate_output_namespace(paths, options):
    if options.export_target == "html_dashboard":
        if not paths.html_dashboard_file:
            raise ValueError("HTML dashboard output path is required for HTML-only export.")
        outputs = (Path(paths.html_dashboard_file),)
    else:
        if not paths.excel_file:
            raise ValueError("Excel file path is required for workbook export.")
        outputs = output_paths(paths.excel_file, dashboard=options.generate_html_dashboard)
        if options.generate_html_dashboard and paths.html_dashboard_file:
            outputs = (outputs[0], Path(paths.html_dashboard_file))
    validate_sources_outside_outputs(outputs, paths.db_file)


def _validate_approved_source_scope(request: ExportRequest) -> None:
    identity, digests = request.existing_database_identity, request.approved_source_digests
    if type(digests) is not tuple or bool(digests) != (identity is not None):
        raise ValueError("An approved source scope requires its existing database identity.")
    report_ids = request.approved_report_ids
    if type(report_ids) is not tuple or (report_ids and (
        len(report_ids) != len(digests) or any(type(value) is not int or value < 1 for value in report_ids)
        or len(set(report_ids)) != len(report_ids)
        or request.filter_query is not None or request.grouping_df is not None
    )):
        raise ValueError("A last-import export requires complete report membership and its own scope.")
    if identity is None:
        return
    if type(identity) is not tuple or len(identity) != 2 or any(type(n) is not int or n < 0 for n in identity):
        raise ValueError("Invalid existing database identity.")
    if any(type(digest) is not str or len(digest) != 64 or
           any(char not in "0123456789abcdef" for char in digest) for digest in digests):
        raise ValueError("Invalid approved report source digest.")


def validate_paths(paths: AppPaths) -> AppPaths:
    """Validate required application paths and optional output constraints."""

    if not isinstance(paths.db_file, str) or not paths.db_file.strip():
        raise ValueError("A database file path is required.")

    if paths.excel_file is not None and (
        not isinstance(paths.excel_file, str) or not paths.excel_file.strip()
    ):
        raise ValueError("Excel file path must be a non-empty string when provided.")

    if paths.excel_file and Path(paths.excel_file).suffix.lower() != ".xlsx":
        raise ValueError("Excel file must use the .xlsx extension.")

    if paths.html_dashboard_file is not None and (
        not isinstance(paths.html_dashboard_file, str)
        or not paths.html_dashboard_file.strip()
    ):
        raise ValueError("HTML dashboard path must be a non-empty string when provided.")

    if (
        paths.html_dashboard_file
        and Path(paths.html_dashboard_file).suffix.lower() != ".html"
    ):
        raise ValueError("HTML dashboard file must use the .html extension.")

    return paths


def validate_export_options(options: ExportOptions) -> ExportOptions:
    """Validate and normalize export option values."""

    def _normalize_required_str(value: object, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be provided as a string.")
        return value.strip().lower()

    preset_value = getattr(options, "preset", ExportOptions.preset)
    preset = preset_value.strip().lower() if isinstance(preset_value, str) else ""
    if preset not in _ALLOWED_EXPORT_PRESETS:
        preset = "fast_diagnostics"

    export_type = _normalize_required_str(
        getattr(options, "export_type", ExportOptions.export_type),
        "export_type",
    )
    if export_type not in _ALLOWED_EXPORT_TYPES:
        raise ValueError(f"Unsupported export type '{getattr(options, 'export_type', None)}'.")

    export_target = _normalize_required_str(
        getattr(options, "export_target", ExportOptions.export_target),
        "export_target",
    )
    if export_target not in _ALLOWED_EXPORT_TARGETS:
        raise ValueError(
            f"Unsupported export target '{getattr(options, 'export_target', None)}'."
        )

    backend_target_raw = getattr(options, "backend_target", ExportOptions.backend_target)
    backend_target = (
        backend_target_raw.strip().lower()
        if isinstance(backend_target_raw, str)
        else ""
    )
    backend_target = _BACKEND_TARGET_ALIASES.get(backend_target, backend_target)
    if backend_target not in _ALLOWED_BACKEND_TARGETS:
        backend_target = ExportOptions.backend_target
    if export_target == "html_dashboard":
        backend_target = "html"
    if (
        export_target == "google_sheets_drive_convert"
        and backend_target == ExportOptions.backend_target
    ):
        backend_target = "google"

    sorting_parameter = _normalize_required_str(
        getattr(options, "sorting_parameter", ExportOptions.sorting_parameter),
        "sorting_parameter",
    )
    if sorting_parameter not in {"date"}.union(_SAMPLE_SORT_ALIASES):
        raise ValueError(
            "Unsupported sorting parameter "
            f"'{getattr(options, 'sorting_parameter', None)}'."
        )

    violin_min = max(
        2,
        int(
            getattr(
                options,
                "violin_plot_min_samplesize",
                ExportOptions.violin_plot_min_samplesize,
            )
        ),
    )
    summary_scale = max(
        0,
        int(getattr(options, "summary_plot_scale", ExportOptions.summary_plot_scale)),
    )
    worker_count = max(
        1,
        int(getattr(options, "chart_worker_count", ExportOptions.chart_worker_count)),
    )
    worker_queue_size = max(
        1,
        int(
            getattr(
                options,
                "chart_worker_queue_size",
                ExportOptions.chart_worker_queue_size,
            )
        ),
    )
    group_analysis_level = _normalize_required_str(
        getattr(options, "group_analysis_level", ExportOptions.group_analysis_level),
        "group_analysis_level",
    )
    resolved_group_analysis_level = _GROUP_ANALYSIS_LEVEL_ALIASES.get(
        group_analysis_level
    )
    if resolved_group_analysis_level is None:
        raise ValueError(
            "Unsupported group analysis level "
            f"'{getattr(options, 'group_analysis_level', None)}'."
        )

    group_analysis_scope = _normalize_required_str(
        getattr(options, "group_analysis_scope", ExportOptions.group_analysis_scope),
        "group_analysis_scope",
    )
    resolved_group_analysis_scope = _GROUP_ANALYSIS_SCOPE_ALIASES.get(
        group_analysis_scope
    )
    if resolved_group_analysis_scope is None:
        raise ValueError(
            "Unsupported group analysis scope "
            f"'{getattr(options, 'group_analysis_scope', None)}'."
        )

    generate_html_dashboard = bool(
        getattr(
            options,
            "generate_html_dashboard",
            ExportOptions.generate_html_dashboard,
        )
    )
    generate_summary_sheet = bool(
        getattr(
            options,
            "generate_summary_sheet",
            ExportOptions.generate_summary_sheet,
        )
    )
    if export_target == "html_dashboard":
        generate_html_dashboard = True
        generate_summary_sheet = True

    return ExportOptions(
        preset=preset,
        export_type=export_type,
        export_target=export_target,
        backend_target=backend_target,
        sorting_parameter=sorting_parameter,
        violin_plot_min_samplesize=violin_min,
        summary_plot_scale=summary_scale,
        hide_ok_results=bool(
            getattr(options, "hide_ok_results", ExportOptions.hide_ok_results)
        ),
        generate_summary_sheet=generate_summary_sheet,
        generate_html_dashboard=generate_html_dashboard,
        include_industrial_context=bool(
            getattr(
                options,
                "include_industrial_context",
                ExportOptions.include_industrial_context,
            )
        ),
        allow_non_essential_chart_skipping=bool(
            getattr(
                options,
                "allow_non_essential_chart_skipping",
                ExportOptions.allow_non_essential_chart_skipping,
            )
        ),
        chart_worker_count=worker_count,
        chart_worker_queue_size=worker_queue_size,
        group_analysis_level=resolved_group_analysis_level,
        group_analysis_scope=resolved_group_analysis_scope,
        dashboard_visual_settings=normalize_dashboard_visual_settings(
            getattr(
                options,
                "dashboard_visual_settings",
                ExportOptions.dashboard_visual_settings,
            )
        ),
    )


__all__ = [
    "AppPaths",
    "ExportOptions",
    "ExportRequest",
    "validate_export_options",
    "validate_export_request",
    "validate_paths",
]
