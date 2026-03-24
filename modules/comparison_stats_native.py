"""Optional native bridge for comparison-stats bootstrap CI sampling."""

from __future__ import annotations

import os
from typing import Literal

try:
    from _metroliza_comparison_stats_native import bootstrap_percentile_ci as _native_bootstrap_percentile_ci  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_bootstrap_percentile_ci = None

BackendChoice = Literal['auto', 'native', 'python']


def _runtime_backend_choice() -> BackendChoice:
    choice = os.getenv('METROLIZA_COMPARISON_STATS_CI_BACKEND', 'auto').strip().lower()
    if choice in {'auto', 'native', 'python'}:
        return choice
    return 'auto'


def native_backend_available() -> bool:
    return _native_bootstrap_percentile_ci is not None


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
