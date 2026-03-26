"""Unified backend diagnostics for native/py fallback status surfaces."""

from __future__ import annotations

from typing import Any

from modules import chart_renderer, cmm_native_parser, comparison_stats_native, distribution_fit_candidate_native, distribution_fit_native, group_stats_native


def _build_backend_entry(*, available: bool, selected_mode: str, effective_backend: str, error: str = "") -> dict[str, Any]:
    normalized_selected = str(selected_mode or "auto").strip().lower() or "auto"
    normalized_effective = str(effective_backend or "python").strip().lower() or "python"
    forced_native_failure = normalized_selected == "native" and normalized_effective != "native"
    status = "forced_native_failure" if forced_native_failure else ("native_available" if available else "native_unavailable_fallback")
    entry = {
        "available": bool(available),
        "selected_mode": normalized_selected,
        "effective_backend": normalized_effective,
        "forced_native_failure": forced_native_failure,
        "status": status,
    }
    if error:
        entry["error"] = str(error)
    return entry


def _resolve_cmm_parser_entry() -> dict[str, Any]:
    selected_mode = cmm_native_parser._runtime_backend_choice()
    available = cmm_native_parser.native_backend_available()
    try:
        effective = cmm_native_parser.resolve_cmm_parser_backend()
        return _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend=effective)
    except Exception as exc:
        return _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend="python", error=str(exc))


def _resolve_cmm_persistence_entry() -> dict[str, Any]:
    selected_mode = cmm_native_parser._runtime_persistence_backend_choice()
    available = cmm_native_parser.native_persistence_backend_available()
    try:
        effective = cmm_native_parser.resolve_cmm_persistence_backend()
        return _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend=effective)
    except Exception as exc:
        return _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend="python", error=str(exc))


def _resolve_comparison_ci_entry() -> dict[str, Any]:
    selected_mode = comparison_stats_native._runtime_backend_choice()
    available = comparison_stats_native.native_backend_available()
    effective = "native" if (selected_mode != "python" and available) else "python"
    return _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend=effective)


def _resolve_comparison_pairwise_entry() -> dict[str, Any]:
    selected_mode = comparison_stats_native._runtime_pairwise_backend_choice()
    available = comparison_stats_native.native_backend_available()
    effective = "native" if (selected_mode != "python" and available) else "python"
    return _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend=effective)


def _resolve_distribution_fit_entry() -> dict[str, Any]:
    selected_mode = "auto"
    available = distribution_fit_native.native_backend_available()
    effective = "native" if available else "python"
    return _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend=effective)


def _resolve_distribution_fit_candidate_entry() -> dict[str, Any]:
    selected_mode = distribution_fit_candidate_native.resolve_kernel_mode()
    available = distribution_fit_candidate_native.native_backend_available()
    if selected_mode == distribution_fit_candidate_native.KERNEL_MODE_PYTHON:
        effective = "python"
    elif selected_mode == distribution_fit_candidate_native.KERNEL_MODE_NATIVE:
        effective = "native" if available else "python"
    else:
        effective = "native" if available else "python"
    return _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend=effective)


def _resolve_group_stats_entry() -> dict[str, Any]:
    selected_mode = group_stats_native._runtime_backend_choice()
    available = group_stats_native.native_backend_available()
    if selected_mode == "python":
        effective = "python"
    elif selected_mode == "native":
        effective = "native" if available else "python"
    else:
        effective = "native" if available else "python"
    return _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend=effective)


def _resolve_chart_renderer_entry() -> dict[str, Any]:
    selected_mode = chart_renderer._runtime_backend_choice()
    available = chart_renderer.native_chart_backend_available()
    histogram_available = chart_renderer.native_histogram_backend_available()
    distribution_available = chart_renderer.native_distribution_backend_available()
    try:
        effective = chart_renderer.resolve_chart_renderer_backend()
        entry = _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend=effective)
        entry["histogram_available"] = histogram_available
        entry["distribution_available"] = distribution_available
        return entry
    except Exception as exc:
        entry = _build_backend_entry(available=available, selected_mode=selected_mode, effective_backend="matplotlib", error=str(exc))
        entry["histogram_available"] = histogram_available
        entry["distribution_available"] = distribution_available
        return entry


def build_backend_diagnostic_summary() -> dict[str, dict[str, Any]]:
    """Build a per-module backend summary used by startup/export diagnostics."""
    return {
        "cmm_parser": _resolve_cmm_parser_entry(),
        "cmm_persistence": _resolve_cmm_persistence_entry(),
        "comparison_stats_ci": _resolve_comparison_ci_entry(),
        "comparison_stats_pairwise": _resolve_comparison_pairwise_entry(),
        "distribution_fit": _resolve_distribution_fit_entry(),
        "distribution_fit_candidate": _resolve_distribution_fit_candidate_entry(),
        "group_stats": _resolve_group_stats_entry(),
        "chart_renderer": _resolve_chart_renderer_entry(),
    }


def format_backend_diagnostic_lines(summary: dict[str, dict[str, Any]]) -> list[str]:
    """Return stable human-readable lines for logs/UI debug metadata."""
    lines: list[str] = []
    for component in sorted(summary):
        payload = summary.get(component) or {}
        details = (
            f"{component}: status={payload.get('status')}, available={payload.get('available')}, "
            f"selected={payload.get('selected_mode')}, effective={payload.get('effective_backend')}"
        )
        error = payload.get("error")
        if error:
            details = f"{details}, error={error}"
        lines.append(details)
    return lines
