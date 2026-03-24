"""Optional native bridge for comparison-stats calculations."""

from __future__ import annotations

import os
from typing import Literal

try:
    from _metroliza_comparison_stats_native import bootstrap_percentile_ci as _native_bootstrap_percentile_ci  # type: ignore
    from _metroliza_comparison_stats_native import pairwise_stats as _native_pairwise_stats  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_bootstrap_percentile_ci = None
    _native_pairwise_stats = None

BackendChoice = Literal['auto', 'native', 'python']


def _runtime_backend_choice() -> BackendChoice:
    choice = os.getenv('METROLIZA_COMPARISON_STATS_CI_BACKEND', 'auto').strip().lower()
    if choice in {'auto', 'native', 'python'}:
        return choice
    return 'auto'


def native_backend_available() -> bool:
    return _native_bootstrap_percentile_ci is not None and _native_pairwise_stats is not None


def _runtime_pairwise_backend_choice() -> BackendChoice:
    choice = os.getenv('METROLIZA_COMPARISON_STATS_BACKEND', 'auto').strip().lower()
    if choice in {'auto', 'native', 'python'}:
        return choice
    return 'auto'


def bootstrap_percentile_ci_native(
    *,
    effect_kernel: str,
    groups: list[list[float]],
    level: float,
    iterations: int,
    seed: int,
) -> tuple[float, float] | None:
    """Execute bootstrap percentile CI via native backend when enabled/available."""
    backend = _runtime_backend_choice()
    if backend == 'python':
        return None
    if backend == 'native' and _native_bootstrap_percentile_ci is None:
        raise RuntimeError('Native comparison-stats CI backend requested but unavailable')
    if _native_bootstrap_percentile_ci is None:
        return None

    return _native_bootstrap_percentile_ci(
        str(effect_kernel),
        [[float(value) for value in group] for group in groups],
        float(level),
        int(iterations),
        int(seed),
    )


def pairwise_stats_native(
    *,
    labels: list[str],
    groups: list[list[float]],
    alpha: float,
    correction_method: str,
    non_parametric: bool,
    equal_var: bool,
) -> list[dict[str, float | str | bool | None]] | None:
    """Execute full pairwise stats via native backend when enabled/available."""
    backend = _runtime_pairwise_backend_choice()
    if backend == 'python':
        return None
    if backend == 'native' and _native_pairwise_stats is None:
        raise RuntimeError('Native comparison-stats backend requested but unavailable')
    if _native_pairwise_stats is None:
        return None

    rows = _native_pairwise_stats(
        [str(label) for label in labels],
        [[float(value) for value in group] for group in groups],
        float(alpha),
        str(correction_method),
        bool(non_parametric),
        bool(equal_var),
    )
    return [dict(row) for row in rows]
