"""Distribution fitting helpers with GOF, model selection, and tail-risk estimation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import (
    foldnorm,
    gamma,
    gaussian_kde,
    halfnorm,
    johnsonsu,
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


def _safe_float(value):
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


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
    params: tuple,
    sample_size: int,
    observed_stat: float,
    iterations: int,
    random_seed: int | None,
):
    if iterations <= 0:
        return None
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


def _fit_candidate(candidate: _CandidateDistribution, values: np.ndarray):
    fit_kwargs = {'floc': 0.0} if candidate.force_loc_zero else {}
    params = tuple(candidate.fit_method(values, **fit_kwargs))
    if candidate.positive_support and params:
        params = list(params)
        params[-2] = 0.0
        params = tuple(params)

    logpdf = candidate.scipy_dist.logpdf(values, *params)
    if not np.all(np.isfinite(logpdf)):
        raise ValueError('logpdf returned invalid values')

    n = values.size
    nll = float(-np.sum(logpdf))
    k = len(params)
    aic = float(2 * k + 2 * nll)
    bic = float(k * math.log(n) + 2 * nll)

    ad_stat = _ad_statistic(values, lambda x: candidate.scipy_dist.cdf(x, *params))
    ks_stat, ks_pvalue = kstest(values, candidate.scipy_dist.cdf, args=params)

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


def _compute_tail_risk(dist, params, lsl, usl) -> dict:
    below_lsl = None if lsl is None else float(np.clip(dist.cdf(lsl, *params), 0.0, 1.0))
    above_usl = None if usl is None else float(np.clip(1.0 - dist.cdf(usl, *params), 0.0, 1.0))

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
):
    """Fit distributions, score GOF, classify quality, and estimate tail risk.

    Returns a dictionary payload for compatibility with existing render/export paths.
    """

    del nom  # kept for backwards compatibility in call-sites.

    values = pd.to_numeric(pd.Series(list(measurements)), errors='coerce').dropna().to_numpy(dtype=float)
    sample_size = int(values.size)

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

    spread = x_max - x_min
    x_values = np.linspace(x_min - 0.03 * spread, x_max + 0.03 * spread, max(20, point_count))

    notes: list[str] = []
    candidates = []
    for candidate in _candidate_pool_for_mode(inferred_mode):
        try:
            fitted = _fit_candidate(candidate, values)
            if monte_carlo_gof_samples > 0:
                fitted['gof']['ad_pvalue'] = _estimate_ad_pvalue_monte_carlo(
                    dist=candidate.scipy_dist,
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
        risk_estimates=_compute_tail_risk(selected_dist, best['params'], lsl_value, usl_value),
        model_candidates=ranked,
        notes=sorted(set(notes)),
    )
    return result.to_dict()
