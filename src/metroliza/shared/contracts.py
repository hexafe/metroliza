"""Lazy compatibility facade for package-owned request contracts.

New canonical code should import contracts from their owning package:
``metroliza.exporting.contracts``, ``metroliza.industrial.contracts``,
``metroliza.tabular.contracts``, or ``metroliza.shared.parse_contracts``.
The aliases here preserve the historical public API without loading feature
packages during a cold import of this module.
"""

from __future__ import annotations

from importlib import import_module


_COMPAT_EXPORTS = {
    "AppPaths": ("metroliza.exporting.contracts", "AppPaths"),
    "DashboardInteractivityOptions": (
        "metroliza.shared.dashboard_interactivity",
        "DashboardInteractivityOptions",
    ),
    "ExportOptions": ("metroliza.exporting.contracts", "ExportOptions"),
    "ExportRequest": ("metroliza.exporting.contracts", "ExportRequest"),
    "GroupingAssignment": ("metroliza.tabular.contracts", "GroupingAssignment"),
    "GroupingAssignments": ("metroliza.tabular.contracts", "GroupingAssignments"),
    "IndustrialAnalyticsRequest": (
        "metroliza.industrial.contracts",
        "IndustrialAnalyticsRequest",
    ),
    "ParseRequest": ("metroliza.shared.parse_contracts", "ParseRequest"),
    "ProductionAggregationState": (
        "metroliza.industrial.industrial_analytics_state",
        "ProductionAggregationState",
    ),
    "ProductionChartSelection": (
        "metroliza.industrial.industrial_analytics_state",
        "ProductionChartSelection",
    ),
    "ProductionFilterState": (
        "metroliza.industrial.industrial_analytics_state",
        "ProductionFilterState",
    ),
    "ProductionMetricSelection": (
        "metroliza.industrial.industrial_analytics_state",
        "ProductionMetricSelection",
    ),
    "ReferenceCohortState": (
        "metroliza.industrial.industrial_analytics_state",
        "ReferenceCohortState",
    ),
    "TabularAnalyticsLoadResult": (
        "metroliza.tabular.tabular_analytics_service",
        "TabularAnalyticsLoadResult",
    ),
    "TabularColumnFilter": (
        "metroliza.tabular.tabular_analytics_service",
        "TabularColumnFilter",
    ),
    "normalize_dashboard_interactivity_options": (
        "metroliza.shared.dashboard_interactivity",
        "normalize_dashboard_interactivity_options",
    ),
    "normalize_dashboard_visual_settings": (
        "metroliza.charts.dashboard_visual_options",
        "normalize_dashboard_visual_settings",
    ),
    "require_analytics_identifier": (
        "metroliza.industrial.industrial_analytics_state",
        "require_identifier",
    ),
    "validate_export_options": (
        "metroliza.exporting.contracts",
        "validate_export_options",
    ),
    "validate_export_request": (
        "metroliza.exporting.contracts",
        "validate_export_request",
    ),
    "validate_grouping_assignments": (
        "metroliza.tabular.contracts",
        "validate_grouping_assignments",
    ),
    "validate_grouping_df": (
        "metroliza.tabular.contracts",
        "validate_grouping_df",
    ),
    "validate_industrial_analytics_request": (
        "metroliza.industrial.contracts",
        "validate_industrial_analytics_request",
    ),
    "validate_parse_request": (
        "metroliza.shared.parse_contracts",
        "validate_parse_request",
    ),
    "validate_paths": ("metroliza.exporting.contracts", "validate_paths"),
}

__all__ = sorted(_COMPAT_EXPORTS)


def __getattr__(name: str):
    target = _COMPAT_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
