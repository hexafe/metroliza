"""Build and render the Group Comparison worksheet sections for exports.

Statistical rationale:
    The sheet is designed to keep assumption checks, omnibus test choice,
    pairwise correction, and effect-size context in one deterministic view.

Fallback behavior:
    Empty/invalid inputs still render all section scaffolding with explicit
    "no rows/data" markers so users can distinguish missing data from failures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from modules.characteristic_alias_service import resolve_characteristic_alias
from modules.comparison_stats import ComparisonStatsConfig, compute_metric_pairwise_stats
from modules.distribution_shape_analysis import compute_distribution_difference
from modules.group_stats_tests import select_group_stat_test


SECTION_GAP = 2

INTERPRETATION_NOTES = [
    'Alpha threshold: 0.05 (results below alpha are treated as statistically significant).',
    'Raw p-value: probability of observing the data assuming no true group difference.',
    'Adjusted p-value: multiple-comparison corrected p-value (Holm by default; configurable Holm/BH) used for significance decisions.',
    'Significance bands: adjusted p >= 0.05 (green), 0.01 to < 0.05 (yellow), < 0.01 (red).',
    'Effect size guide (|d|): < 0.2 small/negligible, 0.2 to 0.5 moderate, > 0.5 large.',
]


def _build_pairwise_group_matrices(pairwise_df):
    """Build per-metric square matrices for adjusted p-values and effect sizes."""
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
            f'lowest mean={lowest_group} ({group_means.iloc[-1]:.3f}).'
        )

    if pairwise_df.empty:
        insights.extend(
            [
                'Significant pairwise findings: none (no pairwise comparisons were available).',
                'No-difference outcomes: none (no pairwise comparisons were available).',
                'Small-sample warning: no pairwise comparisons were available.',
                'Assumption/test-choice notes: no per-metric test selection was available.',
            ]
        )
        return insights

    adj_p = pd.to_numeric(pairwise_df['adjusted p-value'], errors='coerce')

    significant = pairwise_df[adj_p < 0.05]
    if significant.empty:
        insights.append('Significant pairwise findings: none at adjusted p < 0.05.')
    else:
        significant_labels = [
            f"{row['Metric']} ({row['Group A']} vs {row['Group B']}, adj p={row['adjusted p-value']:.4f})"
            for _, row in significant.sort_values(['Metric', 'adjusted p-value', 'Group A', 'Group B']).iterrows()
        ]
        insights.append('Significant pairwise findings: ' + '; '.join(significant_labels) + '.')

    no_difference = pairwise_df[adj_p >= 0.05]
    if no_difference.empty:
        insights.append('No-difference outcomes: all tested pairs were significant after adjustment.')
    else:
        no_diff_labels = [
            f"{row['Metric']} ({row['Group A']} vs {row['Group B']}, adj p={row['adjusted p-value']:.4f})"
            for _, row in no_difference.sort_values(['Metric', 'adjusted p-value', 'Group A', 'Group B']).iterrows()
        ]
        insights.append('No-difference outcomes: ' + '; '.join(no_diff_labels) + '.')

    small_sample_pairs = pairwise_df[(pairwise_df['n(A)'] < 5) | (pairwise_df['n(B)'] < 5)]
    if small_sample_pairs.empty:
        insights.append('Small-sample warning: all compared groups had n >= 5.')
    else:
        warning_labels = [
            f"{row['Metric']} ({row['Group A']} n={row['n(A)']}, {row['Group B']} n={row['n(B)']})"
            for _, row in small_sample_pairs.sort_values(['Metric', 'Group A', 'Group B']).iterrows()
        ]
        insights.append('Small-sample warning (n < 5): ' + '; '.join(warning_labels) + '.')

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
        insights.append('Distribution-shape findings: no distribution-shape tests were available.')
    else:
        shape_significant = [
            row for row in distribution_summary_rows if str(row.get('significant?', '')).strip().upper() == 'YES'
        ]
        if shape_significant:
            labels = [f"{row['Metric']} ({row.get('Test used')}, p={row.get('raw p-value'):.4f})" for row in shape_significant if row.get('raw p-value') is not None]
            insights.append('Distribution-shape findings: significant differences detected for ' + '; '.join(labels) + '.')
        else:
            insights.append('Distribution-shape findings: no statistically significant shape differences were detected.')

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


def prepare_group_comparison_payload(grouped_df, *, alias_db_path=None):
    """Prepare metadata, summary rows, pairwise rows, matrices, and insights.

    Rationale:
        Converts export-filtered long-form measurements into stable comparison
        artifacts used by both tables and heatmaps.

    Fallback behavior:
        Returns deterministic empty payload sections when the filtered dataframe
        has no usable numeric measurements.
    """
    if not isinstance(grouped_df, pd.DataFrame) or grouped_df.empty:
        return {
            'metadata': [('Rows', 0), ('Groups', 0), ('Headers', 0), ('Alpha', 0.05), ('Correction method', 'Holm'), ('Group sample sizes', 'No groups')],
            'overall_summary': [('Pairwise tests', 0), ('Significant (p < 0.05)', 0), ('Large effects (|d| >= 0.8)', 0)],
            'pairwise_rows': [],
            'overall_test_rows': [],
            'distribution_profile_rows': [],
            'distribution_difference_rows': [],
            'distribution_pairwise_rows': [],
            'significance_matrices': {},
            'effect_matrices': {},
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
        post_hoc_strategy = 'Dunn' if selected_test in {'Mann-Whitney U', 'Kruskal-Wallis'} else 'Tukey'
        overall_test_rows.append(
            {
                'Metric': metric_key,
                'Selected test': selected_test,
                'p-value': selector_result.get('p_value'),
                'Sample sizes': ', '.join(f"{key}:{value}" for key, value in selector_result.get('sample_sizes', {}).items()),
                'normality check used': 'Shapiro-Wilk',
                'variance test used': selector_result.get('assumptions', {}).get('variance_homogeneity', {}).get('test') or 'Brown-Forsythe',
                'omnibus test used': selected_test,
                'post-hoc strategy': post_hoc_strategy,
                'Assumptions / warnings': '; '.join(selector_result.get('warnings', [])) or 'None',
            }
        )

        comparison_rows = compute_metric_pairwise_stats(
            metric_key,
            group_series,
            config=ComparisonStatsConfig(alpha=0.05, correction_method='holm'),
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
                    'p-value': item.get('p_value'),
                    'adjusted p-value': item.get('adjusted_p_value'),
                    'effect size': item.get('effect_size'),
                    'significant': item.get('significant'),
                    'n(A)': len(sample_left),
                    'n(B)': len(sample_right),
                    'Mean Δ (A-B)': mean_delta,
                    'normality check used': item.get('normality_check_used'),
                    'variance test used': item.get('variance_test_used'),
                    'omnibus test used': item.get('omnibus_test_used'),
                    'post-hoc strategy': item.get('post_hoc_strategy'),
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
    large_effect_series = pd.to_numeric(pairwise_df['effect size'], errors='coerce') if not pairwise_df.empty else pd.Series(dtype=float)
    large_effect_count = int((large_effect_series.abs() >= 0.8).sum()) if not pairwise_df.empty else 0

    return {
        'metadata': [
            ('Rows', len(working)),
            ('Groups', working['GROUP'].nunique()),
            ('Headers', working['metric_key'].nunique()),
            ('Alpha', 0.05),
            ('Correction method', 'Holm'),
            ('Group sample sizes', _summarize_group_sample_sizes(working)),
        ],
        'overall_summary': [
            ('Pairwise tests', len(pairwise_rows)),
            ('Significant (p < 0.05)', significant_count),
            ('Large effects (|d| >= 0.8)', large_effect_count),
        ],
        'pairwise_rows': pairwise_rows,
        'overall_test_rows': overall_test_rows,
        'distribution_profile_rows': [
            {k: v for k, v in row.items() if not k.startswith('_')} for row in distribution_profile_rows
        ],
        'distribution_difference_rows': distribution_difference_rows,
        'distribution_pairwise_rows': distribution_pairwise_rows,
        'significance_matrices': significance_matrices,
        'effect_matrices': effect_matrices,
        'insights': _build_insights(working, pairwise_df, overall_test_rows, distribution_difference_rows),
    }


def _write_kv_section(worksheet, row, title, items):
    worksheet.write(row, 0, title)
    row += 1
    for key, value in items:
        worksheet.write(row, 0, key)
        worksheet.write(row, 1, value)
        row += 1
    return row + SECTION_GAP


def _write_table(worksheet, row, title, rows):
    worksheet.write(row, 0, title)
    row += 1
    if not rows:
        worksheet.write(row, 0, 'No rows')
        return row + SECTION_GAP + 1

    headers = list(rows[0].keys())
    for col, header in enumerate(headers):
        worksheet.write(row, col, header)
    row += 1
    for data_row in rows:
        for col, header in enumerate(headers):
            worksheet.write(row, col, data_row.get(header))
        row += 1
    return row + SECTION_GAP


def _sanitize_matrix_value(value):
    if pd.isna(value):
        return None

    if pd.api.types.is_number(value) and not isinstance(value, bool):
        if not np.isfinite(value):
            return None

    return value


def _write_matrix(worksheet, row, title, matrix_df, *, matrix_type):
    worksheet.write(row, 0, title)
    row += 1
    if matrix_df.empty:
        worksheet.write(row, 0, 'No heatmap data')
        return row + SECTION_GAP + 1

    worksheet.write(row, 0, 'Group')
    for col, column_name in enumerate(matrix_df.columns, start=1):
        worksheet.write(row, col, column_name)
    row += 1

    first_data_row = row
    for group, values in matrix_df.iterrows():
        worksheet.write(row, 0, group)
        for col, value in enumerate(values.tolist(), start=1):
            worksheet.write(row, col, _sanitize_matrix_value(value))
        row += 1

    first_col = 1
    last_col = max(1, len(matrix_df.columns))
    if matrix_type == 'significance':
        worksheet.conditional_format(
            first_data_row,
            first_col,
            row - 1,
            last_col,
            {'type': 'cell', 'criteria': '>=', 'value': 0.05},
        )
        worksheet.conditional_format(
            first_data_row,
            first_col,
            row - 1,
            last_col,
            {'type': 'cell', 'criteria': 'between', 'minimum': 0.01, 'maximum': 0.049999},
        )
        worksheet.conditional_format(
            first_data_row,
            first_col,
            row - 1,
            last_col,
            {'type': 'cell', 'criteria': '<', 'value': 0.01},
        )
    else:
        worksheet.conditional_format(
            first_data_row,
            first_col,
            row - 1,
            last_col,
            {'type': 'cell', 'criteria': '<', 'value': 0.2},
        )
        worksheet.conditional_format(
            first_data_row,
            first_col,
            row - 1,
            last_col,
            {'type': 'cell', 'criteria': 'between', 'minimum': 0.2, 'maximum': 0.5},
        )
        worksheet.conditional_format(
            first_data_row,
            first_col,
            row - 1,
            last_col,
            {'type': 'cell', 'criteria': '>', 'value': 0.5},
        )
    return row + SECTION_GAP


def _write_matrix_collection(worksheet, row, title, matrices, *, matrix_type):
    worksheet.write(row, 0, title)
    row += 1
    if not matrices:
        worksheet.write(row, 0, 'No heatmap data')
        return row + SECTION_GAP + 1

    for metric in sorted(matrices):
        row = _write_matrix(worksheet, row, f'Metric: {metric}', matrices[metric], matrix_type=matrix_type)
    return row


def write_group_comparison_sheet(worksheet, payload):
    """Render the complete Group Comparison worksheet layout.

    Fallback behavior:
        Section headers are always emitted even when rows are absent, ensuring
        workbook consumers and tests can rely on a stable report schema.
    """
    row = 0
    worksheet.write(row, 0, 'How to interpret these results')
    row += 1
    for note in INTERPRETATION_NOTES:
        worksheet.write(row, 0, f'• {note}')
        row += 1
    row += SECTION_GAP

    row = _write_kv_section(worksheet, row, 'Metadata', payload.get('metadata', []))
    row = _write_kv_section(worksheet, row, 'Overall Test Summary', payload.get('overall_summary', []))
    row = _write_table(worksheet, row, 'Recommended Statistical Tests', payload.get('overall_test_rows', []))
    row = _write_table(worksheet, row, 'Distribution profile by group', payload.get('distribution_profile_rows', []))
    row = _write_table(worksheet, row, 'Distribution difference summary', payload.get('distribution_difference_rows', []))
    row = _write_table(worksheet, row, 'Pairwise Tables', payload.get('pairwise_rows', []))
    row = _write_table(worksheet, row, 'Distribution pairwise tables', payload.get('distribution_pairwise_rows', []))
    row = _write_matrix_collection(
        worksheet,
        row,
        'Significance Matrix (adjusted p-values)',
        payload.get('significance_matrices', {}),
        matrix_type='significance',
    )
    row = _write_matrix_collection(
        worksheet,
        row,
        'Effect Size Matrix (|d|)',
        payload.get('effect_matrices', {}),
        matrix_type='effect',
    )

    worksheet.write(row, 0, 'Insights')
    row += 1
    for insight in payload.get('insights', []):
        worksheet.write(row, 0, f'• {insight}')
        row += 1

    worksheet.set_column(0, 0, 34)
    worksheet.set_column(1, 10, 18)
    worksheet.freeze_panes(1, 0)
