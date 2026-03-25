"""Distribution fitting helpers with GOF, model selection, and tail-risk estimation."""

from __future__ import annotations

import math
from collections.abc import MutableMapping
from dataclasses import asdict, dataclass, field
from hashlib import blake2b
from typing import Callable

import numpy as np
import pandas as pd
from modules.distribution_fit_native import (
    compute_ad_ks_statistics_native,
    estimate_ad_pvalue_monte_carlo_native,
)
from modules.distribution_fit_candidate_native import (
    build_kernel_input,
    compute_candidate_metrics,
)
from scipy.stats import (
    foldnorm,
    gamma,
    gaussian_kde,
    halfnorm,
    johnsonsu,
    kstwo,
    kstest,
    lognorm,
    norm,
    skewnorm,
    weibull_min,
)


@dataclass(frozen=True)
class _CandidateDistribution:
    name: str
    display_name: str
    scipy_dist: object
    fit_method: Callable[..., tuple]
    positive_support: bool = False
    force_loc_zero: bool = False


@dataclass
class DistributionFitResult:
    status: str
    sample_size: int
    inferred_support_mode: str
    selected_model: dict | None
    selected_model_pdf: dict | None
    selected_model_cdf: dict | None
    kde_reference_pdf: dict | None
    gof_metrics: dict | None
    ranking_metrics: list[dict]
    fit_quality: dict
    risk_estimates: dict
    model_candidates: list[dict]
    warning: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key in ('selected_model_pdf', 'selected_model_cdf', 'kde_reference_pdf'):
            curve = payload.get(key)
            if isinstance(curve, dict):
                if curve.get('x') is not None:
                    curve['x'] = np.asarray(curve['x'])
                if curve.get('y') is not None:
                    curve['y'] = np.asarray(curve['y'])
        return payload


_BILATERAL_CANDIDATES: tuple[_CandidateDistribution, ...] = (
    _CandidateDistribution('norm', 'Normal', norm, norm.fit),
    _CandidateDistribution('skewnorm', 'Skew Normal', skewnorm, skewnorm.fit),
    _CandidateDistribution('johnsonsu', 'Johnson SU', johnsonsu, johnsonsu.fit),
)

_POSITIVE_CANDIDATES: tuple[_CandidateDistribution, ...] = (
    _CandidateDistribution('halfnorm', 'Half Normal', halfnorm, halfnorm.fit, True, True),
    _CandidateDistribution('foldnorm', 'Folded Normal', foldnorm, foldnorm.fit, True, True),
    _CandidateDistribution('gamma', 'Gamma', gamma, gamma.fit, True, True),
    _CandidateDistribution('weibull_min', 'Weibull (Min)', weibull_min, weibull_min.fit, True, True),
    _CandidateDistribution('lognorm', 'Lognormal', lognorm, lognorm.fit, True, True),
)

_DISTRIBUTION_BY_NAME = {
    'norm': norm,
    'skewnorm': skewnorm,
    'johnsonsu': johnsonsu,
    'halfnorm': halfnorm,
    'foldnorm': foldnorm,
    'gamma': gamma,
    'weibull_min': weibull_min,
    'lognorm': lognorm,
}

# Stable candidate-kernel contract (frozen for Rust/Python parity):
# Input: contiguous float64 1D sample array + candidate model metadata (distribution + fitted params).
# Output: nll, aic, bic, ad_statistic, ks_statistic, and kernel error flags (consumed internally for fallback).


def resolve_density_curve_sampling(sample_size, *, requested_point_count=100):
    """Resolve curve point density and KDE smoothing safeguards for low sample sizes."""
    n = max(0, int(sample_size))
    if n <= 10:
        return {'point_count': min(int(requested_point_count), 40), 'kde_min_bandwidth': 0.45}
    if n <= 20:
        return {'point_count': min(int(requested_point_count), 60), 'kde_min_bandwidth': 0.35}
    if n <= 40:
        return {'point_count': min(int(requested_point_count), 80), 'kde_min_bandwidth': 0.25}
    return {'point_count': max(20, int(requested_point_count)), 'kde_min_bandwidth': 0.0}


def _safe_float(value):
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _coerce_measurements_array(measurements) -> np.ndarray:
    if isinstance(measurements, np.ndarray):
        values = np.asarray(measurements, dtype=float)
        if values.ndim != 1:
            values = values.reshape(-1)
        if np.all(np.isfinite(values)):
            return np.ascontiguousarray(values)
        return np.ascontiguousarray(values[np.isfinite(values)])

    values = pd.to_numeric(pd.Series(list(measurements)), errors='coerce').dropna().to_numpy(dtype=float)
    return np.ascontiguousarray(values)


def measurement_fingerprint(values: np.ndarray):
    """Public fingerprint helper for callers that precompute cache keys per group."""
    return _measurement_fingerprint(values)


def _infer_support_mode(values: np.ndarray, tolerance: float = 1e-9) -> str:
    min_value = float(np.min(values))
    near_zero_count = int(np.sum(np.abs(values) <= tolerance))
    zero_ratio = near_zero_count / max(values.size, 1)
    if min_value >= -tolerance and (near_zero_count > 0 or zero_ratio >= 0.02):
        return 'one_sided_zero_bound_positive'
    return 'bilateral_signed'


def _candidate_pool_for_mode(mode: str) -> tuple[_CandidateDistribution, ...]:
    if mode == 'one_sided_zero_bound_positive':
        return _POSITIVE_CANDIDATES
    return _BILATERAL_CANDIDATES


def _resolve_curve_x_values(values: np.ndarray, *, point_count: int, coverage_padding: float = 0.03):
    x_min = float(np.min(values))
    x_max = float(np.max(values))
    if np.isclose(x_min, x_max):
        return None
    spread = x_max - x_min
    sampling = resolve_density_curve_sampling(int(values.size), requested_point_count=point_count)
    resolved_point_count = max(20, int(sampling['point_count']))
    return np.linspace(x_min - (coverage_padding * spread), x_max + (coverage_padding * spread), resolved_point_count)


def _measurement_fingerprint(values: np.ndarray):
    normalized = np.ascontiguousarray(np.asarray(values, dtype=float))
    digest = blake2b(normalized.tobytes(), digest_size=16).hexdigest()
    return (int(normalized.size), digest)


def _fit_cache_key(
    *,
    values: np.ndarray,
    lsl,
    usl,
    point_count: int,
    include_kde_reference: bool,
    gof_acceptance_alpha: float,
    monte_carlo_gof_samples: int,
    monte_carlo_seed: int | None,
):
    return (
        _measurement_fingerprint(values),
        _safe_float(lsl),
        _safe_float(usl),
        int(point_count),
        bool(include_kde_reference),
        float(gof_acceptance_alpha),
        int(monte_carlo_gof_samples),
        None if monte_carlo_seed is None else int(monte_carlo_seed),
    )


def _clone_curve_payload(curve: dict | None):
    if not isinstance(curve, dict):
        return curve
    cloned = dict(curve)
    if curve.get('x') is not None:
        cloned['x'] = np.asarray(curve['x'], dtype=float).copy()
    if curve.get('y') is not None:
        cloned['y'] = np.asarray(curve['y'], dtype=float).copy()
    return cloned


def clone_fit_payload(payload: dict | None):
    if not isinstance(payload, dict):
        return payload
    cloned = dict(payload)
    for key in ('selected_model_pdf', 'selected_model_cdf', 'kde_reference_pdf'):
        cloned[key] = _clone_curve_payload(payload.get(key))
    if isinstance(payload.get('selected_model'), dict):
        cloned['selected_model'] = dict(payload['selected_model'])
    if isinstance(payload.get('gof_metrics'), dict):
        cloned['gof_metrics'] = dict(payload['gof_metrics'])
    if isinstance(payload.get('fit_quality'), dict):
        cloned['fit_quality'] = dict(payload['fit_quality'])
    if isinstance(payload.get('risk_estimates'), dict):
        cloned['risk_estimates'] = dict(payload['risk_estimates'])
    if isinstance(payload.get('ranking_metrics'), list):
        cloned['ranking_metrics'] = [dict(item) if isinstance(item, dict) else item for item in payload['ranking_metrics']]
    if isinstance(payload.get('model_candidates'), list):
        cloned['model_candidates'] = [dict(item) if isinstance(item, dict) else item for item in payload['model_candidates']]
    if isinstance(payload.get('notes'), list):
        cloned['notes'] = list(payload['notes'])
    return cloned


def _build_density_curve(dist, params, x_values: np.ndarray):
    try:
        y_values = dist.pdf(x_values, *params)
    except Exception:
        return None
    if not np.all(np.isfinite(y_values)):
        return None
    return {'x': np.asarray(x_values), 'y': np.asarray(y_values)}


def _build_cdf_curve(dist, params, x_values: np.ndarray):
    try:
        y_values = dist.cdf(x_values, *params)
    except Exception:
        return None
    if not np.all(np.isfinite(y_values)):
        return None
    return {'x': np.asarray(x_values), 'y': np.asarray(np.clip(y_values, 0.0, 1.0))}


def _build_kde_reference_curve(values: np.ndarray, x_values: np.ndarray):
    if values.size < 2:
        return None
    try:
        kde = gaussian_kde(values)
        sampling = resolve_density_curve_sampling(int(values.size), requested_point_count=int(np.asarray(x_values).size))
        min_bandwidth = float(sampling.get('kde_min_bandwidth', 0.0))
        if min_bandwidth > 0:
            kde.set_bandwidth(bw_method=max(float(kde.factor), min_bandwidth))
        y_values = kde(x_values)
    except Exception:
        return None
    if not np.all(np.isfinite(y_values)):
        return None
    return {'x': np.asarray(x_values), 'y': np.asarray(y_values)}


def _ad_statistic(sample: np.ndarray, cdf: Callable[[np.ndarray], np.ndarray]) -> float:
    sorted_values = np.sort(sample)
    n = sorted_values.size
    probs = np.clip(cdf(sorted_values), 1e-12, 1.0 - 1e-12)
    reverse_probs = np.clip(1.0 - probs[::-1], 1e-12, 1.0)
    idx = np.arange(1, n + 1)
    stat = -n - np.sum((2 * idx - 1) * (np.log(probs) + np.log(reverse_probs))) / n
    return float(stat)


def _estimate_ad_pvalue_monte_carlo(
    *,
    dist,
    distribution_name: str,
    params: tuple,
    sample_size: int,
    observed_stat: float,
    iterations: int,
    random_seed: int | None,
):
    if iterations <= 0:
        return None

    native_result = estimate_ad_pvalue_monte_carlo_native(
        distribution=distribution_name,
        fitted_params=params,
        sample_size=sample_size,
        observed_stat=observed_stat,
        iterations=iterations,
        seed=random_seed,
    )
    if native_result is not None:
        p_value, _valid_trials = native_result
        return p_value

    rng = np.random.default_rng(random_seed)
    exceed_count = 0
    valid_trials = 0
    for _ in range(iterations):
        simulated = np.asarray(dist.rvs(*params, size=sample_size, random_state=rng), dtype=float)
        if simulated.size != sample_size or not np.all(np.isfinite(simulated)):
            continue
        sim_stat = _ad_statistic(simulated, lambda x: dist.cdf(x, *params))
        valid_trials += 1
        if sim_stat >= observed_stat:
            exceed_count += 1
    if valid_trials == 0:
        return None
    return float((exceed_count + 1) / (valid_trials + 1))


def _classify_fit_quality(gof_pvalue: float | None, selected_is_acceptable: bool) -> dict:
    if gof_pvalue is None:
        return {'label': 'unreliable', 'score': 0.1}
    if selected_is_acceptable and gof_pvalue >= 0.10:
        return {'label': 'strong', 'score': 1.0}
    if selected_is_acceptable and gof_pvalue >= 0.05:
        return {'label': 'medium', 'score': 0.75}
    if gof_pvalue >= 0.01:
        return {'label': 'weak', 'score': 0.45}
    return {'label': 'unreliable', 'score': 0.1}


def _fit_candidate(candidate: _CandidateDistribution, values: np.ndarray, *, kernel_mode: str | None = None):
    fit_kwargs = {'floc': 0.0} if candidate.force_loc_zero else {}
    params = tuple(candidate.fit_method(values, **fit_kwargs))
    if candidate.positive_support and params:
        params = list(params)
        params[-2] = 0.0
        params = tuple(params)

    kernel_input = build_kernel_input(
        sample_values=values,
        distribution=candidate.name,
        fitted_params=params,
    )
    kernel_output = compute_candidate_metrics(kernel_input, mode=kernel_mode)

    n = values.size
    nll = None if kernel_output is None else kernel_output.nll
    aic = None if kernel_output is None else kernel_output.aic
    bic = None if kernel_output is None else kernel_output.bic
    ad_stat = None if kernel_output is None else kernel_output.ad_statistic
    ks_stat = None if kernel_output is None else kernel_output.ks_statistic

    if nll is None or aic is None or bic is None:
        logpdf = candidate.scipy_dist.logpdf(values, *params)
        if not np.all(np.isfinite(logpdf)):
            raise ValueError('logpdf returned invalid values')
        nll = float(-np.sum(logpdf))
        k = len(params)
        aic = float(2 * k + 2 * nll)
        bic = float(k * math.log(n) + 2 * nll)

    if ad_stat is None:
        native_stats = compute_ad_ks_statistics_native(
            distribution=candidate.name,
            fitted_params=params,
            sample_values=values,
        )
        if native_stats is not None:
            ad_stat, ks_stat = native_stats

    if ad_stat is None:
        ad_stat = _ad_statistic(values, lambda x: candidate.scipy_dist.cdf(x, *params))

    if ks_stat is None:
        ks_stat, ks_pvalue = kstest(values, candidate.scipy_dist.cdf, args=params)
        ks_stat = float(ks_stat)
        ks_pvalue = float(ks_pvalue)
    else:
        ks_stat = float(ks_stat)
        ks_pvalue = float(kstwo.sf(ks_stat, n)) if n > 0 else None

    return {
        'model': candidate.name,
        'display_name': candidate.display_name,
        'params': tuple(float(v) for v in params),
        'metrics': {'nll': nll, 'aic': aic, 'bic': bic},
        'gof': {
            'ad_statistic': float(ad_stat),
            'ad_pvalue': None,
            'ad_pvalue_method': 'not_estimated',
            'ks_statistic': float(ks_stat),
            'ks_pvalue': float(ks_pvalue),
        },
    }


def build_fit_curve_payload(
    measurements,
    *,
    point_count: int = 100,
    mode: str = 'normal_fit',
    distribution_fit_result: dict | None = None,
):
    """Return canonical histogram overlay curve payloads for export/render callers."""
    values = _coerce_measurements_array(measurements)
    if values.size == 0:
        return None

    if distribution_fit_result:
        if mode == 'kde':
            kde_curve = distribution_fit_result.get('kde_reference_pdf')
            if kde_curve is not None:
                return _clone_curve_payload(kde_curve)
        else:
            selected_curve = distribution_fit_result.get('selected_model_pdf')
            if selected_curve is not None:
                return _clone_curve_payload(selected_curve)

    x_values = _resolve_curve_x_values(values, point_count=point_count, coverage_padding=0.0)
    if x_values is None:
        return None

    if mode == 'kde':
        return _build_kde_reference_curve(values, x_values)

    if distribution_fit_result:
        selected_model = distribution_fit_result.get('selected_model') or {}
        model_name = selected_model.get('name') or selected_model.get('model')
        params = selected_model.get('params')
        dist = _DISTRIBUTION_BY_NAME.get(model_name)
        if dist is not None and params:
            return _build_density_curve(dist, params, x_values)

    mu, std = norm.fit(values)
    if std <= 0:
        return None
    return _build_density_curve(norm, (mu, std), x_values)


def compute_estimated_tail_metrics(distribution_fit_result, *, lsl=None, usl=None):
    """Return export-friendly tail metrics derived from canonical fit risk estimates."""
    distribution_fit_result = distribution_fit_result or {}
    risk_estimates = distribution_fit_result.get('risk_estimates') or {}
    outside_probability = risk_estimates.get('outside_probability')
    if outside_probability is None:
        selected_model = distribution_fit_result.get('selected_model') or {}
        model_name = selected_model.get('name') or selected_model.get('model')
        params = selected_model.get('params')
        dist = _DISTRIBUTION_BY_NAME.get(model_name)
        inferred_support_mode = distribution_fit_result.get('inferred_support_mode')
        if dist is None or not params:
            return {
                'estimated_nok_pct': None,
                'estimated_nok_ppm': None,
                'estimated_yield_pct': None,
                'estimated_tail_below_lsl': None,
                'estimated_tail_above_usl': None,
            }
        recomputed = _compute_tail_risk(
            dist,
            params,
            lsl,
            usl,
            inferred_support_mode=inferred_support_mode,
        )
        outside_probability = recomputed.get('outside_probability')
        risk_estimates = recomputed
        if outside_probability is None:
            return {
                'estimated_nok_pct': None,
                'estimated_nok_ppm': None,
                'estimated_yield_pct': None,
                'estimated_tail_below_lsl': None,
                'estimated_tail_above_usl': None,
            }
    return {
        'estimated_nok_pct': outside_probability,
        'estimated_nok_ppm': risk_estimates.get('ppm_nok'),
        'estimated_yield_pct': 1.0 - outside_probability,
        'estimated_tail_below_lsl': risk_estimates.get('below_lsl_probability'),
        'estimated_tail_above_usl': risk_estimates.get('above_usl_probability'),
    }


def _compute_tail_risk(dist, params, lsl, usl, *, inferred_support_mode=None) -> dict:
    below_lsl = None if lsl is None else float(np.clip(dist.cdf(lsl, *params), 0.0, 1.0))
    above_usl = None if usl is None else float(np.clip(1.0 - dist.cdf(usl, *params), 0.0, 1.0))

    if inferred_support_mode == 'one_sided_zero_bound_positive' and lsl is not None and np.isclose(lsl, 0.0):
        below_lsl = 0.0
        lsl = None

    if inferred_support_mode == 'one_sided_zero_bound_negative' and usl is not None and np.isclose(usl, 0.0):
        above_usl = 0.0
        usl = None

    if lsl is not None and usl is not None:
        nok_probability = float(np.clip((below_lsl or 0.0) + (above_usl or 0.0), 0.0, 1.0))
        spec_type = 'bilateral'
    elif usl is not None:
        nok_probability = float(np.clip(above_usl or 0.0, 0.0, 1.0))
        spec_type = 'upper_only'
    elif lsl is not None:
        nok_probability = float(np.clip(below_lsl or 0.0, 0.0, 1.0))
        spec_type = 'lower_only'
    else:
        nok_probability = None
        spec_type = 'none'

    if nok_probability is None:
        risk_label = 'unknown'
    elif nok_probability <= 1e-4:
        risk_label = 'low'
    elif nok_probability <= 1e-3:
        risk_label = 'moderate'
    elif nok_probability <= 1e-2:
        risk_label = 'elevated'
    else:
        risk_label = 'high'

    return {
        'spec_type': spec_type,
        'below_lsl_probability': below_lsl,
        'above_usl_probability': above_usl,
        'outside_probability': nok_probability,
        'nok_percent': None if nok_probability is None else nok_probability * 100.0,
        'ppm_nok': None if nok_probability is None else nok_probability * 1_000_000.0,
        'expected_ppm_outside': None if nok_probability is None else nok_probability * 1_000_000.0,
        'yield_percent': None if nok_probability is None else (1.0 - nok_probability) * 100.0,
        'risk_label': risk_label,
    }


def _failure_result(sample_size: int, inferred_support_mode: str, warning: str, notes: list[str] | None = None):
    result = DistributionFitResult(
        status='failed',
        warning=warning,
        sample_size=sample_size,
        inferred_support_mode=inferred_support_mode,
        selected_model=None,
        selected_model_pdf=None,
        selected_model_cdf=None,
        kde_reference_pdf=None,
        gof_metrics=None,
        ranking_metrics=[],
        fit_quality={'label': 'unreliable', 'score': 0.1},
        risk_estimates={
            'spec_type': 'none',
            'below_lsl_probability': None,
            'above_usl_probability': None,
            'outside_probability': None,
            'nok_percent': None,
            'ppm_nok': None,
            'expected_ppm_outside': None,
            'yield_percent': None,
            'risk_label': 'unknown',
        },
        model_candidates=[],
        notes=notes or [],
    )
    return result.to_dict()


def fit_measurement_distribution(
    measurements,
    *,
    lsl=None,
    usl=None,
    nom=None,
    point_count: int = 100,
    include_kde_reference: bool = True,
    gof_acceptance_alpha: float = 0.05,
    monte_carlo_gof_samples: int = 0,
    monte_carlo_seed: int | None = None,
    candidate_kernel_mode: str | None = None,
    memoization_cache: MutableMapping | None = None,
    measurement_signature: tuple[int, str] | None = None,
):
    """Fit distributions, score GOF, classify quality, and estimate tail risk.

    Returns a dictionary payload for compatibility with existing render/export paths.
    """

    del nom  # kept for backwards compatibility in call-sites.

    values = _coerce_measurements_array(measurements)
    sample_size = int(values.size)

    cache_key = None
    if memoization_cache is not None and sample_size > 0:
        fit_signature = measurement_signature if measurement_signature is not None else _measurement_fingerprint(values)
        cache_key = (
            fit_signature,
            _safe_float(lsl),
            _safe_float(usl),
            int(point_count),
            bool(include_kde_reference),
            float(gof_acceptance_alpha),
            int(monte_carlo_gof_samples),
            None if monte_carlo_seed is None else int(monte_carlo_seed),
        )
        cached = memoization_cache.get(cache_key)
        if cached is not None:
            return clone_fit_payload(cached)

    inferred_mode = 'unknown'
    if sample_size >= 1:
        inferred_mode = _infer_support_mode(values)

    if sample_size < 3:
        return _failure_result(
            sample_size,
            inferred_mode,
            warning='Distribution fit unavailable: at least 3 valid measurements are required.',
        )

    x_min = float(np.min(values))
    x_max = float(np.max(values))
    if np.isclose(x_min, x_max):
        return _failure_result(
            sample_size,
            inferred_mode,
            warning='Distribution fit unavailable: measurements are effectively constant.',
        )

    lsl_value = _safe_float(lsl)
    usl_value = _safe_float(usl)

    x_values = _resolve_curve_x_values(values, point_count=point_count)

    notes: list[str] = []
    candidates = []
    for candidate in _candidate_pool_for_mode(inferred_mode):
        try:
            fitted = _fit_candidate(candidate, values, kernel_mode=candidate_kernel_mode)
            if monte_carlo_gof_samples > 0:
                fitted['gof']['ad_pvalue'] = _estimate_ad_pvalue_monte_carlo(
                    dist=candidate.scipy_dist,
                    distribution_name=candidate.name,
                    params=fitted['params'],
                    sample_size=sample_size,
                    observed_stat=fitted['gof']['ad_statistic'],
                    iterations=monte_carlo_gof_samples,
                    random_seed=monte_carlo_seed,
                )
                fitted['gof']['ad_pvalue_method'] = 'ad_parametric_bootstrap'
            else:
                fitted['gof']['ad_pvalue'] = fitted['gof']['ks_pvalue']
                fitted['gof']['ad_pvalue_method'] = 'ks_proxy'
                notes.append('AD p-value estimated via KS proxy; set monte_carlo_gof_samples>0 for bootstrap.')
            candidates.append(fitted)
        except Exception as exc:
            notes.append(f"Skipped {candidate.name}: {exc}")

    if not candidates:
        return _failure_result(
            sample_size,
            inferred_mode,
            warning='Distribution fit failed for all candidate models.',
            notes=notes,
        )

    for candidate in candidates:
        gof_pvalue = candidate['gof']['ad_pvalue']
        candidate['gof']['is_acceptable'] = bool(
            gof_pvalue is not None and gof_pvalue >= gof_acceptance_alpha
        )

    acceptable = [c for c in candidates if c['gof']['is_acceptable']]
    if acceptable:
        best = min(acceptable, key=lambda c: c['metrics']['bic'])
        selection_mode = 'best_bic_among_acceptable_gof'
    else:
        best = min(candidates, key=lambda c: c['metrics']['bic'])
        selection_mode = 'best_bic_overall_downgraded_quality'
        notes.append('No model met GOF threshold; selected best BIC overall with downgraded quality.')

    ranked = sorted(candidates, key=lambda c: c['metrics']['bic'])

    selected_dist = next(
        c.scipy_dist for c in _candidate_pool_for_mode(inferred_mode) if c.name == best['model']
    )
    selected_pdf = _build_density_curve(selected_dist, best['params'], x_values)
    selected_cdf = _build_cdf_curve(selected_dist, best['params'], x_values)

    fit_quality = _classify_fit_quality(best['gof']['ad_pvalue'], best['gof']['is_acceptable'])

    result = DistributionFitResult(
        status='ok',
        warning=None,
        sample_size=sample_size,
        inferred_support_mode=inferred_mode,
        selected_model={
            'name': best['model'],
            'display_name': best['display_name'],
            'params': best['params'],
            'selection_mode': selection_mode,
        },
        selected_model_pdf=selected_pdf,
        selected_model_cdf=selected_cdf,
        kde_reference_pdf=_build_kde_reference_curve(values, x_values) if include_kde_reference else None,
        gof_metrics=best['gof'],
        ranking_metrics=[
            {
                'rank': idx + 1,
                'model': c['model'],
                'display_name': c['display_name'],
                'nll': c['metrics']['nll'],
                'aic': c['metrics']['aic'],
                'bic': c['metrics']['bic'],
                'ad_statistic': c['gof']['ad_statistic'],
                'ad_pvalue': c['gof']['ad_pvalue'],
                'ad_pvalue_method': c['gof']['ad_pvalue_method'],
                'ks_statistic': c['gof']['ks_statistic'],
                'ks_pvalue': c['gof']['ks_pvalue'],
                'is_acceptable_gof': c['gof']['is_acceptable'],
            }
            for idx, c in enumerate(ranked)
        ],
        fit_quality=fit_quality,
        risk_estimates=_compute_tail_risk(
            selected_dist,
            best['params'],
            lsl_value,
            usl_value,
            inferred_support_mode=inferred_mode,
        ),
        model_candidates=ranked,
        notes=sorted(set(notes)),
    )
    payload = result.to_dict()
    if memoization_cache is not None and cache_key is not None:
        memoization_cache[cache_key] = clone_fit_payload(payload)
    return payload


def fit_measurement_distribution_batch(
    grouped_measurements: dict[str, np.ndarray],
    *,
    lsl_by_group: dict[str, float | None] | None = None,
    usl_by_group: dict[str, float | None] | None = None,
    point_count: int = 100,
    include_kde_reference: bool = True,
    gof_acceptance_alpha: float = 0.05,
    monte_carlo_gof_samples: int = 0,
    monte_carlo_seed: int | None = None,
    candidate_kernel_mode: str | None = None,
    memoization_cache: MutableMapping | None = None,
    fingerprints_by_group: dict[str, tuple[int, str]] | None = None,
) -> dict[str, dict]:
    """Batch distribution-fit API for pre-cleaned, contiguous ndarray inputs."""

    lsl_by_group = lsl_by_group or {}
    usl_by_group = usl_by_group or {}
    result: dict[str, dict] = {}

    for group_name, values in grouped_measurements.items():
        group_values = np.ascontiguousarray(np.asarray(values, dtype=float))
        result[group_name] = fit_measurement_distribution(
            group_values,
            lsl=lsl_by_group.get(group_name),
            usl=usl_by_group.get(group_name),
            point_count=point_count,
            include_kde_reference=include_kde_reference,
            gof_acceptance_alpha=gof_acceptance_alpha,
            monte_carlo_gof_samples=monte_carlo_gof_samples,
            monte_carlo_seed=monte_carlo_seed,
            candidate_kernel_mode=candidate_kernel_mode,
            memoization_cache=memoization_cache,
            measurement_signature=None if fingerprints_by_group is None else fingerprints_by_group.get(group_name),
        )
    return result
