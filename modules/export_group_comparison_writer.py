"""Build and render the Group Comparison worksheet sections for exports."""

from __future__ import annotations

import pandas as pd

from modules.comparison_stats import ComparisonStatsConfig, compute_metric_pairwise_stats
from modules.group_stats_tests import select_group_stat_test


SECTION_GAP = 2



def prepare_group_comparison_payload(grouped_df):
    """Prepare metadata, summary rows, pairwise rows, heatmaps, and insights."""
    if not isinstance(grouped_df, pd.DataFrame) or grouped_df.empty:
        return {
            'metadata': [('Rows', 0), ('Groups', 0), ('Headers', 0)],
            'overall_summary': [('Pairwise tests', 0), ('Significant (p < 0.05)', 0), ('Large effects (|d| >= 0.8)', 0)],
            'pairwise_rows': [],
            'significance_heatmap': pd.DataFrame(),
            'effect_heatmap': pd.DataFrame(),
            'insights': ['No grouped measurement rows available for comparison.'],
        }

    working = grouped_df.copy()
    if 'GROUP' not in working.columns:
        working['GROUP'] = 'UNGROUPED'
    working['GROUP'] = working['GROUP'].fillna('UNGROUPED').astype(str)
    working['metric_key'] = working.get('HEADER - AX', working.get('HEADER', 'UNKNOWN')).fillna('UNKNOWN').astype(str)

    numeric_meas = pd.to_numeric(working.get('MEAS'), errors='coerce')
    working = working.assign(MEAS=numeric_meas)
    working = working.dropna(subset=['MEAS'])

    pairwise_rows = []
    overall_test_rows = []
    sig_map = {}
    effect_map = {}

    for metric_key, metric_frame in working.groupby('metric_key', sort=False):
        group_series = {
            group_name: group_values['MEAS'].tolist()
            for group_name, group_values in metric_frame.groupby('GROUP', sort=False)
        }

        selector_result = select_group_stat_test(
            labels=list(group_series.keys()),
            grouped_values=list(group_series.values()),
        )
        overall_test_rows.append(
            {
                'Metric': metric_key,
                'Selected test': selector_result.get('test_name') or 'N/A',
                'p-value': selector_result.get('p_value'),
                'Sample sizes': ', '.join(f"{key}:{value}" for key, value in selector_result.get('sample_sizes', {}).items()),
                'Assumptions / warnings': '; '.join(selector_result.get('warnings', [])) or 'None',
            }
        )

        comparison_rows = compute_metric_pairwise_stats(
            metric_key,
            group_series,
            config=ComparisonStatsConfig(correction_method='holm'),
        )
        for item in comparison_rows:
            group_a = item['group_a']
            group_b = item['group_b']
            sample_left = group_series[group_a]
            sample_right = group_series[group_b]
            mean_delta = float(pd.Series(sample_left).mean() - pd.Series(sample_right).mean())
            p_value = item.get('p_value')
            effect = item.get('effect_size')
            pairwise_rows.append(
                {
                    'Metric': metric_key,
                    'Group A': group_a,
                    'Group B': group_b,
                    'n(A)': len(sample_left),
                    'n(B)': len(sample_right),
                    'Mean Δ (A-B)': mean_delta,
                    'Test': item.get('test_used'),
                    'p-value': p_value,
                    'Adjusted p-value': item.get('adjusted_p_value'),
                    'Effect size': effect,
                    'Significant': item.get('significant'),
                }
            )
            label = f'{group_a} vs {group_b}'
            sig_map.setdefault(metric_key, {})[label] = p_value
            effect_map.setdefault(metric_key, {})[label] = effect

    pairwise_df = pd.DataFrame(pairwise_rows)
    significant_count = int(pairwise_df['Significant'].sum()) if not pairwise_df.empty else 0
    large_effect_count = int((pairwise_df['Effect size'].abs() >= 0.8).sum()) if not pairwise_df.empty else 0

    insights = []
    if pairwise_df.empty:
        insights.append('Not enough distinct groups per metric to compute pairwise comparisons.')
    else:
        top_effect = pairwise_df.iloc[pairwise_df['Effect size'].abs().fillna(0).idxmax()]
        insights.append(
            f"Largest effect: {top_effect['Metric']} ({top_effect['Group A']} vs {top_effect['Group B']}) effect={top_effect['Effect size']:.3f}."
        )
        insights.append(f'Significant comparisons (adjusted p < 0.05): {significant_count}.')

    return {
        'metadata': [
            ('Rows', len(working)),
            ('Groups', working['GROUP'].nunique()),
            ('Headers', working['metric_key'].nunique()),
        ],
        'overall_summary': [
            ('Pairwise tests', len(pairwise_rows)),
            ('Significant (p < 0.05)', significant_count),
            ('Large effects (|d| >= 0.8)', large_effect_count),
        ],
        'pairwise_rows': pairwise_rows,
        'overall_test_rows': overall_test_rows,
        'significance_heatmap': pd.DataFrame(sig_map).T,
        'effect_heatmap': pd.DataFrame(effect_map).T,
        'insights': insights,
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


def _write_heatmap(worksheet, row, title, heatmap_df, *, color):
    worksheet.write(row, 0, title)
    row += 1
    if heatmap_df.empty:
        worksheet.write(row, 0, 'No heatmap data')
        return row + SECTION_GAP + 1

    worksheet.write(row, 0, 'Metric')
    for col, column_name in enumerate(heatmap_df.columns, start=1):
        worksheet.write(row, col, column_name)
    row += 1

    first_data_row = row
    for metric, values in heatmap_df.iterrows():
        worksheet.write(row, 0, metric)
        for col, value in enumerate(values.tolist(), start=1):
            worksheet.write(row, col, value)
        row += 1

    worksheet.conditional_format(
        first_data_row,
        1,
        row - 1,
        max(1, len(heatmap_df.columns)),
        {
            'type': '3_color_scale',
            'min_color': '#FFFFFF',
            'mid_color': '#FFE699',
            'max_color': color,
        },
    )
    return row + SECTION_GAP


def write_group_comparison_sheet(worksheet, payload):
    """Render the complete Group Comparison worksheet layout."""
    row = 0
    worksheet.write(row, 0, 'Group Comparison - Interpretation Guide')
    row += 1
    worksheet.write(row, 0, 'Use p-value (< 0.05) for statistical significance and Cohen d for effect magnitude.')
    row += SECTION_GAP

    row = _write_kv_section(worksheet, row, 'Metadata', payload.get('metadata', []))
    row = _write_kv_section(worksheet, row, 'Overall Test Summary', payload.get('overall_summary', []))
    row = _write_table(worksheet, row, 'Recommended Statistical Tests', payload.get('overall_test_rows', []))
    row = _write_table(worksheet, row, 'Pairwise Tables', payload.get('pairwise_rows', []))
    row = _write_heatmap(worksheet, row, 'Significance Heatmap (p-values)', payload.get('significance_heatmap', pd.DataFrame()), color='#F4B183')
    row = _write_heatmap(worksheet, row, 'Effect Size Heatmap (|d|)', payload.get('effect_heatmap', pd.DataFrame()).abs(), color='#9DC3E6')

    worksheet.write(row, 0, 'Insights')
    row += 1
    for insight in payload.get('insights', []):
        worksheet.write(row, 0, f'• {insight}')
        row += 1

    worksheet.set_column(0, 0, 34)
    worksheet.set_column(1, 10, 18)
    worksheet.freeze_panes(1, 0)
