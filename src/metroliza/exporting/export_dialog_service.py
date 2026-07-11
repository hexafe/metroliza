"""UI-independent orchestration helpers for export dialog workflows."""

from metroliza.exporting.contracts import (
    AppPaths,
    ExportOptions,
    ExportRequest,
    validate_export_options,
    validate_export_request,
)
from metroliza.exporting.export_preset_utils import build_export_options_for_preset
from pathlib import Path


def _int_or_default(value, default):
    try:
        return int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return int(default)


def build_export_options_payload(
    selected_preset,
    export_type,
    export_target,
    sorting_parameter,
    violin_input,
    summary_scale_input,
    hide_ok_results,
    generate_html_dashboard=False,
    include_industrial_context=False,
    group_analysis_level="off",
    group_analysis_scope="auto",
    dashboard_visual_settings=None,
):
    """Build a validated export-options payload from UI field values."""
    preset_options = build_export_options_for_preset(selected_preset)
    preset_export_target = preset_options.get('export_target') or ExportOptions.export_target
    return ExportOptions(
        preset=selected_preset,
        export_type=export_type or preset_options['export_type'],
        export_target=export_target or preset_export_target,
        sorting_parameter=sorting_parameter or preset_options['sorting_parameter'],
        violin_plot_min_samplesize=_int_or_default(
            violin_input,
            preset_options['violin_plot_min_samplesize'],
        ),
        summary_plot_scale=_int_or_default(
            summary_scale_input,
            preset_options['summary_plot_scale'],
        ),
        hide_ok_results=bool(hide_ok_results),
        generate_summary_sheet=bool(preset_options['generate_summary_sheet']),
        generate_html_dashboard=bool(generate_html_dashboard or preset_options.get('generate_html_dashboard')),
        include_industrial_context=bool(include_industrial_context),
        group_analysis_level=group_analysis_level,
        group_analysis_scope=group_analysis_scope,
        dashboard_visual_settings=dashboard_visual_settings,
    )


def normalize_excel_export_path(excel_file):
    """Return an export path string, appending .xlsx when no suffix is provided."""
    raw_path = str(excel_file or "").strip()
    if not raw_path:
        return raw_path
    path = Path(raw_path)
    if not path.suffix:
        path = path.with_suffix(".xlsx")
    return str(path)


def normalize_html_dashboard_export_path(html_file):
    """Return an HTML dashboard path string, appending .html when no suffix is provided."""
    raw_path = str(html_file or "").strip()
    if not raw_path:
        return raw_path
    path = Path(raw_path)
    if not path.suffix:
        path = path.with_suffix(".html")
    return str(path)


def build_validated_export_request(
    *,
    db_file,
    excel_file,
    selected_preset,
    export_type,
    export_target,
    sorting_parameter,
    violin_input,
    summary_scale_input,
    hide_ok_results,
    filter_query,
    grouping_df,
    generate_html_dashboard=False,
    include_industrial_context=False,
    group_analysis_level="off",
    group_analysis_scope="auto",
    dashboard_visual_settings=None,
):
    """Build and validate ``ExportRequest`` from raw dialog selections."""
    options = validate_export_options(
        build_export_options_payload(
            selected_preset=selected_preset,
            export_type=export_type,
            export_target=export_target,
            sorting_parameter=sorting_parameter,
            violin_input=violin_input,
            summary_scale_input=summary_scale_input,
            hide_ok_results=hide_ok_results,
            generate_html_dashboard=generate_html_dashboard,
            include_industrial_context=include_industrial_context,
            group_analysis_level=group_analysis_level,
            group_analysis_scope=group_analysis_scope,
            dashboard_visual_settings=dashboard_visual_settings,
        )
    )
    if options.export_target == "html_dashboard":
        paths = AppPaths(
            db_file=db_file,
            excel_file=None,
            html_dashboard_file=normalize_html_dashboard_export_path(excel_file),
        )
    else:
        paths = AppPaths(
            db_file=db_file,
            excel_file=normalize_excel_export_path(excel_file),
            html_dashboard_file=None,
        )

    return validate_export_request(
        ExportRequest(
            paths=paths,
            options=options,
            filter_query=filter_query,
            grouping_df=grouping_df,
        )
    )


def build_export_completion_message(*, excel_file, export_target, completion_metadata):
    """Compose the completion dialog payload for local and Google export flows."""
    metadata = completion_metadata or {}
    warnings = [str(w) for w in metadata.get('conversion_warnings', []) if str(w).strip()]
    dashboard_warnings = [str(w) for w in metadata.get('html_dashboard_warnings', []) if str(w).strip()]
    summary_warnings = [str(w) for w in metadata.get('summary_sheet_warnings', []) if str(w).strip()]
    fallback_message = str(metadata.get('fallback_message', '')).strip()
    converted_url = str(metadata.get('converted_url', '')).strip()
    export_directory_line = build_export_directory_link_line(excel_file)
    dashboard_file_line = build_export_artifact_link_line('HTML dashboard', metadata.get('html_dashboard_path'))

    def _append_warning_sections(message_lines):
        if dashboard_warnings:
            message_lines.extend(["", "HTML dashboard warnings:", *[f"- {warning}" for warning in dashboard_warnings]])
        if summary_warnings:
            message_lines.extend(["", "Summary sheet warnings:", *[f"- {warning}" for warning in summary_warnings]])

    if export_target == 'html_dashboard':
        message_lines = ["HTML dashboard exported successfully!"]
        if dashboard_file_line:
            message_lines.extend(["", dashboard_file_line])
        _append_warning_sections(message_lines)
        if summary_warnings:
            return 'warning', 'Export completed with warnings', "\n".join(message_lines)
        return 'info', 'Export successful', "\n".join(message_lines)

    base_success_lines = ["Data exported successfully!"]
    artifact_lines = [line for line in (export_directory_line, dashboard_file_line) if line]
    for artifact_line in artifact_lines:
        base_success_lines.extend(["", artifact_line])

    if export_target == 'google_sheets_drive_convert':
        if warnings or fallback_message:
            message_lines = [
                f"Data exported locally to {excel_file}.",
            ]
            if export_directory_line:
                message_lines.append(export_directory_line)
            if dashboard_file_line:
                message_lines.append(dashboard_file_line)
            message_lines.extend([
                "",
                "Google Sheets conversion was not fully completed.",
            ])
            if converted_url:
                message_lines.append(f"Google Sheet: {converted_url}")
            if warnings:
                message_lines.append("Warnings/Errors:")
                message_lines.extend(f"- {warning}" for warning in warnings)
            _append_warning_sections(message_lines)
            return 'warning', 'Export completed with Google fallback', "\n".join(message_lines)

        if converted_url:
            message_lines = list(base_success_lines)
            message_lines.extend(["", f"Google Sheet: {converted_url}"])
            _append_warning_sections(message_lines)
            if summary_warnings:
                return 'warning', 'Export completed with warnings', "\n".join(message_lines)
            return 'info', 'Export successful', "\n".join(message_lines)

    _append_warning_sections(base_success_lines)
    if summary_warnings:
        return 'warning', 'Export completed with warnings', "\n".join(base_success_lines)
    return 'info', 'Export successful', "\n".join(base_success_lines)


def build_export_directory_link_line(excel_file):
    """Build a file:// URI pointing to the exported file for clickable dialogs."""
    try:
        export_file_uri = Path(str(excel_file)).resolve(strict=False).as_uri()
    except Exception:
        return ""
    return f"Export file: {export_file_uri}"


def build_export_folder_link_line(excel_file):
    """Build a file:// URI pointing to the export parent folder for clickable dialogs."""
    try:
        export_folder_uri = Path(str(excel_file)).resolve(strict=False).parent.as_uri()
    except Exception:
        return ""
    return f"Export folder: {export_folder_uri}"


def build_export_artifact_link_line(label, file_path):
    """Build a generic file:// URI line for additional export artifacts."""
    if not str(label or "").strip() or not str(file_path or "").strip():
        return ""
    try:
        artifact_uri = Path(str(file_path)).resolve(strict=False).as_uri()
    except Exception:
        return ""
    return f"{label}: {artifact_uri}"
