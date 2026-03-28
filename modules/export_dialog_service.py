"""UI-independent orchestration helpers for export dialog workflows."""

from modules.contracts import AppPaths, ExportOptions, ExportRequest, validate_export_options, validate_paths
from modules.export_preset_utils import build_export_options_for_preset
from pathlib import Path


def build_export_options_payload(
    selected_preset,
    export_type,
    export_target,
    sorting_parameter,
    violin_input,
    summary_scale_input,
    hide_ok_results,
    generate_html_dashboard=False,
    group_analysis_level="off",
    group_analysis_scope="auto",
):
    """Build a validated export-options payload from UI field values."""
    preset_options = build_export_options_for_preset(selected_preset)
    return ExportOptions(
        preset=selected_preset,
        export_type=export_type or preset_options['export_type'],
        export_target=export_target or ExportOptions.export_target,
        sorting_parameter=sorting_parameter or preset_options['sorting_parameter'],
        violin_plot_min_samplesize=int(violin_input if violin_input not in (None, "") else preset_options['violin_plot_min_samplesize']),
        summary_plot_scale=int(summary_scale_input if summary_scale_input not in (None, "") else preset_options['summary_plot_scale']),
        hide_ok_results=bool(hide_ok_results),
        generate_summary_sheet=bool(preset_options['generate_summary_sheet']),
        generate_html_dashboard=bool(generate_html_dashboard),
        group_analysis_level=group_analysis_level,
        group_analysis_scope=group_analysis_scope,
    )


def build_validated_export_request(*, db_file, excel_file, selected_preset, export_type, export_target, sorting_parameter, violin_input, summary_scale_input, hide_ok_results, filter_query, grouping_df, generate_html_dashboard=False, group_analysis_level="off", group_analysis_scope="auto"):
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
            group_analysis_level=group_analysis_level,
            group_analysis_scope=group_analysis_scope,
        )
    )

    paths = AppPaths(db_file=db_file, excel_file=str(excel_file))
    validate_paths(paths)
    return ExportRequest(
        paths=paths,
        options=options,
        filter_query=filter_query,
        grouping_df=grouping_df,
    )


def build_export_completion_message(*, excel_file, export_target, completion_metadata):
    """Compose the completion dialog payload for local and Google export flows."""
    metadata = completion_metadata or {}
    warnings = [str(w) for w in metadata.get('conversion_warnings', []) if str(w).strip()]
    dashboard_warnings = [str(w) for w in metadata.get('html_dashboard_warnings', []) if str(w).strip()]
    fallback_message = str(metadata.get('fallback_message', '')).strip()
    converted_url = str(metadata.get('converted_url', '')).strip()
    backend_diagnostic_lines = [str(line) for line in metadata.get('backend_diagnostics_lines', []) if str(line).strip()]
    export_directory_line = build_export_directory_link_line(excel_file)
    dashboard_file_line = build_export_artifact_link_line('HTML dashboard', metadata.get('html_dashboard_path'))
    dashboard_assets_line = build_export_artifact_link_line('Dashboard assets', metadata.get('html_dashboard_assets_path'))

    base_success_lines = [f"Data exported successfully to {excel_file}."]
    if export_directory_line:
        base_success_lines.append(export_directory_line)
    if dashboard_file_line:
        base_success_lines.append(dashboard_file_line)
    if dashboard_assets_line:
        base_success_lines.append(dashboard_assets_line)

    if export_target == 'google_sheets_drive_convert':
        if warnings or fallback_message:
            message_lines = [
                f"Data exported locally to {excel_file}.",
            ]
            if export_directory_line:
                message_lines.append(export_directory_line)
            if dashboard_file_line:
                message_lines.append(dashboard_file_line)
            if dashboard_assets_line:
                message_lines.append(dashboard_assets_line)
            message_lines.extend([
                "",
                "Google Sheets conversion was not fully completed.",
            ])
            if converted_url:
                message_lines.append(f"Google Sheet: {converted_url}")
            if warnings:
                message_lines.append("Warnings/Errors:")
                message_lines.extend(f"- {warning}" for warning in warnings)
            if dashboard_warnings:
                message_lines.extend(["", "HTML dashboard warnings:", *[f"- {warning}" for warning in dashboard_warnings]])
            if backend_diagnostic_lines:
                message_lines.extend(["", "Backend diagnostics:", *[f"- {line}" for line in backend_diagnostic_lines]])
            return 'warning', 'Export completed with Google fallback', "\n".join(message_lines)

        if converted_url:
            message_lines = list(base_success_lines)
            message_lines.extend([
                "",
                f"Google Sheet: {converted_url}",
            ])
            if dashboard_warnings:
                message_lines.extend(["", "HTML dashboard warnings:", *[f"- {warning}" for warning in dashboard_warnings]])
            if backend_diagnostic_lines:
                message_lines.extend(["", "Backend diagnostics:", *[f"- {line}" for line in backend_diagnostic_lines]])
            return 'info', 'Export successful', "\n".join(message_lines)

    if dashboard_warnings:
        base_success_lines.extend(["", "HTML dashboard warnings:", *[f"- {warning}" for warning in dashboard_warnings]])
    if backend_diagnostic_lines:
        base_success_lines.extend(["", "Backend diagnostics:", *[f"- {line}" for line in backend_diagnostic_lines]])
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
