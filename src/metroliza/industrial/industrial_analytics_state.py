"""Pure state contracts for cached production analytics workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any, Literal, Mapping

from metroliza.industrial.industrial_workflow_state import parse_reference_values


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

MetricSourceKind = Literal["fixed", "dynamic"]
NumericCoercionPolicy = Literal["coerce", "strict"]
DynamicFilterOperator = Literal[
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "contains",
    "starts_with",
    "ends_with",
    "in",
    "not_in",
    "is_null",
    "is_not_null",
]
DynamicFilterValueKind = Literal["auto", "text", "numeric"]
ProductionTimeBucket = Literal["none", "hour", "day", "week", "month", "year"]
ProductionAggregationMethod = Literal[
    "mean",
    "median",
    "count",
    "sum",
    "min",
    "max",
    "std",
    "p05",
    "p95",
    "first",
    "last",
]
ReferenceCohortMode = Literal["highlight", "compare_rest", "filter_selected", "group_selected"]


FIXED_PRODUCTION_FIELDS: tuple[tuple[str, str], ...] = (
    ("source_db_alias", "Source"),
    ("source_record_key", "Source record"),
    ("process_timestamp", "Process time"),
    ("reference", "Reference"),
    ("part_number", "Part number"),
    ("part_name", "Part name"),
    ("revision", "Revision"),
    ("serial", "Serial"),
    ("batch_lot", "Batch / lot"),
    ("work_order", "Work order"),
    ("station", "Station"),
    ("line", "Line"),
    ("operator_name", "Operator"),
    ("process_status", "Process status"),
)
FIXED_PRODUCTION_FIELD_LABELS = dict(FIXED_PRODUCTION_FIELDS)
FIXED_PRODUCTION_FIELD_NAMES = frozenset(FIXED_PRODUCTION_FIELD_LABELS)
REFERENCE_COHORT_GROUP_FIELDS = frozenset({"reference_cohort", "reference_marked"})

SUPPORTED_DYNAMIC_FILTER_OPERATORS = frozenset(
    {
        "eq",
        "ne",
        "lt",
        "lte",
        "gt",
        "gte",
        "contains",
        "starts_with",
        "ends_with",
        "in",
        "not_in",
        "is_null",
        "is_not_null",
    }
)
SUPPORTED_DYNAMIC_VALUE_KINDS = frozenset({"auto", "text", "numeric"})
SUPPORTED_TIME_BUCKETS = frozenset({"none", "hour", "day", "week", "month", "year"})
SUPPORTED_AGGREGATION_METHODS = frozenset(
    {"mean", "median", "count", "sum", "min", "max", "std", "p05", "p95", "first", "last"}
)
SUPPORTED_COHORT_MODES = frozenset(
    {"highlight", "compare_rest", "filter_selected", "group_selected"}
)


def require_identifier(field_name: str, value: str) -> None:
    """Validate a SQLite-safe simple identifier used by analytics SQL builders."""

    if not _IDENTIFIER_RE.fullmatch(str(value or "")):
        raise ValueError(
            f"Invalid {field_name}: '{value}'. Use letters, numbers, and underscores only, "
            "starting with a letter or underscore."
        )


def _normalize_text_values(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


def _normalize_int_values(values: tuple[int, ...] | list[int] | None) -> tuple[int, ...]:
    if not values:
        return ()
    normalized: list[int] = []
    seen: set[int] = set()
    for value in values:
        parsed = int(value)
        if parsed in seen:
            continue
        seen.add(parsed)
        normalized.append(parsed)
    return tuple(normalized)


def _normalize_mapping_values(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    return {str(key): nested for key, nested in value.items()}


def _optional_finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def production_field_label(field_name: str) -> str:
    """Return a user-facing label for a fixed or dynamic production field."""

    if field_name in FIXED_PRODUCTION_FIELD_LABELS:
        return FIXED_PRODUCTION_FIELD_LABELS[field_name]
    return str(field_name or "").replace("_", " ").strip().title()


@dataclass(frozen=True)
class DynamicFieldFilter:
    """Filter rule for values stored in industrial_record_values."""

    field_name: str
    operator: DynamicFilterOperator = "eq"
    value: Any = None
    values: tuple[Any, ...] = ()
    value_kind: DynamicFilterValueKind = "auto"

    def __post_init__(self) -> None:
        field_name = str(self.field_name or "").strip()
        require_identifier("dynamic field", field_name)
        operator = str(self.operator or "eq").strip().lower()
        if operator not in SUPPORTED_DYNAMIC_FILTER_OPERATORS:
            raise ValueError(f"Unsupported dynamic filter operator: {self.operator}")
        value_kind = str(self.value_kind or "auto").strip().lower()
        if value_kind not in SUPPORTED_DYNAMIC_VALUE_KINDS:
            raise ValueError(f"Unsupported dynamic filter value kind: {self.value_kind}")

        values = self.values
        if operator in {"in", "not_in"} and not values and self.value is not None:
            values = self.value if isinstance(self.value, tuple | list) else (self.value,)
        if operator in {"in", "not_in"} and not values:
            raise ValueError(f"{operator} dynamic filters require at least one value")
        if operator not in {"is_null", "is_not_null", "in", "not_in"} and self.value is None:
            raise ValueError(f"{operator} dynamic filters require a value")

        object.__setattr__(self, "field_name", field_name)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "values", tuple(values or ()))
        object.__setattr__(self, "value_kind", value_kind)


@dataclass(frozen=True)
class ProductionFilterState:
    """User-selected cached production data filters."""

    source_profile_ids: tuple[int, ...] = ()
    source_db_aliases: tuple[str, ...] = ()
    time_start: str | None = None
    time_end: str | None = None
    references: tuple[str, ...] = ()
    part_numbers: tuple[str, ...] = ()
    part_names: tuple[str, ...] = ()
    revisions: tuple[str, ...] = ()
    serials: tuple[str, ...] = ()
    batch_lots: tuple[str, ...] = ()
    work_orders: tuple[str, ...] = ()
    stations: tuple[str, ...] = ()
    lines: tuple[str, ...] = ()
    operators: tuple[str, ...] = ()
    process_statuses: tuple[str, ...] = ()
    dynamic_filters: tuple[DynamicFieldFilter, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_profile_ids", _normalize_int_values(self.source_profile_ids))
        for field_name in (
            "source_db_aliases",
            "references",
            "part_numbers",
            "part_names",
            "revisions",
            "serials",
            "batch_lots",
            "work_orders",
            "stations",
            "lines",
            "operators",
            "process_statuses",
        ):
            object.__setattr__(self, field_name, _normalize_text_values(getattr(self, field_name)))
        object.__setattr__(self, "dynamic_filters", tuple(self.dynamic_filters or ()))

    @property
    def is_applied(self) -> bool:
        return any(
            (
                self.source_profile_ids,
                self.source_db_aliases,
                self.time_start,
                self.time_end,
                self.references,
                self.part_numbers,
                self.part_names,
                self.revisions,
                self.serials,
                self.batch_lots,
                self.work_orders,
                self.stations,
                self.lines,
                self.operators,
                self.process_statuses,
                self.dynamic_filters,
            )
        )

    def summary(self) -> str:
        if not self.is_applied:
            return "Filters: not applied"
        parts = []
        for label, values in (
            ("Source", self.source_db_aliases),
            ("Reference", self.references),
            ("Part", self.part_numbers),
            ("Revision", self.revisions),
            ("Serial", self.serials),
            ("Batch", self.batch_lots),
            ("Station", self.stations),
            ("Line", self.lines),
            ("Operator", self.operators),
            ("Status", self.process_statuses),
        ):
            if values:
                parts.append(f"{label}: {values[0]}" if len(values) == 1 else f"{label}: {len(values)}")
        if self.source_profile_ids:
            parts.append(f"Source ids: {len(self.source_profile_ids)}")
        if self.time_start or self.time_end:
            parts.append(f"Time: {self.time_start or 'start'} to {self.time_end or 'end'}")
        if self.dynamic_filters:
            parts.append(f"Dynamic: {len(self.dynamic_filters)}")
        return "Filters: " + "; ".join(parts)


@dataclass(frozen=True)
class ProductionMetricSelection:
    """One numeric production metric selected for analysis."""

    field_name: str
    display_label: str = ""
    source_kind: MetricSourceKind = "dynamic"
    numeric_coercion: NumericCoercionPolicy = "coerce"
    limits_source: str = ""
    lsl: float | None = None
    usl: float | None = None

    def __post_init__(self) -> None:
        field_name = str(self.field_name or "").strip()
        require_identifier("metric field", field_name)
        source_kind = str(self.source_kind or "dynamic").strip().lower()
        if source_kind not in {"fixed", "dynamic"}:
            raise ValueError(f"Unsupported metric source kind: {self.source_kind}")
        numeric_coercion = str(self.numeric_coercion or "coerce").strip().lower()
        if numeric_coercion not in {"coerce", "strict"}:
            raise ValueError(f"Unsupported numeric coercion policy: {self.numeric_coercion}")
        display_label = str(self.display_label or "").strip() or production_field_label(field_name)
        object.__setattr__(self, "field_name", field_name)
        object.__setattr__(self, "display_label", display_label)
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "numeric_coercion", numeric_coercion)
        object.__setattr__(self, "limits_source", str(self.limits_source or "").strip())
        object.__setattr__(self, "lsl", _optional_finite_float(self.lsl))
        object.__setattr__(self, "usl", _optional_finite_float(self.usl))


@dataclass(frozen=True)
class ProductionAggregationState:
    """Time-bucket and aggregation choices for selected production metrics."""

    time_bucket: ProductionTimeBucket = "none"
    aggregation_methods: tuple[ProductionAggregationMethod, ...] = ("mean",)
    group_fields: tuple[str, ...] = ()
    include_raw_row_count: bool = True

    def __post_init__(self) -> None:
        time_bucket = str(self.time_bucket or "none").strip().lower()
        if time_bucket not in SUPPORTED_TIME_BUCKETS:
            raise ValueError(f"Unsupported production time bucket: {self.time_bucket}")
        methods = tuple(
            dict.fromkeys(str(method or "").strip().lower() for method in self.aggregation_methods)
        )
        if not methods:
            raise ValueError("Select at least one aggregation method.")
        invalid_methods = [method for method in methods if method not in SUPPORTED_AGGREGATION_METHODS]
        if invalid_methods:
            raise ValueError(f"Unsupported aggregation method(s): {', '.join(invalid_methods)}")
        group_fields = tuple(dict.fromkeys(str(field or "").strip() for field in self.group_fields))
        for field_name in group_fields:
            require_identifier("group field", field_name)
        object.__setattr__(self, "time_bucket", time_bucket)
        object.__setattr__(self, "aggregation_methods", methods)
        object.__setattr__(self, "group_fields", group_fields)
        object.__setattr__(self, "include_raw_row_count", bool(self.include_raw_row_count))

    @property
    def is_aggregated(self) -> bool:
        return self.time_bucket != "none" or bool(self.group_fields)


@dataclass(frozen=True)
class ReferenceCohortState:
    """Pasted-reference cohort behavior for filtering, highlighting, and grouping."""

    references: tuple[str, ...] = ()
    label: str = "Selected references"
    color: str = "#d62728"
    style_key: str = "selected"
    mode: ReferenceCohortMode = "highlight"

    def __post_init__(self) -> None:
        mode = str(self.mode or "highlight").strip().lower()
        if mode not in SUPPORTED_COHORT_MODES:
            raise ValueError(f"Unsupported reference cohort mode: {self.mode}")
        label = str(self.label or "").strip() or "Selected references"
        color = str(self.color or "").strip() or "#d62728"
        object.__setattr__(self, "references", _normalize_text_values(self.references))
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "color", color)
        object.__setattr__(self, "style_key", str(self.style_key or "selected").strip())
        object.__setattr__(self, "mode", mode)

    @classmethod
    def from_text(
        cls,
        value: str,
        *,
        label: str = "Selected references",
        mode: ReferenceCohortMode = "highlight",
    ) -> "ReferenceCohortState":
        return cls(references=parse_reference_values(value), label=label, mode=mode)

    @property
    def is_applied(self) -> bool:
        return bool(self.references)

    def summary(self) -> str:
        if not self.references:
            return "Reference cohort: not applied"
        return f"Reference cohort: {len(self.references)} selected ({self.mode.replace('_', ' ')})"


@dataclass(frozen=True)
class ProductionChartSelection:
    """Enabled production analytics chart families."""

    time_series: bool = True
    histogram: bool = True
    violin: bool = False
    box: bool = False
    groupstats: bool = False

    @property
    def has_any(self) -> bool:
        return any((self.time_series, self.histogram, self.violin, self.box, self.groupstats))

    def enabled_chart_types(self) -> tuple[str, ...]:
        chart_types = []
        for field_name in ("time_series", "histogram", "violin", "box", "groupstats"):
            if bool(getattr(self, field_name)):
                chart_types.append(field_name)
        return tuple(chart_types)


@dataclass(frozen=True)
class ProductionAnalyticsRequest:
    """Complete production analytics request independent of Qt widgets."""

    db_file: str | None = None
    output_path: str | None = None
    filters: ProductionFilterState = field(default_factory=ProductionFilterState)
    metrics: tuple[ProductionMetricSelection, ...] = ()
    aggregation: ProductionAggregationState = field(default_factory=ProductionAggregationState)
    reference_cohort: ReferenceCohortState = field(default_factory=ReferenceCohortState)
    charts: ProductionChartSelection = field(default_factory=ProductionChartSelection)
    settings: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_file", str(self.db_file or "").strip() or None)
        object.__setattr__(self, "output_path", str(self.output_path or "").strip() or None)
        object.__setattr__(self, "metrics", tuple(self.metrics or ()))
        object.__setattr__(self, "settings", _normalize_mapping_values(self.settings))


@dataclass(frozen=True)
class ProductionAnalyticsReadiness:
    """Validation result used by dialogs and workers before running analytics."""

    ok: bool
    messages: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        if self.ok:
            return "Ready to create production analytics."
        return self.messages[0] if self.messages else "Production analytics is not ready."


def validate_production_analytics_request(
    request: ProductionAnalyticsRequest,
    *,
    require_output_path: bool = True,
) -> ProductionAnalyticsReadiness:
    """Return readiness messages without raising for normal missing user selections."""

    messages: list[str] = []
    if not request.db_file:
        messages.append("Select a Metroliza report database with cached production data.")
    if not request.metrics:
        messages.append("Select at least one production metric.")
    if not request.charts.has_any:
        messages.append("Select at least one chart or analysis output.")
    if require_output_path and not request.output_path:
        messages.append("Select an output dashboard path.")
    return ProductionAnalyticsReadiness(ok=not messages, messages=tuple(messages))


__all__ = [
    "DynamicFieldFilter",
    "ProductionAggregationState",
    "ProductionAnalyticsReadiness",
    "ProductionAnalyticsRequest",
    "ProductionChartSelection",
    "ProductionFilterState",
    "ProductionMetricSelection",
    "ReferenceCohortState",
    "parse_reference_values",
    "production_field_label",
    "require_identifier",
    "validate_production_analytics_request",
]
