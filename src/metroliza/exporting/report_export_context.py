"""Describe the source and frozen settings of a Reports export."""

from pathlib import Path

from metroliza.exporting.contracts import ExportRequest
from metroliza.exporting.export_preset_utils import get_export_preset_label
from metroliza.reports.report_query_service import (
    build_measurement_export_query,
    build_measurement_filter_query,
)

REPORT_SCOPE_SHEET = "REPORT SCOPE"
_TARGET_LABELS = {
    "excel_xlsx": "Excel workbook",
    "google_sheets_drive_convert": "Excel workbook + Google Sheets",
    "html_dashboard": "Standalone HTML dashboard",
}


def _filter_description(request: ExportRequest) -> str:
    if request.filter_description:
        return request.filter_description
    if request.filter_query in (None, "", build_measurement_export_query(), build_measurement_filter_query()):
        return "All measurements in the report scope"
    return "Custom measurement filter"


def _grouping_description(request: ExportRequest) -> str:
    assignments = request.grouping_df
    if not assignments:
        return "No group assignments"
    groups = tuple(dict.fromkeys(assignment.group for assignment in assignments))
    names = ", ".join(name[:80] for name in groups[:5])
    suffix = f" and {len(groups) - 5} more" if len(groups) > 5 else ""
    return f"{len(assignments):,} report assignments · {names}{suffix}"


def export_settings(request: ExportRequest) -> dict[str, str | int | bool]:
    """Display-only settings. The exact filter query remains the data authority."""
    options = request.options
    count = len(request.approved_report_ids or request.approved_source_digests)
    return {
        "Report scope": f"{count:,} approved imported reports" if count else "Selected database",
        "Filters": _filter_description(request),
        "Grouping": _grouping_description(request),
        "Preset": get_export_preset_label(options.preset),
        "Target": _TARGET_LABELS[options.export_target],
        "Chart type": options.export_type.title(),
        "Sort by": "Date" if options.sorting_parameter == "date" else "Sample number",
        "Extended plots": options.generate_summary_sheet,
        "HTML dashboard": options.generate_html_dashboard,
        "Hide OK-only columns": options.hide_ok_results,
        "Group analysis": options.group_analysis_level.title(),
        "Violin minimum observations": options.violin_plot_min_samplesize,
        "Summary Y-axis scale": options.summary_plot_scale,
    }


def report_scope_entries(request: ExportRequest) -> dict[str, str | int | bool]:
    entries = {
        "Source database": Path(request.paths.db_file).name,
        **export_settings(request),
        "Report scope schema": 1,
    }
    if request.application_version:
        entries["Metroliza version"] = request.application_version
    return entries


def report_scope_warnings(metadata) -> tuple[str, ...]:
    warnings = (*metadata.get("summary_sheet_warnings", ()), *metadata.get("group_analysis_warnings", ()))
    unique = tuple(dict.fromkeys(str(warning)[:400] for warning in warnings if warning))
    remainder = (f"{len(unique) - 8} additional chart or grouping warnings.",) if len(unique) > 8 else ()
    return (*unique[:8], *remainder)
