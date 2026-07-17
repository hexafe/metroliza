"""UI-independent orchestration helpers for export dialog workflows."""

from metroliza.exporting.contracts import (
    AppPaths,
    ExportOptions,
    ExportRequest,
    validate_export_options,
    validate_export_request,
)
from metroliza.exporting.export_preset_utils import build_export_options_for_preset
from metroliza.exporting.export_outcomes import (
    ExportRunResult,
    build_export_run_message,
    derive_export_run_result,
    format_export_diagnostics,
)
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


def build_export_completion_message(
    *,
    excel_file,
    export_target,
    completion_metadata,
    run_result: ExportRunResult | None = None,
    cancelled: bool = False,
    terminal_failure: str = "",
):
    """Compose primary completion copy from all requested artifact outcomes."""

    result = run_result or derive_export_run_result(
        excel_file=excel_file,
        export_target=export_target,
        completion_metadata=completion_metadata,
        cancelled=cancelled,
        terminal_failure=terminal_failure,
    )
    return build_export_run_message(result)


def build_export_completion_diagnostics(
    *,
    excel_file,
    export_target,
    completion_metadata,
    run_result: ExportRunResult | None = None,
    cancelled: bool = False,
    terminal_failure: str = "",
):
    """Return copyable diagnostics kept out of the primary completion copy."""

    result = run_result or derive_export_run_result(
        excel_file=excel_file,
        export_target=export_target,
        completion_metadata=completion_metadata,
        cancelled=cancelled,
        terminal_failure=terminal_failure,
    )
    return format_export_diagnostics(result)


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
