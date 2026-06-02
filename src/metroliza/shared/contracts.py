"""Immutable request/config contracts plus validation entry points.

This module defines frozen dataclasses used to pass parse and export configuration
through the application. It also provides validator helpers that enforce required
fields, normalize supported option values, and return validated request objects
for the canonical export workflows, including the single-sheet Group Analysis
contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pandas as pd

from metroliza.charts.dashboard_visual_options import normalize_dashboard_visual_settings
from metroliza.shared.dashboard_interactivity import (
    DashboardInteractivityOptions,
    normalize_dashboard_interactivity_options,
)
from metroliza.industrial.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
    require_identifier as require_analytics_identifier,
)
from metroliza.tabular.tabular_analytics_service import TabularAnalyticsLoadResult, TabularColumnFilter


@dataclass(frozen=True)
class ParseRequest:
    """Request payload for parsing a source directory into a target database.

    Attributes:
        source_directory: Input folder containing source files to parse.
        db_file: Output database path where parsed content is written.
        metadata_parsing_mode: Metadata extraction depth. ``"light"`` skips OCR
            fallback for faster ingestion; ``"complete"`` keeps OCR fallback for
            stronger header metadata coverage.
        run_background_metadata_enrichment: When true, a light parse can be
            followed by a user-enabled complete metadata pass in the parser
            thread without reparsing measurements.

    Usage notes:
        Pass to ``validate_parse_request`` before use so required string fields are
        checked and path validation is applied consistently.
    """

    source_directory: str
    db_file: str
    metadata_parsing_mode: str = "complete"
    run_background_metadata_enrichment: bool = False


@dataclass(frozen=True)
class AppPaths:
    """Filesystem paths required by export and parse workflows.

    Attributes:
        db_file: Database path; required and must be a non-empty string.
        excel_file: Optional Excel output path; when provided it must end in
            ``.xlsx``.
        html_dashboard_file: Optional standalone HTML dashboard output path;
            when provided it must end in ``.html``.

    Usage notes:
        ``validate_paths`` enforces required/optional path constraints but does not
        rewrite path values.
    """

    db_file: str
    excel_file: str | None = None
    html_dashboard_file: str | None = None


@dataclass(frozen=True)
class ExportOptions:
    """Configurable export behavior with normalized defaults.

    Attributes:
        preset: Export preset; unsupported values normalize to
            ``"fast_diagnostics"``.
        export_type: Export mode, currently ``"line"`` or ``"scatter"``.
        export_target: Destination format/provider identifier.
        backend_target: Backend implementation target; aliases may normalize to
            canonical values.
        sorting_parameter: Sort key; supports ``"date"`` and sample-style aliases.
        violin_plot_min_samplesize: Lower-bounded numeric threshold for violin
            plots.
        summary_plot_scale: Non-negative scaling value for summary plots.
        hide_ok_results: Toggles hiding passing results in exports.
        generate_summary_sheet: Toggles summary sheet generation.
        generate_html_dashboard: Toggles sidecar HTML dashboard generation.
        include_industrial_context: Toggles cached industrial context columns and
            worksheet output when local Oznak-linked data exists.
        allow_non_essential_chart_skipping: Enables dropping optional summary
            charts under bottleneck optimization.
        chart_worker_count: Worker process/thread count, minimum of ``1``.
        chart_worker_queue_size: Queue size for chart workers, minimum of ``1``.
        group_analysis_level: Workbook-level Group Analysis mode. Supported
            values are ``"off"``, ``"light"``, and ``"standard"``.
            ``"light"`` and ``"standard"`` produce the user-facing
            ``Group Analysis`` worksheet by default; they do not automatically
            add a separate diagnostics worksheet. Internal/debug flows may
            still opt into a separate internal diagnostics worksheet explicitly.
        group_analysis_scope: Requested Group Analysis scope. Supported values
            are ``"auto"``, ``"single_reference"``, and
            ``"multi_reference"``.

    Usage notes:
        ``validate_export_options`` returns a normalized copy with sanitized
        casing/aliases and bounded numeric settings. Group Analysis defaults are
        user-facing only: Light/Standard target the canonical Group Analysis
        worksheet and do not imply a separate diagnostics worksheet unless an
        internal/debug export path enables it explicitly.
    """

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
    chart_worker_count: int = 2
    chart_worker_queue_size: int = 4
    group_analysis_level: str = "off"
    group_analysis_scope: str = "auto"
    dashboard_visual_settings: dict | None = None


@dataclass(frozen=True)
class GroupingAssignment:
    """Logical grouping assignment keyed by canonical report identity.

    Attributes:
        group: Required target group label.
        report_id: Required canonical report identity key when persisted.

    Usage notes:
        ``report_id`` is the only supported grouping identity in the report
        metadata schema.
    """

    group: str
    report_id: int | None = None
    reference: str | None = None
    fileloc: str | None = None
    filename: str | None = None
    date: str | None = None
    sample_number: str | None = None


@dataclass(frozen=True)
class ExportRequest:
    """Top-level immutable export request contract.

    Attributes:
        paths: Required filesystem path bundle.
        options: Export behavior settings to validate and normalize.
        filter_query: Optional query expression used to filter records.
        grouping_df: Optional grouping overrides DataFrame keyed by ``REPORT_ID``
            or by full composite alternate-key columns.

    Usage notes:
        Validate with ``validate_export_request`` to receive nested normalized
        options and a copied validated grouping frame when non-empty.
    """

    paths: AppPaths
    options: ExportOptions
    filter_query: str | None = None
    grouping_df: pd.DataFrame | None = None


@dataclass(frozen=True)
class IndustrialAnalyticsRequest:
    """Top-level immutable request contract for shared analytics workflows."""

    source_kind: str
    output_dashboard_file: str
    dashboard_detail_mode: str = "full"
    db_file: str = ""
    input_file: str = ""
    output_workbook_file: str = ""
    metric_selection: tuple[ProductionMetricSelection, ...] = ()
    filter_state: ProductionFilterState | None = None
    aggregation_state: ProductionAggregationState | None = None
    cohort_state: ReferenceCohortState | None = None
    chart_selection: ProductionChartSelection | None = None
    separate_parameter_sheets: bool = True
    sheet_name: str | int | None = None
    timestamp_column: str | None = None
    reference_column: str | None = None
    tabular_load_result: TabularAnalyticsLoadResult | None = None
    tabular_filter_columns: tuple[str, ...] = ()
    tabular_filter_keys: tuple[tuple[str, ...], ...] = ()
    tabular_column_filters: tuple[TabularColumnFilter, ...] = ()
    grouping_df: pd.DataFrame | None = None
    dashboard_visual_settings: dict | None = None
    dashboard_interactivity_options: DashboardInteractivityOptions | dict | None = None


def validate_export_request(request: ExportRequest) -> ExportRequest:
    """Validate an export request and normalize nested contracts.

    Args:
        request: Export request object to validate. ``filter_query`` is optional,
            but when present it must be a string.

    Returns:
        ExportRequest: New request instance containing validated paths, normalized
        export options, and validated grouping DataFrame. Nested values may be
        copied/normalized by their validators.

    Raises:
        ValueError: If ``request`` is not an ``ExportRequest`` instance or if any
        nested validator rejects unsupported values, missing required fields, or
        invalid file suffixes.

    Invariants:
        Delegates all path/options/grouping checks to dedicated validators so the
        returned request has internally consistent contracts.
    """

    if not isinstance(request, ExportRequest):
        raise ValueError("Export request must be provided as an ExportRequest instance.")

    validated_options = validate_export_options(request.options)
    validated_paths = validate_paths(request.paths)
    validated_grouping_df = validate_grouping_df(request.grouping_df)

    if request.filter_query is not None and not isinstance(request.filter_query, str):
        raise ValueError("Filter query must be a string when provided.")

    if validated_options.export_target == "html_dashboard":
        if not validated_paths.html_dashboard_file:
            raise ValueError("HTML dashboard output path is required for HTML-only export.")
    elif not validated_paths.excel_file:
        raise ValueError("Excel file path is required for workbook export.")

    return ExportRequest(
        paths=validated_paths,
        options=validated_options,
        filter_query=request.filter_query,
        grouping_df=validated_grouping_df,
    )


def validate_industrial_analytics_request(
    request: IndustrialAnalyticsRequest,
    *,
    require_runnable: bool = False,
) -> IndustrialAnalyticsRequest:
    """Validate and normalize a shared analytics request."""

    if not isinstance(request, IndustrialAnalyticsRequest):
        raise ValueError("Analytics request must be provided as an IndustrialAnalyticsRequest instance.")

    source_kind = _normalize_analytics_source_kind(request.source_kind)
    output_dashboard_file = _normalize_optional_output_path(
        request.output_dashboard_file,
        suffix=".html",
        field_name="dashboard output path",
        required=require_runnable,
    )
    output_workbook_file = _normalize_optional_output_path(
        request.output_workbook_file,
        suffix=".xlsx",
        field_name="workbook output path",
        required=False,
    )
    db_file = _normalize_optional_text(request.db_file, field_name="database path")
    input_file = _normalize_optional_text(request.input_file, field_name="CSV/Excel input path")

    if require_runnable and source_kind == "production_cache" and not db_file:
        raise ValueError("Select a Metroliza report database before creating analytics.")
    if require_runnable and source_kind == "tabular_file" and not input_file:
        raise ValueError("Select a CSV or Excel file before creating analytics.")

    return IndustrialAnalyticsRequest(
        source_kind=source_kind,
        output_dashboard_file=output_dashboard_file,
        dashboard_detail_mode=_normalize_dashboard_detail_mode(request.dashboard_detail_mode),
        db_file=db_file,
        input_file=input_file,
        output_workbook_file=output_workbook_file,
        metric_selection=_normalize_metric_selection(request.metric_selection),
        filter_state=_normalize_filter_state(request.filter_state),
        aggregation_state=_normalize_aggregation_state(request.aggregation_state),
        cohort_state=_normalize_cohort_state(request.cohort_state),
        chart_selection=_normalize_chart_selection(request.chart_selection),
        separate_parameter_sheets=bool(request.separate_parameter_sheets),
        sheet_name=_normalize_sheet_name(request.sheet_name),
        timestamp_column=_normalize_optional_identifier(request.timestamp_column, "time column"),
        reference_column=_normalize_optional_identifier(request.reference_column, "part/id column"),
        tabular_load_result=_normalize_tabular_load_result(request.tabular_load_result),
        tabular_filter_columns=_normalize_filter_columns(request.tabular_filter_columns),
        tabular_filter_keys=_normalize_filter_keys(request.tabular_filter_keys),
        tabular_column_filters=_normalize_column_filters(request.tabular_column_filters),
        grouping_df=validate_grouping_df(request.grouping_df),
        dashboard_visual_settings=normalize_dashboard_visual_settings(
            request.dashboard_visual_settings
        ),
        dashboard_interactivity_options=_normalize_dashboard_interactivity_options(
            request.dashboard_interactivity_options
        ),
    )


_ALLOWED_EXPORT_TYPES = {"line", "scatter"}
_ALLOWED_EXPORT_PRESETS = {"fast_diagnostics", "full_report", "html_dashboard_only"}
_ALLOWED_EXPORT_TARGETS = {"excel_xlsx", "google_sheets_drive_convert", "html_dashboard"}
_ALLOWED_BACKEND_TARGETS = {"excel", "google", "html"}
_BACKEND_TARGET_ALIASES = {"google_sheets": "google", "googlesheets": "google"}
_SAMPLE_SORT_ALIASES = {"sample", "sample #", "sample number", "part #", "part number"}
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
_PARSE_METADATA_MODE_ALIASES = {
    "light": "light",
    "fast": "light",
    "lite": "light",
    "complete": "complete",
    "full": "complete",
    "standard": "complete",
}
_ANALYTICS_SOURCE_KINDS = {"production_cache", "tabular_file"}
_DASHBOARD_DETAIL_MODES = {"fast", "full"}


def validate_paths(paths: AppPaths) -> AppPaths:
    """Validate required application paths and optional output target constraints.

    Args:
        paths: Path bundle where ``db_file`` must be a non-empty string and
            optional output paths must be non-empty strings when provided.

    Returns:
        AppPaths: The same ``paths`` instance; values are validated but not copied
        or normalized.

    Raises:
        ValueError: If required fields are missing/empty or if output paths use
        invalid suffixes.

    Invariants:
        Performs shape/content checks only and does not mutate path text.
    """

    if not isinstance(paths.db_file, str) or not paths.db_file.strip():
        raise ValueError("A database file path is required.")

    if paths.excel_file is not None and (not isinstance(paths.excel_file, str) or not paths.excel_file.strip()):
        raise ValueError("Excel file path must be a non-empty string when provided.")

    if paths.excel_file:
        suffix = Path(paths.excel_file).suffix.lower()
        if suffix != ".xlsx":
            raise ValueError("Excel file must use the .xlsx extension.")

    if paths.html_dashboard_file is not None and (
        not isinstance(paths.html_dashboard_file, str) or not paths.html_dashboard_file.strip()
    ):
        raise ValueError("HTML dashboard path must be a non-empty string when provided.")

    if paths.html_dashboard_file:
        suffix = Path(paths.html_dashboard_file).suffix.lower()
        if suffix != ".html":
            raise ValueError("HTML dashboard file must use the .html extension.")

    return paths


def validate_parse_request(request: ParseRequest) -> ParseRequest:
    """Validate parse request inputs.

    Args:
        request: Parse request where ``source_directory`` and ``db_file`` are both
            required non-empty strings.

    Returns:
        ParseRequest: A request instance with normalized metadata parsing mode.

    Raises:
        ValueError: If ``request`` is not a ``ParseRequest`` instance or required
        fields are missing/empty.

    Invariants:
        Reuses ``validate_paths`` for ``db_file`` validation to keep path rules
        consistent between parse and export workflows.
    """

    if not isinstance(request, ParseRequest):
        raise ValueError("Parse request must be provided as a ParseRequest instance.")

    if not isinstance(request.source_directory, str) or not request.source_directory.strip():
        raise ValueError("A source directory is required.")

    validate_paths(AppPaths(db_file=request.db_file))

    mode_value = getattr(request, "metadata_parsing_mode", ParseRequest.metadata_parsing_mode)
    if not isinstance(mode_value, str):
        raise ValueError("metadata_parsing_mode must be provided as a string.")
    metadata_parsing_mode = _PARSE_METADATA_MODE_ALIASES.get(mode_value.strip().lower())
    if metadata_parsing_mode is None:
        raise ValueError(f"Unsupported metadata parsing mode '{mode_value}'.")
    if not isinstance(request.run_background_metadata_enrichment, bool):
        raise ValueError("run_background_metadata_enrichment must be a boolean.")

    return ParseRequest(
        source_directory=request.source_directory,
        db_file=request.db_file,
        metadata_parsing_mode=metadata_parsing_mode,
        run_background_metadata_enrichment=request.run_background_metadata_enrichment,
    )


def validate_export_options(options: ExportOptions) -> ExportOptions:
    """Validate and normalize export option values.

    Args:
        options: Export settings object-like value. Required string fields must be
            present as strings and supported by the allowed option sets.

    Returns:
        ExportOptions: A new normalized options instance. String settings are
        lowercased/trimmed, aliases are canonicalized, unsupported presets fall
        back to defaults, and numeric values are clamped to minimum bounds.

    Raises:
        ValueError: If required option fields are not strings or contain
        unsupported values (for ``export_type``, ``export_target``, or
        ``sorting_parameter``).

    Invariants:
        Always returns an ``ExportOptions`` instance with canonical backend target
        behavior and bounded numeric settings.
    """

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
        raise ValueError(f"Unsupported export target '{getattr(options, 'export_target', None)}'.")

    backend_target_raw = getattr(options, "backend_target", ExportOptions.backend_target)
    backend_target = backend_target_raw.strip().lower() if isinstance(backend_target_raw, str) else ""
    backend_target = _BACKEND_TARGET_ALIASES.get(backend_target, backend_target)
    if backend_target not in _ALLOWED_BACKEND_TARGETS:
        backend_target = ExportOptions.backend_target
    if export_target == "html_dashboard":
        backend_target = "html"
    if export_target == "google_sheets_drive_convert" and backend_target == ExportOptions.backend_target:
        backend_target = "google"

    sorting_parameter = _normalize_required_str(
        getattr(options, "sorting_parameter", ExportOptions.sorting_parameter),
        "sorting_parameter",
    )
    allowed_sorting = {"date"}.union(_SAMPLE_SORT_ALIASES)
    if sorting_parameter not in allowed_sorting:
        raise ValueError(f"Unsupported sorting parameter '{getattr(options, 'sorting_parameter', None)}'.")

    violin_min = max(2, int(getattr(options, "violin_plot_min_samplesize", ExportOptions.violin_plot_min_samplesize)))
    summary_scale = max(0, int(getattr(options, "summary_plot_scale", ExportOptions.summary_plot_scale)))
    worker_count = max(1, int(getattr(options, "chart_worker_count", ExportOptions.chart_worker_count)))
    worker_queue_size = max(1, int(getattr(options, "chart_worker_queue_size", ExportOptions.chart_worker_queue_size)))
    group_analysis_level = _normalize_required_str(
        getattr(options, "group_analysis_level", ExportOptions.group_analysis_level),
        "group_analysis_level",
    )
    group_analysis_level = _GROUP_ANALYSIS_LEVEL_ALIASES.get(group_analysis_level)
    if group_analysis_level is None:
        raise ValueError(
            f"Unsupported group analysis level '{getattr(options, 'group_analysis_level', None)}'."
        )

    group_analysis_scope = _normalize_required_str(
        getattr(options, "group_analysis_scope", ExportOptions.group_analysis_scope),
        "group_analysis_scope",
    )
    group_analysis_scope = _GROUP_ANALYSIS_SCOPE_ALIASES.get(group_analysis_scope)
    if group_analysis_scope is None:
        raise ValueError(
            f"Unsupported group analysis scope '{getattr(options, 'group_analysis_scope', None)}'."
        )

    generate_html_dashboard = bool(
        getattr(options, "generate_html_dashboard", ExportOptions.generate_html_dashboard)
    )
    generate_summary_sheet = bool(getattr(options, "generate_summary_sheet", ExportOptions.generate_summary_sheet))
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
        hide_ok_results=bool(getattr(options, "hide_ok_results", ExportOptions.hide_ok_results)),
        generate_summary_sheet=generate_summary_sheet,
        generate_html_dashboard=generate_html_dashboard,
        include_industrial_context=bool(
            getattr(options, "include_industrial_context", ExportOptions.include_industrial_context)
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
        group_analysis_level=group_analysis_level,
        group_analysis_scope=group_analysis_scope,
        dashboard_visual_settings=normalize_dashboard_visual_settings(
            getattr(options, "dashboard_visual_settings", ExportOptions.dashboard_visual_settings)
        ),
    )


def validate_grouping_df(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Validate optional grouping assignments DataFrame.

    Args:
        df: Optional DataFrame of grouping assignments. Non-empty frames must
            include ``GROUP`` plus ``REPORT_ID``.

    Returns:
        pd.DataFrame | None: ``None`` when input is ``None``; the original empty
        DataFrame when input is empty; otherwise a copy of the validated
        non-empty frame.

    Raises:
        ValueError: If ``df`` is not a DataFrame or if required grouping columns
        are missing.

    Invariants:
        Non-empty valid inputs are returned as a copy to avoid downstream
        side-effects from caller-owned DataFrame mutation.
    """

    if df is None:
        return None

    if not isinstance(df, pd.DataFrame):
        raise ValueError("Grouping assignments must be provided as a pandas DataFrame.")

    if df.empty:
        return df

    if "GROUP" not in df.columns:
        raise ValueError("Grouping DataFrame must include a GROUP column.")

    if "REPORT_ID" not in df.columns:
        raise ValueError("Grouping DataFrame must include REPORT_ID.")

    return df.copy()


def _normalize_analytics_source_kind(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Analytics source kind must be provided as a string.")
    source_kind = value.strip().lower()
    if source_kind not in _ANALYTICS_SOURCE_KINDS:
        raise ValueError(f"Unsupported analytics source kind: {value}")
    return source_kind


def _normalize_dashboard_detail_mode(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Dashboard rendering mode must be provided as a string.")
    detail_mode = value.strip().lower()
    if detail_mode not in _DASHBOARD_DETAIL_MODES:
        raise ValueError(f"Unsupported dashboard rendering mode: {value}")
    return detail_mode


def _normalize_dashboard_interactivity_options(value: object) -> DashboardInteractivityOptions:
    if value is not None and not isinstance(value, (DashboardInteractivityOptions, dict)):
        raise ValueError(
            "Dashboard interactivity options must be provided as a "
            "DashboardInteractivityOptions instance or mapping."
        )
    return normalize_dashboard_interactivity_options(value, strict=True)


def _normalize_optional_output_path(
    value: object,
    *,
    suffix: str,
    field_name: str,
    required: bool,
) -> str:
    text = _normalize_optional_text(value, field_name=field_name)
    if not text:
        if required:
            raise ValueError(f"A {field_name} is required.")
        return ""
    path = Path(text)
    if not path.suffix:
        path = path.with_suffix(suffix)
    elif path.suffix.lower() != suffix:
        raise ValueError(f"{field_name.capitalize()} must use the {suffix} extension.")
    return str(path)


def _normalize_optional_text(value: object, *, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name.capitalize()} must be provided as a string when set.")
    return value.strip()


def _normalize_metric_selection(
    value: tuple[ProductionMetricSelection, ...] | list[ProductionMetricSelection] | None,
) -> tuple[ProductionMetricSelection, ...]:
    if not value:
        return ()
    metrics = tuple(value)
    if any(not isinstance(metric, ProductionMetricSelection) for metric in metrics):
        raise ValueError("Analytics metric selection must contain ProductionMetricSelection entries.")
    return metrics


def _normalize_filter_state(value: ProductionFilterState | None) -> ProductionFilterState:
    if value is None:
        return ProductionFilterState()
    if not isinstance(value, ProductionFilterState):
        raise ValueError("Analytics filter state must be a ProductionFilterState instance.")
    return value


def _normalize_aggregation_state(value: ProductionAggregationState | None) -> ProductionAggregationState:
    if value is None:
        return ProductionAggregationState()
    if not isinstance(value, ProductionAggregationState):
        raise ValueError("Analytics aggregation state must be a ProductionAggregationState instance.")
    return value


def _normalize_cohort_state(value: ReferenceCohortState | None) -> ReferenceCohortState:
    if value is None:
        return ReferenceCohortState()
    if not isinstance(value, ReferenceCohortState):
        raise ValueError("Analytics cohort state must be a ReferenceCohortState instance.")
    return value


def _normalize_chart_selection(value: ProductionChartSelection | None) -> ProductionChartSelection:
    if value is None:
        return ProductionChartSelection()
    if not isinstance(value, ProductionChartSelection):
        raise ValueError("Analytics chart selection must be a ProductionChartSelection instance.")
    return value


def _normalize_sheet_name(value: object) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        return text or None
    raise ValueError("Excel sheet selection must be a string, integer, or None.")


def _normalize_optional_identifier(value: object, field_name: str) -> str | None:
    text = _normalize_optional_text(value, field_name=field_name)
    if not text:
        return None
    require_analytics_identifier(field_name, text)
    return text


def _normalize_tabular_load_result(value: TabularAnalyticsLoadResult | None) -> TabularAnalyticsLoadResult | None:
    if value is None:
        return None
    if not isinstance(value, TabularAnalyticsLoadResult):
        raise ValueError("Loaded CSV/Excel data must be a TabularAnalyticsLoadResult instance.")
    return value


def _normalize_filter_columns(value: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not value:
        return ()
    columns: list[str] = []
    for column in value:
        normalized = _normalize_optional_identifier(column, "tabular filter column")
        if normalized:
            columns.append(normalized)
    return tuple(columns)


def _normalize_filter_keys(
    value: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None,
) -> tuple[tuple[str, ...], ...]:
    if not value:
        return ()
    normalized_keys: list[tuple[str, ...]] = []
    for key in value:
        if not isinstance(key, tuple | list):
            raise ValueError("Tabular filter keys must be sequences of strings.")
        normalized_parts = tuple(str(part).strip() for part in key if str(part).strip())
        if normalized_parts:
            normalized_keys.append(normalized_parts)
    return tuple(normalized_keys)


def _normalize_column_filters(
    value: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None,
) -> tuple[TabularColumnFilter, ...]:
    if not value:
        return ()
    filters = tuple(value)
    if any(not isinstance(item, TabularColumnFilter) for item in filters):
        raise ValueError("Tabular column filters must contain TabularColumnFilter entries.")
    return filters
