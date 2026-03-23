"""Distribution-shape analysis helpers shared by group comparison exports."""

from __future__ import annotations

from functools import lru_cache
from itertools import combinations
import hashlib
import inspect
import warnings

import numpy as np
from scipy.stats import anderson_ksamp, ks_2samp, wasserstein_distance

from modules.comparison_stats import _adjust_pvalues
from modules.distribution_fit_service import fit_measurement_distribution


DEFAULT_DISTRIBUTION_FIT_POLICY = {
    'mode': 'always',
    'max_fit_samples_per_metric': None,
}


def resolve_distribution_fit_policy(policy=None):
    resolved = dict(DEFAULT_DISTRIBUTION_FIT_POLICY)
    if policy:
        resolved.update(policy)
    resolved['mode'] = str(resolved.get('mode') or 'always').strip().lower()
    max_fit_samples = resolved.get('max_fit_samples_per_metric')
    resolved['max_fit_samples_per_metric'] = int(max_fit_samples) if max_fit_samples not in {None, ''} else None
    return resolved


def should_profile_distribution_fits(*, grouped_numeric, policy=None):
    resolved = resolve_distribution_fit_policy(policy)
    mode = resolved['mode']
    if mode == 'never':
        return False
    if mode == 'always':
        return True
    if mode == 'skip_large_exports':
        max_fit_samples = resolved.get('max_fit_samples_per_metric')
        if max_fit_samples is None:
            return True
        total_samples = sum(int(values.size) for values in grouped_numeric.values())
        return total_samples <= max_fit_samples
    return True


def _clean_numeric(values):
    arr = np.asarray(values, dtype=float)
    return arr[np.isfinite(arr)]


def _sample_fingerprint(values):
    numeric = np.ascontiguousarray(np.asarray(values, dtype=np.float64))
    digest = hashlib.sha1(numeric.tobytes()).hexdigest()
    return (int(numeric.size), digest)


def _get_cached_fit_result(*, metric, group_name, numeric_values, fit_cache=None):
    if fit_cache is None:
        return fit_measurement_distribution(numeric_values.tolist())

    cache_key = (metric, group_name, _sample_fingerprint(numeric_values))
    if cache_key not in fit_cache:
        fit_cache[cache_key] = fit_measurement_distribution(numeric_values.tolist())
    return fit_cache[cache_key]


def _yes_no(flag):
    return 'YES' if bool(flag) else 'NO'


def _wasserstein_severity_label(distance):
    numeric_distance = float(distance) if distance is not None else None
    if numeric_distance is None:
        return 'Not reported'
    absolute_distance = abs(numeric_distance)
    if absolute_distance < 0.1:
        return 'Low'
    if absolute_distance < 0.5:
        return 'Moderate'
    return 'High'


def _summarize_fit_notes(notes):
    normalized = [str(note or '').strip() for note in (notes or []) if str(note or '').strip()]
    if not normalized:
        return 'Use fit quality as guidance only.'
    if any('monte_carlo_gof_samples>0' in note or 'ks proxy' in note.lower() for note in normalized):
        return 'Model fit quality is approximate.'
    if any(note.lower().startswith('skipped ') for note in normalized):
        return 'Fit quality estimated approximately.'
    return 'Use fit quality as guidance only.'


@lru_cache(maxsize=1)
def _anderson_ksamp_supports_variant():
    return 'variant' in inspect.signature(anderson_ksamp).parameters


def _run_anderson_ksamp(samples):
    kwargs = {'variant': True} if _anderson_ksamp_supports_variant() else {'midrank': True}
    with warnings.catch_warnings():
        warnings.filterwarnings(
            'ignore',
            message=r'p-value (?:floored|capped): .*',
            category=UserWarning,
        )
        return anderson_ksamp(samples, **kwargs)


def _build_fit_profile_row(metric, group_name, numeric_values, *, fit_cache=None):
    fit = _get_cached_fit_result(
        metric=metric,
        group_name=group_name,
        numeric_values=numeric_values,
        fit_cache=fit_cache,
    )
    fit_quality = (fit.get('fit_quality') or {}).get('label')
    gof = fit.get('gof_metrics') or {}
    selected_model = fit.get('selected_model') or {}
    support_mode = str(fit.get('inferred_support_mode') or 'unknown').replace('_', ' ')

    warning = fit.get('warning')
    if warning:
        warning_text = 'Distribution fit unavailable for this group.'
    else:
        warning_text = _summarize_fit_notes(fit.get('notes') or [])

    return {
        'Metric': metric,
        'Group': group_name,
        'n': int(numeric_values.size),
        'best fit model': selected_model.get('display_name') or 'Not available',
        'fit quality': fit_quality or 'unreliable',
        'AD p-value': gof.get('ad_pvalue'),
        'KS p-value': gof.get('ks_pvalue'),
        'GOF acceptable?': _yes_no(gof.get('is_acceptable')),
        'Support mode': support_mode,
        'Warning / notes summary': warning_text,
        '_fit_status': fit.get('status'),
        '_fit_quality': str(fit_quality or '').lower(),
    }


def build_distribution_profile_rows(metric, grouped_values, *, fit_cache=None, values_are_clean=False):
    numeric_by_group = {
        group_name: (np.asarray(values, dtype=float) if values_are_clean else _clean_numeric(values))
        for group_name, values in grouped_values.items()
    }
    rows = []
    for group_name in sorted(numeric_by_group):
        rows.append(
            _build_fit_profile_row(
                metric,
                group_name,
                numeric_by_group[group_name],
                fit_cache=fit_cache,
            )
        )
    return rows


def _build_profile_rows(metric, numeric_by_group, *, fit_cache=None, fit_policy=None):
    if not should_profile_distribution_fits(grouped_numeric=numeric_by_group, policy=fit_policy):
        return [
            {
                'Metric': metric,
                'Group': group_name,
                'n': int(values.size),
                'best fit model': 'Skipped by policy',
                'fit quality': 'not run',
                'AD p-value': None,
                'KS p-value': None,
                'GOF acceptable?': 'NO',
                'Support mode': 'not assessed',
                'Warning / notes summary': 'Distribution fit skipped by policy for large exports.',
                '_fit_status': 'skipped_policy',
                '_fit_quality': 'not run',
            }
            for group_name, values in sorted(numeric_by_group.items())
        ]
    return build_distribution_profile_rows(
        metric,
        numeric_by_group,
        fit_cache=fit_cache,
        values_are_clean=True,
    )


def _build_pairwise_comparison_rows(metric, numeric_by_group, *, alpha=0.05, correction_method='holm', weak_fit_present=False):
    pairwise_rows = []
    raw_p_values = []
    for group_a, group_b in combinations(sorted(numeric_by_group), 2):
        sample_a = numeric_by_group[group_a]
        sample_b = numeric_by_group[group_b]
        test_used = 'Kolmogorov-Smirnov (2-sample)'
        p_value = None
        distance = None
        flags = []

        if sample_a.size < 2 or sample_b.size < 2:
            flags.append('LOW N')
            comment = 'descriptive only: insufficient data for a stable distribution shape test.'
            verdict = 'descriptive only'
        elif np.isclose(np.std(sample_a), 0.0) and np.isclose(np.std(sample_b), 0.0):
            flags.append('LOW VARIATION')
            comment = 'caution: both groups are nearly constant, so the distribution shape test has limited value.'
            verdict = 'caution'
        else:
            stat = ks_2samp(sample_a, sample_b, alternative='two-sided', mode='auto')
            p_value = float(stat.pvalue)
            distance = float(wasserstein_distance(sample_a, sample_b))
            verdict = 'difference' if p_value < alpha else 'no difference'
            comment = 'difference detected in distribution shape.' if p_value < alpha else 'No statistically significant distribution shape difference detected.'
            if weak_fit_present:
                flags.append('FIT QUALITY CAUTION')
                if verdict == 'difference':
                    verdict = 'caution'
                    comment = 'caution: shape signal detected, but one or more group fit quality results are weak/unreliable.'

        raw_p_values.append(p_value)
        pairwise_rows.append(
            {
                'Metric': metric,
                'Group A': group_a,
                'Group B': group_b,
                'distribution test used': test_used,
                'raw p-value': p_value,
                'adjusted p-value': None,
                'distance metric': distance,
                'Wasserstein distance': distance,
                'Practical severity': _wasserstein_severity_label(distance) if distance is not None else 'Not reported',
                'verdict': verdict,
                'comment': comment,
                'flags': '; '.join(flags) if flags else 'none',
            }
        )

    adjusted = _adjust_pvalues(raw_p_values, correction_method)
    for row, adj in zip(pairwise_rows, adjusted):
        row['adjusted p-value'] = adj
        if adj is not None and row['verdict'] not in {'descriptive only', 'caution'}:
            row['verdict'] = 'difference' if adj < alpha else 'no difference'
            row['comment'] = (
                'difference in distribution shape remains significant after multiple-comparison correction.'
                if adj < alpha
                else 'No distribution shape difference after multiple-comparison correction.'
            )
    return pairwise_rows


def _build_omnibus_result(metric, numeric_by_group, profile_rows, pairwise_rows, *, alpha=0.05):
    groups = sorted(numeric_by_group)
    fit_unavailable = any(row['_fit_status'] not in {'ok', 'skipped_policy'} for row in profile_rows)
    omnibus_warning = 'None'
    omnibus_p = None
    omnibus_test = 'N/A'
    if len(groups) == 2:
        omnibus_test = 'Kolmogorov-Smirnov (2-sample)'
        if pairwise_rows:
            omnibus_p = pairwise_rows[0]['raw p-value']
    elif len(groups) >= 3:
        omnibus_test = 'Anderson-Darling k-sample'
        valid_samples = [numeric_by_group[group] for group in groups if numeric_by_group[group].size >= 2]
        if len(valid_samples) < 3:
            omnibus_warning = 'Too few samples for k-sample distribution test.'
        else:
            try:
                ad_result = _run_anderson_ksamp(valid_samples)
                omnibus_p = float(getattr(ad_result, 'pvalue', np.nan))
            except Exception:
                omnibus_warning = 'Distribution difference test was not reliable for this metric.'

    significant = bool(omnibus_p is not None and np.isfinite(omnibus_p) and omnibus_p < alpha)
    if fit_unavailable:
        omnibus_warning = 'Interpret with caution: distribution fit is unavailable for one or more groups.'

    verdict = (
        'difference detected in distribution shape.'
        if significant
        else 'No statistically significant distribution shape differences were detected.'
    )
    if fit_unavailable:
        verdict = 'caution: distribution fit quality is unreliable for one or more groups.'

    return {
        'Metric': metric,
        'Test used': omnibus_test,
        'raw p-value': omnibus_p,
        'adjusted p-value': None,
        'significant?': _yes_no(significant),
        'warning / assumptions': omnibus_warning,
        'comment / verdict': verdict,
    }


def compute_distribution_difference(
    metric,
    grouped_values,
    *,
    alpha=0.05,
    correction_method='holm',
    fit_cache=None,
    fit_policy=None,
):
    numeric_by_group = {name: _clean_numeric(grouped_values[name]) for name in sorted(grouped_values)}
    profile_rows = _build_profile_rows(metric, numeric_by_group, fit_cache=fit_cache, fit_policy=fit_policy)
    weak_fit_present = any(row['_fit_quality'] in {'weak', 'unreliable', ''} for row in profile_rows)
    pairwise_rows = _build_pairwise_comparison_rows(
        metric,
        numeric_by_group,
        alpha=alpha,
        correction_method=correction_method,
        weak_fit_present=weak_fit_present,
    )
    omnibus_row = _build_omnibus_result(metric, numeric_by_group, profile_rows, pairwise_rows, alpha=alpha)
    return {
        'profile_rows': profile_rows,
        'omnibus_row': omnibus_row,
        'pairwise_rows': pairwise_rows,
    }
