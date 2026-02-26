from dataclasses import dataclass
from pathlib import Path
import pandas as pd


@dataclass(frozen=True)
class ParseRequest:
    source_directory: str
    db_file: str


@dataclass(frozen=True)
class AppPaths:
    db_file: str
    excel_file: str | None = None


@dataclass(frozen=True)
class ExportOptions:
    preset: str = "fast_diagnostics"
    export_type: str = "line"
    export_target: str = "excel_xlsx"
    backend_target: str = "excel"
    sorting_parameter: str = "date"
    violin_plot_min_samplesize: int = 6
    summary_plot_scale: int = 0
    hide_ok_results: bool = False
    generate_summary_sheet: bool = False


@dataclass(frozen=True)
class GroupingAssignment:
    group: str
    report_id: int | None = None
    reference: str | None = None
    fileloc: str | None = None
    filename: str | None = None
    date: str | None = None
    sample_number: str | None = None


@dataclass(frozen=True)
class ExportRequest:
    paths: AppPaths
    options: ExportOptions
    filter_query: str | None = None
    grouping_df: pd.DataFrame | None = None


def validate_export_request(request: ExportRequest) -> ExportRequest:
    if not isinstance(request, ExportRequest):
        raise ValueError("Export request must be provided as an ExportRequest instance.")

    validated_paths = validate_paths(request.paths)
    validated_options = validate_export_options(request.options)
    validated_grouping_df = validate_grouping_df(request.grouping_df)

    if request.filter_query is not None and not isinstance(request.filter_query, str):
        raise ValueError("Filter query must be a string when provided.")

    return ExportRequest(
        paths=validated_paths,
        options=validated_options,
        filter_query=request.filter_query,
        grouping_df=validated_grouping_df,
    )


_ALLOWED_EXPORT_TYPES = {"line", "scatter"}
_ALLOWED_EXPORT_PRESETS = {"fast_diagnostics", "full_report"}
_ALLOWED_EXPORT_TARGETS = {"excel_xlsx", "google_sheets_drive_convert"}
_ALLOWED_BACKEND_TARGETS = {"excel", "google"}
_BACKEND_TARGET_ALIASES = {"google_sheets": "google", "googlesheets": "google"}
_SAMPLE_SORT_ALIASES = {"sample", "sample #", "sample number", "part #", "part number"}


def validate_paths(paths: AppPaths) -> AppPaths:
    if not isinstance(paths.db_file, str) or not paths.db_file.strip():
        raise ValueError("A database file path is required.")

    if paths.excel_file is not None and (not isinstance(paths.excel_file, str) or not paths.excel_file.strip()):
        raise ValueError("Excel file path must be a non-empty string when provided.")

    if paths.excel_file:
        suffix = Path(paths.excel_file).suffix.lower()
        if suffix != ".xlsx":
            raise ValueError("Excel file must use the .xlsx extension.")

    return paths


def validate_parse_request(request: ParseRequest) -> ParseRequest:
    if not isinstance(request.source_directory, str) or not request.source_directory.strip():
        raise ValueError("A source directory is required.")

    validate_paths(AppPaths(db_file=request.db_file))
    return request


def validate_export_options(options: ExportOptions) -> ExportOptions:
    preset_value = getattr(options, "preset", ExportOptions.preset)
    preset = preset_value.strip().lower() if isinstance(preset_value, str) else ""
    if preset not in _ALLOWED_EXPORT_PRESETS:
        preset = "fast_diagnostics"

    export_type = getattr(options, "export_type", ExportOptions.export_type).strip().lower()
    if export_type not in _ALLOWED_EXPORT_TYPES:
        raise ValueError(f"Unsupported export type '{getattr(options, 'export_type', None)}'.")

    export_target = getattr(options, "export_target", ExportOptions.export_target).strip().lower()
    if export_target not in _ALLOWED_EXPORT_TARGETS:
        raise ValueError(f"Unsupported export target '{getattr(options, 'export_target', None)}'.")

    backend_target_raw = getattr(options, "backend_target", ExportOptions.backend_target)
    backend_target = backend_target_raw.strip().lower() if isinstance(backend_target_raw, str) else ""
    backend_target = _BACKEND_TARGET_ALIASES.get(backend_target, backend_target)
    if backend_target not in _ALLOWED_BACKEND_TARGETS:
        backend_target = ExportOptions.backend_target
    if export_target == "google_sheets_drive_convert" and backend_target == ExportOptions.backend_target:
        backend_target = "google"

    sorting_parameter = getattr(options, "sorting_parameter", ExportOptions.sorting_parameter).strip().lower()
    allowed_sorting = {"date"}.union(_SAMPLE_SORT_ALIASES)
    if sorting_parameter not in allowed_sorting:
        raise ValueError(f"Unsupported sorting parameter '{getattr(options, 'sorting_parameter', None)}'.")

    violin_min = max(2, int(getattr(options, "violin_plot_min_samplesize", ExportOptions.violin_plot_min_samplesize)))
    summary_scale = max(0, int(getattr(options, "summary_plot_scale", ExportOptions.summary_plot_scale)))

    return ExportOptions(
        preset=preset,
        export_type=export_type,
        export_target=export_target,
        backend_target=backend_target,
        sorting_parameter=sorting_parameter,
        violin_plot_min_samplesize=violin_min,
        summary_plot_scale=summary_scale,
        hide_ok_results=bool(getattr(options, "hide_ok_results", ExportOptions.hide_ok_results)),
        generate_summary_sheet=bool(getattr(options, "generate_summary_sheet", ExportOptions.generate_summary_sheet)),
    )


def validate_grouping_df(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None:
        return None

    if not isinstance(df, pd.DataFrame):
        raise ValueError("Grouping assignments must be provided as a pandas DataFrame.")

    if df.empty:
        return df

    if "GROUP" not in df.columns:
        raise ValueError("Grouping DataFrame must include a GROUP column.")

    has_identity = "REPORT_ID" in df.columns
    composite_key_cols = {"REFERENCE", "FILELOC", "FILENAME", "DATE", "SAMPLE_NUMBER"}
    has_composite = composite_key_cols.issubset(df.columns)

    if not (has_identity or has_composite):
        raise ValueError(
            "Grouping DataFrame must include REPORT_ID or the full composite key: "
            "REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER."
        )

    return df.copy()
