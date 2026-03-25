"""Pairwise comparison statistics for grouped metric samples.

Statistical rationale:
    - Reuses assumption checks from :mod:`modules.group_stats_tests` to align
      pairwise test choice with omnibus selection (parametric vs non-parametric).
    - Applies multiplicity correction (Holm default) before significance flags.
    - Reports practical effect magnitudes to complement p-values.

Fallback behavior:
    - This module currently uses pairwise tests plus multiplicity correction,
      not dedicated post-hoc procedures such as Tukey/Games-Howell/Dunn.
    - Invalid/insufficient groups propagate ``None`` p-values/effects rather than
      raising, allowing export pipelines to keep deterministic table shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Callable

import numpy as np
from scipy.stats import mannwhitneyu, rankdata, ttest_ind

from modules.comparison_stats_native import bootstrap_percentile_ci_native, pairwise_stats_native
from modules.group_stats_tests import select_group_stat_test


@dataclass(frozen=True)
class ComparisonStatsConfig:
    alpha: float = 0.05
    correction_method: str = 'holm'
    include_effect_size_ci: bool = False
    ci_level: float = 0.95
    ci_bootstrap_iterations: int = 1000
    multi_group_effect: str = 'eta_squared'


def _cohen_d(sample_a: np.ndarray, sample_b: np.ndarray) -> float | None:
    if sample_a.size < 2 or sample_b.size < 2:
        return None
    var_a = float(np.var(sample_a, ddof=1))
    var_b = float(np.var(sample_b, ddof=1))
    pooled_num = (sample_a.size - 1) * var_a + (sample_b.size - 1) * var_b
    pooled_den = sample_a.size + sample_b.size - 2
    if pooled_den <= 0:
        return None
    pooled = pooled_num / pooled_den
    if pooled <= 0:
        return None
    return float((np.mean(sample_a) - np.mean(sample_b)) / np.sqrt(pooled))


def _cliffs_delta(sample_a: np.ndarray, sample_b: np.ndarray) -> float | None:
    if sample_a.size == 0 or sample_b.size == 0:
        return None

    n_a = sample_a.size
    n_b = sample_b.size
    pooled = np.concatenate((sample_a, sample_b))
    ranks = rankdata(pooled, method='average')
    rank_sum_a = float(np.sum(ranks[:n_a], dtype=np.float64))
    u_statistic = rank_sum_a - (n_a * (n_a + 1) / 2.0)
    return float((2.0 * u_statistic) / (n_a * n_b) - 1.0)


def _eta_or_omega_squared(groups: list[np.ndarray], *, use_omega: bool) -> float | None:
    if len(groups) < 2:
        return None
    sizes = np.array([group.size for group in groups], dtype=float)
    if np.any(sizes < 2):
        return None
    values = np.concatenate(groups)
    grand_mean = float(np.mean(values))
    ss_between = float(np.sum([group.size * (np.mean(group) - grand_mean) ** 2 for group in groups]))
    ss_within = float(np.sum([np.sum((group - np.mean(group)) ** 2) for group in groups]))
    ss_total = ss_between + ss_within
    if np.isclose(ss_total, 0.0):
        return None
    if not use_omega:
        return float(ss_between / ss_total)

    df_between = float(len(groups) - 1)
    df_within = float(values.size - len(groups))
    if df_within <= 0:
        return None
    ms_within = ss_within / df_within
    denom = ss_total + ms_within
    if np.isclose(denom, 0.0):
        return None
    omega_sq = (ss_between - (df_between * ms_within)) / denom
    return float(max(0.0, omega_sq))


def _bootstrap_ci(
    *,
    rng: np.random.Generator,
    sample_builder: Callable[[], Any],
    effect_fn: Callable[[Any], float | None],
    level: float,
    iterations: int,
) -> tuple[float, float] | None:
    estimates: list[float] = []
    for _ in range(max(1, iterations)):
        sampled = sample_builder()
        estimate = effect_fn(sampled)
        if estimate is not None and not np.isnan(estimate):
            estimates.append(float(estimate))
    if not estimates:
        return None

    lower_q = ((1.0 - level) / 2.0) * 100.0
    upper_q = (1.0 - (1.0 - level) / 2.0) * 100.0
    return (float(np.percentile(estimates, lower_q)), float(np.percentile(estimates, upper_q)))


def _bootstrap_effect_percentile_ci(
    *,
    effect_kernel: str,
    groups: list[np.ndarray],
    level: float,
    iterations: int,
    seed: int = 42,
) -> tuple[float, float] | None:
    native_ci = bootstrap_percentile_ci_native(
        effect_kernel=effect_kernel,
        groups=[np.ascontiguousarray(group, dtype=np.float64) for group in groups],
        level=level,
        iterations=iterations,
        seed=seed,
    )
    if native_ci is not None:
        return native_ci

    rng = np.random.default_rng(seed)
    if effect_kernel in {'cohen_d', 'cliffs_delta'}:
        if len(groups) != 2:
            return None
        sample_a = groups[0]
        sample_b = groups[1]
        if sample_a.size == 0 or sample_b.size == 0:
            return None
        return _bootstrap_ci(
            rng=rng,
            sample_builder=lambda: [
                sample_a[rng.integers(0, sample_a.size, sample_a.size)],
                sample_b[rng.integers(0, sample_b.size, sample_b.size)],
            ],
            effect_fn=lambda sampled: _pairwise_effect_size(
                sampled[0],
                sampled[1],
                non_parametric=effect_kernel == 'cliffs_delta',
            ),
            level=level,
            iterations=iterations,
        )

    if effect_kernel in {'eta_squared', 'omega_squared'}:
        if len(groups) < 2 or any(group.size == 0 for group in groups):
            return None
        return _bootstrap_ci(
            rng=rng,
            sample_builder=lambda: [group[rng.integers(0, group.size, group.size)] for group in groups],
            effect_fn=lambda sampled: _eta_or_omega_squared(sampled, use_omega=effect_kernel == 'omega_squared'),
            level=level,
            iterations=iterations,
        )
    raise ValueError(f'Unsupported effect kernel: {effect_kernel}')


def _adjust_pvalues(p_values: list[float | None], method: str) -> list[float | None]:
    indexed = [(idx, p) for idx, p in enumerate(p_values) if p is not None and not np.isnan(p)]
    adjusted: list[float | None] = [None] * len(p_values)
    if not indexed:
        return adjusted

    m = len(indexed)
    sorted_pairs = sorted(indexed, key=lambda x: x[1])

    normalized = _normalize_correction_method(method)
    if normalized == 'holm':
        running_max = 0.0
        for rank, (original_idx, p_value) in enumerate(sorted_pairs):
            factor = m - rank
            corrected = min(1.0, p_value * factor)
            running_max = max(running_max, corrected)
            adjusted[original_idx] = float(running_max)
    elif normalized == 'bh':
        running_min = 1.0
        for reverse_rank, (original_idx, p_value) in enumerate(reversed(sorted_pairs), start=1):
            rank = m - reverse_rank + 1
            corrected = min(1.0, p_value * m / rank)
            running_min = min(running_min, corrected)
            adjusted[original_idx] = float(running_min)
    else:
        raise ValueError(f'Unsupported correction method: {method}')
    return adjusted


def _normalize_correction_method(method: str) -> str:
    normalized = method.strip().lower().replace('-', '_')
    aliases = {
        'holm_bonferroni': 'holm',
        'benjamini_hochberg': 'bh',
        'fdr_bh': 'bh',
    }
    return aliases.get(normalized, normalized)


def _format_correction_method(method: str) -> str:
    normalized = _normalize_correction_method(method)
    labels = {
        'holm': 'Holm',
        'bh': 'Benjamini-Hochberg',
    }
    if normalized not in labels:
        raise ValueError(f'Unsupported correction method: {method}')
    return labels[normalized]


def _describe_correction_policy(method: str) -> str:
    normalized = _normalize_correction_method(method)
    labels = {
        'holm': 'Strict family-wise error control (Holm)',
        'bh': 'Exploratory false-discovery-rate control (Benjamini-Hochberg/FDR)',
    }
    if normalized not in labels:
        raise ValueError(f'Unsupported correction method: {method}')
    return labels[normalized]


def _describe_pairwise_strategy(*, non_parametric: bool, equal_var: bool, correction_method: str) -> str:
    correction_label = _format_correction_method(correction_method)
    if non_parametric:
        return f'pairwise Mann-Whitney + {correction_label}'
    if equal_var:
        return f'pairwise t-tests + {correction_label}'
    return f'pairwise Welch t-tests + {correction_label}'


def _pairwise_p_value(sample_a: np.ndarray, sample_b: np.ndarray, *, non_parametric: bool, equal_var: bool) -> tuple[str, float | None]:
    if sample_a.size < 2 or sample_b.size < 2:
        return ('insufficient_n', None)
    if non_parametric:
        _, p_value = mannwhitneyu(sample_a, sample_b, alternative='two-sided')
        return ('Mann-Whitney U', None if np.isnan(p_value) else float(p_value))
    _, p_value = ttest_ind(sample_a, sample_b, equal_var=equal_var, nan_policy='omit')
    return ('Student t-test' if equal_var else 'Welch t-test', None if np.isnan(p_value) else float(p_value))


def _effect_size_metadata(*, non_parametric: bool, multi_group_effect: str) -> tuple[str, str]:
    if non_parametric:
        return ('cliffs_delta', 'cliffs_delta')
    omnibus_type = 'omega_squared' if multi_group_effect == 'omega_squared' else 'eta_squared'
    return ('cohen_d', omnibus_type)


def _pairwise_effect_size(sample_a: np.ndarray, sample_b: np.ndarray, *, non_parametric: bool) -> float | None:
    return _cliffs_delta(sample_a, sample_b) if non_parametric else _cohen_d(sample_a, sample_b)


def _compute_pairwise_core_native(
    *,
    labels: list[str],
    numeric_groups: dict[str, np.ndarray],
    config: ComparisonStatsConfig,
    is_non_parametric: bool,
    equal_var: bool,
) -> list[dict[str, Any]] | None:
    native_rows = pairwise_stats_native(
        labels=labels,
        groups=[np.ascontiguousarray(numeric_groups[label], dtype=np.float64) for label in labels],
        alpha=config.alpha,
        correction_method=config.correction_method,
        non_parametric=is_non_parametric,
        equal_var=equal_var,
    )
    if native_rows is None:
        return None
    return [
        {
            'group_a': str(row['group_a']),
            'group_b': str(row['group_b']),
            'test_used': str(row['test_used']),
            'pairwise_test_name': str(row['test_used']),
            'p_value': row.get('p_value'),
            'effect_size': row.get('effect_size'),
            'adjusted_p_value': row.get('adjusted_p_value'),
            'significant': bool(row.get('significant', False)),
        }
        for row in native_rows
    ]


def compute_metric_pairwise_stats(
    metric_key: str,
    grouped_values: dict[str, list[float] | np.ndarray],
    *,
    config: ComparisonStatsConfig | None = None,
) -> list[dict[str, Any]]:
    """Compute pairwise rows with aligned test selection and p-value correction.

    Rationale:
        Uses one assumption-driven decision per metric, then applies it
        consistently across all pairs to reduce researcher degrees of freedom.

    Fallback behavior:
        Returns rows with ``None`` where tests/effects cannot be computed (for
        example n < 2), and still emits adjusted-p placeholders for stable
        downstream rendering.
    """
    config = config or ComparisonStatsConfig()

    labels = list(grouped_values.keys())
    numeric_groups = {
        label: np.asarray(values, dtype=float)[~np.isnan(np.asarray(values, dtype=float))]
        for label, values in grouped_values.items()
    }
    selector_result = select_group_stat_test(labels=labels, grouped_values=[numeric_groups[label] for label in labels])
    selected_test = selector_result.get('test_name') or 'Unknown'
    is_non_parametric = selected_test in {'Mann-Whitney U', 'Kruskal-Wallis'}
    variance_assumption = selector_result.get('assumptions', {}).get('variance_homogeneity', {})
    variance_status = variance_assumption.get('status')
    equal_var = variance_status == 'passed'
    normality_check_used = 'Shapiro-Wilk'
    variance_test_used = variance_assumption.get('test') or 'Brown-Forsythe'
    assumption_outcomes = selector_result.get('assumption_outcomes', {})
    correction_method_label = _format_correction_method(config.correction_method)
    correction_policy = _describe_correction_policy(config.correction_method)
    post_hoc_strategy = _describe_pairwise_strategy(
        non_parametric=is_non_parametric,
        equal_var=equal_var,
        correction_method=config.correction_method,
    )

    pairwise_effect_type, omnibus_effect_type = _effect_size_metadata(
        non_parametric=is_non_parametric,
        multi_group_effect=config.multi_group_effect,
    )

    overall_effect: float | None = None
    overall_ci: tuple[float, float] | None = None
    if len(labels) > 2:
        overall_effect = _eta_or_omega_squared(
            [numeric_groups[label] for label in labels],
            use_omega=config.multi_group_effect == 'omega_squared',
        )
        if config.include_effect_size_ci and overall_effect is not None:
            overall_ci = _bootstrap_effect_percentile_ci(
                effect_kernel='omega_squared' if config.multi_group_effect == 'omega_squared' else 'eta_squared',
                groups=[numeric_groups[label] for label in labels],
                level=config.ci_level,
                iterations=config.ci_bootstrap_iterations,
            )

    pairwise_rows = _compute_pairwise_core_native(
        labels=labels,
        numeric_groups=numeric_groups,
        config=config,
        is_non_parametric=is_non_parametric,
        equal_var=equal_var,
    )
    if pairwise_rows is None:
        pairwise_rows = []
        raw_p_values: list[float | None] = []
        for group_a, group_b in combinations(labels, 2):
            sample_a = numeric_groups[group_a]
            sample_b = numeric_groups[group_b]
            test_used, p_value = _pairwise_p_value(sample_a, sample_b, non_parametric=is_non_parametric, equal_var=equal_var)
            raw_p_values.append(p_value)
            pairwise_rows.append(
                {
                    'group_a': group_a,
                    'group_b': group_b,
                    'test_used': test_used,
                    'pairwise_test_name': test_used,
                    'p_value': p_value,
                    'effect_size': _pairwise_effect_size(sample_a, sample_b, non_parametric=is_non_parametric),
                }
            )
        adjusted = _adjust_pvalues(raw_p_values, config.correction_method)
        for row, adjusted_p in zip(pairwise_rows, adjusted):
            row['adjusted_p_value'] = adjusted_p
            row['significant'] = bool(adjusted_p is not None and adjusted_p < config.alpha)

    rows: list[dict[str, Any]] = []
    for pairwise in pairwise_rows:
        group_a = str(pairwise['group_a'])
        group_b = str(pairwise['group_b'])
        sample_a = numeric_groups[group_a]
        sample_b = numeric_groups[group_b]
        effect_size = pairwise.get('effect_size')
        effect_ci = None
        if config.include_effect_size_ci and effect_size is not None:
            effect_ci = _bootstrap_effect_percentile_ci(
                effect_kernel='cliffs_delta' if is_non_parametric else 'cohen_d',
                groups=[sample_a, sample_b],
                level=config.ci_level,
                iterations=config.ci_bootstrap_iterations,
            )

        row = {
            'metric': metric_key,
            'group_a': group_a,
            'group_b': group_b,
            'test_used': pairwise['test_used'],
            'pairwise_test_name': pairwise['pairwise_test_name'],
            'p_value': pairwise.get('p_value'),
            'effect_size': effect_size,
            'effect_type': pairwise_effect_type,
            'pairwise_effect_type': pairwise_effect_type,
            'normality_check_used': normality_check_used,
            'variance_test_used': variance_test_used,
            'omnibus_test_used': selected_test,
            'omnibus_test_name': selected_test,
            'post_hoc_strategy': post_hoc_strategy,
            'correction_method': correction_method_label,
            'correction_policy': correction_policy,
            'assumption_outcomes': assumption_outcomes,
            'selection_detail': assumption_outcomes.get('selection_detail'),
        }
        if effect_ci is not None:
            row['effect_size_ci'] = effect_ci
        if len(labels) > 2:
            row['omnibus_effect_size'] = overall_effect
            row['omnibus_effect_type'] = omnibus_effect_type
            row['effect_types'] = {
                'pairwise': pairwise_effect_type,
                'omnibus': omnibus_effect_type,
            }
            if overall_ci is not None:
                row['omnibus_effect_size_ci'] = overall_ci
        rows.append(row)
    for row, pairwise in zip(rows, pairwise_rows):
        row['adjusted_p_value'] = pairwise.get('adjusted_p_value')
        row['significant'] = bool(pairwise.get('significant', False))
        row.setdefault('effect_types', {'pairwise': pairwise_effect_type, 'omnibus': row.get('omnibus_effect_type')})

    return rows


__all__ = [
    'ComparisonStatsConfig',
    'compute_metric_pairwise_stats',
    '_describe_correction_policy',
    '_adjust_pvalues',
    '_describe_pairwise_strategy',
    '_format_correction_method',
]
