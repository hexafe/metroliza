"""Legacy/internal Group Comparison worksheet helpers retained for migration support.

This module is no longer part of the default export contract. Canonical
user-facing workbook output now flows through the Group Analysis
service/writer path instead.

Fallback behavior:
    Empty/invalid inputs still render deterministic legacy scaffolding with
    explicit markers so internal validation can distinguish missing data from
    failures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from modules.characteristic_alias_service import resolve_characteristic_alias
from modules.comparison_stats import (
    ComparisonStatsConfig,
    _describe_correction_policy,
    _describe_pairwise_strategy,
    _format_correction_method,
    compute_metric_pairwise_stats,
)
from modules.distribution_shape_analysis import compute_distribution_difference
from modules.group_stats_tests import select_group_stat_test


SECTION_GAP = 2

BASE_INTERPRETATION_NOTES = [
    'Alpha threshold: 0.05. Comparisons below this level are treated as statistically reliable signals.',
    'Adjusted p-value: this is the comparison p-value after correcting for the fact that many group pairs were checked. Use this value to judge whether a difference is statistically reliable.',
    'If the normality check cannot be trusted for every usable group, the worksheet falls back to the more cautious non-parametric path.',
    'The location tests focus on whether one group is generally higher or lower than another. The shape tests separately check whether the groups differ in spread, consistency, or overall pattern.',
    'Shape differences can matter even when averages look similar, because one group may still be less consistent, more skewed, or split into multiple patterns.',
    'Use the results as a prioritization aid: monitor small or uncertain gaps, and investigate large or repeatable gaps before changing the process.',
]


EFFECT_TYPE_METADATA = {
    'cohen_d': {
        'label': "Cohen's d",
        'absolute_symbol': '|d|',
        'matrix_title': "Pairwise Cohen's d Matrix (|d|)",
        'summary_label': 'Large effects (|d| >= 0.8)',
        'summary_threshold': 0.8,
        'bands': (0.2, 0.5),
        'interpretation': "Pairwise effect guide (Cohen's d, absolute magnitude |d|): below 0.2 is negligible, 0.2 to below 0.5 is small, 0.5 to below 0.8 is medium, and 0.8 or above is large. Darker cells mean larger practical differences.",
    },
    'cliffs_delta': {
        'label': "Cliff's delta",
        'absolute_symbol': '|δ|',
        'matrix_title': "Pairwise Cliff's delta Matrix (|δ|)",
        'summary_label': "Large effects (|δ| >= 0.474)",
        'summary_threshold': 0.474,
        'bands': (0.147, 0.33),
        'interpretation': "Pairwise effect guide (Cliff's delta, absolute magnitude |δ|): below 0.147 is negligible, 0.147 to below 0.33 is small, 0.33 to below 0.474 is medium, and 0.474 or above is large. Darker cells mean larger practical differences.",
    },
    'eta_squared': {
        'label': 'eta squared',
        'interpretation': 'Omnibus effect guide (eta squared, η²): estimated share of overall variation explained by group membership in the multi-group test.',
    },
    'omega_squared': {
        'label': 'omega squared',
        'interpretation': 'Omnibus effect guide (omega squared, ω²): a less biased estimate of how much overall variation is tied to group membership in the multi-group test.',
    },
}




def _ordered_effect_types(values):
    ordered = []
    for value in values:
        normalized = str(value or '').strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _effect_label(effect_type):
    metadata = EFFECT_TYPE_METADATA.get(effect_type, {})
    return metadata.get('label', effect_type.replace('_', ' ') if effect_type else 'effect size')


def _describe_effect_types(effect_types):
    if not effect_types:
        return 'not reported'
    labels = [_effect_label(effect_type) for effect_type in effect_types]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f'{labels[0]} and {labels[1]}'
    return ', '.join(labels[:-1]) + f', and {labels[-1]}'


def _build_effect_reporting_metadata(pairwise_rows):
    pairwise_types = _ordered_effect_types(row.get('pairwise_effect_type') or row.get('effect type') for row in pairwise_rows)
    omnibus_types = _ordered_effect_types(row.get('omnibus_effect_type') or row.get('omnibus effect type') for row in pairwise_rows)

    if len(pairwise_types) == 1 and pairwise_types[0] in EFFECT_TYPE_METADATA:
        pairwise_meta = EFFECT_TYPE_METADATA[pairwise_types[0]]
        matrix_title = pairwise_meta['matrix_title']
        summary_label = pairwise_meta.get('summary_label')
        summary_threshold = pairwise_meta.get('summary_threshold')
        effect_bands = pairwise_meta.get('bands')
    else:
        matrix_title = 'Pairwise Effect Magnitude Matrix (absolute effect size)'
        summary_label = None
        summary_threshold = None
        effect_bands = None

    return {
        'pairwise_effect_types': pairwise_types,
        'omnibus_effect_types': omnibus_types,
        'pairwise_matrix_title': matrix_title,
        'pairwise_summary_label': summary_label,
        'pairwise_summary_threshold': summary_threshold,
        'pairwise_effect_bands': effect_bands,
    }


def _build_interpretation_notes(payload):
    notes = list(BASE_INTERPRETATION_NOTES)
    effect_metadata = payload.get('effect_reporting', {})
    pairwise_types = effect_metadata.get('pairwise_effect_types', [])
    omnibus_types = effect_metadata.get('omnibus_effect_types', [])
    correction_policy = payload.get('correction_policy')

    if not pairwise_types:
        notes.append('Pairwise effect sizes: none were reported, so practical gap sizing is limited.')
    elif len(pairwise_types) == 1 and pairwise_types[0] in EFFECT_TYPE_METADATA:
        notes.append(EFFECT_TYPE_METADATA[pairwise_types[0]]['interpretation'])
    else:
        notes.append(
            'Pairwise effect sizes use mixed statistics ('
            + _describe_effect_types(pairwise_types)
            + '), so use the effect-type column and practical interpretation text together when judging how large a gap really is.'
        )

    if omnibus_types:
        omnibus_notes = [
            EFFECT_TYPE_METADATA[effect_type]['interpretation']
            for effect_type in omnibus_types
            if effect_type in EFFECT_TYPE_METADATA and 'interpretation' in EFFECT_TYPE_METADATA[effect_type]
        ]
        for note in omnibus_notes:
            if note not in notes:
                notes.append(note)

    if correction_policy:
        notes.append(f'Correction policy: {correction_policy}. This keeps the worksheet from over-calling differences just because many pairs were tested.')

    if payload.get('distribution_pairwise_rows'):
        notes.append('Distribution-shape pairwise tables keep both adjusted p-values and Wasserstein distance so statistical evidence and practical separation stay visible together.')
        notes.append('Wasserstein distance is a practical clue about separation between full distributions. It is not, by itself, a spec-limit pass/fail decision.')

    notes.append('Suggested actions are intentionally cautious: large and reliable gaps point to investigation, while weak or small signals point to monitoring or collecting more data first.')

    return notes


def _safe_numeric(value):
    numeric = pd.to_numeric(pd.Series([value]), errors='coerce').iloc[0]
    return None if pd.isna(numeric) else float(numeric)


def _sample_size_caution(row):
    n_a = row.get('n(A)')
    n_b = row.get('n(B)')
    if n_a is None or n_b is None:
        return False
    return n_a < 5 or n_b < 5


def _effect_band_tuple(effect_type):
    metadata = EFFECT_TYPE_METADATA.get(effect_type, {})
    low_band, mid_band = metadata.get('bands', (0.2, 0.5))
    high_band = metadata.get('summary_threshold', mid_band)
    return low_band, mid_band, high_band


def _practical_magnitude(effect_value, effect_type):
    numeric_effect = _safe_numeric(effect_value)
    if numeric_effect is None:
        return 'unknown'

    absolute_effect = abs(numeric_effect)
    low_band, mid_band, high_band = _effect_band_tuple(effect_type)
    if absolute_effect < low_band:
        return 'tiny'
    if absolute_effect < mid_band:
        return 'small'
    if absolute_effect < high_band:
        return 'moderate'
    return 'large'


def _pairwise_takeaway(row):
    adjusted_p = _safe_numeric(row.get('adjusted p-value'))
    effect_type = row.get('effect type')
    magnitude = _practical_magnitude(row.get('effect size'), effect_type)
    small_sample = _sample_size_caution(row)

    if adjusted_p is None:
        base = 'The statistical signal is incomplete, so this comparison should be treated as unresolved.'
    elif adjusted_p <= 0.01:
        base = 'The groups differ clearly after multiple-comparison correction.'
    elif adjusted_p <= 0.05:
        base = 'The groups show a statistically reliable difference after correction.'
    else:
        base = 'There is not enough corrected statistical evidence to call this a clear difference.'

    magnitude_text = {
        'tiny': 'The practical gap looks tiny.',
        'small': 'The practical gap looks small.',
        'moderate': 'The practical gap looks moderate.',
        'large': 'The practical gap looks large enough to matter in practice.',
        'unknown': 'The practical gap size was not reported clearly.',
    }[magnitude]

    if adjusted_p is not None and adjusted_p > 0.05 and magnitude in {'moderate', 'large'}:
        magnitude_text = 'The practical gap may matter, but the statistical evidence is still weak after correction.'
    elif adjusted_p is not None and adjusted_p <= 0.05 and magnitude == 'tiny':
        magnitude_text = 'The result is statistically reliable, but the practical gap looks tiny and may be operationally minor.'

    caution_text = ' Sample sizes are small, so confidence should stay cautious.' if small_sample else ''
    return f'{base} {magnitude_text}{caution_text}'


def _pairwise_action(row):
    adjusted_p = _safe_numeric(row.get('adjusted p-value'))
    magnitude = _practical_magnitude(row.get('effect size'), row.get('effect type'))
    small_sample = _sample_size_caution(row)

    if adjusted_p is not None and adjusted_p <= 0.05 and magnitude == 'large':
        action = 'Large practical difference; prioritize investigation and check whether setup, operator, tooling, or material changes align with this gap.'
    elif adjusted_p is not None and adjusted_p <= 0.05 and magnitude in {'moderate', 'small'}:
        action = 'Review process differences between these groups before changing settings, and confirm whether the gap matters operationally.'
    elif adjusted_p is not None and adjusted_p <= 0.05:
        action = 'No immediate process change is required; keep monitoring because the statistical signal may be stronger than the operational impact.'
    elif magnitude in {'moderate', 'large'}:
        action = 'Possible meaningful gap without strong corrected evidence; collect more data and verify before changing the process.'
    else:
        action = 'No immediate action; continue monitoring.'

    if small_sample:
        action = 'Statistical signal is weak or sample is small; verify with more data before changing process.'
        if adjusted_p is not None and adjusted_p <= 0.05 and magnitude == 'large':
            action += ' This pair is still worth early investigation because the observed gap is large.'
    return action


def _relative_position(values, target_value):
    ordered = pd.Series(values).sort_values(kind='mergesort')
    if ordered.empty:
        return 'unknown'
    if target_value <= ordered.iloc[0]:
        return 'lowest'
    if target_value >= ordered.iloc[-1]:
        return 'highest'
    midpoint = ordered.median()
    if target_value == midpoint:
        return 'near center'
    return 'above center' if target_value > midpoint else 'below center'


def _build_group_profile_rows(working: pd.DataFrame):
    if working.empty:
        return []

    rows = []
    for metric_key, metric_frame in working.groupby('metric_key', sort=False):
        group_stats = metric_frame.groupby('GROUP', sort=True)['MEAS'].agg(['mean', 'median', 'count'])
        means = group_stats['mean'].tolist()
        for group_name, stats in group_stats.iterrows():
            position = _relative_position(means, stats['mean'])
            if position == 'highest':
                summary = 'This group is currently the highest on this metric.'
                process_meaning = 'If higher values are undesirable for this metric, this group is a strong candidate for process review.'
            elif position == 'lowest':
                summary = 'This group is currently the lowest on this metric.'
                process_meaning = 'If lower values are undesirable for this metric, this group is a strong candidate for process review.'
            elif position == 'near center':
                summary = 'This group sits near the middle of the pack.'
                process_meaning = 'This group looks comparatively typical on this metric, so monitoring may be enough unless other evidence disagrees.'
            else:
                summary = f'This group sits {position.replace("-", " ")} relative to the other groups.'
                process_meaning = 'This group stands out somewhat, so it is worth checking for setup, tooling, material lot, operator pattern, or measurement-system differences before changing the process.'

            rows.append(
                {
                    'Metric': metric_key,
                    'Group': group_name,
                    'n': int(stats['count']),
                    'Mean': round(float(stats['mean']), 4),
                    'Median': round(float(stats['median']), 4),
                    'Relative position': position,
                    'Plain-language summary': summary,
                    'Practical process meaning': process_meaning,
                }
            )
    return rows

def _build_pairwise_group_matrices(pairwise_df):
    """Build per-metric square matrices for adjusted p-values and location-effect magnitudes."""
    if pairwise_df.empty:
        return {}, {}

    significance_matrices = {}
    effect_matrices = {}

    for metric, metric_rows in pairwise_df.groupby('Metric', sort=True):
        groups = pd.unique(metric_rows[['Group A', 'Group B']].values.ravel('K')).tolist()
        sig_df = pd.DataFrame(index=groups, columns=groups, dtype=float)
        effect_df = pd.DataFrame(index=groups, columns=groups, dtype=float)

        for group in groups:
            sig_df.loc[group, group] = np.nan
            effect_df.loc[group, group] = np.nan

        for _, comparison in metric_rows.iterrows():
            group_a = comparison['Group A']
            group_b = comparison['Group B']
            adjusted_p = comparison.get('adjusted p-value')
            effect = comparison.get('effect size')
            sig_df.loc[group_a, group_b] = adjusted_p
            sig_df.loc[group_b, group_a] = adjusted_p
            absolute_effect = abs(effect) if pd.notna(effect) else effect
            effect_df.loc[group_a, group_b] = absolute_effect
            effect_df.loc[group_b, group_a] = absolute_effect

        significance_matrices[metric] = sig_df
        effect_matrices[metric] = effect_df

    return significance_matrices, effect_matrices


def _build_insights(working, pairwise_df, overall_test_rows, distribution_summary_rows=None):
    """Create deterministic insight bullets for the worksheet."""
    if working.empty:
        return ['No grouped measurement rows available for comparison.']

    insights = []
    group_means = working.groupby('GROUP')['MEAS'].mean().sort_values(ascending=False)
    if not group_means.empty:
        highest_group = group_means.index[0]
        lowest_group = group_means.index[-1]
        insights.append(
            f'Central tendency: highest mean={highest_group} ({group_means.iloc[0]:.3f}), '
            f'lowest mean={lowest_group} ({group_means.iloc[-1]:.3f}). Use this as a quick ranking, not as proof that every pair is meaningfully different.'
        )

    if pairwise_df.empty:
        insights.extend(
            [
                'Significant pairwise findings: none (no pairwise location comparisons available).',
                'difference: none (no pairwise location comparisons available).',
                'caution: no pairwise location comparisons available.',
            ]
        )
    else:
        adj_p = pd.to_numeric(pairwise_df['adjusted p-value'], errors='coerce')

        significant = pairwise_df[adj_p < 0.05]
        if significant.empty:
            insights.append('Significant pairwise findings: none at adjusted p < 0.05, so there is not enough corrected evidence for a clear location difference.')
        else:
            significant_labels = [
                f"{row['Metric']} ({row['Group A']} vs {row['Group B']}, adj p={row['adjusted p-value']:.4f})"
                for _, row in significant.sort_values(['Metric', 'adjusted p-value', 'Group A', 'Group B']).iterrows()
            ]
            insights.append('Significant pairwise findings: ' + '; '.join(significant_labels) + '.')

        no_difference = pairwise_df[adj_p >= 0.05]
        if no_difference.empty:
            insights.append('difference: all tested pairs were significant after adjustment, but use effect size to judge whether the gaps are operationally important.')
        else:
            no_diff_labels = [
                f"{row['Metric']} ({row['Group A']} vs {row['Group B']}, adj p={row['adjusted p-value']:.4f})"
                for _, row in no_difference.sort_values(['Metric', 'adjusted p-value', 'Group A', 'Group B']).iterrows()
            ]
            insights.append('difference: ' + '; '.join(no_diff_labels) + '.')

        small_sample_pairs = pairwise_df[(pairwise_df['n(A)'] < 5) | (pairwise_df['n(B)'] < 5)]
        if small_sample_pairs.empty:
            insights.append('caution: all compared groups had n >= 5, so sample-size risk is lower.')
        else:
            warning_labels = [
                f"{row['Metric']} ({row['Group A']} n={row['n(A)']}, {row['Group B']} n={row['n(B)']})"
                for _, row in small_sample_pairs.sort_values(['Metric', 'Group A', 'Group B']).iterrows()
            ]
            insights.append('caution (n < 5): ' + '; '.join(warning_labels) + '.')

    if not overall_test_rows:
        insights.append('Assumption/test-choice notes: no per-metric test selection was available.')
    else:
        notes = []
        for item in sorted(overall_test_rows, key=lambda x: x.get('Metric', '')):
            note = item.get('Assumptions / warnings') or 'None'
            notes.append(f"{item.get('Metric', 'Unknown')}: {item.get('Selected test', 'N/A')} [{note}]")
        insights.append('Assumption/test-choice notes: ' + '; '.join(notes) + '.')

    distribution_summary_rows = distribution_summary_rows or []
    if not distribution_summary_rows:
        insights.append('distribution shape: no distribution-shape tests were available.')
    else:
        shape_significant = [
            row for row in distribution_summary_rows if str(row.get('significant?', '')).strip().upper() == 'YES'
        ]
        if shape_significant:
            labels = [
                f"{row['Metric']} ({row.get('Test used')}, p={row.get('raw p-value'):.4f})"
                for row in shape_significant
                if row.get('raw p-value') is not None
            ]
            if pairwise_df.empty:
                insights.append('Distribution-shape findings: significant differences detected for ' + '; '.join(labels) + '.')
            else:
                insights.append('distribution shape: difference detected for ' + '; '.join(labels) + '.')
        else:
            insights.append('distribution shape: no statistically significant shape differences were detected after correction, so spread/consistency differences are not strongly supported here.')

    return insights


def _summarize_group_sample_sizes(working: pd.DataFrame) -> str:
    if working.empty:
        return 'No groups'
    counts = working.groupby('GROUP', sort=True)['MEAS'].size()
    return ', '.join(f"{group}:{int(size)}" for group, size in counts.items())


def _resolve_metric_aliases_for_comparison(working: pd.DataFrame, *, alias_db_path=None) -> pd.Series:
    """Resolve comparison metric keys with reference-scoped alias precedence."""
    base_metric = working.get('HEADER - AX', working.get('HEADER', 'UNKNOWN')).fillna('UNKNOWN').astype(str)
    if alias_db_path is None:
        return base_metric

    resolved_metric = base_metric.copy()
    reference_series = None
    if 'REFERENCE' in working.columns:
        reference_series = working['REFERENCE'].fillna('').astype(str).str.strip()

    for row_index, metric_name in resolved_metric.items():
        normalized_metric_name = str(metric_name or '').strip()
        if not normalized_metric_name:
            continue
        reference_value = None
        if reference_series is not None:
            reference_value = reference_series.get(row_index) or None
        resolved_metric.at[row_index] = resolve_characteristic_alias(
            normalized_metric_name,
            reference_value,
            alias_db_path,
        )

    return resolved_metric


def prepare_group_comparison_payload(grouped_df, *, alias_db_path=None, correction_method='holm'):
    """Prepare metadata, summary rows, pairwise rows, matrices, and insights.

    Rationale:
        Converts export-filtered long-form measurements into stable comparison
        artifacts used by both tables and heatmaps.

    Fallback behavior:
        Returns deterministic empty payload sections when the filtered dataframe
        has no usable numeric measurements.
    """
    if not isinstance(grouped_df, pd.DataFrame) or grouped_df.empty:
        correction_method = _format_correction_method(correction_method)
        correction_policy = _describe_correction_policy(correction_method)
        return {
            'metadata': [('Rows', 0), ('Groups', 0), ('Headers', 0), ('Alpha', 0.05), ('Correction method', correction_method), ('Correction policy', correction_policy), ('Group sample sizes', 'No groups')],
            'overall_summary': [('Pairwise tests', 0), ('Significant (p < 0.05)', 0)],
            'pairwise_rows': [],
            'group_profile_rows': [],
            'overall_test_rows': [],
            'distribution_profile_rows': [],
            'distribution_difference_rows': [],
            'distribution_pairwise_rows': [],
            'significance_matrices': {},
            'effect_matrices': {},
            'effect_reporting': _build_effect_reporting_metadata([]),
            'correction_policy': correction_policy,
            'insights': ['No grouped measurement rows available for comparison.'],
        }

    working = grouped_df.copy()
    if 'GROUP' not in working.columns:
        working['GROUP'] = 'UNGROUPED'
    working['GROUP'] = working['GROUP'].fillna('UNGROUPED').astype(str)
    working['metric_key'] = _resolve_metric_aliases_for_comparison(working, alias_db_path=alias_db_path)

    numeric_meas = pd.to_numeric(working.get('MEAS'), errors='coerce')
    working = working.assign(MEAS=numeric_meas)
    working = working.dropna(subset=['MEAS'])

    correction_method = _format_correction_method(correction_method)
    correction_policy = _describe_correction_policy(correction_method)
    pairwise_rows = []
    overall_test_rows = []
    distribution_profile_rows = []
    distribution_difference_rows = []
    distribution_pairwise_rows = []

    for metric_key, metric_frame in working.groupby('metric_key', sort=False):
        group_series = {
            group_name: group_values['MEAS'].tolist()
            for group_name, group_values in metric_frame.groupby('GROUP', sort=False)
        }

        selector_result = select_group_stat_test(
            labels=list(group_series.keys()),
            grouped_values=list(group_series.values()),
        )
        selected_test = selector_result.get('test_name') or 'N/A'
        is_non_parametric = selected_test in {'Mann-Whitney U', 'Kruskal-Wallis'}
        variance_test = selector_result.get('assumptions', {}).get('variance_homogeneity', {}).get('test') or 'Brown-Forsythe'
        variance_status = selector_result.get('assumptions', {}).get('variance_homogeneity', {}).get('status')
        post_hoc_strategy = _describe_pairwise_strategy(
            non_parametric=is_non_parametric,
            equal_var=variance_status == 'passed',
            correction_method=correction_method,
        )
        overall_test_rows.append(
            {
                'Metric': metric_key,
                'Selected test': selected_test,
                'omnibus test name': selected_test,
                'p-value': selector_result.get('p_value'),
                'Sample sizes': ', '.join(f"{key}:{value}" for key, value in selector_result.get('sample_sizes', {}).items()),
                'normality check used': 'Shapiro-Wilk',
                'variance test used': variance_test,
                'omnibus test used': selected_test,
                'assumption outcomes': selector_result.get('assumption_outcomes', {}),
                'post-hoc strategy': post_hoc_strategy,
                'correction method': correction_method,
                'correction policy': correction_policy,
                'Assumptions / warnings': '; '.join(selector_result.get('warnings', [])) or 'None',
            }
        )

        comparison_rows = compute_metric_pairwise_stats(
            metric_key,
            group_series,
            config=ComparisonStatsConfig(alpha=0.05, correction_method=correction_method),
        )
        for item in comparison_rows:
            group_a = item['group_a']
            group_b = item['group_b']
            sample_left = group_series[group_a]
            sample_right = group_series[group_b]
            mean_delta = float(pd.Series(sample_left).mean() - pd.Series(sample_right).mean())
            pairwise_rows.append(
                {
                    'Metric': metric_key,
                    'Group A': group_a,
                    'Group B': group_b,
                    'test used': item.get('test_used'),
                    'pairwise test name': item.get('pairwise_test_name', item.get('test_used')),
                    'p-value': item.get('p_value'),
                    'adjusted p-value': item.get('adjusted_p_value'),
                    'effect size': item.get('effect_size'),
                    'effect type': item.get('effect_type'),
                    'pairwise_effect_type': item.get('pairwise_effect_type', item.get('effect_type')),
                    'effect size ci': item.get('effect_size_ci'),
                    'omnibus effect size': item.get('omnibus_effect_size'),
                    'omnibus effect type': item.get('omnibus_effect_type'),
                    'omnibus_effect_type': item.get('omnibus_effect_type'),
                    'effect types': item.get('effect_types'),
                    'omnibus effect size ci': item.get('omnibus_effect_size_ci'),
                    'significant': item.get('significant'),
                    'n(A)': len(sample_left),
                    'n(B)': len(sample_right),
                    'Mean Δ (A-B)': mean_delta,
                    'normality check used': item.get('normality_check_used'),
                    'variance test used': item.get('variance_test_used'),
                    'omnibus test used': item.get('omnibus_test_used'),
                    'omnibus test name': item.get('omnibus_test_name', item.get('omnibus_test_used')),
                    'assumption outcomes': item.get('assumption_outcomes'),
                    'selection detail': item.get('selection_detail'),
                    'post-hoc strategy': item.get('post_hoc_strategy'),
                    'correction method': item.get('correction_method'),
                    'correction policy': item.get('correction_policy', correction_policy),
                }
            )

        distribution_result = compute_distribution_difference(
            metric_key,
            group_series,
            alpha=0.05,
            correction_method='holm',
        )
        distribution_profile_rows.extend(distribution_result.get('profile_rows', []))
        distribution_difference_rows.append(distribution_result.get('omnibus_row', {}))
        distribution_pairwise_rows.extend(distribution_result.get('pairwise_rows', []))

    pairwise_df = pd.DataFrame(pairwise_rows)
    significance_matrices, effect_matrices = _build_pairwise_group_matrices(pairwise_df)
    significant_count = int(pairwise_df['significant'].sum()) if not pairwise_df.empty else 0
    effect_reporting = _build_effect_reporting_metadata(pairwise_rows)

    overall_summary = [
        ('Pairwise tests', len(pairwise_rows)),
        ('Significant (p < 0.05)', significant_count),
    ]
    summary_threshold = effect_reporting.get('pairwise_summary_threshold')
    summary_label = effect_reporting.get('pairwise_summary_label')
    if summary_threshold is not None and summary_label and not pairwise_df.empty:
        effect_series = pd.to_numeric(pairwise_df['effect size'], errors='coerce')
        overall_summary.append((summary_label, int((effect_series.abs() >= summary_threshold).sum())))

    return {
        'metadata': [
            ('Rows', len(working)),
            ('Groups', working['GROUP'].nunique()),
            ('Headers', working['metric_key'].nunique()),
            ('Alpha', 0.05),
            ('Correction method', correction_method),
            ('Correction policy', correction_policy),
            ('Group sample sizes', _summarize_group_sample_sizes(working)),
        ],
        'overall_summary': overall_summary,
        'pairwise_rows': pairwise_rows,
        'group_profile_rows': _build_group_profile_rows(working),
        'overall_test_rows': overall_test_rows,
        'distribution_profile_rows': [
            {k: v for k, v in row.items() if not k.startswith('_')} for row in distribution_profile_rows
        ],
        'distribution_difference_rows': distribution_difference_rows,
        'distribution_pairwise_rows': distribution_pairwise_rows,
        'significance_matrices': significance_matrices,
        'effect_matrices': effect_matrices,
        'effect_reporting': effect_reporting,
        'correction_policy': correction_policy,
        'insights': _build_insights(working, pairwise_df, overall_test_rows, distribution_difference_rows),
    }




def _normalize_comment(value):
    text = str(value or '').strip()
    return text if text else 'None'


def _effect_magnitude_label(effect_value, effect_type):
    numeric_effect = pd.to_numeric(pd.Series([effect_value]), errors='coerce').iloc[0]
    if pd.isna(numeric_effect):
        return 'Not reported'

    absolute_effect = abs(float(numeric_effect))
    bands = EFFECT_TYPE_METADATA.get(effect_type, {}).get('bands')
    if not bands:
        return f'{absolute_effect:.3f}'

    low_band, mid_band = bands
    summary_threshold = EFFECT_TYPE_METADATA.get(effect_type, {}).get('summary_threshold') or mid_band
    if absolute_effect < low_band:
        magnitude = 'Negligible'
    elif absolute_effect < mid_band:
        magnitude = 'Small'
    elif absolute_effect < summary_threshold:
        magnitude = 'Medium'
    else:
        magnitude = 'Large'
    return f'{magnitude} ({absolute_effect:.3f})'


def _build_pairwise_display_rows(pairwise_rows):
    display_rows = []
    for row in pairwise_rows:
        metric = row.get('Metric', 'Unknown')
        group_a = row.get('Group A', 'Unknown')
        group_b = row.get('Group B', 'Unknown')
        effect_type = row.get('effect type')
        comments = []
        if row.get('significant'):
            comments.append('Adjusted significant')
        assumption_warning = _normalize_comment(row.get('normality check used'))
        variance_warning = _normalize_comment(row.get('variance test used'))
        correction_policy = _normalize_comment(row.get('correction policy'))
        assumption_outcomes = row.get('assumption outcomes') or {}
        selection_detail = _normalize_comment(row.get('selection detail') or assumption_outcomes.get('selection_detail'))
        if assumption_warning != 'None':
            comments.append(f'Normality: {assumption_warning}')
        if variance_warning != 'None':
            comments.append(f'Variance: {variance_warning}')
        if correction_policy != 'None':
            comments.append(f'Correction: {correction_policy}')
        if selection_detail != 'None':
            comments.append(f'Selection: {selection_detail}')

        display_rows.append({
            'Metric': metric,
            'Group A': group_a,
            'Group B': group_b,
            'Pairwise test': row.get('pairwise test name', row.get('test used')),
            'Adjusted p-value': row.get('adjusted p-value'),
            'Pairwise effect size': row.get('effect size'),
            'Effect type': _effect_label(effect_type),
            'Delta mean or median': row.get('Mean Δ (A-B)'),
            'Practical interpretation': _effect_magnitude_label(row.get('effect size'), effect_type),
            'Plain-language takeaway': _pairwise_takeaway(row),
            'Suggested action': _pairwise_action(row),
            'Flags / comments': '; '.join(comments) if comments else 'None',
        })
    return display_rows


def _distribution_takeaway(row):
    adjusted_p = _safe_numeric(row.get('adjusted p-value'))
    fit_quality = str(row.get('Fit quality') or row.get('fit quality') or '').strip().lower()
    severity = str(row.get('Practical severity') or row.get('practical severity') or '').strip().lower()

    if adjusted_p is not None and adjusted_p <= 0.05:
        takeaway = 'These groups may have similar averages, but their spread or pattern differs in a statistically reliable way.'
    else:
        takeaway = 'No strong evidence of a shape difference after correction.'

    if severity in {'moderate', 'high'}:
        takeaway += ' The Wasserstein distance suggests practical separation in the overall distribution shape.'
    if fit_quality and fit_quality not in {'good', 'strong'}:
        takeaway += ' Fit quality is not strong, so confirm before acting.'
    return takeaway


def _distribution_action(row):
    adjusted_p = _safe_numeric(row.get('adjusted p-value'))
    severity = str(row.get('Practical severity') or row.get('practical severity') or '').strip().lower()
    fit_quality = str(row.get('Fit quality') or row.get('fit quality') or '').strip().lower()

    if adjusted_p is not None and adjusted_p <= 0.05 and severity == 'high':
        action = 'Shape difference looks material; review consistency drivers such as setup, tooling, material, operator pattern, or measurement-system differences.'
    elif adjusted_p is not None and adjusted_p <= 0.05:
        action = 'Review whether one group is more variable or less predictable before changing the process.'
    else:
        action = 'Monitor rather than escalate; there is not enough corrected evidence for a shape-driven change.'

    if fit_quality and fit_quality not in {'good', 'strong'}:
        action = 'Shape difference is visible, but fit quality is weak, so confirm with more data before acting.'
    return action


def _build_distribution_pairwise_display_rows(rows):
    display_rows = []
    for row in rows:
        display = dict(row)
        display['Plain-language takeaway'] = _distribution_takeaway(row)
        display['Suggested action'] = _distribution_action(row)
        display_rows.append(display)
    return display_rows


def _build_summary_block(payload):
    metadata = dict(payload.get('metadata', []))
    pairwise_rows = payload.get('pairwise_rows', [])
    overall_tests = payload.get('overall_test_rows', [])
    distribution_rows = payload.get('distribution_difference_rows', [])

    strongest_effect = 'None reported'
    if pairwise_rows:
        strongest_row = max(
            pairwise_rows,
            key=lambda item: abs(pd.to_numeric(pd.Series([item.get('effect size')]), errors='coerce').iloc[0]) if pd.notna(pd.to_numeric(pd.Series([item.get('effect size')]), errors='coerce').iloc[0]) else -1,
        )
        strongest_effect = (
            f"{strongest_row.get('Metric')} ({strongest_row.get('Group A')} vs {strongest_row.get('Group B')}): "
            f"{_effect_magnitude_label(strongest_row.get('effect size'), strongest_row.get('effect type'))}"
        )

    omnibus_results = 'None'
    if overall_tests:
        omnibus_results = '; '.join(
            f"{row.get('Metric')}: {row.get('Selected test')} (p={row.get('p-value')})"
            for row in overall_tests
        )

    warnings = []
    for row in overall_tests:
        warning_text = _normalize_comment(row.get('Assumptions / warnings'))
        if warning_text != 'None':
            warnings.append(f"{row.get('Metric')}: {warning_text}")
    shape_flags = [
        row for row in distribution_rows
        if isinstance(row, dict) and pd.to_numeric(pd.Series([row.get('adjusted p-value')]), errors='coerce').notna().iloc[0]
    ]
    if shape_flags:
        warnings.append(f'Shape differences reviewed separately ({len(shape_flags)} metrics).')

    return [
        ('Metric counts', metadata.get('Headers', 0)),
        ('Groups analyzed', metadata.get('Group sample sizes', metadata.get('Groups', 0))),
        ('Correction method', metadata.get('Correction method', 'N/A')),
        ('Correction policy', metadata.get('Correction policy', 'N/A')),
        ('Per-metric omnibus test / p-value', omnibus_results),
        ('Significant adjusted pairwise location findings', int(sum(bool(row.get('significant')) for row in pairwise_rows))),
        ('Strongest practical location effect', strongest_effect),
        ('Warnings / assumptions', '; '.join(warnings) if warnings else 'None'),
    ]


def _column_width_for_header(header):
    width_map = {
        'Metric': 22,
        'Group': 12,
        'Group A': 12,
        'Group B': 12,
        'n': 10,
        'Mean': 12,
        'Median': 12,
        'Pairwise test': 18,
        'Adjusted p-value': 14,
        'Pairwise effect size': 16,
        'Effect type': 16,
        'Delta mean or median': 18,
        'Relative position': 18,
        'Practical interpretation': 34,
        'Plain-language summary': 42,
        'Practical process meaning': 40,
        'Plain-language takeaway': 44,
        'Suggested action': 36,
        'Flags / comments': 38,
        'Warning / notes summary': 42,
        'Wasserstein distance': 18,
        'Practical severity': 18,
    }
    return width_map.get(header, 18)


LONG_TEXT_HEADERS = {
    'Practical interpretation',
    'Plain-language summary',
    'Practical process meaning',
    'Plain-language takeaway',
    'Suggested action',
    'Flags / comments',
    'Warning / notes summary',
    'Notes',
    'Assumptions / warnings',
}


def _set_table_column_widths(worksheet, headers, formats=None):
    body_format = (formats or {}).get('body')
    wrapped_format = (formats or {}).get('wrapped')
    for col, header in enumerate(headers):
        fmt = wrapped_format if header in LONG_TEXT_HEADERS else body_format
        worksheet.set_column(col, col, _column_width_for_header(header), fmt)


def _get_workbook(worksheet):
    return (
        getattr(worksheet, '_workbook', None)
        or getattr(worksheet, 'book', None)
        or getattr(worksheet, 'workbook', None)
        or worksheet
    )


def _safe_add_format(workbook, properties):
    if workbook is None:
        return properties
    if hasattr(workbook, 'add_format'):
        return workbook.add_format(properties)
    if hasattr(workbook, 'workbook_add_format'):
        return workbook.workbook_add_format(properties)
    return properties


def _apply_final_column_layout(worksheet, formats):
    final_widths = {
        0: 24,
        1: 14,
        2: 14,
        3: 18,
        4: 14,
        5: 16,
        6: 16,
        7: 18,
        8: 34,
        9: 44,
        10: 36,
        11: 38,
    }
    for col, width in final_widths.items():
        fmt = formats['wrapped'] if col in {0, 8, 9, 10, 11} else formats['body']
        worksheet.set_column(col, col, width, fmt)


def _build_format_bundle(worksheet):
    cached = getattr(worksheet, '_group_comparison_formats', None)
    if cached is not None:
        return cached
    workbook = _get_workbook(worksheet)
    bundle = {
        'section_title': _safe_add_format(workbook, {'bold': True, 'font_size': 13, 'bg_color': '#D9E2F3', 'border': 1}),
        'table_header': _safe_add_format(workbook, {'bold': True, 'bg_color': '#D9EAD3', 'border': 1, 'text_wrap': True, 'valign': 'top'}),
        'body': _safe_add_format(workbook, {'border': 1, 'valign': 'top'}),
        'wrapped': _safe_add_format(workbook, {'border': 1, 'text_wrap': True, 'valign': 'top'}),
        'numeric': _safe_add_format(workbook, {'border': 1, 'num_format': '0.0000', 'valign': 'top'}),
        'note': _safe_add_format(workbook, {'text_wrap': True, 'valign': 'top', 'font_color': '#404040'}),
        'legend': _safe_add_format(workbook, {'bold': True, 'text_wrap': True, 'font_color': '#404040'}),
        'matrix_header': _safe_add_format(workbook, {'bold': True, 'bg_color': '#EDEDED', 'border': 1, 'align': 'center'}),
        'matrix_label': _safe_add_format(workbook, {'bold': True, 'border': 1}),
        'matrix_value': _safe_add_format(workbook, {'border': 1, 'num_format': '0.0000', 'align': 'center'}),
        'matrix_blank': _safe_add_format(workbook, {'bg_color': '#E7E6E6', 'border': 1}),
        'sig_strong': _safe_add_format(workbook, {'bg_color': '#F4CCCC', 'font_color': '#7F0000', 'border': 1}),
        'sig_warn': _safe_add_format(workbook, {'bg_color': '#FFE599', 'font_color': '#7F6000', 'border': 1}),
        'sig_ok': _safe_add_format(workbook, {'bg_color': '#D9EAD3', 'font_color': '#274E13', 'border': 1}),
        'effect_low': _safe_add_format(workbook, {'bg_color': '#FFF2CC', 'border': 1}),
        'effect_mid': _safe_add_format(workbook, {'bg_color': '#F9CB9C', 'border': 1}),
        'effect_med': _safe_add_format(workbook, {'bg_color': '#9FC5E8', 'border': 1}),
        'effect_high': _safe_add_format(workbook, {'bg_color': '#6D9EEB', 'font_color': '#FFFFFF', 'border': 1}),
    }
    setattr(worksheet, '_group_comparison_formats', bundle)
    return bundle

def _safe_chart_series_name(name):
    text = str(name or '').strip()
    return text[:120] if text else 'Series'


def _build_group_comparison_chart_payload(payload):
    pairwise_rows = payload.get('pairwise_rows', []) or []
    if not pairwise_rows:
        return {}

    pairwise_df = pd.DataFrame(pairwise_rows).copy()
    if pairwise_df.empty:
        return {}

    pairwise_df['adjusted p-value'] = pd.to_numeric(pairwise_df.get('adjusted p-value'), errors='coerce')
    pairwise_df['effect size'] = pd.to_numeric(pairwise_df.get('effect size'), errors='coerce')
    pairwise_df['abs_effect_size'] = pairwise_df['effect size'].abs()
    pairwise_df['pair_label'] = pairwise_df['Group A'].astype(str) + ' vs ' + pairwise_df['Group B'].astype(str)
    pairwise_df['label'] = pairwise_df['Metric'].astype(str) + ' | ' + pairwise_df['pair_label']

    ranked_df = pairwise_df.dropna(subset=['abs_effect_size']).sort_values(
        ['abs_effect_size', 'adjusted p-value', 'Metric', 'Group A', 'Group B'],
        ascending=[False, True, True, True, True],
        kind='mergesort',
    ).head(8).copy()

    scatter_df = pairwise_df.dropna(subset=['abs_effect_size', 'adjusted p-value']).sort_values(
        ['Metric', 'adjusted p-value', 'Group A', 'Group B'],
        kind='mergesort',
    ).copy()
    if not scatter_df.empty:
        clipped = scatter_df['adjusted p-value'].clip(lower=1e-12)
        scatter_df['neg_log10_adj_p'] = -np.log10(clipped)

    return {
        'ranked_effects': ranked_df.to_dict('records'),
        'effect_vs_p': scatter_df.to_dict('records'),
    }


def _render_group_comparison_charts(worksheet, start_row, payload):
    if not hasattr(worksheet, 'insert_chart'):
        return start_row
    workbook = _get_workbook(worksheet)
    if workbook is None or not hasattr(workbook, 'add_chart'):
        return start_row

    chart_payload = _build_group_comparison_chart_payload(payload)
    ranked_rows = chart_payload.get('ranked_effects') or []
    scatter_rows = chart_payload.get('effect_vs_p') or []
    if not ranked_rows and not scatter_rows:
        return start_row

    row = start_row
    formats = _build_format_bundle(worksheet)
    worksheet.write(row, 0, 'Comparison Charts', formats['section_title'])
    row += 1

    next_chart_row = row
    chart_height_rows = 18

    if ranked_rows:
        worksheet.write(row, 0, 'Ranked Pairwise Effects', formats['section_title'])
        data_header_row = row + 1
        headers = ['Label', 'Absolute effect size']
        for col, header in enumerate(headers):
            worksheet.write(data_header_row, col, header, formats['table_header'])
        for offset, entry in enumerate(ranked_rows, start=1):
            worksheet.write(data_header_row + offset, 0, entry['label'], formats['wrapped'])
            worksheet.write(data_header_row + offset, 1, entry['abs_effect_size'], formats['numeric'])

        ranked_chart = workbook.add_chart({'type': 'bar'})
        ranked_chart.add_series({
            'name': 'Absolute effect size',
            'categories': [worksheet.name, data_header_row + 1, 0, data_header_row + len(ranked_rows), 0],
            'values': [worksheet.name, data_header_row + 1, 1, data_header_row + len(ranked_rows), 1],
            'fill': {'color': '#4F81BD'},
            'border': {'none': True},
        })
        ranked_chart.set_title({'name': 'Ranked pairwise effects'})
        ranked_chart.set_legend({'position': 'none'})
        ranked_chart.set_size({'width': 520, 'height': 300})
        ranked_chart.set_x_axis({'name': 'Absolute effect size', 'major_gridlines': {'visible': False}})
        ranked_chart.set_y_axis({'reverse': True})
        worksheet.insert_chart(row, 3, ranked_chart, {'x_offset': 8, 'y_offset': 2})
        next_chart_row = max(next_chart_row, row + chart_height_rows)

    if scatter_rows:
        scatter_title_row = row if not ranked_rows else row
        scatter_col = 11 if ranked_rows else 0
        worksheet.write(scatter_title_row, scatter_col, 'Effect vs Adjusted p', formats['section_title'])
        data_header_row = scatter_title_row + 1
        headers = ['Metric', 'Pair', '|effect|', '-log10(adj p)']
        for col, header in enumerate(headers):
            worksheet.write(data_header_row, scatter_col + col, header, formats['table_header'])

        metric_positions = {}
        for entry in scatter_rows:
            metric_positions.setdefault(entry['Metric'], []).append(entry)

        for index, (metric, entries) in enumerate(metric_positions.items()):
            base_col = scatter_col + index * 4
            # Keep metric data contiguous by series while chart remains compact.
            for offset, entry in enumerate(entries, start=1):
                worksheet.write(data_header_row + offset, base_col + 0, metric, formats['body'])
                worksheet.write(data_header_row + offset, base_col + 1, entry['pair_label'], formats['wrapped'])
                worksheet.write(data_header_row + offset, base_col + 2, entry['abs_effect_size'], formats['numeric'])
                worksheet.write(data_header_row + offset, base_col + 3, entry['neg_log10_adj_p'], formats['numeric'])

        scatter_chart = workbook.add_chart({'type': 'scatter', 'subtype': 'straight_with_markers'})
        for index, (metric, entries) in enumerate(metric_positions.items()):
            base_col = scatter_col + index * 4
            scatter_chart.add_series({
                'name': _safe_chart_series_name(metric),
                'categories': [worksheet.name, data_header_row + 1, base_col + 2, data_header_row + len(entries), base_col + 2],
                'values': [worksheet.name, data_header_row + 1, base_col + 3, data_header_row + len(entries), base_col + 3],
                'marker': {'type': 'circle', 'size': 6},
                'line': {'none': True},
            })
        scatter_chart.set_title({'name': 'Effect vs adjusted p'})
        scatter_chart.set_legend({'position': 'bottom'} if len(metric_positions) > 1 else {'position': 'none'})
        scatter_chart.set_size({'width': 520, 'height': 300})
        scatter_chart.set_x_axis({'name': '|effect size|', 'major_gridlines': {'visible': False}})
        scatter_chart.set_y_axis({'name': '-log10(adj p)'})
        worksheet.insert_chart(scatter_title_row, scatter_col + 5, scatter_chart, {'x_offset': 8, 'y_offset': 2})
        next_chart_row = max(next_chart_row, scatter_title_row + chart_height_rows)

    return next_chart_row + SECTION_GAP

def _write_kv_section(worksheet, row, title, items):
    formats = _build_format_bundle(worksheet)
    worksheet.write(row, 0, title, formats['section_title'])
    row += 1
    for key, value in items:
        value_format = formats['wrapped'] if isinstance(value, str) and len(value) > 40 else formats['body']
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value_format = formats['numeric']
        worksheet.write(row, 0, key, formats['table_header'])
        worksheet.write(row, 1, value, value_format)
        row += 1
    return row + SECTION_GAP


def _write_table(worksheet, row, title, rows):
    formats = _build_format_bundle(worksheet)
    worksheet.write(row, 0, title, formats['section_title'])
    row += 1
    if not rows:
        worksheet.write(row, 0, 'No rows', formats['note'])
        return row + SECTION_GAP + 1, None

    headers = list(rows[0].keys())
    for col, header in enumerate(headers):
        worksheet.write(row, col, header, formats['table_header'])
    header_row = row
    _set_table_column_widths(worksheet, headers, formats=formats)
    row += 1
    for data_row in rows:
        for col, header in enumerate(headers):
            value = data_row.get(header)
            if isinstance(value, (dict, list, tuple, set)):
                value = str(value)
            cell_format = formats['wrapped'] if header in LONG_TEXT_HEADERS or (isinstance(value, str) and len(value) > 40) else formats['body']
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cell_format = formats['numeric']
            worksheet.write(row, col, value, cell_format)
        row += 1
    return row + SECTION_GAP, header_row


def _write_note_line(worksheet, row, text, note_format):
    if hasattr(worksheet, 'merge_range'):
        worksheet.merge_range(row, 0, row, 3, text, note_format)
    else:
        worksheet.write(row, 0, text, note_format)


def _sanitize_matrix_value(value):
    if pd.isna(value):
        return None

    if pd.api.types.is_number(value) and not isinstance(value, bool):
        if not np.isfinite(value):
            return None

    return value


def _finite_matrix_max(matrix_df, default):
    numeric_values = pd.to_numeric(matrix_df.to_numpy().ravel(), errors='coerce')
    finite_values = numeric_values[np.isfinite(numeric_values)]
    if finite_values.size == 0:
        return default
    return max(float(finite_values.max()), default)


def _matrix_legend_lines(matrix_type, effect_bands=None, effect_type=None):
    if matrix_type == 'significance':
        return [
            'Legend: gray cells are blank or self-comparisons and should be ignored.',
            'Red means a very strong statistical signal (adjusted p ≤ 0.01). Yellow means a weaker but still important signal (0.01 < adjusted p ≤ 0.05). Green means no statistically reliable difference after correction (> 0.05).',
        ]

    low_band, mid_band = effect_bands or (0.2, 0.5)
    high_band = EFFECT_TYPE_METADATA.get(effect_type or '', {}).get('summary_threshold', mid_band)
    return [
        'Legend: darker cells mean larger practical differences between groups. Gray cells are self-comparisons and should be ignored.',
        f'Light fill: below {low_band:.3f} (smallest tier). Amber: {low_band:.3f} to below {mid_band:.3f}. Blue: {mid_band:.3f} to below {high_band:.3f}. Dark blue: {high_band:.3f} or higher (largest practical tier).',
    ]


def _apply_matrix_conditional_formats(worksheet, first_data_row, first_col, last_row, last_col, *, matrix_type, formats, effect_bands=None, effect_type=None):
    if matrix_type == 'significance':
        rules = [
            {'type': 'blanks', 'format': formats['matrix_blank']},
            {'type': 'cell', 'criteria': '<=', 'value': 0.01, 'format': formats['sig_strong']},
            {'type': 'cell', 'criteria': 'between', 'minimum': 0.0100000001, 'maximum': 0.05, 'format': formats['sig_warn']},
            {'type': 'cell', 'criteria': '>', 'value': 0.05, 'format': formats['sig_ok']},
        ]
    else:
        low_band, mid_band = effect_bands or (0.2, 0.5)
        high_band = EFFECT_TYPE_METADATA.get(effect_type or '', {}).get('summary_threshold', mid_band)
        rules = [
            {'type': 'blanks', 'format': formats['matrix_blank']},
            {'type': 'cell', 'criteria': '<', 'value': low_band, 'format': formats['effect_low']},
            {'type': 'cell', 'criteria': 'between', 'minimum': low_band, 'maximum': max(low_band, mid_band - 1e-9), 'format': formats['effect_mid']},
            {'type': 'cell', 'criteria': 'between', 'minimum': mid_band, 'maximum': max(mid_band, high_band - 1e-9), 'format': formats['effect_med']},
            {'type': 'cell', 'criteria': '>=', 'value': high_band, 'format': formats['effect_high']},
        ]

    for rule in rules:
        worksheet.conditional_format(first_data_row, first_col, last_row, last_col, rule)


def _write_matrix(worksheet, row, title, matrix_df, *, matrix_type, effect_bands=None, effect_type=None):
    formats = _build_format_bundle(worksheet)
    worksheet.write(row, 0, title, formats['section_title'])
    row += 1
    for legend_line in _matrix_legend_lines(matrix_type, effect_bands=effect_bands, effect_type=effect_type):
        worksheet.write(row, 0, legend_line, formats['legend'])
        row += 1
    if matrix_df.empty:
        worksheet.write(row, 0, 'No heatmap data', formats['note'])
        return row + SECTION_GAP + 1

    worksheet.write(row, 0, 'Group', formats['matrix_header'])
    for col, column_name in enumerate(matrix_df.columns, start=1):
        worksheet.write(row, col, column_name, formats['matrix_header'])
        worksheet.set_column(col, col, 12, formats['matrix_value'])
    row += 1

    first_data_row = row
    for group, values in matrix_df.iterrows():
        worksheet.write(row, 0, group, formats['matrix_label'])
        for col, value in enumerate(values.tolist(), start=1):
            worksheet.write(row, col, _sanitize_matrix_value(value), formats['matrix_value'])
        row += 1

    first_col = 1
    last_col = max(1, len(matrix_df.columns))
    _apply_matrix_conditional_formats(
        worksheet,
        first_data_row,
        first_col,
        row - 1,
        last_col,
        matrix_type=matrix_type,
        formats=formats,
        effect_bands=effect_bands,
        effect_type=effect_type,
    )
    return row + SECTION_GAP


def _write_matrix_collection(worksheet, row, title, matrices, *, matrix_type, effect_bands=None, effect_type=None):
    formats = _build_format_bundle(worksheet)
    worksheet.write(row, 0, title, formats['section_title'])
    row += 1
    if not matrices:
        worksheet.write(row, 0, 'No heatmap data', formats['note'])
        return row + SECTION_GAP + 1

    for metric in sorted(matrices):
        row = _write_matrix(
            worksheet,
            row,
            f'Metric: {metric}',
            matrices[metric],
            matrix_type=matrix_type,
            effect_bands=effect_bands,
            effect_type=effect_type,
        )
    return row


def write_group_comparison_sheet(worksheet, payload):
    """Render the legacy Group Comparison worksheet for internal migration checks.

    This writer is retained only for non-default/internal validation paths and
    is not part of the canonical user-facing export contract.

    Fallback behavior:
        Section headers are always emitted even when rows are absent so legacy
        validation callers and tests can rely on a stable schema.
    """
    formats = _build_format_bundle(worksheet)
    row = 0
    row = _write_kv_section(worksheet, row, 'Summary Block', _build_summary_block(payload))

    worksheet.write(row, 0, 'Location / Central-Tendency Tests', formats['section_title'])
    row += 1
    row, _ = _write_table(worksheet, row, 'Group Profile Summary', payload.get('group_profile_rows', []))
    row = _write_kv_section(worksheet, row, 'Location / Central-Tendency Summary', payload.get('overall_summary', []))
    row, _ = _write_table(worksheet, row, 'Location / Central-Tendency Test Details', payload.get('overall_test_rows', []))

    pairwise_rows = _build_pairwise_display_rows(payload.get('pairwise_rows', []))
    row, pairwise_header_row = _write_table(worksheet, row, 'Location / Central-Tendency Pairwise Comparison Table', pairwise_rows)
    row = _render_group_comparison_charts(worksheet, row, payload)

    worksheet.write(row, 0, 'Distribution Shape Section', formats['section_title'])
    row += 1
    row, _ = _write_table(worksheet, row, 'Distribution Shape Profile By Group', payload.get('distribution_profile_rows', []))
    row, _ = _write_table(worksheet, row, 'Distribution Shape Summary', payload.get('distribution_difference_rows', []))
    row, _ = _write_table(worksheet, row, 'Distribution Shape Pairwise Table', _build_distribution_pairwise_display_rows(payload.get('distribution_pairwise_rows', [])))

    worksheet.write(row, 0, 'Matrices', formats['section_title'])
    row += 1
    row = _write_matrix_collection(
        worksheet,
        row,
        'Location Significance Matrix (Adjusted P-Values)',
        payload.get('significance_matrices', {}),
        matrix_type='significance',
    )
    row = _write_matrix_collection(
        worksheet,
        row,
        payload.get('effect_reporting', {}).get('pairwise_matrix_title', 'Pairwise Effect Magnitude Matrix (absolute effect size)'),
        payload.get('effect_matrices', {}),
        matrix_type='effect',
        effect_bands=payload.get('effect_reporting', {}).get('pairwise_effect_bands'),
        effect_type=(payload.get('effect_reporting', {}).get('pairwise_effect_types') or [None])[0],
    )

    worksheet.write(row, 0, 'Notes', formats['section_title'])
    row += 1
    for note in _build_interpretation_notes(payload):
        _write_note_line(worksheet, row, f'• {note}', formats['note'])
        row += 1
    for insight in payload.get('insights', []):
        _write_note_line(worksheet, row, f'• {insight}', formats['note'])
        row += 1

    _apply_final_column_layout(worksheet, formats)
    worksheet.freeze_panes((pairwise_header_row or 0), 0)
