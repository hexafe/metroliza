"""Fit candidate probability distributions and summarize fit/risk diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde, kstest, laplace, logistic, norm


@dataclass(frozen=True)
class _CandidateDistribution:
    name: str
    display_name: str
    scipy_dist: object
    fit_method: Callable[[np.ndarray], tuple]


_CANDIDATES: tuple[_CandidateDistribution, ...] = (
    _CandidateDistribution(name='normal', display_name='Normal', scipy_dist=norm, fit_method=norm.fit),
    _CandidateDistribution(name='logistic', display_name='Logistic', scipy_dist=logistic, fit_method=logistic.fit),
    _CandidateDistribution(name='laplace', display_name='Laplace', scipy_dist=laplace, fit_method=laplace.fit),
)


def _safe_float(value):
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _quality_label(*, ks_pvalue: float | None):
    if ks_pvalue is None:
        return {'label': 'unknown', 'score': 0.0}
    if ks_pvalue >= 0.20:
        return {'label': 'excellent', 'score': 1.0}
    if ks_pvalue >= 0.10:
        return {'label': 'good', 'score': 0.8}
    if ks_pvalue >= 0.05:
        return {'label': 'fair', 'score': 0.6}
    if ks_pvalue >= 0.01:
        return {'label': 'weak', 'score': 0.35}
    return {'label': 'poor', 'score': 0.1}


def _risk_label(total_outside_probability: float | None):
    if total_outside_probability is None:
        return 'unknown'
    if total_outside_probability <= 1e-4:
        return 'low'
    if total_outside_probability <= 1e-3:
        return 'moderate'
    if total_outside_probability <= 1e-2:
        return 'elevated'
    return 'high'


def _build_density_curve(dist, params, x_values):
    y_values = dist.pdf(x_values, *params)
    if not np.all(np.isfinite(y_values)):
        return None
    return {
        'x': np.asarray(x_values),
        'y': np.asarray(y_values),
    }


def _build_kde_reference_curve(numeric_measurements: np.ndarray, x_values: np.ndarray):
    if numeric_measurements.size < 2:
        return None
    try:
        kde = gaussian_kde(numeric_measurements)
        y_values = kde(x_values)
    except Exception:
        return None
    if not np.all(np.isfinite(y_values)):
        return None
    return {
        'x': np.asarray(x_values),
        'y': np.asarray(y_values),
    }


def fit_measurement_distribution(
    measurements,
    *,
    lsl=None,
    usl=None,
    nom=None,
    point_count: int = 100,
    include_kde_reference: bool = True,
):
    """Fit candidate distributions and return model ranking + overlay payloads.

    Returns a dictionary payload intended for histogram overlays and summary annotations.
    """

    lsl_value = _safe_float(lsl)
    usl_value = _safe_float(usl)
    nom_value = _safe_float(nom)

    numeric_measurements = (
        pd.to_numeric(pd.Series(list(measurements)), errors='coerce').dropna().to_numpy(dtype=float)
    )
    sample_size = int(numeric_measurements.size)

    failure_payload = {
        'status': 'failed',
        'warning': 'Distribution fit unavailable; using descriptive histogram only.',
        'sample_size': sample_size,
        'selected_model': None,
        'selected_model_pdf': None,
        'kde_reference_pdf': None,
        'gof_metrics': None,
        'ranking_metrics': [],
        'fit_quality': {'label': 'unknown', 'score': 0.0},
        'risk_estimates': {
            'below_lsl_probability': None,
            'above_usl_probability': None,
            'outside_probability': None,
            'expected_ppm_outside': None,
            'risk_label': 'unknown',
            'nominal_probability_density': None,
        },
        'model_candidates': [],
    }

    if sample_size < 3:
        return failure_payload

    x_min = float(np.min(numeric_measurements))
    x_max = float(np.max(numeric_measurements))
    if np.isclose(x_min, x_max):
        return failure_payload

    spread = x_max - x_min
    x_values = np.linspace(x_min - 0.03 * spread, x_max + 0.03 * spread, max(point_count, 20))

    candidates = []
    for candidate in _CANDIDATES:
        try:
            params = tuple(candidate.fit_method(numeric_measurements))
            log_likelihood_terms = candidate.scipy_dist.logpdf(numeric_measurements, *params)
            if not np.all(np.isfinite(log_likelihood_terms)):
                continue
            log_likelihood = float(np.sum(log_likelihood_terms))
            parameter_count = len(params)
            aic = float((2 * parameter_count) - (2 * log_likelihood))
            bic = float((parameter_count * math.log(sample_size)) - (2 * log_likelihood))
            ks_statistic, ks_pvalue = kstest(numeric_measurements, candidate.scipy_dist.cdf, args=params)

            candidates.append(
                {
                    'model': candidate.name,
                    'display_name': candidate.display_name,
                    'params': tuple(float(value) for value in params),
                    'log_likelihood': log_likelihood,
                    'aic': aic,
                    'bic': bic,
                    'ks_statistic': float(ks_statistic),
                    'ks_pvalue': float(ks_pvalue),
                }
            )
        except Exception:
            continue

    if not candidates:
        return failure_payload

    ranked_candidates = sorted(candidates, key=lambda item: (item['bic'], item['ks_statistic'], item['aic']))
    selected = ranked_candidates[0]

    candidate_dist = next(item for item in _CANDIDATES if item.name == selected['model'])
    selected_pdf = _build_density_curve(candidate_dist.scipy_dist, selected['params'], x_values)
    if selected_pdf is None:
        return failure_payload

    ranking_metrics = []
    for rank, candidate in enumerate(ranked_candidates, start=1):
        ranking_metrics.append(
            {
                'rank': rank,
                'model': candidate['model'],
                'display_name': candidate['display_name'],
                'aic': candidate['aic'],
                'bic': candidate['bic'],
                'ks_statistic': candidate['ks_statistic'],
                'ks_pvalue': candidate['ks_pvalue'],
            }
        )

    selected_dist = candidate_dist.scipy_dist
    selected_params = selected['params']

    below_lsl = float(selected_dist.cdf(lsl_value, *selected_params)) if lsl_value is not None else None
    above_usl = float(1.0 - selected_dist.cdf(usl_value, *selected_params)) if usl_value is not None else None

    outside_probability = 0.0
    has_bound = False
    if below_lsl is not None:
        outside_probability += max(0.0, min(1.0, below_lsl))
        has_bound = True
    if above_usl is not None:
        outside_probability += max(0.0, min(1.0, above_usl))
        has_bound = True
    outside_probability = max(0.0, min(1.0, outside_probability)) if has_bound else None

    nominal_density = None
    if nom_value is not None:
        try:
            nominal_density = float(selected_dist.pdf(nom_value, *selected_params))
            if not np.isfinite(nominal_density):
                nominal_density = None
        except Exception:
            nominal_density = None

    fit_quality = _quality_label(ks_pvalue=selected['ks_pvalue'])

    return {
        'status': 'ok',
        'warning': None,
        'sample_size': sample_size,
        'selected_model': {
            'name': selected['model'],
            'display_name': selected['display_name'],
            'params': selected['params'],
        },
        'selected_model_pdf': selected_pdf,
        'kde_reference_pdf': _build_kde_reference_curve(numeric_measurements, x_values) if include_kde_reference else None,
        'gof_metrics': {
            'ks_statistic': selected['ks_statistic'],
            'ks_pvalue': selected['ks_pvalue'],
            'log_likelihood': selected['log_likelihood'],
        },
        'ranking_metrics': ranking_metrics,
        'fit_quality': fit_quality,
        'risk_estimates': {
            'below_lsl_probability': below_lsl,
            'above_usl_probability': above_usl,
            'outside_probability': outside_probability,
            'expected_ppm_outside': (outside_probability * 1_000_000.0) if outside_probability is not None else None,
            'risk_label': _risk_label(outside_probability),
            'nominal_probability_density': nominal_density,
        },
        'model_candidates': ranked_candidates,
    }
