"""Optional native bridge for distribution-fit Monte Carlo AD bootstrap."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from modules.runtime_backend_policy import should_prefer_python_backend_in_auto_mode

try:
    from _metroliza_distribution_fit_native import (  # type: ignore
        compute_ad_ks_statistics as _native_compute_ad_ks_statistics,
        estimate_ad_pvalue_monte_carlo as _native_estimate_ad_pvalue_monte_carlo,
    )
except Exception:  # pragma: no cover - optional native module
    _native_estimate_ad_pvalue_monte_carlo = None
    _native_compute_ad_ks_statistics = None


def native_monte_carlo_backend_available() -> bool:
    return _native_estimate_ad_pvalue_monte_carlo is not None


def native_ad_ks_backend_available() -> bool:
    return _native_compute_ad_ks_statistics is not None


def native_backend_available() -> bool:
    return native_monte_carlo_backend_available() and native_ad_ks_backend_available()


def _as_float64_1d_contiguous(values: Sequence[float] | np.ndarray) -> np.ndarray:
    if isinstance(values, np.ndarray) and values.dtype == np.float64 and values.flags['C_CONTIGUOUS']:
        array = values
    else:
        array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError('Expected 1D numeric input')
    if array.flags['C_CONTIGUOUS']:
        return array
    return np.ascontiguousarray(array)


def estimate_ad_pvalue_monte_carlo_native(
    *,
    distribution: str,
    fitted_params: Sequence[float],
    sample_size: int,
    observed_stat: float,
    iterations: int,
    seed: int | None,
) -> tuple[float | None, int] | None:
    """Execute AD Monte Carlo p-value estimation via native backend when available."""
    if should_prefer_python_backend_in_auto_mode():
        return None
    if _native_estimate_ad_pvalue_monte_carlo is None:
        return None

    normalized_params = _as_float64_1d_contiguous(fitted_params)

    return _native_estimate_ad_pvalue_monte_carlo(
        distribution,
        normalized_params,
        int(sample_size),
        float(observed_stat),
        int(iterations),
        None if seed is None else int(seed),
    )


def compute_ad_ks_statistics_native(
    *,
    distribution: str,
    fitted_params: Sequence[float],
    sample_values: Sequence[float],
) -> tuple[float, float] | None:
    """Execute AD+KS statistic kernels via native backend when available."""
    if should_prefer_python_backend_in_auto_mode():
        return None
    if _native_compute_ad_ks_statistics is None:
        return None

    normalized_params = _as_float64_1d_contiguous(fitted_params)
    normalized_samples = _as_float64_1d_contiguous(sample_values)

    return _native_compute_ad_ks_statistics(
        distribution,
        normalized_params,
        normalized_samples,
    )
