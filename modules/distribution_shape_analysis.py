"""Distribution-shape analysis helpers shared by group comparison exports."""

from __future__ import annotations

from itertools import combinations

import numpy as np
from scipy.stats import anderson_ksamp, ks_2samp, wasserstein_distance

from modules.comparison_stats import _adjust_pvalues
from modules.distribution_fit_service import fit_measurement_distribution


def _clean_numeric(values):
    arr = np.asarray(values, dtype=float)
    return arr[np.isfinite(arr)]


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


def _fit_profile_row(metric, group_name, values):
    numeric = _clean_numeric(values)
    fit = fit_measurement_distribution(numeric.tolist())
    fit_quality = (fit.get('fit_quality') or {}).get('label')
    gof = fit.get('gof_metrics') or {}
    selected_model = fit.get('selected_model') or {}
    support_mode = str(fit.get('inferred_support_mode') or 'unknown').replace('_', ' ')

    warning = fit.get('warning')
    if warning:
        warning_text = 'Distribution fit unavailable for this group.'
    else:
        warning_text = '; '.join(fit.get('notes') or []) or 'None'

    return {
        'Metric': metric,
        'Group': group_name,
        'n': int(numeric.size),
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


def build_distribution_profile_rows(metric, grouped_values):
    rows = []
    for group_name in sorted(grouped_values):
        rows.append(_fit_profile_row(metric, group_name, grouped_values[group_name]))
    return rows


def compute_distribution_difference(metric, grouped_values, *, alpha=0.05, correction_method='holm'):
    groups = sorted(grouped_values)
    numeric = {name: _clean_numeric(grouped_values[name]) for name in groups}
    profile_rows = build_distribution_profile_rows(metric, grouped_values)

    weak_fit_present = any(row['_fit_quality'] in {'weak', 'unreliable', ''} for row in profile_rows)
    fit_unavailable = any(row['_fit_status'] != 'ok' for row in profile_rows)

    pairwise_rows = []
    raw_p_values = []
    for group_a, group_b in combinations(groups, 2):
        sample_a = numeric[group_a]
        sample_b = numeric[group_b]
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

    omnibus_warning = 'None'
    omnibus_p = None
    omnibus_test = 'N/A'
    if len(groups) == 2:
        omnibus_test = 'Kolmogorov-Smirnov (2-sample)'
        if pairwise_rows:
            omnibus_p = pairwise_rows[0]['raw p-value']
    elif len(groups) >= 3:
        omnibus_test = 'Anderson-Darling k-sample'
        valid_samples = [numeric[group] for group in groups if numeric[group].size >= 2]
        if len(valid_samples) < 3:
            omnibus_warning = 'Too few samples for k-sample distribution test.'
        else:
            try:
                ad_result = anderson_ksamp(valid_samples)
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

    omnibus_row = {
        'Metric': metric,
        'Test used': omnibus_test,
        'raw p-value': omnibus_p,
        'adjusted p-value': None,
        'significant?': _yes_no(significant),
        'warning / assumptions': omnibus_warning,
        'comment / verdict': verdict,
    }
    return {
        'profile_rows': profile_rows,
        'omnibus_row': omnibus_row,
        'pairwise_rows': pairwise_rows,
    }
