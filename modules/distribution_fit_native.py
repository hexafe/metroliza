"""Optional native bridge for distribution-fit Monte Carlo AD bootstrap."""

from __future__ import annotations

from typing import Sequence

try:
    from _metroliza_distribution_fit_native import estimate_ad_pvalue_monte_carlo as _native_estimate_ad_pvalue_monte_carlo  # type: ignore
except Exception:  # pragma: no cover - optional native module
    _native_estimate_ad_pvalue_monte_carlo = None


def native_backend_available() -> bool:
    return _native_estimate_ad_pvalue_monte_carlo is not None


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
    if _native_estimate_ad_pvalue_monte_carlo is None:
        return None

    return _native_estimate_ad_pvalue_monte_carlo(
        distribution,
        [float(v) for v in fitted_params],
        int(sample_size),
        float(observed_stat),
        int(iterations),
        None if seed is None else int(seed),
    )
