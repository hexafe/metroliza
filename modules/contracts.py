"""Immutable request/config contracts plus validation and normalization entry points.

This module defines frozen dataclasses used to pass parse and export configuration
through the application. It also provides validator helpers that enforce required
fields, normalize supported option values, and return validated request objects.
"""

from dataclasses import dataclass
from pathlib import Path
import pandas as pd


@dataclass(frozen=True)
class ParseRequest:
    """Request payload for parsing a source directory into a target database.

    Attributes:
        source_directory: Input folder containing source files to parse.
        db_file: Output database path where parsed content is written.

    Usage notes:
        Pass to ``validate_parse_request`` before use so required string fields are
        checked and path validation is applied consistently.
    """

    source_directory: str
    db_file: str


@dataclass(frozen=True)
class AppPaths:
    """Filesystem paths required by export and parse workflows.

    Attributes:
        db_file: Database path; required and must be a non-empty string.
        excel_file: Optional Excel output path; when provided it must end in
            ``.xlsx``.

    Usage notes:
        ``validate_paths`` enforces required/optional path constraints but does not
        rewrite path values.
    """

    db_file: str
    excel_file: str | None = None


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
        allow_non_essential_chart_skipping: Enables dropping optional summary
            charts under bottleneck optimization.
        chart_worker_count: Worker process/thread count, minimum of ``1``.
        chart_worker_queue_size: Queue size for chart workers, minimum of ``1``.

    Usage notes:
        ``validate_export_options`` returns a normalized copy with sanitized
        casing/aliases and bounded numeric settings.
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
    allow_non_essential_chart_skipping: bool = False
    chart_worker_count: int = 2
    chart_worker_queue_size: int = 4


@dataclass(frozen=True)
class GroupingAssignment:
    """Logical grouping assignment keyed by identity or composite optional fields.

    Attributes:
        group: Required target group label.
        report_id: Optional primary identity key.
        reference: Optional composite-key component.
        fileloc: Optional composite-key component.
        filename: Optional composite-key component.
        date: Optional composite-key component.
        sample_number: Optional composite-key component.

    Usage notes:
        ``report_id`` can be used as an alternate key. If omitted, the composite
        optional fields are expected to be used together as a full alternate key.
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
    """Validate required application paths and optional Excel target constraints.

    Args:
        paths: Path bundle where ``db_file`` must be a non-empty string and
            ``excel_file`` is optional but, when provided, must be non-empty.

    Returns:
        AppPaths: The same ``paths`` instance; values are validated but not copied
        or normalized.

    Raises:
        ValueError: If required fields are missing/empty or if ``excel_file`` has
        an invalid suffix other than ``.xlsx``.

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

    return paths


def validate_parse_request(request: ParseRequest) -> ParseRequest:
    """Validate parse request inputs.

    Args:
        request: Parse request where ``source_directory`` and ``db_file`` are both
            required non-empty strings.

    Returns:
        ParseRequest: The same request instance after validation; no fields are
        copied or normalized.

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
    return request


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
        allow_non_essential_chart_skipping=bool(
            getattr(
                options,
                "allow_non_essential_chart_skipping",
                ExportOptions.allow_non_essential_chart_skipping,
            )
        ),
        chart_worker_count=worker_count,
        chart_worker_queue_size=worker_queue_size,
    )


def validate_grouping_df(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Validate optional grouping assignments DataFrame.

    Args:
        df: Optional DataFrame of grouping assignments. Non-empty frames must
            include ``GROUP`` plus either ``REPORT_ID`` or the full composite key
            columns ``REFERENCE``, ``FILELOC``, ``FILENAME``, ``DATE``, and
            ``SAMPLE_NUMBER``.

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

    has_identity = "REPORT_ID" in df.columns
    composite_key_cols = {"REFERENCE", "FILELOC", "FILENAME", "DATE", "SAMPLE_NUMBER"}
    has_composite = composite_key_cols.issubset(df.columns)

    if not (has_identity or has_composite):
        raise ValueError(
            "Grouping DataFrame must include REPORT_ID or the full composite key: "
            "REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER."
        )

    return df.copy()
