"""Qualification-only unavailable-native control around the real core journey."""
from __future__ import annotations

import os
import sys
from contextvars import ContextVar

MODE_ENV = "METROLIZA_WINDOWS_CANDIDATE_NATIVE_MODE"
_UNAVAILABLE_ACTIVE = ContextVar("candidate_unavailable_active", default=False)
_UNJOINED_OWNERS = []


class _UnjoinedNativeOwner(SystemExit):
    """A synthetic child must exit into its Job without switching a live worker."""

    def __init__(self):
        super().__init__(22)


def abort_unavailable_after_join_failure(owner) -> None:
    """Call only after the owned worker's bounded join returned false."""
    if _UNAVAILABLE_ACTIVE.get():
        _UNJOINED_OWNERS.append(owner)
        raise _UnjoinedNativeOwner()


def close_report_owner(window, app) -> None:
    """Cancel and join actual report workers before unwinding the native scope."""
    workspace = getattr(window, "_reports_workspace", None)
    workers = () if workspace is None else tuple(
        worker for worker in (workspace.preflight_thread, workspace.parse_thread) if worker is not None
    )
    if workspace is not None:
        workspace._request_active_worker_cancellation()
    for worker in workers:
        if not worker.wait(20000):
            abort_unavailable_after_join_failure(window)
            _UNJOINED_OWNERS.append(window)
            raise ValueError("candidate_report_worker_join_deadline")
    app.processEvents()
    if not window.close() or window.isVisible():
        _UNJOINED_OWNERS.append(window)
        raise ValueError("candidate_report_owner_close_refused")
    app.processEvents()


def _bindings():
    from metroliza.native_bridges import (
        cmm_native_parser, comparison_stats_native, distribution_fit_native,
        distribution_fit_candidate_native, group_stats_native,
    )
    from metroliza.charts import chart_renderer

    groups = (
        ("cmm", cmm_native_parser, ("parse_blocks", "normalize_measurement_rows", "persist_measurement_rows")),
        ("comparison", comparison_stats_native, ("bootstrap_percentile_ci", "bootstrap_percentile_ci_batch", "pairwise_stats")),
        ("distribution", distribution_fit_native, ("compute_ad_ks_statistics", "estimate_ad_pvalue_monte_carlo")),
        ("candidate", distribution_fit_candidate_native, ("compute_candidate_metrics", "compute_candidate_metrics_batch", "compute_candidate_fit_params_batch")),
        ("group", group_stats_native, ("coerce_sequence_to_float64",)),
        ("chart", chart_renderer, ("render_histogram_png", "render_distribution_png", "render_iqr_png", "render_trend_png")),
    )
    return [(label + "." + name, module, "_native_" + name)
            for label, module, names in groups for name in names]


def _prepare_native_control():
    gates = ("METROLIZA_STARTUP_SMOKE", "METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION")
    if not all(os.environ.get(name) == "1" for name in gates):
        raise ValueError("candidate_native_gate_missing")
    mode = os.environ.get(MODE_ENV, "default")
    if mode not in {"default", "unavailable"}:
        raise ValueError("candidate_native_mode_invalid")
    bindings = _bindings()
    originals = [(name, module, attr, getattr(module, attr)) for name, module, attr in bindings]
    if len(originals) != 16 or any(value is not None and not callable(value) for _, _, _, value in originals):
        raise ValueError("candidate_native_bindings_invalid")
    available = sum(callable(value) for _, _, _, value in originals)
    packaged = bool(getattr(sys, "frozen", False))
    if packaged and available != len(originals):
        raise ValueError("candidate_native_package_bindings_missing")
    return mode, originals, available, packaged


def run_with_native_mode(operation) -> dict:
    """Restore exact bindings after the fully joined operation, even on interruption.

    This forces unavailable callables, not missing package files. The operation
    retains the real parsers, SQLite services, statistical algorithms and exports.
    """
    mode, originals, available, packaged = _prepare_native_control()
    token = _UNAVAILABLE_ACTIVE.set(mode == "unavailable")
    restore = True
    try:
        if mode == "unavailable":
            for _, module, attr, _ in originals:
                setattr(module, attr, None)
        operation()
        if mode == "unavailable" and any(getattr(module, attr) is not None for _, module, attr, _ in originals):
            raise ValueError("candidate_native_control_changed")
    except _UnjoinedNativeOwner:
        # Only a failed bounded join reaches this path. The owned Job tears
        # down this failed synthetic child; no receipt can report success.
        restore = False
        raise
    finally:
        _UNAVAILABLE_ACTIVE.reset(token)
        if restore:
            for _, module, attr, value in originals:
                setattr(module, attr, value)
    if any(getattr(module, attr) is not value for _, module, attr, value in originals):
        raise ValueError("candidate_native_restore_failed")
    return {
        "mode": mode, "runtime_context": "packaged" if packaged else "source",
        "bindings": [name for name, _, _, _ in originals],
        "available_before": available,
        "forced_unavailable": len(originals) if mode == "unavailable" else 0,
        "restored": True,
    }
