"""Reusable statistical test-selection utilities for grouped numeric samples."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import warnings

import numpy as np
from scipy.stats import f, f_oneway, kruskal, levene, mannwhitneyu, shapiro, ttest_ind


@dataclass(frozen=True)
class GroupPreprocessResult:
    """Normalized values and preprocessing metadata for a single group."""

    label: str
    values: np.ndarray
    sample_size: int
    is_empty: bool
    is_constant: bool
    is_small_n: bool
    warnings: list[str]


def preprocess_group(label: Any, values: Any, *, small_n_threshold: int = 3) -> GroupPreprocessResult:
    """Coerce one group to numeric, drop NaNs, and return quality flags."""

    numeric_values = np.asarray(values, dtype=object)
    coerced: list[float] = []
    for value in numeric_values:
        try:
            coerced.append(float(value))
        except (TypeError, ValueError):
            coerced.append(np.nan)
    numeric_values = np.asarray(coerced, dtype=float)
    numeric_values = numeric_values[~np.isnan(numeric_values)]

    sample_size = int(numeric_values.size)
    is_empty = sample_size == 0
    is_constant = bool(sample_size > 1 and np.isclose(np.std(numeric_values, ddof=1), 0.0))
    is_small_n = sample_size < int(small_n_threshold)

    warnings: list[str] = []
    if is_empty:
        warnings.append('empty_after_nan_drop')
    if is_constant:
        warnings.append('constant_values')
    if is_small_n:
        warnings.append('small_n')

    return GroupPreprocessResult(
        label=str(label),
        values=numeric_values,
        sample_size=sample_size,
        is_empty=is_empty,
        is_constant=is_constant,
        is_small_n=is_small_n,
        warnings=warnings,
    )


def _safe_shapiro(values: np.ndarray) -> tuple[float | None, str]:
    n = int(values.size)
    if n < 3:
        return None, 'skipped_n_lt_3'
    if n > 5000:
        return None, 'skipped_n_gt_5000'
    if n > 1 and np.isclose(np.std(values, ddof=1), 0.0):
        return None, 'skipped_constant'

    stat, p_value = shapiro(values)
    if np.isnan(p_value):
        return None, 'failed'
    return float(p_value), 'ok'


def _welch_anova_p_value(groups: list[np.ndarray]) -> float | None:
    # Welch (1951) one-way ANOVA approximation.
    sizes = np.array([len(group) for group in groups], dtype=float)
    variances = np.array([np.var(group, ddof=1) for group in groups], dtype=float)
    means = np.array([np.mean(group) for group in groups], dtype=float)

    if np.any(sizes < 2) or np.any(variances <= 0):
        return None

    weights = sizes / variances
    weight_sum = float(np.sum(weights))
    if weight_sum <= 0:
        return None

    weighted_mean = float(np.sum(weights * means) / weight_sum)
    k = float(len(groups))

    numerator = np.sum(weights * (means - weighted_mean) ** 2) / (k - 1.0)
    correction = 1.0 + (2.0 * (k - 2.0) / (k**2 - 1.0)) * np.sum(((1.0 - (weights / weight_sum)) ** 2) / (sizes - 1.0))
    if np.isclose(correction, 0.0):
        return None

    f_stat = numerator / correction
    df1 = k - 1.0
    df2_denom = 3.0 * np.sum(((1.0 - (weights / weight_sum)) ** 2) / (sizes - 1.0))
    if np.isclose(df2_denom, 0.0):
        return None
    df2 = (k**2 - 1.0) / df2_denom
    if df1 <= 0 or df2 <= 0:
        return None

    p_value = 1.0 - f.cdf(f_stat, df1, df2)
    return None if np.isnan(p_value) else float(p_value)


def select_group_stat_test(
    labels: list[Any],
    grouped_values: list[Any],
    *,
    alpha: float = 0.05,
    small_n_threshold: int = 3,
    variance_test: str = 'brown_forsythe',
) -> dict[str, Any]:
    """Select and run a statistical test from grouped samples with assumption checks."""

    if len(labels) != len(grouped_values):
        return {
            'test_name': None,
            'p_value': None,
            'sample_sizes': {},
            'assumptions': {
                'normality': {},
                'variance_homogeneity': {'test': None, 'p_value': None, 'status': 'not_checked'},
            },
            'assumption_outcomes': {
                'normality': 'not_checked',
                'variance_homogeneity': 'not_checked',
                'selection_mode': 'unavailable',
                'selection_detail': 'Assumption checks were not completed because labels and grouped values had different lengths.',
            },
            'warnings': ['input_length_mismatch'],
            'preprocess': {},
        }

    preprocessed = [
        preprocess_group(label, values, small_n_threshold=small_n_threshold)
        for label, values in zip(labels, grouped_values)
    ]
    usable = [group for group in preprocessed if not group.is_empty]

    sample_sizes = {group.label: group.sample_size for group in preprocessed}
    preprocess_warnings = {group.label: group.warnings for group in preprocessed if group.warnings}

    result: dict[str, Any] = {
        'test_name': None,
        'p_value': None,
        'sample_sizes': sample_sizes,
        'assumptions': {
            'normality': {},
            'variance_homogeneity': {'test': None, 'p_value': None, 'status': 'not_checked'},
        },
        'assumption_outcomes': {
            'normality': 'not_checked',
            'variance_homogeneity': 'not_checked',
            'selection_mode': 'unavailable',
            'selection_detail': 'Assumption checks were not completed.',
        },
        'warnings': [],
        'preprocess': preprocess_warnings,
    }

    if len(usable) < 2:
        result['warnings'].append('fewer_than_two_non_empty_groups')
        return result

    shapiro_results: dict[str, dict[str, Any]] = {}
    normality_failures = 0
    for group in usable:
        p_value, status = _safe_shapiro(group.values)
        passed = None if p_value is None else bool(p_value >= alpha)
        if passed is False:
            normality_failures += 1
        shapiro_results[group.label] = {'p_value': p_value, 'status': status, 'passed': passed}

    result['assumptions']['normality'] = shapiro_results
    any_normality_measured = any(item.get('passed') is not None for item in shapiro_results.values())
    any_normality_skipped = any(item.get('status') != 'ok' for item in shapiro_results.values())
    normality_pass = normality_failures == 0 and any_normality_measured

    if normality_failures > 0:
        normality_outcome = 'failed'
        normality_detail = 'At least one usable group failed Shapiro-Wilk, so the selection falls back to the non-parametric path.'
    elif any_normality_measured and not any_normality_skipped:
        normality_outcome = 'passed'
        normality_detail = 'All usable groups passed Shapiro-Wilk, so parametric paths remain eligible.'
    elif any_normality_measured and any_normality_skipped:
        normality_outcome = 'mixed'
        normality_detail = 'Some groups passed Shapiro-Wilk but at least one check was skipped, so selection treats normality as unresolved and uses the non-parametric path.'
    else:
        normality_outcome = 'skipped'
        normality_detail = 'All usable normality checks were skipped, so selection treats normality as unresolved and uses the non-parametric path.'

    center = 'median' if variance_test == 'brown_forsythe' else 'mean'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        _, lev_p = levene(*(group.values for group in usable), center=center)
    variance_passed = bool(not np.isnan(lev_p) and lev_p >= alpha)
    variance_outcome = 'passed' if variance_passed else 'failed'
    result['assumptions']['variance_homogeneity'] = {
        'test': 'Brown-Forsythe' if center == 'median' else 'Levene',
        'p_value': None if np.isnan(lev_p) else float(lev_p),
        'status': variance_outcome,
    }

    k = len(usable)
    arrays = [group.values for group in usable]

    if any(group.sample_size < 2 for group in usable):
        result['assumption_outcomes'] = {
            'normality': normality_outcome,
            'variance_homogeneity': variance_outcome,
            'selection_mode': 'unavailable',
            'selection_detail': 'At least one usable group had fewer than 2 values, so no omnibus test was selected.',
        }
        result['warnings'].append('contains_group_with_n_lt_2')
        return result

    selection_mode = 'non_parametric'
    selection_detail = normality_detail
    try:
        if k == 2:
            if normality_pass:
                if variance_passed:
                    _, p_value = ttest_ind(arrays[0], arrays[1], equal_var=True, nan_policy='omit')
                    result['test_name'] = 'Student t-test'
                    selection_mode = 'parametric_equal_variance'
                    selection_detail = 'Shapiro-Wilk passed for all usable groups and Brown-Forsythe/Levene passed, so the equal-variance parametric path was used.'
                else:
                    _, p_value = ttest_ind(arrays[0], arrays[1], equal_var=False, nan_policy='omit')
                    result['test_name'] = 'Welch t-test'
                    selection_mode = 'parametric_unequal_variance'
                    selection_detail = 'Shapiro-Wilk passed for all usable groups but Brown-Forsythe/Levene failed, so the unequal-variance parametric path was used.'
            else:
                _, p_value = mannwhitneyu(arrays[0], arrays[1], alternative='two-sided')
                result['test_name'] = 'Mann-Whitney U'
                selection_mode = 'non_parametric'
                selection_detail = normality_detail
        else:
            if normality_pass:
                if variance_passed:
                    _, p_value = f_oneway(*arrays)
                    result['test_name'] = 'ANOVA'
                    selection_mode = 'parametric_equal_variance'
                    selection_detail = 'Shapiro-Wilk passed for all usable groups and Brown-Forsythe/Levene passed, so ANOVA was used.'
                else:
                    p_value = _welch_anova_p_value(arrays)
                    result['test_name'] = 'Welch ANOVA'
                    selection_mode = 'parametric_unequal_variance'
                    selection_detail = 'Shapiro-Wilk passed for all usable groups but Brown-Forsythe/Levene failed, so Welch ANOVA was used.'
            else:
                _, p_value = kruskal(*arrays)
                result['test_name'] = 'Kruskal-Wallis'
                selection_mode = 'non_parametric'
                selection_detail = normality_detail

        if p_value is None or np.isnan(p_value):
            result['warnings'].append('test_returned_nan')
        else:
            result['p_value'] = float(p_value)
    except ValueError as exc:
        result['warnings'].append(f'test_error:{exc}')

    result['assumption_outcomes'] = {
        'normality': normality_outcome,
        'variance_homogeneity': variance_outcome,
        'selection_mode': selection_mode,
        'selection_detail': selection_detail,
    }

    if any(group.is_constant for group in usable):
        result['warnings'].append('contains_constant_group')

    return result
