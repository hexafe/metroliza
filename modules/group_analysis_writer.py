"""Worksheet writers for the rebuilt Group Analysis export surfaces."""

from __future__ import annotations


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

    metadata_rows = [
        {'Field': 'Reference', 'Value': metric_row.get('reference')},
        {'Field': 'Group count', 'Value': metric_row.get('group_count')},
        {'Field': 'Spec status', 'Value': metric_row.get('spec_status')},
        {'Field': 'Cp', 'Value': metric_row.get('capability', {}).get('cp')},
        {'Field': 'Cpk', 'Value': metric_row.get('capability', {}).get('cpk')},
    ]
    row = _write_table(worksheet, row, ['Field', 'Value'], metadata_rows)
    row += SECTION_GAP

    row = _write_section_title(worksheet, row, 'Descriptive stats')
    desc_rows = [
        {
            'Group': entry.get('group'),
            'n': entry.get('n'),
            'mean': entry.get('mean'),
            'std': entry.get('std'),
            'min': entry.get('min'),
            'max': entry.get('max'),
        }
        for entry in metric_row.get('descriptive_stats', [])
    ]
    row = _write_table(worksheet, row, ['Group', 'n', 'mean', 'std', 'min', 'max'], desc_rows)
    row += SECTION_GAP

    row = _write_section_title(worksheet, row, 'Pairwise comparisons')
    pairwise_rows = [
        {
            'Group A': entry.get('group_a'),
            'Group B': entry.get('group_b'),
            'adj p-value': entry.get('adjusted_p_value'),
            'effect size': entry.get('effect_size'),
            'test': entry.get('test_used'),
            'significant': entry.get('significant'),
        }
        for entry in metric_row.get('pairwise_rows', [])
    ]
    row = _write_table(
        worksheet,
        row,
        ['Group A', 'Group B', 'adj p-value', 'effect size', 'test', 'significant'],
        pairwise_rows,
    )
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
        {'Field': 'Effective scope', 'Value': diagnostics_payload.get('effective_scope')},
        {'Field': 'Reference count', 'Value': diagnostics_payload.get('reference_count')},
        {'Field': 'Metric count', 'Value': diagnostics_payload.get('metric_count')},
        {'Field': 'Skipped metric count', 'Value': diagnostics_payload.get('skipped_metric_count')},
    ]
    skip_reason = diagnostics_payload.get('skip_reason')
    if skip_reason:
        metadata_rows.append({'Field': 'Skip reason code', 'Value': skip_reason.get('code')})
        metadata_rows.append({'Field': 'Skip reason', 'Value': skip_reason.get('message')})
    row = _write_table(worksheet, row, ['Field', 'Value'], metadata_rows)
    row += SECTION_GAP

    row = _write_section_title(worksheet, row, 'Analyzed metrics')
    analyzed_rows = [
        {
            'metric': entry.get('metric'),
            'reference': entry.get('reference'),
            'groups': entry.get('group_count'),
            'spec_status': entry.get('spec_status'),
            'pairwise_rows': len(entry.get('pairwise_rows', [])),
        }
        for entry in diagnostics_payload.get('metrics', [])
    ]
    row = _write_table(worksheet, row, ['metric', 'reference', 'groups', 'spec_status', 'pairwise_rows'], analyzed_rows)
    row += SECTION_GAP

    row = _write_section_title(worksheet, row, 'Skipped metrics')
    row = _write_table(worksheet, row, ['metric', 'reason'], diagnostics_payload.get('skipped_metrics', []))

    worksheet.freeze_panes(1, 0)
