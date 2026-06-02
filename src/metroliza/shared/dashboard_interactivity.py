"""Shared dashboard interactivity option contracts and formatting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DASHBOARD_INTERACTIVITY_MODES = frozenset({"auto", "sampled", "static", "full"})
DASHBOARD_POPULATION_LAYER_MODES = frozenset({"auto", "interactive", "static"})
DASHBOARD_INTERACTIVITY_DEFAULT_SAMPLE_SIZE = 50_000
DASHBOARD_INTERACTIVITY_MIN_SAMPLE_SIZE = 5_000
DASHBOARD_INTERACTIVITY_MAX_SAMPLE_SIZE = 200_000

DASHBOARD_INTERACTIVITY_LABELS = {
    "auto": "Auto",
    "sampled": "Interactive random sample",
    "static": "Snapshots only",
    "full": "All rows",
}
DASHBOARD_POPULATION_LAYER_LABELS = {
    "auto": "Auto",
    "interactive": "Interactive points",
    "static": "Static image",
}


@dataclass(frozen=True)
class DashboardInteractivityOptions:
    """Normalized dashboard interactivity strategy for large Plotly datasets."""

    mode: str = "auto"
    sample_size: int = DASHBOARD_INTERACTIVITY_DEFAULT_SAMPLE_SIZE
    population_layer_mode: str = "auto"


def normalize_dashboard_interactivity_options(
    value: object,
    *,
    default_mode: str = "auto",
    default_sample_size: int = DASHBOARD_INTERACTIVITY_DEFAULT_SAMPLE_SIZE,
    default_population_layer_mode: str = "auto",
    strict: bool = True,
    min_sample_size: int = DASHBOARD_INTERACTIVITY_MIN_SAMPLE_SIZE,
    max_sample_size: int | None = DASHBOARD_INTERACTIVITY_MAX_SAMPLE_SIZE,
) -> DashboardInteractivityOptions:
    """Normalize interactivity options, optionally raising on invalid user input."""

    mode = _normalize_mode(
        _raw_option(value, "mode", "mode"),
        default=default_mode,
        allowed=DASHBOARD_INTERACTIVITY_MODES,
        field_name="dashboard interactivity mode",
        strict=strict,
    )
    population_layer_mode = _normalize_mode(
        _raw_option(value, "population_layer_mode", "populationLayerMode"),
        default=default_population_layer_mode,
        allowed=DASHBOARD_POPULATION_LAYER_MODES,
        field_name="dashboard POPULATION layer mode",
        strict=strict,
    )
    sample_size = _normalize_sample_size(
        _raw_option(value, "sample_size", "sampleSize"),
        default=default_sample_size,
        strict=strict,
        min_sample_size=min_sample_size,
        max_sample_size=max_sample_size,
    )
    return DashboardInteractivityOptions(
        mode=mode,
        sample_size=sample_size,
        population_layer_mode=population_layer_mode,
    )


def normalize_dashboard_interactivity_mapping(
    value: object,
    *,
    default_mode: str = "auto",
    default_sample_size: int = DASHBOARD_INTERACTIVITY_DEFAULT_SAMPLE_SIZE,
    default_population_layer_mode: str = "auto",
    strict: bool = False,
    min_sample_size: int = 1,
    max_sample_size: int | None = None,
) -> dict[str, int | str]:
    """Return dashboard interactivity options as the dict shape used by renderers."""

    options = normalize_dashboard_interactivity_options(
        value,
        default_mode=default_mode,
        default_sample_size=default_sample_size,
        default_population_layer_mode=default_population_layer_mode,
        strict=strict,
        min_sample_size=min_sample_size,
        max_sample_size=max_sample_size,
    )
    return {
        "mode": options.mode,
        "sample_size": options.sample_size,
        "population_layer_mode": options.population_layer_mode,
    }


def summarize_dashboard_interactivity_options(
    value: object,
    *,
    default_sample_size: int = DASHBOARD_INTERACTIVITY_DEFAULT_SAMPLE_SIZE,
    source_row_count: int | None = None,
    dashboard_row_count: int | None = None,
) -> str:
    """Return the concise user-facing summary for dashboard interactivity settings."""

    detail = summarize_dashboard_sampling_options(
        value,
        default_sample_size=default_sample_size,
        source_row_count=source_row_count,
        dashboard_row_count=dashboard_row_count,
    )
    population_label = summarize_dashboard_population_layer_options(value)
    return f"{detail}; POPULATION layer {population_label.casefold()}"


def summarize_dashboard_sampling_options(
    value: object,
    *,
    default_sample_size: int = DASHBOARD_INTERACTIVITY_DEFAULT_SAMPLE_SIZE,
    source_row_count: int | None = None,
    dashboard_row_count: int | None = None,
) -> str:
    """Return the concise user-facing summary for Plotly interactivity/sample settings."""

    options = normalize_dashboard_interactivity_options(
        value,
        strict=False,
        min_sample_size=1,
        max_sample_size=None,
        default_sample_size=default_sample_size,
    )
    label = DASHBOARD_INTERACTIVITY_LABELS.get(
        options.mode,
        options.mode.replace("_", " ").strip().title() or "Auto",
    )
    if options.mode in {"auto", "sampled"}:
        if (
            source_row_count is not None
            and dashboard_row_count is not None
            and int(source_row_count) <= options.sample_size
            and int(dashboard_row_count) >= int(source_row_count)
        ):
            detail = f"{label}, all {int(source_row_count):,} rows rendered"
        else:
            detail = f"{label}, {options.sample_size:,} interactive random sample limit"
    else:
        detail = label
    return detail


def summarize_dashboard_population_layer_options(value: object) -> str:
    """Return the concise user-facing summary for the POPULATION layer render setting."""

    options = normalize_dashboard_interactivity_options(
        value,
        strict=False,
        min_sample_size=1,
        max_sample_size=None,
    )
    return DASHBOARD_POPULATION_LAYER_LABELS.get(
        options.population_layer_mode,
        options.population_layer_mode.replace("_", " ").strip().title() or "Auto",
    )


def _raw_option(value: object, snake_name: str, camel_name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, DashboardInteractivityOptions):
        return getattr(value, snake_name)
    if isinstance(value, dict):
        return value.get(snake_name, value.get(camel_name))
    return getattr(value, snake_name, getattr(value, camel_name, None))


def _normalize_mode(
    value: object,
    *,
    default: str,
    allowed: frozenset[str],
    field_name: str,
    strict: bool,
) -> str:
    if value is None:
        candidate = default
    elif isinstance(value, str):
        candidate = value.strip().casefold()
    elif strict:
        raise ValueError(f"{field_name.title()} must be provided as a string.")
    else:
        candidate = default
    if candidate in allowed:
        return candidate
    if strict:
        raise ValueError(f"Unsupported {field_name}: {value}")
    return default if default in allowed else next(iter(allowed))


def _normalize_sample_size(
    value: object,
    *,
    default: int,
    strict: bool,
    min_sample_size: int,
    max_sample_size: int | None,
) -> int:
    try:
        parsed = int(default if value is None else value)
    except (TypeError, ValueError) as exc:
        if strict:
            raise ValueError("Dashboard interactivity sample size must be an integer.") from exc
        parsed = int(default)
    lower_bound = max(1, int(min_sample_size))
    upper_bound = int(max_sample_size) if max_sample_size is not None else None
    if parsed < lower_bound or (upper_bound is not None and parsed > upper_bound):
        if strict:
            if upper_bound is None:
                raise ValueError(
                    "Dashboard interactivity sample size must be at least "
                    f"{lower_bound}."
                )
            raise ValueError(
                "Dashboard interactivity sample size must be between "
                f"{lower_bound} and {upper_bound}."
            )
        parsed = max(lower_bound, parsed)
        if upper_bound is not None:
            parsed = min(parsed, upper_bound)
    return parsed
