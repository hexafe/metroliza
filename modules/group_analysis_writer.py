"""Worksheet writers for the rebuilt Group Analysis export surfaces."""

from __future__ import annotations

from modules.group_analysis_service import get_spec_status_label

SECTION_GAP = 1


def _write_section_title(worksheet, row, title):
    worksheet.write(row, 0, title)
    return row + 1


def _write_table(worksheet, row, headers, rows):
    for col, header in enumerate(headers):
        worksheet.write(row, col, header)
    row += 1
    if not rows:
        worksheet.write(row, 0, '(no rows)')
        return row + 1

    for entry in rows:
        for col, header in enumerate(headers):
            worksheet.write(row, col, entry.get(header))
        row += 1
    return row


def _write_metric_section(worksheet, row, metric_row):
    row = _write_section_title(worksheet, row, f"Metric: {metric_row.get('metric', 'Unknown')}")

    spec_status_label = metric_row.get('spec_status_label') or get_spec_status_label(metric_row.get('spec_status'))
    metric_meta_rows = [
        {'Field': 'Groups', 'Value': metric_row.get('group_count')},
        {'Field': 'Spec status', 'Value': spec_status_label},
        {'Field': 'Comment', 'Value': metric_row.get('diagnostics_comment') or (metric_row.get('comparability_summary') or {}).get('summary')},
    ]
    row = _write_table(worksheet, row, ['Field', 'Value'], metric_meta_rows)
    row += SECTION_GAP

    row = _write_section_title(worksheet, row, 'Descriptive stats')
    desc_rows = [
        {
            'Group': entry.get('group'),
            'n': entry.get('n'),
            'mean': entry.get('mean'),
            'std': entry.get('std'),
            'median': entry.get('median'),
            'IQR': entry.get('iqr'),
            'min': entry.get('min'),
            'max': entry.get('max'),
            'Cp': entry.get('cp'),
            'Capability': entry.get('capability'),
            'Capability type': entry.get('capability_type'),
            'Flags': entry.get('flags'),
        }
        for entry in metric_row.get('descriptive_stats', [])
    ]
    row = _write_table(
        worksheet,
        row,
        ['Group', 'n', 'mean', 'std', 'median', 'IQR', 'min', 'max', 'Cp', 'Capability', 'Capability type', 'Flags'],
        desc_rows,
    )
    row += SECTION_GAP

    row = _write_section_title(worksheet, row, 'Pairwise comparisons')
    pairwise_rows = [
        {
            'Group A': entry.get('group_a'),
            'Group B': entry.get('group_b'),
            'adj p-value': entry.get('adjusted_p_value'),
            'effect size': entry.get('effect_size'),
            'test': entry.get('test_used'),
            'Delta mean': entry.get('delta_mean'),
            'Difference': entry.get('difference'),
            'Comment': entry.get('comment'),
        }
        for entry in metric_row.get('pairwise_rows', [])
    ]
    row = _write_table(
        worksheet,
        row,
        ['Group A', 'Group B', 'adj p-value', 'effect size', 'test', 'Delta mean', 'Difference', 'Comment'],
        pairwise_rows,
    )
    row += SECTION_GAP

    insights = metric_row.get('insights', [])
    concise_line = insights[0] if insights else 'No insight available.'
    worksheet.write(row, 0, 'Comment')
    worksheet.write(row, 1, concise_line)
    row += 1
    row += SECTION_GAP
    return row


def write_group_analysis_sheet(worksheet, payload):
    """Write compact metric-level Group Analysis output into a worksheet."""
    row = 0
    row = _write_section_title(worksheet, row, 'Group Analysis')
    summary_rows = [
        {'Field': 'Status', 'Value': payload.get('status')},
        {'Field': 'Effective scope', 'Value': payload.get('effective_scope')},
        {'Field': 'Metric count', 'Value': len(payload.get('metric_rows', []))},
    ]
    if payload.get('skip_reason'):
        summary_rows.append({'Field': 'Skip reason', 'Value': payload['skip_reason'].get('message')})
    row = _write_table(worksheet, row, ['Field', 'Value'], summary_rows)
    row += SECTION_GAP

    for metric_row in payload.get('metric_rows', []):
        row = _write_metric_section(worksheet, row, metric_row)

    worksheet.freeze_panes(1, 0)


def write_group_analysis_diagnostics_sheet(worksheet, diagnostics_payload):
    """Write diagnostics details for scope resolution and metric coverage."""
    row = 0
    row = _write_section_title(worksheet, row, 'Group Analysis Diagnostics')

    metadata_rows = [
        {'Field': 'Requested scope', 'Value': diagnostics_payload.get('requested_scope')},
        {'Field': 'Requested level', 'Value': diagnostics_payload.get('requested_level')},
        {'Field': 'Execution status', 'Value': diagnostics_payload.get('execution_status')},
        {'Field': 'Effective scope', 'Value': diagnostics_payload.get('effective_scope')},
        {'Field': 'Reference count', 'Value': diagnostics_payload.get('reference_count')},
        {'Field': 'Group count', 'Value': diagnostics_payload.get('group_count')},
        {'Field': 'Metric count', 'Value': diagnostics_payload.get('metric_count')},
        {'Field': 'Skipped metric count', 'Value': diagnostics_payload.get('skipped_metric_count')},
    ]
    skip_reason = diagnostics_payload.get('skip_reason')
    if skip_reason:
        metadata_rows.append({'Field': 'Skip reason code', 'Value': skip_reason.get('code')})
        metadata_rows.append({'Field': 'Skip reason', 'Value': skip_reason.get('message')})
    row = _write_table(worksheet, row, ['Field', 'Value'], metadata_rows)
    row += SECTION_GAP

    warning_summary = diagnostics_payload.get('warning_summary', {})
    row = _write_section_title(worksheet, row, 'Warning summary')
    warning_rows = [
        {'Field': 'Warning count', 'Value': warning_summary.get('count', 0)},
        {'Field': 'Messages', 'Value': '; '.join(warning_summary.get('messages', [])) or 'none'},
        {
            'Field': 'Skip reason counts',
            'Value': '; '.join(
                f"{reason}={count}"
                for reason, count in sorted((warning_summary.get('skip_reason_counts') or {}).items())
            )
            or 'none',
        },
    ]
    row = _write_table(worksheet, row, ['Field', 'Value'], warning_rows)
    row += SECTION_GAP

    histogram_skip_summary = diagnostics_payload.get('histogram_skip_summary', {})
    row = _write_section_title(worksheet, row, 'Histogram skip summary')
    histogram_rows = [
        {'Field': 'Applies', 'Value': histogram_skip_summary.get('applies', False)},
        {'Field': 'Count', 'Value': histogram_skip_summary.get('count', 0)},
        {
            'Field': 'Reasons',
            'Value': '; '.join(
                f"{reason}={count}"
                for reason, count in sorted((histogram_skip_summary.get('reason_counts') or {}).items())
            )
            or 'none',
        },
    ]
    row = _write_table(worksheet, row, ['Field', 'Value'], histogram_rows)
    row += SECTION_GAP

    unmatched_metrics_summary = diagnostics_payload.get('unmatched_metrics_summary', {})
    row = _write_section_title(worksheet, row, 'Possible unmatched metrics across references')
    unmatched_rows = [
        {'Field': 'Count', 'Value': unmatched_metrics_summary.get('count', 0)},
    ]
    metrics = unmatched_metrics_summary.get('metrics', []) or []
    if metrics:
        unmatched_rows.append(
            {
                'Field': 'Metrics',
                'Value': '; '.join(
                    (
                        f"{entry.get('metric')}: "
                        f"present=[{', '.join(entry.get('present_references', []))}] "
                        f"missing=[{', '.join(entry.get('missing_references', []))}]"
                    )
                    for entry in metrics
                ),
            }
        )
    else:
        unmatched_rows.append({'Field': 'Metrics', 'Value': 'none'})
    row = _write_table(worksheet, row, ['Field', 'Value'], unmatched_rows)
    row += SECTION_GAP

    row = _write_section_title(worksheet, row, 'Metric coverage')
    coverage_rows = [
        {
            'Metric': entry.get('Metric', entry.get('metric')),
            'Groups': entry.get('Groups', entry.get('groups', entry.get('group_count'))),
            'Spec status': entry.get('Spec status', entry.get('spec_status_label') or get_spec_status_label(entry.get('spec_status'))),
            'Pairwise comparisons': entry.get(
                'Pairwise comparisons',
                entry.get('pairwise_comparisons', len(entry.get('pairwise_rows', []) or [])),
            ),
            'Included in Light': entry.get('Included in Light', entry.get('included_in_light', 'NO')),
            'Included in Standard': entry.get('Included in Standard', entry.get('included_in_standard', 'NO')),
            'Comment': entry.get('Comment', entry.get('comment', entry.get('diagnostics_comment') or 'Analyzed')),
        }
        for entry in (diagnostics_payload.get('metric_diagnostics_rows') or [])
    ]
    if not coverage_rows:
        coverage_rows = [
            {
                'Metric': entry.get('metric'),
                'Groups': entry.get('group_count'),
                'Spec status': entry.get('spec_status_label') or get_spec_status_label(entry.get('spec_status')),
                'Pairwise comparisons': len(entry.get('pairwise_rows', []) or []),
                'Included in Light': 'YES',
                'Included in Standard': 'YES' if str(entry.get('spec_status') or '').upper() == 'EXACT_MATCH' else 'NO',
                'Comment': entry.get('diagnostics_comment') or 'Analyzed',
            }
            for entry in diagnostics_payload.get('metrics', [])
        ]
        coverage_rows.extend(
            {
                'Metric': entry.get('metric'),
                'Groups': entry.get('group_count'),
                'Spec status': get_spec_status_label(entry.get('reason')),
                'Pairwise comparisons': 0,
                'Included in Light': 'NO',
                'Included in Standard': 'NO',
                'Comment': f"Skipped: {entry.get('reason')}",
            }
            for entry in diagnostics_payload.get('skipped_metrics', [])
        )

    row = _write_table(
        worksheet,
        row,
        [
            'Metric',
            'Groups',
            'Spec status',
            'Pairwise comparisons',
            'Included in Light',
            'Included in Standard',
            'Comment',
        ],
        coverage_rows,
    )

    row += SECTION_GAP

    worksheet.freeze_panes(1, 0)
