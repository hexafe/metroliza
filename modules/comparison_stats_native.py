"""Optional native bridge for comparison-stats calculations."""

from __future__ import annotations

import os
from typing import Literal, Sequence

import numpy as np
from modules.runtime_backend_policy import should_prefer_python_backend_in_auto_mode

try:
    from _metroliza_comparison_stats_native import bootstrap_percentile_ci as _native_bootstrap_percentile_ci  # type: ignore
    from _metroliza_comparison_stats_native import bootstrap_percentile_ci_batch as _native_bootstrap_percentile_ci_batch  # type: ignore
    from _metroliza_comparison_stats_native import pairwise_stats as _native_pairwise_stats  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_bootstrap_percentile_ci = None
    _native_bootstrap_percentile_ci_batch = None
    _native_pairwise_stats = None

BackendChoice = Literal['auto', 'native', 'python']


def _runtime_backend_choice() -> BackendChoice:
    choice = os.getenv('METROLIZA_COMPARISON_STATS_CI_BACKEND', 'auto').strip().lower()
    if choice in {'auto', 'native', 'python'}:
        if choice == 'auto' and should_prefer_python_backend_in_auto_mode():
            return 'python'
        return choice
    return 'auto'


def native_backend_available() -> bool:
    return (
        _native_bootstrap_percentile_ci is not None
        and _native_bootstrap_percentile_ci_batch is not None
        and _native_pairwise_stats is not None
    )


def _runtime_pairwise_backend_choice() -> BackendChoice:
    choice = os.getenv('METROLIZA_COMPARISON_STATS_BACKEND', 'auto').strip().lower()
    if choice in {'auto', 'native', 'python'}:
        if choice == 'auto' and should_prefer_python_backend_in_auto_mode():
            return 'python'
        return choice
    return 'auto'


def _normalize_native_groups(groups: Sequence[np.ndarray | list[float]]) -> list[np.ndarray]:
    normalized: list[np.ndarray] = []
    for group in groups:
        if isinstance(group, np.ndarray) and group.dtype == np.float64 and group.flags['C_CONTIGUOUS']:
            normalized.append(group)
            continue
        normalized.append(np.ascontiguousarray(np.asarray(group, dtype=np.float64)))
    return normalized


def bootstrap_percentile_ci_native(
    *,
    effect_kernel: str,
    groups: Sequence[np.ndarray | list[float]],
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

    normalized_groups = _normalize_native_groups(groups)

    return _native_bootstrap_percentile_ci(
        str(effect_kernel),
        normalized_groups,
        float(level),
        int(iterations),
        int(seed),
    )


def bootstrap_percentile_ci_batch_native(
    *,
    effect_kernel: str,
    groups: Sequence[np.ndarray | list[float]],
    pairs: Sequence[tuple[int, int]],
    level: float,
    iterations: int,
    seed: int,
) -> list[tuple[float, float] | None] | None:
    """Execute batch bootstrap percentile CIs via native backend when enabled/available."""
    backend = _runtime_backend_choice()
    if backend == 'python':
        return None
    if backend == 'native' and _native_bootstrap_percentile_ci_batch is None:
        raise RuntimeError('Native comparison-stats CI backend requested but unavailable')
    if _native_bootstrap_percentile_ci_batch is None:
        return None

    normalized_groups = _normalize_native_groups(groups)
    normalized_pairs = [(int(left), int(right)) for left, right in pairs]

    result = _native_bootstrap_percentile_ci_batch(
        str(effect_kernel),
        normalized_groups,
        normalized_pairs,
        float(level),
        int(iterations),
        int(seed),
    )
    return [None if ci is None else (float(ci[0]), float(ci[1])) for ci in result]


def pairwise_stats_native(
    *,
    labels: list[str],
    groups: Sequence[np.ndarray | list[float]],
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

    normalized_groups = _normalize_native_groups(groups)

    rows = _native_pairwise_stats(
        [str(label) for label in labels],
        normalized_groups,
        float(alpha),
        str(correction_method),
        bool(non_parametric),
        bool(equal_var),
    )
    return [dict(row) for row in rows]
