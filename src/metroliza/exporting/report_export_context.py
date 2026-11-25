"""Describe the source and frozen settings of a Reports export."""

from dataclasses import dataclass
from pathlib import Path

from metroliza.exporting.contracts import ExportRequest
from metroliza.exporting.export_preset_utils import get_export_preset_label
from metroliza.reports.db import quote_identifier
from metroliza.reports.report_query_service import (
    build_measurement_export_query,
    build_measurement_filter_query,
)

REPORT_SCOPE_SHEET = "REPORT SCOPE"
REPORT_SCOPE_KEY = "completed_report_scope"
_COMPLETION_FIELDS = (
    "Source database", "Report scope", "Filters", "Grouping",
    "Selected source reports", "Parser IDs", "Data through (report date)",
    "Analysed measurement rows", "Analysis method", "Analysis method version",
    "Group Analysis effective scope", "Metroliza version",
)
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


def report_selection_from_snapshot(connection, snapshot_name) -> tuple[tuple[str, str | int], ...]:
    """Summarize the immutable selection without publishing source file paths."""
    columns = {
        name.upper() for (name,) in connection.execute(
            "SELECT name FROM pragma_table_info(?, 'temp')", (snapshot_name,),
        )
    }
    if not {"REPORT_ID", "DATE", "PARSER_ID"}.issubset(columns):
        return ()  # A custom legacy export query may omit source provenance.

    table = quote_identifier(snapshot_name)
    report_count, latest_date, has_unknown_date = connection.execute(
        f"""SELECT COUNT(DISTINCT REPORT_ID),
             MAX(CASE WHEN DATE = date(DATE, '+0 days') THEN DATE END),
             MAX(CASE WHEN DATE = date(DATE, '+0 days') THEN 0 ELSE 1 END)
             FROM temp.{table} WHERE REPORT_ID IS NOT NULL"""
    ).fetchone()
    if latest_date and has_unknown_date:
        latest_date += " (other report dates unavailable)"
    parser_limit = 12
    parsers = [value for (value,) in connection.execute(
        f"""SELECT DISTINCT substr(trim(PARSER_ID), 1, 80) AS parser
             FROM temp.{table} WHERE REPORT_ID IS NOT NULL AND typeof(PARSER_ID) = 'text'
             AND trim(PARSER_ID) <> '' ORDER BY parser LIMIT ?""",
        (parser_limit + 1,),
    )]
    parser_text = ", ".join(parsers[:parser_limit])
    if len(parsers) > parser_limit:
        parser_text += " and more"
    return (
        ("Selected source reports", report_count),
        ("Parser IDs", parser_text or "Unavailable"),
        ("Data through (report date)", latest_date or "Unavailable"),
    )


def report_scope_warnings(metadata) -> tuple[str, ...]:
    warnings = (*metadata.get("summary_sheet_warnings", ()), *metadata.get("group_analysis_warnings", ()))
    unique = tuple(dict.fromkeys(str(warning)[:400] for warning in warnings if warning))
    remainder = (f"{len(unique) - 8} additional chart or grouping warnings.",) if len(unique) > 8 else ()
    return (*unique[:8], *remainder)



@dataclass(frozen=True)
class ReportExportScope:
    entries: tuple[tuple[str, str | int | bool], ...]
    warnings: tuple[str, ...]

    def completion_text(self) -> str:
        fields = dict(self.entries)
        lines = ["Report scope"]
        lines.extend(f"{label} — {fields[label]}" for label in _COMPLETION_FIELDS if label in fields)
        if self.warnings:
            lines.append("Analysis warnings")
            lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines)


def freeze_report_export_scope(
    request: ExportRequest, metadata, *, measurement_rows: int | None, effective_group_scope: str | None,
    selection: tuple[tuple[str, str | int], ...] = (),
) -> ReportExportScope:
    """Project one frozen set of facts from the completed analysis stages."""
    entries = report_scope_entries(request)
    if measurement_rows is not None:
        entries["Report scope schema"] = 2
        entries["Analysed measurement rows"] = measurement_rows
        entries["Analysis method"] = "Reports measurements by reference or report, header and axis"
        entries["Analysis method version"] = 1
    if effective_group_scope:
        entries["Group Analysis effective scope"] = effective_group_scope.replace("_", " ").title()
    if selection and measurement_rows is not None:
        entries["Report scope schema"] = 3
        entries.update(selection)
    return ReportExportScope(tuple(entries.items()), report_scope_warnings(metadata))
