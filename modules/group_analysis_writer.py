"""Worksheet writers for the rebuilt Group Analysis export surfaces."""

from __future__ import annotations

from modules.group_analysis_service import get_spec_status_label

SECTION_GAP = 1
DEFAULT_PLOT_ROW_SPAN = 16


def _resolve_metric_plot_assets(plot_assets, metric_name):
    if not isinstance(plot_assets, dict):
        return {}
    metric_assets = (plot_assets.get('metrics') or {}).get(metric_name)
    return metric_assets if isinstance(metric_assets, dict) else {}


def _insert_plot_image(worksheet, row, asset):
    if not hasattr(worksheet, 'insert_image'):
        return False

    options = {}
    image_ref = ''
    if isinstance(asset, dict):
        if asset.get('path'):
            image_ref = str(asset.get('path'))
        image_data = asset.get('image_data')
        if image_data is not None:
            options['image_data'] = image_data
        if asset.get('x_scale') is not None:
            options['x_scale'] = asset.get('x_scale')
        if asset.get('y_scale') is not None:
            options['y_scale'] = asset.get('y_scale')

    if not image_ref and 'image_data' not in options:
        return False

    worksheet.insert_image(row, 1, image_ref, options)
    return True


def _get_workbook(worksheet):
    return getattr(worksheet, 'book', None) or getattr(worksheet, 'workbook', None)


def _build_formats(worksheet):
    """Create reusable worksheet formats when a workbook is available."""
    workbook = _get_workbook(worksheet)
    if workbook is None or not hasattr(workbook, 'add_format'):
        return {}

    cached = getattr(worksheet, '_group_analysis_formats', None)
    if cached is not None:
        return cached

    formats = {
        'positive': workbook.add_format({'bg_color': '#E6F4EA', 'font_color': '#1E4620'}),
        'neutral': workbook.add_format({'bg_color': '#EEF2F7', 'font_color': '#334155'}),
        'warning': workbook.add_format({'bg_color': '#FFF4CC', 'font_color': '#7A4E00'}),
        'strong_warning': workbook.add_format({'bg_color': '#FDE2E1', 'font_color': '#8B1C13', 'bold': True}),
        'muted': workbook.add_format({'bg_color': '#F7F7F7', 'font_color': '#8A8F98'}),
        'yes': workbook.add_format({'bg_color': '#E8F3FF', 'font_color': '#0B4F8C', 'bold': True}),
        'no': workbook.add_format({'bg_color': '#F3F4F6', 'font_color': '#6B7280'}),
        'delta_mean_fixed_3': workbook.add_format({'num_format': '0.000'}),
    }
    setattr(worksheet, '_group_analysis_formats', formats)
    return formats


def _style_rule(formats, key, **extra):
    rule = dict(extra)
    if key in formats:
        rule['format'] = formats[key]
    return rule


def _apply_conditional(worksheet, first_row, first_col, last_row, last_col, rule):
    if first_row > last_row or first_col > last_col or not hasattr(worksheet, 'conditional_format'):
        return
    worksheet.conditional_format(first_row, first_col, last_row, last_col, rule)


def _write_section_title(worksheet, row, title):
    worksheet.write(row, 0, title)
    return row + 1


def _write_table(worksheet, row, headers, rows):
    row, _ = _write_table_with_bounds(worksheet, row, headers, rows)
    return row


def _write_table_with_bounds(worksheet, row, headers, rows):
    header_row = row
    for col, header in enumerate(headers):
        worksheet.write(row, col, header)
    row += 1
    if not rows:
        worksheet.write(row, 0, '(no rows)')
        return row + 1, {'header_row': header_row, 'first_data_row': row, 'last_data_row': row, 'headers': headers}

    first_data_row = row
    for entry in rows:
        for col, header in enumerate(headers):
            worksheet.write(row, col, entry.get(header))
        row += 1
    return row, {'header_row': header_row, 'first_data_row': first_data_row, 'last_data_row': row - 1, 'headers': headers}


def _apply_metric_pairwise_formats(worksheet, bounds):
    headers = bounds['headers']
    first = bounds['first_data_row']
    last = bounds['last_data_row']
    if first > last:
        return
    formats = _build_formats(worksheet)

    difference_col = headers.index('Difference')
    comment_col = headers.index('Comment')
    flags_col = headers.index('Flags') if 'Flags' in headers else None
    pvalue_col = headers.index('adj p-value')
    effect_col = headers.index('effect size')
    delta_mean_col = headers.index('Delta mean') if 'Delta mean' in headers else None

    _apply_conditional(worksheet, first, difference_col, last, difference_col, _style_rule(formats, 'strong_warning', type='text', criteria='containing', value='YES'))
    _apply_conditional(worksheet, first, difference_col, last, difference_col, _style_rule(formats, 'neutral', type='text', criteria='containing', value='NO'))
    _apply_conditional(worksheet, first, comment_col, last, comment_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='USE CAUTION'))
    _apply_conditional(worksheet, first, comment_col, last, comment_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='DESCRIPTIVE ONLY'))

    if flags_col is not None:
        _apply_conditional(worksheet, first, flags_col, last, flags_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='LOW N'))
        _apply_conditional(worksheet, first, flags_col, last, flags_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='IMBALANCED N'))
        _apply_conditional(worksheet, first, flags_col, last, flags_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='SPEC?'))
        _apply_conditional(worksheet, first, flags_col, last, flags_col, _style_rule(formats, 'strong_warning', type='text', criteria='containing', value='SEVERELY IMBALANCED N'))

    # Restrained emphasis for clearly significant p-values and very large effects.
    _apply_conditional(worksheet, first, pvalue_col, last, pvalue_col, _style_rule(formats, 'positive', type='cell', criteria='<', value=0.01))
    _apply_conditional(worksheet, first, effect_col, last, effect_col, _style_rule(formats, 'positive', type='cell', criteria='>=', value=1.0))

    if delta_mean_col is not None:
        _apply_conditional(
            worksheet,
            first,
            delta_mean_col,
            last,
            delta_mean_col,
            _style_rule(formats, 'delta_mean_fixed_3', type='no_blanks'),
        )


def _apply_spec_status_and_flag_formats(worksheet, bounds):
    headers = bounds['headers']
    first = bounds['first_data_row']
    last = bounds['last_data_row']
    if first > last:
        return
    formats = _build_formats(worksheet)

    spec_col = headers.index('Spec status')
    comment_col = headers.index('Comment')

    _apply_conditional(worksheet, first, spec_col, last, spec_col, _style_rule(formats, 'positive', type='text', criteria='containing', value='Exact match'))
    _apply_conditional(worksheet, first, spec_col, last, spec_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='Limits differ'))
    _apply_conditional(worksheet, first, spec_col, last, spec_col, _style_rule(formats, 'strong_warning', type='text', criteria='containing', value='Nominal differs'))
    _apply_conditional(worksheet, first, spec_col, last, spec_col, _style_rule(formats, 'muted', type='text', criteria='containing', value='Spec missing'))
    _apply_conditional(worksheet, first, spec_col, last, spec_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='Invalid spec'))

    _apply_conditional(worksheet, first, comment_col, last, comment_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='LOW N'))
    _apply_conditional(worksheet, first, comment_col, last, comment_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='IMBALANCED N'))
    _apply_conditional(worksheet, first, comment_col, last, comment_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='SPEC?'))
    _apply_conditional(worksheet, first, comment_col, last, comment_col, _style_rule(formats, 'strong_warning', type='text', criteria='containing', value='SEVERELY IMBALANCED N'))

    light_col = headers.index('Included in Light')
    standard_col = headers.index('Included in Standard')
    _apply_conditional(worksheet, first, light_col, last, light_col, _style_rule(formats, 'yes', type='text', criteria='containing', value='YES'))
    _apply_conditional(worksheet, first, light_col, last, light_col, _style_rule(formats, 'no', type='text', criteria='containing', value='NO'))
    _apply_conditional(worksheet, first, standard_col, last, standard_col, _style_rule(formats, 'yes', type='text', criteria='containing', value='YES'))
    _apply_conditional(worksheet, first, standard_col, last, standard_col, _style_rule(formats, 'no', type='text', criteria='containing', value='NO'))


def _write_metric_section(worksheet, row, metric_row, *, plot_assets=None):
    row = _write_section_title(worksheet, row, f"Metric: {metric_row.get('metric', 'Unknown')}")

    spec_status_label = metric_row.get('spec_status_label') or get_spec_status_label(metric_row.get('spec_status'))
    metric_meta_rows = [
        {'Field': 'Groups', 'Value': metric_row.get('group_count')},
        {'Field': 'Spec status', 'Value': spec_status_label},
        {'Field': 'Distribution difference', 'Value': (metric_row.get('distribution_difference') or {}).get('comment / verdict')},
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
            'Best fit model': entry.get('best_fit_model'),
            'Fit quality': entry.get('fit_quality'),
            'Distribution caution': entry.get('distribution_shape_caution'),
            'Flags': entry.get('flags'),
        }
        for entry in metric_row.get('descriptive_stats', [])
    ]
    row = _write_table(
        worksheet,
        row,
        [
            'Group', 'n', 'mean', 'std', 'median', 'IQR', 'min', 'max', 'Cp', 'Capability', 'Capability type',
            'Best fit model', 'Fit quality', 'Distribution caution', 'Flags',
        ],
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
            'Flags': entry.get('flags'),
        }
        for entry in metric_row.get('pairwise_rows', [])
    ]
    row, pairwise_bounds = _write_table_with_bounds(
        worksheet,
        row,
        ['Group A', 'Group B', 'adj p-value', 'effect size', 'test', 'Delta mean', 'Difference', 'Comment', 'Flags'],
        pairwise_rows,
    )
    _apply_metric_pairwise_formats(worksheet, pairwise_bounds)
    row += SECTION_GAP

    insights = metric_row.get('insights', [])
    concise_line = insights[0] if insights else 'No insight available.'
    worksheet.write(row, 0, 'Comment')
    worksheet.write(row, 1, concise_line)
    row += 1

    plot_eligibility = metric_row.get('plot_eligibility') or {}
    analysis_level = str(metric_row.get('analysis_level') or '').strip().lower()
    if analysis_level == 'standard':
        metric_assets = _resolve_metric_plot_assets(plot_assets, metric_row.get('metric'))
        row += SECTION_GAP
        row = _write_section_title(worksheet, row, 'Standard plot slots')
        worksheet.write(row, 0, 'Plot')
        worksheet.write(row, 1, 'Status')
        worksheet.write(row, 2, 'Detail')
        row += 1

        for plot_key, plot_label in (('violin', 'Violin'), ('histogram', 'Histogram')):
            eligibility = plot_eligibility.get(plot_key) or {}
            eligible = bool(eligibility.get('eligible'))
            skip_reason = str(eligibility.get('skip_reason') or 'ineligible')
            asset = metric_assets.get(plot_key)

            if not eligible:
                worksheet.write(row, 0, plot_label)
                worksheet.write(row, 1, 'SKIPPED')
                worksheet.write(row, 2, skip_reason)
                row += 1
                continue

            inserted = _insert_plot_image(worksheet, row + 1, asset)
            if inserted:
                worksheet.write(row, 0, plot_label)
                worksheet.write(row, 1, 'INSERTED')
                worksheet.write(row, 2, 'Chart inserted')
                row_span = DEFAULT_PLOT_ROW_SPAN
                if isinstance(asset, dict) and isinstance(asset.get('row_span'), int) and asset.get('row_span') > 0:
                    row_span = int(asset.get('row_span'))
                row += 1 + row_span
            else:
                worksheet.write(row, 0, plot_label)
                worksheet.write(row, 1, 'SKIPPED')
                worksheet.write(row, 2, 'asset_missing')
                row += 1

    row += SECTION_GAP
    return row


def write_group_analysis_sheet(worksheet, payload, *, plot_assets=None):
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

    normalized_level = str(payload.get('analysis_level') or 'light').strip().lower()
    for metric_row in payload.get('metric_rows', []):
        metric_with_level = dict(metric_row)
        metric_with_level['analysis_level'] = normalized_level
        row = _write_metric_section(worksheet, row, metric_with_level, plot_assets=plot_assets)

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

    status_counts = diagnostics_payload.get('status_counts', {}) or {}
    spec_status_keys = ['EXACT_MATCH', 'LIMIT_MISMATCH', 'NOM_MISMATCH', 'INVALID_SPEC']
    row = _write_section_title(worksheet, row, 'Spec status counts')
    status_count_rows = [
        {
            'Status key': status_key,
            'Status': get_spec_status_label(status_key),
            'Count': status_counts.get(status_key, 0),
        }
        for status_key in spec_status_keys
    ]
    row = _write_table(worksheet, row, ['Status key', 'Status', 'Count'], status_count_rows)
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

    row, coverage_bounds = _write_table_with_bounds(
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
    _apply_spec_status_and_flag_formats(worksheet, coverage_bounds)

    row += SECTION_GAP

    worksheet.freeze_panes(1, 0)
