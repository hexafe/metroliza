"""Worksheet writers for the canonical Group Analysis workbook sheet."""

from __future__ import annotations

from pathlib import Path

from modules.group_analysis_service import get_spec_status_label

SECTION_GAP = 1
DEFAULT_PLOT_ROW_SPAN = 16
DEFAULT_ROW_HEIGHT = 22
DEFAULT_LINE_HEIGHT = 14
GROUP_ANALYSIS_COLUMN_WIDTHS = {
    0: 18,
    1: 18,
    2: 16,
    3: 12,
    4: 18,
    5: 12,
    6: 15,
    7: 22,
    8: 22,
    9: 24,
    10: 21,
    11: 28,
    12: 16,
    13: 24,
    14: 18,
}
METRIC_TITLE_LAST_COL = 14
TITLE_LAST_COL = 14


REPO_ROOT = Path(__file__).resolve().parent.parent
GROUP_ANALYSIS_MANUAL_PDF_PATH = REPO_ROOT / 'docs' / 'user_manual' / 'group_analysis' / 'user_manual.pdf'
GROUP_ANALYSIS_MANUAL_GITHUB_URL = (
    'https://github.com/hexafe/metroliza/blob/master/docs/user_manual/group_analysis/user_manual.md'
)
GROUP_ANALYSIS_MANUAL_PDF_GITHUB_URL = (
    'https://github.com/hexafe/metroliza/blob/master/docs/user_manual/group_analysis/user_manual.pdf'
)


_PLOT_SKIP_REASON_LABELS = {
    'low_group_samples': 'Not enough samples in one or more groups.',
    'low_total_samples': 'Not enough total samples to show this plot.',
    'asset_missing': 'Plot could not be shown because the image asset is unavailable.',
}


def _get_plot_skip_reason_label(reason_code):
    code = str(reason_code or '').strip().lower()
    if not code:
        return 'Plot was not shown.'
    return _PLOT_SKIP_REASON_LABELS.get(code, 'Plot was not shown due to analysis constraints.')


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


def _get_native_worksheet(worksheet):
    return getattr(worksheet, '_worksheet', worksheet)


def _get_workbook(worksheet):
    native = _get_native_worksheet(worksheet)
    return (
        getattr(worksheet, '_workbook', None)
        or getattr(native, 'book', None)
        or getattr(native, 'workbook', None)
        or getattr(worksheet, 'book', None)
        or getattr(worksheet, 'workbook', None)
    )


def _build_formats(worksheet):
    """Create reusable worksheet formats when a workbook is available."""
    workbook = _get_workbook(worksheet)
    if workbook is None or not hasattr(workbook, 'add_format'):
        return {}

    cached = getattr(worksheet, '_group_analysis_formats', None)
    if cached is not None:
        return cached

    formats = {
        'title_fmt': workbook.add_format({
            'bg_color': '#1F2937',
            'pattern': 1,
            'font_color': '#FFFFFF',
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'bottom': 2,
        }),
        'metric_fmt': workbook.add_format({
            'bg_color': '#1D4E89',
            'pattern': 1,
            'font_color': '#FFFFFF',
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': False,
            'bottom': 2,
        }),
        'section_fmt': workbook.add_format({
            'bg_color': '#374151',
            'pattern': 1,
            'font_color': '#FFFFFF',
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'bottom': 1,
        }),
        'header_fmt': workbook.add_format({
            'bg_color': '#D9EAF7',
            'pattern': 1,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'bottom': 1,
        }),
        'text_wrap_fmt': workbook.add_format({
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
        }),
        'text_top_fmt': workbook.add_format({
            'align': 'left',
            'valign': 'top',
        }),
        'note_fmt': workbook.add_format({
            'bg_color': '#FFF7D6',
            'pattern': 1,
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
        }),
        'summary_label_fmt': workbook.add_format({
            'bold': True,
            'bg_color': '#EEF2F7',
            'pattern': 1,
            'bottom': 1,
        }),
        'summary_label_wrap_fmt': workbook.add_format({
            'bold': True,
            'bg_color': '#EEF2F7',
            'pattern': 1,
            'bottom': 1,
            'text_wrap': True,
            'valign': 'top',
        }),
        'summary_value_fmt': workbook.add_format({
            'valign': 'top',
            'bottom': 1,
        }),
        'num_fmt': workbook.add_format({'num_format': '0.000', 'valign': 'top'}),
        'pvalue_fmt': workbook.add_format({'num_format': '0.0000', 'valign': 'top'}),
        'default_data_fmt': workbook.add_format({'valign': 'top'}),
        'positive': workbook.add_format({'bg_color': '#E6F4EA', 'font_color': '#1E4620', 'pattern': 1}),
        'neutral': workbook.add_format({'bg_color': '#EEF2F7', 'font_color': '#334155', 'pattern': 1}),
        'warning': workbook.add_format({'bg_color': '#FFF4CC', 'font_color': '#7A4E00', 'pattern': 1}),
        'strong_warning': workbook.add_format({'bg_color': '#FDE2E1', 'font_color': '#8B1C13', 'bold': True, 'pattern': 1}),
        'muted': workbook.add_format({'bg_color': '#F7F7F7', 'font_color': '#8A8F98', 'pattern': 1}),
        'yes': workbook.add_format({'bg_color': '#E8F3FF', 'font_color': '#0B4F8C', 'bold': True, 'pattern': 1}),
        'no': workbook.add_format({'bg_color': '#F3F4F6', 'font_color': '#6B7280', 'pattern': 1}),
        'delta_mean_fixed_3': workbook.add_format({'num_format': '0.000'}),
        'hyperlink_fmt': workbook.add_format({
            'font_color': '#0B4F8C',
            'underline': 1,
            'valign': 'top',
        }),
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


def _write_section_title(worksheet, row, title, *, merge_to_col=None, cell_format=None):
    native = _get_native_worksheet(worksheet)
    if merge_to_col is not None and hasattr(native, 'merge_range'):
        native.merge_range(row, 0, row, merge_to_col, title, cell_format)
    else:
        worksheet.write(row, 0, title, cell_format)
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


def _normalize_text_lines(value):
    text = str(value or '')
    if not text:
        return []
    return text.splitlines() or ['']


def _estimate_wrapped_line_count(value, width):
    width = max(float(width or 0), 8.0)
    approx_chars_per_line = max(int(width * 1.15), 8)
    line_count = 0
    for raw_line in _normalize_text_lines(value):
        text = raw_line.strip()
        if not text:
            line_count += 1
            continue
        current = 0
        wrapped = 1
        for chunk in text.split():
            chunk_len = len(chunk)
            if current == 0:
                current = chunk_len
            elif current + 1 + chunk_len <= approx_chars_per_line:
                current += 1 + chunk_len
            else:
                wrapped += 1
                current = chunk_len
            if current > approx_chars_per_line:
                wrapped += max(0, (current - 1) // approx_chars_per_line)
                current = ((current - 1) % approx_chars_per_line) + 1
        line_count += wrapped
    return max(line_count, 1)


def _estimate_wrapped_row_height(cells, *, minimum=DEFAULT_ROW_HEIGHT, line_height=DEFAULT_LINE_HEIGHT, padding=4):
    max_lines = 1
    for cell in cells:
        if not cell:
            continue
        value = cell.get('value')
        if value in (None, '') or not cell.get('wrap', True):
            continue
        max_lines = max(max_lines, _estimate_wrapped_line_count(value, cell.get('width')))
    return max(minimum, int(max_lines * line_height + padding))


def _estimate_note_height(value, *, width=None):
    return _estimate_wrapped_row_height(
        [{'value': value, 'width': width or GROUP_ANALYSIS_COLUMN_WIDTHS.get(1, 18), 'wrap': True}],
        minimum=30,
    )


def _estimate_metric_title_height(title):
    return 32 if len(str(title or '')) > 90 else 28


def _estimate_header_height(*headers):
    text = ' '.join(str(value or '') for value in headers if value not in (None, ''))
    return max(
        24,
        _estimate_wrapped_row_height(
            [{'value': text, 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(2, 16), 'wrap': True}],
            minimum=24,
            line_height=12,
            padding=2,
        ),
    )


def _coerce_status_label(value):
    normalized = str(value or '').strip().upper()
    if normalized == 'YES':
        return 'DIFFERENCE'
    if normalized == 'NO':
        return 'NO DIFFERENCE'
    return str(value or '').strip()


def _apply_group_analysis_layout(workbook, worksheet, sheet_state):
    if worksheet is None:
        return

    formats = _build_formats(worksheet)
    header_formats = {
        'title': formats.get('title_fmt'),
        'metric': formats.get('metric_fmt'),
        'section': formats.get('section_fmt'),
        'header': formats.get('header_fmt'),
        'note': formats.get('note_fmt'),
        'wrap': formats.get('text_wrap_fmt'),
        'text': formats.get('text_top_fmt'),
        'default': formats.get('default_data_fmt'),
        'num': formats.get('num_fmt'),
        'pvalue': formats.get('pvalue_fmt'),
        'summary_label': formats.get('summary_label_fmt'),
        'summary_label_wrap': formats.get('summary_label_wrap_fmt'),
        'summary_value': formats.get('summary_value_fmt'),
        'hyperlink': formats.get('hyperlink_fmt'),
    }

    if hasattr(worksheet, 'hide_gridlines'):
        worksheet.hide_gridlines(2)

    if hasattr(worksheet, 'set_column'):
        for col, width in GROUP_ANALYSIS_COLUMN_WIDTHS.items():
            worksheet.set_column(col, col, width, header_formats['default'])

    if hasattr(worksheet, 'set_row'):
        for row in sheet_state.get('title_rows', []):
            worksheet.set_row(row, 28, header_formats['title'])
        for row, value in sheet_state.get('metric_rows', []):
            worksheet.set_row(row, max(30, _estimate_metric_title_height(value) + 4), header_formats['metric'])
        for row in sheet_state.get('summary_rows', []):
            worksheet.set_row(row, DEFAULT_ROW_HEIGHT)
        for row in sheet_state.get('index_rows', []):
            worksheet.set_row(row, 24)
        for row in sheet_state.get('section_rows', []):
            worksheet.set_row(row, 22, header_formats['section'])
        for row in sheet_state.get('subsection_rows', []):
            worksheet.set_row(row, 22, header_formats['header'])
        for row, value, width in sheet_state.get('note_rows', []):
            worksheet.set_row(row, _estimate_note_height(value, width=width), header_formats['note'])
        for row, cells in sheet_state.get('wrapped_data_rows', []):
            worksheet.set_row(row, _estimate_wrapped_row_height(cells), header_formats['default'])
        for row, headers in sheet_state.get('header_rows', []):
            worksheet.set_row(row, _estimate_header_height(*headers), header_formats['header'])

    if hasattr(worksheet, 'write'):
        for row, col, value, fmt_key in sheet_state.get('styled_cells', []):
            fmt = header_formats.get(fmt_key)
            if fmt is not None:
                worksheet.write(row, col, value, fmt)

    if hasattr(worksheet, 'write'):
        for row, col, value, fmt_key in sheet_state.get('numeric_cells', []):
            fmt = header_formats.get(fmt_key)
            if fmt is not None:
                worksheet.write(row, col, value, fmt)

    if hasattr(worksheet, 'autofilter'):
        for block in sheet_state.get('autofilter_blocks', []):
            if block['header_row'] < block['last_row']:
                worksheet.autofilter(block['header_row'], block['first_col'], block['last_row'], block['last_col'])


def _write_manual_links(worksheet, row, *, sheet_state=None):
    section_row = row
    row = _write_section_title(worksheet, row, 'User manual')
    if sheet_state is not None:
        sheet_state['section_rows'].append(section_row)
        sheet_state['styled_cells'].append((section_row, 0, 'User manual', 'section'))

    manual_rows = [
        {
            'Field': 'Markdown guide (GitHub)',
            'Label': 'Open Markdown manual',
            'Target': GROUP_ANALYSIS_MANUAL_GITHUB_URL,
            'Tip': 'Open the plain-English Group Analysis guide in the GitHub repository.',
        },
        {
            'Field': 'Printable companion (local PDF)',
            'Label': 'Open PDF manual',
            'Target': GROUP_ANALYSIS_MANUAL_PDF_GITHUB_URL,
            'Tip': 'Open the printable Group Analysis PDF companion in the GitHub repository.',
        },
    ]

    for entry in manual_rows:
        current_row = row
        worksheet.write(current_row, 0, entry['Field'])
        if sheet_state is not None:
            sheet_state['styled_cells'].append((current_row, 0, entry['Field'], 'summary_label_wrap'))
            sheet_state['summary_rows'].append(current_row)

        if hasattr(worksheet, 'write_url'):
            worksheet.write_url(
                current_row,
                1,
                entry['Target'],
                _build_formats(worksheet).get('hyperlink_fmt'),
                entry['Label'],
                entry['Tip'],
            )
        else:
            worksheet.write(current_row, 1, entry['Label'])

        if sheet_state is not None:
            sheet_state['styled_cells'].append((current_row, 1, entry['Label'], 'hyperlink'))
            sheet_state['wrapped_data_rows'].append((
                current_row,
                [
                    {'value': entry['Field'], 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(0, 18), 'wrap': True},
                    {'value': entry['Label'], 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(1, 18), 'wrap': True},
                ],
            ))
        row += 1

    return row + SECTION_GAP


def _write_named_value_rows(worksheet, row, rows, *, sheet_state=None):
    start_row = row
    for entry in rows:
        worksheet.write(row, 0, entry.get('Field'))
        worksheet.write(row, 1, entry.get('Value'))
        if sheet_state is not None:
            sheet_state['styled_cells'].append((row, 0, entry.get('Field'), 'summary_label'))
            fmt_key = 'wrap' if len(str(entry.get('Value') or '')) > 50 else 'summary_value'
            sheet_state['styled_cells'].append((row, 1, entry.get('Value'), fmt_key))
            sheet_state['summary_rows'].append(row)
            if fmt_key == 'wrap':
                sheet_state['wrapped_data_rows'].append((
                    row,
                    [{'value': entry.get('Value'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(1, 18), 'wrap': True}],
                ))
        row += 1
    return row, {'first_row': start_row, 'last_row': row - 1}


def _write_metric_index(worksheet, row, metric_rows, *, sheet_state=None):
    section_row = row
    row = _write_section_title(worksheet, row, 'Metric index')
    if sheet_state is not None:
        sheet_state['section_rows'].append(section_row)
        sheet_state['styled_cells'].append((section_row, 0, 'Metric index', 'section'))

    header_row = row
    headers = ['Metric', 'Status', 'Jump to section']
    for col, header in enumerate(headers):
        worksheet.write(row, col, header)
        if sheet_state is not None:
            sheet_state['styled_cells'].append((row, col, header, 'header'))
    if sheet_state is not None:
        sheet_state['header_rows'].append((header_row, headers))
        sheet_state['wrapped_data_rows'].append((
            header_row,
            [{'value': headers[2], 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(2, 16), 'wrap': True}],
        ))
    row += 1

    for metric_row in metric_rows:
        metric_name = str(metric_row.get('metric') or 'Unknown')
        status_label = metric_row.get('index_status') or 'REVIEW'
        worksheet.write(row, 0, metric_name)
        worksheet.write(row, 1, status_label)
        worksheet.write(row, 2, 'Go to metric')
        if sheet_state is not None:
            sheet_state['index_rows'].append(row)
            sheet_state['styled_cells'].append((row, 0, metric_name, 'text'))
            sheet_state['styled_cells'].append((row, 1, status_label, 'text'))
            sheet_state['metric_index_links'].append((row, 2, metric_name))
        row += 1
    return row + SECTION_GAP


def _apply_metric_pairwise_formats(worksheet, bounds):
    headers = bounds['headers']
    first = bounds['first_data_row']
    last = bounds['last_data_row']
    if first > last:
        return
    formats = _build_formats(worksheet)

    difference_col = headers.index('difference')
    comment_col = headers.index('caution')
    flags_col = headers.index('Flags') if 'Flags' in headers else None
    pvalue_col = headers.index('adj p-value')
    effect_col = headers.index('effect size')
    delta_mean_col = headers.index('Delta mean') if 'Delta mean' in headers else None

    _apply_conditional(worksheet, first, difference_col, last, difference_col, _style_rule(formats, 'strong_warning', type='text', criteria='containing', value='YES'))
    _apply_conditional(worksheet, first, difference_col, last, difference_col, _style_rule(formats, 'neutral', type='text', criteria='containing', value='NO'))
    _apply_conditional(worksheet, first, comment_col, last, comment_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='caution'))
    _apply_conditional(worksheet, first, comment_col, last, comment_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='descriptive only'))

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


def _write_metric_section(worksheet, row, metric_row, *, plot_assets=None, sheet_state=None):
    metric_title_row = row
    metric_title = f"Metric: {metric_row.get('metric', 'Unknown')}"
    row = _write_section_title(
        worksheet,
        row,
        metric_title,
        merge_to_col=METRIC_TITLE_LAST_COL,
        cell_format=_build_formats(worksheet).get('metric_fmt'),
    )
    if sheet_state is not None:
        sheet_state['metric_rows'].append((metric_title_row, metric_title))
        sheet_state['metric_anchor_rows'][str(metric_row.get('metric') or 'Unknown')] = metric_title_row

    spec_status_label = metric_row.get('spec_status_label') or get_spec_status_label(metric_row.get('spec_status'))
    section_row = row
    row = _write_section_title(worksheet, row, 'Metric overview')
    if sheet_state is not None:
        sheet_state['section_rows'].append(section_row)
        sheet_state['styled_cells'].append((section_row, 0, 'Metric overview', 'section'))
    metric_meta_rows = [
        {'Field': 'Spec status', 'Value': spec_status_label},
        {'Field': 'Shape note', 'Value': metric_row.get('metric_note') or (metric_row.get('distribution_difference') or {}).get('comment / verdict')},
        {'Field': 'Recommended action', 'Value': metric_row.get('recommended_action')},
        {'Field': 'Use caution', 'Value': metric_row.get('diagnostics_comment') or (metric_row.get('comparability_summary') or {}).get('summary')},
    ]
    row, meta_bounds = _write_table_with_bounds(worksheet, row, ['Field', 'Value'], metric_meta_rows)
    if sheet_state is not None:
        sheet_state['header_rows'].append((meta_bounds['header_row'], meta_bounds['headers']))
        sheet_state['styled_cells'].extend(
            (meta_bounds['header_row'], col, header, 'header')
            for col, header in enumerate(meta_bounds['headers'])
        )
        for data_row_idx, entry in enumerate(metric_meta_rows):
            data_row = meta_bounds['first_data_row'] + data_row_idx
            sheet_state['styled_cells'].append((data_row, 1, entry.get('Value'), 'wrap'))
            if entry.get('Field') in {'Shape note', 'Recommended action', 'Use caution'} and entry.get('Value'):
                sheet_state['note_rows'].append((data_row, entry.get('Value'), GROUP_ANALYSIS_COLUMN_WIDTHS.get(1, 18)))
    row += SECTION_GAP

    section_row = row
    row = _write_section_title(worksheet, row, 'Descriptive stats')
    if sheet_state is not None:
        sheet_state['section_rows'].append(section_row)
        sheet_state['styled_cells'].append((section_row, 0, 'Descriptive stats', 'section'))
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
            'best fit model': entry.get('best_fit_model'),
            'fit quality': entry.get('fit_quality'),
            'caution': entry.get('distribution_shape_caution'),
            'Flags': entry.get('flags'),
        }
        for entry in metric_row.get('descriptive_stats', [])
    ]
    row, desc_bounds = _write_table_with_bounds(
        worksheet,
        row,
        [
            'Group', 'n', 'mean', 'std', 'median', 'IQR', 'min', 'max', 'Cp', 'Capability', 'Capability type',
            'best fit model', 'fit quality', 'caution', 'Flags',
        ],
        desc_rows,
    )
    if sheet_state is not None:
        sheet_state['header_rows'].append((desc_bounds['header_row'], desc_bounds['headers']))
        sheet_state['styled_cells'].extend(
            (desc_bounds['header_row'], col, header, 'header')
            for col, header in enumerate(desc_bounds['headers'])
        )
        sheet_state['autofilter_blocks'].append({
            'header_row': desc_bounds['header_row'],
            'first_col': 0,
            'last_row': desc_bounds['last_data_row'],
            'last_col': len(desc_bounds['headers']) - 1,
        })
        header_lookup = {header: idx for idx, header in enumerate(desc_bounds['headers'])}
        for data_row_idx, entry in enumerate(desc_rows):
            data_row = desc_bounds['first_data_row'] + data_row_idx
            for header in ('mean', 'std', 'median', 'IQR', 'min', 'max', 'Cp', 'Capability'):
                if header in header_lookup:
                    sheet_state['numeric_cells'].append((data_row, header_lookup[header], entry.get(header), 'num'))
            for header in ('caution', 'best fit model', 'fit quality'):
                if header in header_lookup and entry.get(header):
                    sheet_state['styled_cells'].append((data_row, header_lookup[header], entry.get(header), 'wrap'))
            if entry.get('caution'):
                sheet_state['note_rows'].append((data_row, entry.get('caution'), GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup['caution'], 24)))
            sheet_state['wrapped_data_rows'].append((
                data_row,
                [
                    {'value': entry.get('best fit model'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup.get('best fit model', 11), 28), 'wrap': True},
                    {'value': entry.get('fit quality'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup.get('fit quality', 12), 16), 'wrap': True},
                    {'value': entry.get('caution'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup.get('caution', 13), 24), 'wrap': True},
                ],
            ))
    row += SECTION_GAP

    section_row = row
    row = _write_section_title(worksheet, row, 'Pairwise comparisons')
    if sheet_state is not None:
        sheet_state['section_rows'].append(section_row)
        sheet_state['styled_cells'].append((section_row, 0, 'Pairwise comparisons', 'section'))
    pairwise_rows = [
        {
            'Group A': entry.get('group_a'),
            'Group B': entry.get('group_b'),
            'adj p-value': entry.get('adjusted_p_value'),
            'effect size': entry.get('effect_size'),
            'test': entry.get('test_used'),
            'Delta mean': entry.get('delta_mean'),
            'difference': _coerce_status_label(entry.get('difference_label') or entry.get('difference')),
            'caution': entry.get('comment'),
            'Takeaway': entry.get('takeaway'),
            'Suggested action': entry.get('suggested_action'),
            'Flags': entry.get('flags'),
            'Why this test': entry.get('test_rationale'),
        }
        for entry in metric_row.get('pairwise_rows', [])
    ]
    row, pairwise_bounds = _write_table_with_bounds(
        worksheet,
        row,
        ['Group A', 'Group B', 'adj p-value', 'effect size', 'test', 'Delta mean', 'difference', 'caution', 'Takeaway', 'Suggested action', 'Flags', 'Why this test'],
        pairwise_rows,
    )
    if sheet_state is not None:
        sheet_state['header_rows'].append((pairwise_bounds['header_row'], pairwise_bounds['headers']))
        sheet_state['styled_cells'].extend(
            (pairwise_bounds['header_row'], col, header, 'header')
            for col, header in enumerate(pairwise_bounds['headers'])
        )
        sheet_state['autofilter_blocks'].append({
            'header_row': pairwise_bounds['header_row'],
            'first_col': 0,
            'last_row': pairwise_bounds['last_data_row'],
            'last_col': len(pairwise_bounds['headers']) - 1,
        })
        header_lookup = {header: idx for idx, header in enumerate(pairwise_bounds['headers'])}
        for data_row_idx, entry in enumerate(pairwise_rows):
            data_row = pairwise_bounds['first_data_row'] + data_row_idx
            if 'adj p-value' in header_lookup:
                sheet_state['numeric_cells'].append((data_row, header_lookup['adj p-value'], entry.get('adj p-value'), 'pvalue'))
            if 'effect size' in header_lookup:
                sheet_state['numeric_cells'].append((data_row, header_lookup['effect size'], entry.get('effect size'), 'num'))
            if 'Delta mean' in header_lookup:
                sheet_state['numeric_cells'].append((data_row, header_lookup['Delta mean'], entry.get('Delta mean'), 'num'))
            for header in ('test', 'caution', 'Takeaway', 'Suggested action', 'Flags', 'Why this test'):
                if header in header_lookup and entry.get(header):
                    fmt_key = 'note' if header == 'caution' else 'wrap'
                    sheet_state['styled_cells'].append((data_row, header_lookup[header], entry.get(header), fmt_key))
            if entry.get('caution'):
                sheet_state['note_rows'].append((data_row, entry.get('caution'), GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup['caution'], 22)))
            sheet_state['wrapped_data_rows'].append(
                (
                    data_row,
                    [
                        {'value': entry.get('test'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup.get('test', 4), 18), 'wrap': True},
                        {'value': entry.get('caution'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup.get('caution', 7), 22), 'wrap': True},
                        {'value': entry.get('Takeaway'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup.get('Takeaway', 8), 22), 'wrap': True},
                        {'value': entry.get('Suggested action'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup.get('Suggested action', 9), 24), 'wrap': True},
                        {'value': entry.get('Why this test'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(header_lookup.get('Why this test', 11), 28), 'wrap': True},
                    ],
                )
            )
    _apply_metric_pairwise_formats(worksheet, pairwise_bounds)
    row += SECTION_GAP

    takeaway = str(metric_row.get('metric_takeaway') or '').strip()
    if not takeaway:
        pairwise_rows = metric_row.get('pairwise_rows', []) or []
        if pairwise_rows:
            first_pair = pairwise_rows[0]
            summary = _coerce_status_label(first_pair.get('difference_label') or first_pair.get('difference')) or 'REVIEW'
            action = str(first_pair.get('suggested_action') or '').strip()
            takeaway = f"{first_pair.get('group_a')} vs {first_pair.get('group_b')}: {summary}."
            if action:
                takeaway = f'{takeaway} {action}'
    if takeaway:
        worksheet.write(row, 0, 'Takeaway')
        worksheet.write(row, 1, takeaway)
        if sheet_state is not None:
            sheet_state['styled_cells'].append((row, 0, 'Takeaway', 'summary_label'))
            sheet_state['styled_cells'].append((row, 1, takeaway, 'note'))
            sheet_state['note_rows'].append((row, takeaway, GROUP_ANALYSIS_COLUMN_WIDTHS.get(1, 18)))
        row += 1

    plot_eligibility = metric_row.get('plot_eligibility') or {}
    analysis_level = str(metric_row.get('analysis_level') or '').strip().lower()
    if analysis_level == 'standard':
        metric_assets = _resolve_metric_plot_assets(plot_assets, metric_row.get('metric'))
        row += SECTION_GAP
        section_row = row
        row = _write_section_title(worksheet, row, 'Plots')
        if sheet_state is not None:
            sheet_state['section_rows'].append(section_row)
            sheet_state['styled_cells'].append((section_row, 0, 'Plots', 'section'))
        for plot_key, plot_label in (('violin', 'Violin'), ('histogram', 'Histogram')):
            eligibility = plot_eligibility.get(plot_key) or {}
            eligible = bool(eligibility.get('eligible'))
            skip_reason = str(eligibility.get('skip_reason') or 'ineligible')
            asset = metric_assets.get(plot_key)

            subsection_row = row
            native = _get_native_worksheet(worksheet)
            if hasattr(native, 'merge_range'):
                native.merge_range(subsection_row, 0, subsection_row, 1, plot_label, _build_formats(worksheet).get('header_fmt'))
            else:
                worksheet.write(subsection_row, 0, plot_label)
            if sheet_state is not None:
                sheet_state['subsection_rows'].append(subsection_row)

            if not eligible:
                message = _get_plot_skip_reason_label(skip_reason)
                worksheet.write(subsection_row + 1, 0, 'Note')
                worksheet.write(subsection_row + 1, 1, message)
                if sheet_state is not None:
                    sheet_state['styled_cells'].append((subsection_row + 1, 0, 'Note', 'wrap'))
                    sheet_state['styled_cells'].append((subsection_row + 1, 1, message, 'note'))
                    sheet_state['note_rows'].append((subsection_row + 1, message, GROUP_ANALYSIS_COLUMN_WIDTHS.get(1, 18)))
                row += 2
                continue

            inserted = _insert_plot_image(worksheet, row + 1, asset)
            if inserted:
                row_span = DEFAULT_PLOT_ROW_SPAN
                if isinstance(asset, dict) and isinstance(asset.get('row_span'), int) and asset.get('row_span') > 0:
                    row_span = int(asset.get('row_span'))
                row += 1 + row_span
            else:
                message = _get_plot_skip_reason_label('asset_missing')
                worksheet.write(subsection_row + 1, 0, 'Note')
                worksheet.write(subsection_row + 1, 1, message)
                if sheet_state is not None:
                    sheet_state['styled_cells'].append((subsection_row + 1, 0, 'Note', 'wrap'))
                    sheet_state['styled_cells'].append((subsection_row + 1, 1, message, 'note'))
                    sheet_state['note_rows'].append((subsection_row + 1, message, GROUP_ANALYSIS_COLUMN_WIDTHS.get(1, 18)))
                row += 2

    row += SECTION_GAP
    return row


def write_group_analysis_sheet(worksheet, payload, *, plot_assets=None):
    """Write the canonical user-facing Group Analysis worksheet."""
    sheet_state = {
        'title_rows': [],
        'summary_rows': [],
        'index_rows': [],
        'metric_rows': [],
        'section_rows': [],
        'header_rows': [],
        'subsection_rows': [],
        'note_rows': [],
        'wrapped_data_rows': [],
        'styled_cells': [],
        'numeric_cells': [],
        'autofilter_blocks': [],
        'metric_anchor_rows': {},
        'metric_index_links': [],
    }
    row = 0
    title_row = row
    row = _write_section_title(worksheet, row, 'Group Analysis', merge_to_col=TITLE_LAST_COL, cell_format=_build_formats(worksheet).get('title_fmt'))
    sheet_state['title_rows'].append(title_row)
    summary_rows = [
        {'Field': 'Status', 'Value': payload.get('status')},
        {'Field': 'Effective scope', 'Value': payload.get('effective_scope')},
        {'Field': 'Metric count', 'Value': len(payload.get('metric_rows', []))},
    ]
    if payload.get('skip_reason'):
        summary_rows.append({'Field': 'Skip reason', 'Value': payload['skip_reason'].get('message')})
    row, _summary_bounds = _write_named_value_rows(worksheet, row, summary_rows, sheet_state=sheet_state)
    row += SECTION_GAP
    row = _write_manual_links(worksheet, row, sheet_state=sheet_state)

    normalized_level = str(payload.get('analysis_level') or 'light').strip().lower()
    metric_rows = [dict(metric_row) for metric_row in payload.get('metric_rows', [])]
    for metric_row in metric_rows:
        metric_row['index_status'] = (
            metric_row.get('index_status')
            or metric_row.get('summary_status')
            or _coerce_status_label(((metric_row.get('pairwise_rows') or [{}])[0]).get('difference'))
            or 'REVIEW'
        )
        metric_row['analysis_level'] = normalized_level
    if metric_rows:
        row = _write_metric_index(worksheet, row, metric_rows, sheet_state=sheet_state)

    for metric_row in metric_rows:
        metric_with_level = dict(metric_row)
        row = _write_metric_section(worksheet, row, metric_with_level, plot_assets=plot_assets, sheet_state=sheet_state)

    formats = _build_formats(worksheet)
    native = _get_native_worksheet(worksheet)
    for link_row, link_col, metric_name in sheet_state.get('metric_index_links', []):
        target_row = sheet_state['metric_anchor_rows'].get(metric_name)
        if target_row is None:
            continue
        if hasattr(native, 'write_formula'):
            native.write_formula(
                link_row,
                link_col,
                f'=HYPERLINK("#\'Group Analysis\'!A{target_row + 1}","Go to metric")',
                formats.get('hyperlink_fmt'),
                'Go to metric',
            )
        elif hasattr(worksheet, 'write_url'):
            worksheet.write_url(
                link_row,
                link_col,
                f"internal:'Group Analysis'!A{target_row + 1}",
                formats.get('hyperlink_fmt'),
                'Go to metric',
            )

    _apply_group_analysis_layout(_get_workbook(worksheet), worksheet, sheet_state)


def write_group_analysis_diagnostics_sheet(worksheet, diagnostics_payload):
    """Write internal/debug diagnostics details for scope resolution and metric coverage."""
    row = 0
    row = _write_section_title(worksheet, row, 'Group Analysis Internal Diagnostics')

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
