"""Typed public boundary for industrial analytics dashboard manifests."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, NotRequired, TypedDict, cast


DASHBOARD_SCHEMA = "metroliza.production_analytics_dashboard.v1"


class DashboardSummary(TypedDict):
    """Stable summary fields emitted by the industrial dashboard builder."""

    source_rows: int
    metric_count: int
    chart_count: int
    generated_at: NotRequired[str]
    rows: NotRequired[int]
    aggregate_rows: NotRequired[int]
    time_bucket: NotRequired[str]
    aggregation_methods: NotRequired[list[str]]
    group_fields: NotRequired[list[str]]
    reference_cohort_count: NotRequired[int]
    reference_cohort_mode: NotRequired[str]
    dashboard_title: NotRequired[str]
    dashboard_subtitle: NotRequired[str]
    dashboard_context: NotRequired[dict[str, Any]]
    groupstats_metric_count: NotRequired[int]
    available_optimization_options: NotRequired[list[str]]
    dashboard_interactivity: NotRequired[dict[str, Any]]
    static_population_layer: NotRequired[dict[str, Any]]
    static_group_layers: NotRequired[dict[str, Any]]
    plotly_budget_status: NotRequired[str]
    plotly_budget_reason: NotRequired[str]
    plotly_budget: NotRequired[dict[str, Any]]
    plotly_runtime_status: NotRequired[str]


class DashboardMetric(TypedDict):
    """Metric identity serialized in a dashboard manifest."""

    field_name: str
    display_label: str
    source_kind: str


class ProductionDashboardManifest(TypedDict):
    """Public mutable manifest consumed by the industrial dashboard writer."""

    schema: str
    summary: DashboardSummary
    metrics: list[DashboardMetric]
    charts: list[dict[str, Any]]
    groupstats: dict[str, Any]
    diagnostics: list[dict[str, Any]]


class DashboardPlotlyBudget(TypedDict):
    """Plotly budget details returned by a dashboard write."""

    status: str
    reason: str
    spec_count_budget: int | None
    serialized_json_bytes_budget: int | None


class ProductionDashboardWriteResult(TypedDict):
    """Public mutable result returned after a dashboard write."""

    html_dashboard_path: str
    html_dashboard_assets_path: str
    html_dashboard_chart_count: int
    html_dashboard_interactive_chart_count: int
    html_dashboard_plotly_spec_count: int
    html_dashboard_embedded_plotly_spec_count: int
    html_dashboard_plotly_serialized_json_bytes: int
    html_dashboard_embedded_plotly_serialized_json_bytes: int
    html_dashboard_html_bytes: int
    html_dashboard_plotly_budget: DashboardPlotlyBudget
    html_dashboard_plotly_runtime_status: str
    html_dashboard_static_population_layer: dict[str, Any]
    html_dashboard_timings_s: dict[str, float]


REQUIRED_MANIFEST_KEYS = frozenset(
    {"schema", "summary", "metrics", "charts", "groupstats", "diagnostics"}
)
REQUIRED_SUMMARY_KEYS = frozenset({"source_rows", "metric_count", "chart_count"})
REQUIRED_WRITE_RESULT_KEYS = frozenset(ProductionDashboardWriteResult.__required_keys__)


def validate_dashboard_manifest(manifest: object) -> ProductionDashboardManifest:
    """Validate the public manifest shape without normalizing or mutating it."""

    manifest_dict = _require_dictionary(
        manifest,
        message="Dashboard manifest must be a dictionary.",
    )
    _raise_for_missing_keys(manifest_dict, REQUIRED_MANIFEST_KEYS, subject="Dashboard manifest")
    if manifest_dict["schema"] != DASHBOARD_SCHEMA:
        raise ValueError(
            "Unsupported dashboard manifest schema: "
            f"{manifest_dict['schema']!r}; expected {DASHBOARD_SCHEMA!r}."
        )
    _validate_manifest_summary(manifest_dict["summary"])
    for key in ("metrics", "charts", "diagnostics"):
        _require_dictionary_list(manifest_dict[key], field_name=f"Dashboard manifest {key!r}")
    _require_dictionary(
        manifest_dict["groupstats"],
        message="Dashboard manifest 'groupstats' must be a dictionary.",
    )
    _validate_manifest_metrics(manifest_dict["metrics"])
    return cast(ProductionDashboardManifest, manifest_dict)


def copy_dashboard_manifest_for_render(
    manifest: object,
    *,
    private_optimization_keys: tuple[str, ...] = (),
) -> ProductionDashboardManifest:
    """Copy render-mutated fields while retaining private source objects by identity."""

    validated = validate_dashboard_manifest(manifest)
    manifest_copy: dict[str, Any] = dict(validated)
    manifest_copy["summary"] = dict(validated["summary"])
    copied_charts: list[Any] = []
    for chart in validated["charts"]:
        chart_copy = dict(chart)
        plotly_spec = chart.get("plotly_spec")
        if isinstance(plotly_spec, dict):
            chart_copy["plotly_spec"] = _clone_jsonable(plotly_spec)
        optimization_options = chart.get("optimization_options")
        if isinstance(optimization_options, list):
            chart_copy["optimization_options"] = _clone_optimization_options(
                optimization_options,
                private_keys=private_optimization_keys,
            )
        copied_charts.append(chart_copy)
    manifest_copy["charts"] = copied_charts
    return cast(ProductionDashboardManifest, manifest_copy)


def build_dashboard_write_result(
    *,
    html_dashboard_path: str,
    html_dashboard_assets_path: str,
    chart_count: int,
    interactive_chart_count: int,
    plotly_spec_count: int,
    embedded_plotly_spec_count: int,
    plotly_serialized_json_bytes: int,
    embedded_plotly_serialized_json_bytes: int,
    html_bytes: int,
    plotly_budget_status: str,
    plotly_budget_reason: str,
    plotly_spec_count_budget: int | None,
    plotly_serialized_json_bytes_budget: int | None,
    plotly_runtime_status: str,
    static_population_layer: dict[str, Any],
    timings_s: Mapping[str, float],
) -> ProductionDashboardWriteResult:
    """Build the legacy dictionary result with its exact public key layout."""

    result: ProductionDashboardWriteResult = {
        "html_dashboard_path": html_dashboard_path,
        "html_dashboard_assets_path": html_dashboard_assets_path,
        "html_dashboard_chart_count": int(chart_count),
        "html_dashboard_interactive_chart_count": int(interactive_chart_count),
        "html_dashboard_plotly_spec_count": int(plotly_spec_count),
        "html_dashboard_embedded_plotly_spec_count": int(embedded_plotly_spec_count),
        "html_dashboard_plotly_serialized_json_bytes": int(plotly_serialized_json_bytes),
        "html_dashboard_embedded_plotly_serialized_json_bytes": int(
            embedded_plotly_serialized_json_bytes
        ),
        "html_dashboard_html_bytes": int(html_bytes),
        "html_dashboard_plotly_budget": {
            "status": plotly_budget_status,
            "reason": plotly_budget_reason,
            "spec_count_budget": plotly_spec_count_budget,
            "serialized_json_bytes_budget": plotly_serialized_json_bytes_budget,
        },
        "html_dashboard_plotly_runtime_status": plotly_runtime_status,
        "html_dashboard_static_population_layer": static_population_layer,
        "html_dashboard_timings_s": {key: float(value) for key, value in timings_s.items()},
    }
    return validate_dashboard_write_result(result)


def validate_dashboard_write_result(result: object) -> ProductionDashboardWriteResult:
    """Validate a public dashboard write result without changing object identity."""

    result_dict = _require_dictionary(
        result,
        message="Dashboard write result must be a dictionary.",
    )
    _raise_for_missing_keys(
        result_dict,
        REQUIRED_WRITE_RESULT_KEYS,
        subject="Dashboard write result",
    )
    _validate_write_result_scalars(result_dict)
    _require_dictionary(
        result_dict["html_dashboard_static_population_layer"],
        message=(
            "Dashboard write result 'html_dashboard_static_population_layer' "
            "must be a dictionary."
        ),
    )
    _validate_plotly_budget(result_dict["html_dashboard_plotly_budget"])
    _validate_write_result_timings(result_dict["html_dashboard_timings_s"])
    return cast(ProductionDashboardWriteResult, result_dict)


def _validate_write_result_scalars(result: Mapping[str, Any]) -> None:
    for key in ("html_dashboard_path", "html_dashboard_assets_path"):
        if not isinstance(result[key], str):
            raise ValueError(f"Dashboard write result {key!r} must be a string.")
    for key in (
        "html_dashboard_chart_count",
        "html_dashboard_interactive_chart_count",
        "html_dashboard_plotly_spec_count",
        "html_dashboard_embedded_plotly_spec_count",
        "html_dashboard_plotly_serialized_json_bytes",
        "html_dashboard_embedded_plotly_serialized_json_bytes",
        "html_dashboard_html_bytes",
    ):
        _require_int(result[key], field_name=f"Dashboard write result {key!r}")
    if not isinstance(result["html_dashboard_plotly_runtime_status"], str):
        raise ValueError(
            "Dashboard write result 'html_dashboard_plotly_runtime_status' must be a string."
        )


def _validate_plotly_budget(value: object) -> None:
    budget = _require_dictionary(
        value,
        message="Dashboard write result Plotly budget must be a dictionary.",
    )
    _raise_for_missing_keys(
        budget,
        {"status", "reason", "spec_count_budget", "serialized_json_bytes_budget"},
        subject="Dashboard write result Plotly budget",
    )
    if not isinstance(budget["status"], str) or not isinstance(budget["reason"], str):
        raise ValueError("Dashboard write result Plotly budget status and reason must be strings.")
    for key in ("spec_count_budget", "serialized_json_bytes_budget"):
        value = budget[key]
        if value is not None:
            _require_int(value, field_name=f"Dashboard write result Plotly budget {key!r}")


def _validate_write_result_timings(value: object) -> None:
    timings = value
    if not isinstance(timings, dict) or any(
        not isinstance(key, str) or not isinstance(value, (int, float)) or isinstance(value, bool)
        for key, value in timings.items()
    ):
        raise ValueError("Dashboard write result timings must map strings to numbers.")


def copy_dashboard_write_result(result: object) -> ProductionDashboardWriteResult:
    """Return an independent JSON-compatible copy of a validated write result."""

    return cast(
        ProductionDashboardWriteResult,
        _clone_jsonable(validate_dashboard_write_result(result)),
    )


def _validate_manifest_summary(value: object) -> None:
    summary = _require_dictionary(
        value,
        message="Dashboard manifest summary must be a dictionary.",
    )
    _raise_for_missing_keys(summary, REQUIRED_SUMMARY_KEYS, subject="Dashboard manifest summary")
    for key in REQUIRED_SUMMARY_KEYS:
        _require_int(summary[key], field_name=f"Dashboard manifest summary {key!r}")


def _validate_manifest_metrics(value: object) -> None:
    metrics = _require_dictionary_list(value, field_name="Dashboard manifest 'metrics'")
    for index, metric in enumerate(metrics):
        _raise_for_missing_keys(
            metric,
            {"field_name", "display_label", "source_kind"},
            subject=f"Dashboard manifest metric {index}",
        )
        if any(
            not isinstance(metric[key], str)
            for key in ("field_name", "display_label", "source_kind")
        ):
            raise ValueError(f"Dashboard manifest metric {index} fields must be strings.")


def _require_dictionary(value: object, *, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(message)
    return value


def _require_dictionary_list(value: object, *, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    if any(not isinstance(entry, dict) for entry in value):
        raise ValueError(f"{field_name} entries must be dictionaries.")
    return cast(list[dict[str, Any]], value)


def _raise_for_missing_keys(
    value: Mapping[str, Any],
    required_keys: set[str] | frozenset[str],
    *,
    subject: str,
) -> None:
    missing = sorted(required_keys.difference(value))
    if missing:
        raise ValueError(f"{subject} is missing required keys: {', '.join(missing)}.")


def _require_int(value: object, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")


def _clone_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _clone_optimization_options(
    options: list[Any],
    *,
    private_keys: tuple[str, ...],
) -> list[Any]:
    cloned: list[Any] = []
    for option in options:
        if not isinstance(option, dict):
            cloned.append(_clone_jsonable(option))
            continue
        private_values = {
            key: option.get(key)
            for key in private_keys
            if option.get(key) is not None
        }
        public_option = {key: value for key, value in option.items() if key not in private_keys}
        cloned_option = _clone_jsonable(public_option)
        cloned_option.update(private_values)
        cloned.append(cloned_option)
    return cloned


__all__ = [
    "DASHBOARD_SCHEMA",
    "DashboardMetric",
    "DashboardPlotlyBudget",
    "DashboardSummary",
    "ProductionDashboardManifest",
    "ProductionDashboardWriteResult",
    "REQUIRED_MANIFEST_KEYS",
    "REQUIRED_SUMMARY_KEYS",
    "REQUIRED_WRITE_RESULT_KEYS",
    "build_dashboard_write_result",
    "copy_dashboard_manifest_for_render",
    "copy_dashboard_write_result",
    "validate_dashboard_manifest",
    "validate_dashboard_write_result",
]
