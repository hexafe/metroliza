"""Worksheet writers for the canonical Group Analysis workbook sheet."""

from __future__ import annotations

import math
from pathlib import Path

from modules.export_summary_composition_service import (
    classify_capability_status as _classify_capability_status,
    classify_capability_value as _classify_capability_value,
)
from modules.group_analysis_service import get_spec_status_label

SECTION_GAP = 1
DEFAULT_PLOT_ROW_SPAN = 16
DEFAULT_ROW_HEIGHT = 22
DEFAULT_LINE_HEIGHT = 14
GROUP_ANALYSIS_COLUMN_WIDTHS = {
    0: 16,
    1: 10,
    2: 11,
    3: 11,
    4: 11,
    5: 11,
    6: 11,
    7: 11,
    8: 12,
    9: 12,
    10: 12,
    11: 16,
    12: 14,
    13: 14,
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
        if asset.get('description'):
            options['description'] = str(asset.get('description'))
        if asset.get('decorative') is not None:
            options['decorative'] = bool(asset.get('decorative'))

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

    table_border = 1
    formats = {
        'title_fmt': workbook.add_format({
            'bg_color': '#1F2937',
            'pattern': 1,
            'font_color': '#FFFFFF',
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'border': table_border,
            'bottom': 2,
        }),
        'metric_fmt': workbook.add_format({
            'bg_color': '#1E3A5F',
            'pattern': 1,
            'font_color': '#FFFFFF',
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': False,
            'border': table_border,
            'bottom': 2,
        }),
        'section_fmt': workbook.add_format({
            'bg_color': '#374151',
            'pattern': 1,
            'font_color': '#FFFFFF',
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'border': table_border,
            'bottom': 1,
        }),
        'header_fmt': workbook.add_format({
            'bg_color': '#E8EEF5',
            'pattern': 1,
            'font_color': '#0F172A',
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': table_border,
            'bottom': 1,
        }),
        'text_wrap_fmt': workbook.add_format({
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': table_border,
        }),
        'text_top_fmt': workbook.add_format({
            'align': 'left',
            'valign': 'top',
            'border': table_border,
        }),
        'text_left_middle_fmt': workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': False,
            'border': table_border,
        }),
        'table_center_fmt': workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': table_border,
        }),
        'table_center_wrap_fmt': workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': table_border,
        }),
        'note_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'font_color': '#334155',
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': table_border,
        }),
        'summary_label_fmt': workbook.add_format({
            'bold': True,
            'bg_color': '#EEF2F7',
            'pattern': 1,
            'border': table_border,
            'bottom': 1,
        }),
        'summary_label_wrap_fmt': workbook.add_format({
            'bold': True,
            'bg_color': '#EEF2F7',
            'pattern': 1,
            'border': table_border,
            'bottom': 1,
            'text_wrap': True,
            'valign': 'top',
        }),
        'summary_value_fmt': workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': False,
            'border': table_border,
            'bottom': 1,
        }),
        'summary_value_wrap_fmt': workbook.add_format({
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': table_border,
            'bottom': 1,
        }),
        'overview_value_fmt': workbook.add_format({
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': table_border,
            'bottom': 1,
            'bg_color': '#F8FAFC',
            'pattern': 1,
        }),
        'takeaway_label_fmt': workbook.add_format({
            'bold': True,
            'bg_color': '#EEF2F7',
            'pattern': 1,
            'border': table_border,
            'bottom': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': False,
        }),
        'takeaway_value_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': table_border,
            'bottom': 1,
        }),
        'num_fmt': workbook.add_format({'num_format': '0.000', 'align': 'center', 'valign': 'vcenter', 'border': table_border}),
        'pvalue_fmt': workbook.add_format({'num_format': '0.0000', 'align': 'center', 'valign': 'vcenter', 'border': table_border}),
        'default_data_fmt': workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': table_border}),
        'positive': workbook.add_format({'bg_color': '#E6F4EA', 'font_color': '#1E4620', 'pattern': 1}),
        'neutral': workbook.add_format({'bg_color': '#EEF2F7', 'font_color': '#334155', 'pattern': 1}),
        'warning': workbook.add_format({'bg_color': '#FFF4CC', 'font_color': '#7A4E00', 'pattern': 1}),
        'strong_warning': workbook.add_format({'bg_color': '#FDE2E1', 'font_color': '#8B1C13', 'bold': True, 'pattern': 1}),
        'muted': workbook.add_format({'bg_color': '#F7F7F7', 'font_color': '#556270', 'pattern': 1}),
        'yes': workbook.add_format({'bg_color': '#E8F3FF', 'font_color': '#0B4F8C', 'bold': True, 'pattern': 1}),
        'no': workbook.add_format({'bg_color': '#F3F4F6', 'font_color': '#6B7280', 'pattern': 1}),
        'delta_mean_fixed_3': workbook.add_format({'num_format': '0.000', 'border': table_border}),
        'hyperlink_fmt': workbook.add_format({
            'font_color': '#0B4F8C',
            'underline': 1,
            'valign': 'top',
        }),
        'hyperlink_cell_fmt': workbook.add_format({
            'font_color': '#0B4F8C',
            'underline': 1,
            'align': 'center',
            'valign': 'vcenter',
            'border': table_border,
        }),
        'band_hyperlink_cell_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'font_color': '#0B4F8C',
            'underline': 1,
            'align': 'center',
            'valign': 'vcenter',
            'border': table_border,
        }),
        'card_default_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'font_color': '#0F172A',
            'bold': True,
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': 1,
        }),
        'card_emphasis_fmt': workbook.add_format({
            'bg_color': '#E8F3FF',
            'pattern': 1,
            'font_color': '#0B4F8C',
            'bold': True,
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': 1,
        }),
        'card_warning_fmt': workbook.add_format({
            'bg_color': '#FFF4CC',
            'pattern': 1,
            'font_color': '#7A4E00',
            'bold': True,
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': 1,
        }),
        'card_risk_fmt': workbook.add_format({
            'bg_color': '#FDE2E1',
            'pattern': 1,
            'font_color': '#8B1C13',
            'bold': True,
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': 1,
        }),
        'card_success_fmt': workbook.add_format({
            'bg_color': '#E6F4EA',
            'pattern': 1,
            'font_color': '#1E4620',
            'bold': True,
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': 1,
        }),
        'detail_label_fmt': workbook.add_format({
            'bg_color': '#EEF2F7',
            'pattern': 1,
            'font_color': '#0F172A',
            'bold': True,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
        }),
        'detail_value_fmt': workbook.add_format({
            'bg_color': '#FFFFFF',
            'pattern': 1,
            'font_color': '#0F172A',
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': 1,
        }),
        'detail_note_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'font_color': '#334155',
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': 1,
        }),
        'band_text_left_middle_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': False,
            'border': 1,
        }),
        'band_table_center_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        }),
        'band_table_center_wrap_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1,
        }),
        'band_num_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'num_format': '0.000',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        }),
        'band_pvalue_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'num_format': '0.0000',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        }),
        'band_detail_value_fmt': workbook.add_format({
            'bg_color': '#F8FAFC',
            'pattern': 1,
            'font_color': '#0F172A',
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': 1,
        }),
        'band_detail_note_fmt': workbook.add_format({
            'bg_color': '#F1F5F9',
            'pattern': 1,
            'font_color': '#334155',
            'align': 'left',
            'valign': 'top',
            'text_wrap': True,
            'border': 1,
        }),
        'status_difference_fmt': workbook.add_format({
            'bg_color': '#E8F3FF',
            'pattern': 1,
            'font_color': '#0B4F8C',
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        }),
        'status_no_difference_fmt': workbook.add_format({
            'bg_color': '#E6F4EA',
            'pattern': 1,
            'font_color': '#1E4620',
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        }),
        'status_caution_fmt': workbook.add_format({
            'bg_color': '#FFF4CC',
            'pattern': 1,
            'font_color': '#7A4E00',
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1,
        }),
        'status_review_fmt': workbook.add_format({
            'bg_color': '#EEF2F7',
            'pattern': 1,
            'font_color': '#334155',
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1,
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


def _column_span_width(first_col, last_col):
    total_width = 0.0
    for col in range(int(first_col), int(last_col) + 1):
        total_width += float(GROUP_ANALYSIS_COLUMN_WIDTHS.get(col, 14))
    return max(total_width, 8.0)


def _estimate_span_height(value, first_col, last_col, *, minimum=DEFAULT_ROW_HEIGHT, line_height=DEFAULT_LINE_HEIGHT, padding=4):
    return _estimate_wrapped_row_height(
        [{'value': value, 'width': _column_span_width(first_col, last_col), 'wrap': True}],
        minimum=minimum,
        line_height=line_height,
        padding=padding,
    )


def _truncate_text(value, *, max_chars=180):
    text = str(value or '').strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip(' ,;:.') + '...'


def _merge_row(worksheet, row, first_col, last_col, value, cell_format=None):
    native = _get_native_worksheet(worksheet)
    if first_col != last_col and hasattr(native, 'merge_range'):
        native.merge_range(row, first_col, row, last_col, value, cell_format)
    else:
        worksheet.write(row, first_col, value, cell_format)


def _set_row_height(worksheet, row, height, cell_format=None, options=None):
    if hasattr(worksheet, 'set_row'):
        worksheet.set_row(row, height, cell_format, options or {})


def _set_row_options(worksheet, row, *, level=None, hidden=None, collapsed=None):
    options = {}
    if level is not None:
        options['level'] = int(level)
    if hidden is not None:
        options['hidden'] = bool(hidden)
    if collapsed is not None:
        options['collapsed'] = bool(collapsed)
    if options and hasattr(worksheet, 'set_row'):
        worksheet.set_row(row, None, None, options)


def _combine_nonempty_lines(*values):
    lines = []
    for value in values:
        text = str(value or '').strip()
        if text:
            lines.extend(part for part in text.splitlines() if part.strip())
    return '\n'.join(lines)


def _coerce_status_label(value):
    normalized = str(value or '').strip().upper()
    if normalized == 'YES':
        return 'DIFFERENCE'
    if normalized == 'NO':
        return 'NO DIFFERENCE'
    return str(value or '').strip()


def _format_analysis_level_label(value):
    normalized = str(value or 'light').strip().lower()
    if normalized == 'standard':
        return 'Standard'
    if normalized == 'light':
        return 'Light'
    return normalized.title() if normalized else 'Light'


def _resolve_metric_index_status(metric_row):
    return (
        metric_row.get('index_status')
        or metric_row.get('summary_status')
        or _coerce_status_label(((metric_row.get('pairwise_rows') or [{}])[0]).get('difference'))
        or 'REVIEW'
    )


def _format_metric_insights(metric_row):
    insight_lines = [
        str(value).strip()
        for value in (metric_row.get('insights') or [])
        if str(value or '').strip()
    ]
    return '\n'.join(insight_lines)


def _coerce_finite_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _format_decimal(value, *, digits=3):
    number = _coerce_finite_float(value)
    if number is None:
        return ''
    return f'{number:.{int(digits)}f}'


def _format_ci_interval(interval, *, digits=3):
    if not isinstance(interval, dict):
        return ''
    lower = _format_decimal(interval.get('lower'), digits=digits)
    upper = _format_decimal(interval.get('upper'), digits=digits)
    if not lower or not upper:
        return ''
    return f'95% CI {lower} to {upper}'


def _first_sentence(value):
    text = str(value or '').strip()
    if not text:
        return ''
    for punct in ('. ', '! ', '? '):
        if punct in text:
            return text.split(punct, 1)[0].strip().rstrip('.!?') + punct[0]
    return text


def _pick_priority_pairwise_row(metric_row):
    pairwise_rows = metric_row.get('pairwise_rows') or []
    if not pairwise_rows:
        return None
    return sorted(
        pairwise_rows,
        key=lambda row: (
            _coerce_status_label(row.get('difference_label') or row.get('difference')) != 'DIFFERENCE',
            _coerce_finite_float(row.get('adjusted_p_value')) is None,
            _coerce_finite_float(row.get('adjusted_p_value')) if _coerce_finite_float(row.get('adjusted_p_value')) is not None else float('inf'),
            -abs(_coerce_finite_float(row.get('effect_size')) or 0.0),
            str(row.get('group_a') or ''),
            str(row.get('group_b') or ''),
        ),
    )[0]


def _build_location_priority_signal(metric_row):
    status = str(_resolve_metric_index_status(metric_row) or 'REVIEW').strip().upper() or 'REVIEW'
    best_pair = _pick_priority_pairwise_row(metric_row)
    if best_pair is None:
        return None

    detail_parts = [f"{best_pair.get('group_a')} vs {best_pair.get('group_b')}"]
    adjusted_p = _format_decimal(best_pair.get('adjusted_p_value'), digits=4)
    effect_size = _format_decimal(best_pair.get('effect_size'), digits=3)
    if adjusted_p:
        detail_parts.append(f"adj p={adjusted_p}")
    if effect_size:
        detail_parts.append(f"effect={effect_size}")
    summary = ', '.join(detail_parts)
    flags = str(best_pair.get('flags') or '').strip()

    if status == 'DIFFERENCE':
        return {'kind': 'location_gap', 'rank': 0, 'reason': f'Location gap: {summary}'}
    if status == 'USE CAUTION':
        caution_suffix = f'; {flags}' if flags else '; interpret with caution'
        return {'kind': 'sample_caution', 'rank': 3, 'reason': f'Location signal with caution: {summary}{caution_suffix}'}
    if status == 'APPROXIMATE':
        return {'kind': 'approximate_gap', 'rank': 4, 'reason': f'Approximate location gap: {summary}; moderate effect without corrected significance'}
    return None


def _build_shape_priority_signal(metric_row):
    distribution_verdict = _first_sentence((metric_row.get('distribution_difference') or {}).get('comment / verdict'))
    if distribution_verdict and 'no statistically significant' not in distribution_verdict.lower():
        cleaned = distribution_verdict
        if cleaned.lower().startswith('shape note:'):
            cleaned = cleaned.split(':', 1)[1].strip()
        return {'kind': 'shape_gap', 'rank': 2, 'reason': f'Shape gap: {cleaned}'}
    return None


def _build_capability_priority_signal(metric_row):
    if metric_row.get('capability_allowed') is False:
        return None

    capability_payload = metric_row.get('capability')
    if not isinstance(capability_payload, dict):
        return None

    cp_value = _coerce_finite_float(capability_payload.get('cp'))
    cpk_value = _coerce_finite_float(capability_payload.get('cpk'))
    capability_value = _coerce_finite_float(capability_payload.get('capability'))
    capability_type = str(capability_payload.get('capability_type') or 'Capability').strip() or 'Capability'
    capability_ci = capability_payload.get('capability_ci') if isinstance(capability_payload.get('capability_ci'), dict) else {}
    cpk_ci = capability_ci.get('cpk') if isinstance(capability_ci, dict) else None
    lower_ci = _coerce_finite_float((cpk_ci or {}).get('lower')) if isinstance(cpk_ci, dict) else None
    ci_text = _format_ci_interval(cpk_ci, digits=3)

    if cp_value is not None and cpk_value is not None:
        palette_key = _classify_capability_status(cp_value, cpk_value).get('palette_key')
        label = _capability_readiness_label(palette_key)
        severity = 'risk' if palette_key == 'quality_risk' else 'caution' if palette_key == 'quality_marginal' or (lower_ci is not None and lower_ci < 1.0) else None
        if severity is None:
            return None
        detail = f'Cp={cp_value:.3f}, Cpk={cpk_value:.3f}'
    elif capability_value is not None:
        palette_key = _classify_capability_value(capability_value, label_prefix=capability_type).get('palette_key')
        label = _capability_readiness_label(palette_key)
        severity = 'risk' if palette_key == 'quality_risk' else 'caution' if palette_key == 'quality_marginal' or (lower_ci is not None and lower_ci < 1.0) else None
        if severity is None:
            return None
        detail = f'{capability_type}={capability_value:.3f}'
    else:
        return None

    if ci_text:
        detail = f'{detail}, {ci_text}'
    if lower_ci is not None and lower_ci < 1.0:
        detail = f'{detail}, lower CI < 1.000'

    return {
        'kind': f'capability_{severity}',
        'rank': 1 if severity == 'risk' else 2,
        'reason': f'Capability {label}: {detail}',
    }


def _build_metric_priority_reason(metric_row):
    location_signal = _build_location_priority_signal(metric_row)
    capability_signal = _build_capability_priority_signal(metric_row)
    shape_signal = _build_shape_priority_signal(metric_row)

    if location_signal is not None and location_signal.get('kind') == 'location_gap':
        return location_signal['reason']
    if capability_signal is not None:
        return capability_signal['reason']
    if shape_signal is not None:
        return shape_signal['reason']
    if location_signal is not None:
        return location_signal['reason']

    diagnostics_comment = _first_sentence(metric_row.get('diagnostics_comment'))
    if diagnostics_comment:
        lowered = diagnostics_comment.lower()
        if 'descriptive-only' in lowered:
            return 'Restriction-driven caution: descriptive-only review'
        if 'histogram omitted' in lowered or 'analyzed with caution' in lowered:
            return f'Sample caution: {diagnostics_comment}'
        return diagnostics_comment

    takeaway = _first_sentence(metric_row.get('metric_takeaway'))
    if takeaway:
        return takeaway
    return 'Review descriptive statistics only.'


def _build_metric_index_restriction(metric_row):
    return str(metric_row.get('analysis_restriction_label') or 'Review').strip() or 'Review'


def _build_metric_next_step(metric_row):
    recommended_action = _first_sentence(metric_row.get('recommended_action'))
    if recommended_action:
        return recommended_action
    metric_takeaway = _first_sentence(metric_row.get('metric_takeaway'))
    if metric_takeaway:
        return metric_takeaway
    best_pair = _pick_priority_pairwise_row(metric_row)
    if best_pair is not None:
        suggested_action = _first_sentence(best_pair.get('suggested_action'))
        if suggested_action:
            return suggested_action
    return 'Review the metric detail block before acting.'


def _status_format_key(status_label):
    normalized = str(status_label or '').strip().upper()
    if normalized == 'DIFFERENCE':
        return 'status_difference_fmt'
    if normalized == 'NO DIFFERENCE':
        return 'status_no_difference_fmt'
    if normalized in {'USE CAUTION', 'APPROXIMATE'}:
        return 'status_caution_fmt'
    return 'status_review_fmt'


def _card_format_key(status_label):
    normalized = str(status_label or '').strip().upper()
    if normalized in {'READY', 'OK'}:
        return 'card_success_fmt'
    if normalized in {'DIFFERENCE'}:
        return 'card_emphasis_fmt'
    if normalized in {'USE CAUTION', 'APPROXIMATE'}:
        return 'card_warning_fmt'
    if normalized in {'REVIEW', 'SKIPPED', 'ERROR'}:
        return 'card_risk_fmt' if normalized in {'ERROR'} else 'card_default_fmt'
    return 'card_default_fmt'


def _format_capability_detail(entry):
    capability_type = str(entry.get('capability_type') or '').strip()
    capability_ci = ((entry.get('capability_ci') or {}).get('cpk') if isinstance(entry.get('capability_ci'), dict) else None)
    ci_text = _format_ci_interval(capability_ci, digits=3)
    if capability_type and ci_text:
        return f'{capability_type}\n{ci_text}'
    if capability_type:
        return capability_type
    return ci_text


def _capability_readiness_label(palette_key):
    return {
        'quality_capable': 'capable',
        'quality_good': 'good',
        'quality_marginal': 'marginal',
        'quality_risk': 'risk',
        'quality_unknown': 'unknown',
    }.get(str(palette_key or '').strip().lower(), 'unknown')


def _format_metric_capability_summary(metric_row):
    if metric_row.get('capability_allowed') is False:
        return 'Capability is disabled for this metric because limits are not directly comparable across groups.'

    capability_payload = metric_row.get('capability')
    if not isinstance(capability_payload, dict):
        return ''

    cp_value = _coerce_finite_float(capability_payload.get('cp'))
    cpk_value = _coerce_finite_float(capability_payload.get('cpk'))
    capability_value = _coerce_finite_float(capability_payload.get('capability'))
    capability_type = str(capability_payload.get('capability_type') or 'Capability').strip() or 'Capability'
    capability_ci = capability_payload.get('capability_ci') if isinstance(capability_payload.get('capability_ci'), dict) else {}
    cpk_ci = capability_ci.get('cpk') if isinstance(capability_ci, dict) else None
    lower_ci = _coerce_finite_float((cpk_ci or {}).get('lower')) if isinstance(cpk_ci, dict) else None

    if cp_value is not None and cpk_value is not None:
        readiness = _capability_readiness_label(_classify_capability_status(cp_value, cpk_value).get('palette_key'))
        summary = f'Cp/Cpk {readiness}: Cp={cp_value:.3f}, Cpk={cpk_value:.3f}.'
    elif capability_value is not None:
        readiness = _capability_readiness_label(
            _classify_capability_value(capability_value, label_prefix=capability_type).get('palette_key')
        )
        summary = f'{capability_type} {readiness}: {capability_value:.3f}.'
    else:
        status = str(capability_payload.get('status') or '').strip().lower()
        if status == 'not_applicable':
            return 'Capability is not applicable with the current data or spec definition.'
        return ''

    ci_text = _format_ci_interval(cpk_ci, digits=3)
    if ci_text:
        confidence_note = 'lower bound below 1.000' if lower_ci is not None and lower_ci < 1.0 else 'lower bound at or above 1.000'
        summary = f'{summary} {ci_text}; {confidence_note}.'
    return summary


def _format_metric_stat_signal(metric_row):
    best_pair = _pick_priority_pairwise_row(metric_row)
    if best_pair is None:
        return ''

    status_label = _coerce_status_label(best_pair.get('difference_label') or best_pair.get('difference'))
    status_label = status_label or _resolve_metric_index_status(metric_row) or 'REVIEW'
    verdict = {
        'DIFFERENCE': 'Statistically different',
        'NO DIFFERENCE': 'No statistically significant difference',
        'USE CAUTION': 'Possible difference, interpret with caution',
        'APPROXIMATE': 'Approximate difference only',
    }.get(str(status_label).strip().upper(), 'Review statistical signal')
    comparison = f"{best_pair.get('group_a')} vs {best_pair.get('group_b')}"
    adjusted_p = _format_decimal(best_pair.get('adjusted_p_value'), digits=4)
    effect_size = _format_decimal(best_pair.get('effect_size'), digits=3)

    parts = [f'{comparison}: {verdict}']
    if adjusted_p:
        parts.append(f'adj p={adjusted_p}')
    if effect_size:
        parts.append(f'effect={effect_size}')
    flags = _first_sentence(best_pair.get('flags'))
    if str(status_label).strip().upper() in {'USE CAUTION', 'APPROXIMATE'} and flags:
        parts.append(flags)
    return '; '.join(parts)


def _is_compact_metric(metric_row):
    summary = _metric_priority_summary_parts(metric_row)
    if summary['status'] != 'NO DIFFERENCE':
        return False
    if summary['primary_signal'] is not None:
        return False
    diagnostics_comment = _first_sentence(metric_row.get('diagnostics_comment'))
    return not diagnostics_comment


def _build_metric_anchor_text(metric_row):
    metric_name = str(metric_row.get('metric') or 'Unknown')
    if _is_compact_metric(metric_row):
        return f'Metric: {metric_name} | All clear'
    return f"Metric: {metric_name} | {_truncate_text(_build_metric_priority_reason(metric_row), max_chars=90)}"


def _format_metric_highlights(metric_row, capability_summary_text):
    shape_note = str(
        metric_row.get('metric_note')
        or (metric_row.get('distribution_difference') or {}).get('comment / verdict')
        or ''
    ).strip()
    caution_text = str(
        metric_row.get('diagnostics_comment')
        or (metric_row.get('comparability_summary') or {}).get('summary')
        or ''
    ).strip()
    if _is_compact_metric(metric_row):
        highlights = [
            ('Priority signal', _build_metric_priority_reason(metric_row)),
            ('Capability summary', capability_summary_text),
            ('Recommended action', str(metric_row.get('recommended_action') or '').strip()),
        ]
        return [(label, value) for label, value in highlights if str(value or '').strip()]
    highlights = [
        ('Priority signal', _build_metric_priority_reason(metric_row)),
        ('Capability summary', capability_summary_text),
        ('Shape note', shape_note),
        ('Recommended action', str(metric_row.get('recommended_action') or '').strip()),
        ('Use caution', caution_text),
    ]
    return [(label, value) for label, value in highlights if str(value or '').strip()]


def _format_range_text(lower, upper):
    lower_text = _format_decimal(lower, digits=3)
    upper_text = _format_decimal(upper, digits=3)
    if lower_text and upper_text:
        return f'{lower_text} to {upper_text}'
    return lower_text or upper_text


def _format_distribution_note(entry):
    capability_detail = _format_capability_detail(entry)
    fit_model = str(entry.get('best_fit_model') or '').strip()
    fit_quality = str(entry.get('fit_quality') or '').strip()
    fit_note = ''
    if fit_model and fit_quality:
        fit_note = f'Fit: {fit_model} ({fit_quality})'
    elif fit_model:
        fit_note = f'Fit: {fit_model}'
    elif fit_quality:
        fit_note = f'Fit quality: {fit_quality}'
    caution = str(entry.get('distribution_shape_caution') or '').strip()
    caution_note = f'Caution: {caution}' if caution else ''
    return _combine_nonempty_lines(capability_detail, fit_note, caution_note)


def _format_descriptive_ci(entry):
    capability_ci = ((entry.get('capability_ci') or {}).get('cpk') if isinstance(entry.get('capability_ci'), dict) else None)
    ci_text = _format_ci_interval(capability_ci, digits=3)
    if ci_text:
        return ci_text
    if str(entry.get('capability_type') or '').strip():
        return '95% CI unavailable'
    return ''


def _format_descriptive_fit_model(entry):
    return str(entry.get('best_fit_model') or '').strip()


def _format_descriptive_fit_quality(entry):
    return str(entry.get('fit_quality') or '').strip()


def _format_descriptive_notes(entry):
    parts = []
    caution = _first_sentence(entry.get('distribution_shape_caution'))
    flags = str(entry.get('flags') or '').strip()
    if caution:
        parts.append(caution)
    if flags and flags.lower() != 'none':
        parts.append(flags)
    return '; '.join(parts)


def _format_pairwise_takeaway(entry):
    takeaway = _first_sentence(entry.get('takeaway'))
    if takeaway:
        return takeaway
    status_label = _coerce_status_label(entry.get('difference_label') or entry.get('difference')) or 'REVIEW'
    return f"{entry.get('group_a')} vs {entry.get('group_b')}: {status_label}."


def _format_pairwise_action(entry):
    return _first_sentence(entry.get('suggested_action'))


def _format_pairwise_test_context(entry):
    return str(entry.get('test_used') or '').strip() or 'Comparison test'


def _format_pairwise_rationale(entry):
    return _truncate_text(_first_sentence(entry.get('test_rationale')), max_chars=60)


def _format_pairwise_comment(entry):
    caution = _first_sentence(entry.get('comment'))
    if caution:
        return f'Caution: {caution}'
    return ''


def _is_banded_row(row_index, *, anchor_row):
    return (int(row_index) - int(anchor_row)) % 2 == 1


def _row_format(formats, default_key, banded_key, *, banded):
    if banded and banded_key in formats:
        return formats.get(banded_key)
    return formats.get(default_key)


def _build_attention_summary(metric_rows, *, skipped_count=0):
    ordered_statuses = ['DIFFERENCE', 'USE CAUTION', 'REVIEW', 'NO DIFFERENCE']
    status_counts = {}
    for metric_row in metric_rows:
        status = str(_resolve_metric_index_status(metric_row) or 'REVIEW').strip().upper() or 'REVIEW'
        status_counts[status] = status_counts.get(status, 0) + 1

    parts = [
        f"{status_counts[status]} {status}"
        for status in ordered_statuses
        if status_counts.get(status)
    ]
    for status in sorted(status_counts):
        if status not in ordered_statuses:
            parts.append(f"{status_counts[status]} {status}")
    if skipped_count:
        parts.append(f"{int(skipped_count)} SKIPPED")
    return ', '.join(parts) if parts else 'No analyzed metrics.'


def _build_metric_status_counts(metric_rows):
    counts = {
        'DIFFERENCE': 0,
        'NO DIFFERENCE': 0,
        'CAUTION': 0,
    }
    for metric_row in metric_rows:
        status = str(_resolve_metric_index_status(metric_row) or 'REVIEW').strip().upper() or 'REVIEW'
        if status == 'DIFFERENCE':
            counts['DIFFERENCE'] += 1
        elif status == 'NO DIFFERENCE':
            counts['NO DIFFERENCE'] += 1
        else:
            counts['CAUTION'] += 1
    return counts


def _metric_priority_summary_parts(metric_row):
    status = str(_resolve_metric_index_status(metric_row) or 'REVIEW').strip().upper() or 'REVIEW'
    location_signal = _build_location_priority_signal(metric_row)
    capability_signal = _build_capability_priority_signal(metric_row)
    shape_signal = _build_shape_priority_signal(metric_row)

    primary_signal = None
    if location_signal is not None and location_signal.get('kind') == 'location_gap':
        primary_signal = location_signal
    elif capability_signal is not None:
        primary_signal = capability_signal
    elif shape_signal is not None:
        primary_signal = shape_signal
    elif location_signal is not None:
        primary_signal = location_signal

    p_values = [
        float(row.get('adjusted_p_value'))
        for row in (metric_row.get('pairwise_rows') or [])
        if row.get('adjusted_p_value') is not None
    ]
    best_p = min(p_values) if p_values else float('inf')
    capability_payload = metric_row.get('capability') if isinstance(metric_row.get('capability'), dict) else {}
    lower_ci = _coerce_finite_float((((capability_payload.get('capability_ci') or {}).get('cpk') or {}).get('lower')))
    capability_value = _coerce_finite_float(capability_payload.get('capability'))
    effect_sizes = [
        abs(float(row.get('effect_size')))
        for row in (metric_row.get('pairwise_rows') or [])
        if row.get('effect_size') is not None
    ]
    max_effect = max(effect_sizes) if effect_sizes else 0.0
    return {
        'status': status,
        'primary_signal': primary_signal,
        'best_p': best_p,
        'lower_ci': lower_ci if lower_ci is not None else float('inf'),
        'capability_value': capability_value if capability_value is not None else float('inf'),
        'max_effect': max_effect,
        'reason': _build_metric_priority_reason(metric_row),
        'metric': str(metric_row.get('metric') or ''),
    }


def _metric_priority_sort_key(metric_row):
    summary = _metric_priority_summary_parts(metric_row)
    return (
        summary['primary_signal']['rank'] if summary['primary_signal'] is not None else 5,
        summary['best_p'],
        summary['lower_ci'],
        summary['capability_value'],
        -summary['max_effect'],
        summary['metric'],
    )


def _sorted_metric_rows(metric_rows):
    return sorted(metric_rows, key=_metric_priority_sort_key)


def _metric_priority_badge(metric_row):
    summary = _metric_priority_summary_parts(metric_row)
    signal = summary['primary_signal']
    if signal is not None:
        kind = str(signal.get('kind') or '').strip().lower()
        return {
            'location_gap': 'location gap',
            'capability_risk': 'capability risk',
            'capability_caution': 'capability caution',
            'shape_gap': 'shape gap',
            'sample_caution': 'sample caution',
            'approximate_gap': 'approximate gap',
        }.get(kind, summary['status'].lower())
    return summary['status'].lower()


def _build_compact_priority_metrics_summary(metric_rows, *, limit=2):
    candidates = []
    for metric_row in _sorted_metric_rows(metric_rows):
        summary = _metric_priority_summary_parts(metric_row)
        if summary['primary_signal'] is None and summary['status'] == 'NO DIFFERENCE':
            continue
        badge = _metric_priority_badge(metric_row)
        if math.isfinite(summary['best_p']):
            badge = f'{badge}, adj p={summary["best_p"]:.4f}'
        candidates.append(f"{summary['metric']}: {badge}")
        if len(candidates) >= int(limit):
            break
    return '; '.join(candidates) if candidates else 'No immediate priorities'


def _build_watch_summary(payload, metric_rows):
    diagnostics = payload.get('diagnostics') or {}
    warning_parts = []
    warning_count = int((diagnostics.get('warning_summary') or {}).get('count') or 0)
    unmatched_count = int((diagnostics.get('unmatched_metrics_summary') or {}).get('count') or 0)
    if warning_count:
        warning_parts.append(f"{warning_count} warning{'s' if warning_count != 1 else ''}")
    if unmatched_count:
        warning_parts.append(f"{unmatched_count} uncovered")
    plot_summary = _build_plot_coverage_summary(metric_rows, payload.get('analysis_level'))
    if plot_summary:
        warning_parts.append(plot_summary.replace(' omitted for ', ' omitted: '))
    if str(payload.get('analysis_level') or 'light').strip().lower() == 'standard' and metric_rows:
        warning_parts.append('plots on separate sheet')
    skip_reason = payload.get('skip_reason')
    if skip_reason:
        warning_parts.append(str(skip_reason.get('message') or '').strip())
    return '; '.join(warning_parts)


def _build_priority_metrics_summary(metric_rows):
    ranked_rows = []
    for metric_row in metric_rows:
        summary = _metric_priority_summary_parts(metric_row)
        if summary['primary_signal'] is None and summary['status'] == 'NO DIFFERENCE':
            continue
        ranked_rows.append(
            (
                _metric_priority_sort_key(metric_row),
                f"{summary['metric']} ({summary['status']}: {summary['reason']})",
            )
        )

    if not ranked_rows:
        return 'No metrics currently stand out.'
    top_rows = sorted(ranked_rows)[:3]
    return ', '.join(row[-1] for row in top_rows)


def _build_plot_coverage_summary(metric_rows, analysis_level):
    if str(analysis_level or 'light').strip().lower() != 'standard':
        return ''

    omitted_counts = {'violin': 0, 'histogram': 0}
    for metric_row in metric_rows:
        eligibility = metric_row.get('plot_eligibility') or {}
        for plot_key in omitted_counts:
            plot_meta = eligibility.get(plot_key) or {}
            if plot_meta and not bool(plot_meta.get('eligible')):
                omitted_counts[plot_key] += 1

    parts = []
    for plot_key, label in (('violin', 'violins'), ('histogram', 'histograms')):
        count = omitted_counts[plot_key]
        if count:
            parts.append(f"{label} omitted for {count} metric{'s' if count != 1 else ''}")
    return '; '.join(parts)


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
        'text_left_middle': formats.get('text_left_middle_fmt'),
        'table_center': formats.get('table_center_fmt'),
        'table_center_wrap': formats.get('table_center_wrap_fmt'),
        'default': formats.get('default_data_fmt'),
        'num': formats.get('num_fmt'),
        'pvalue': formats.get('pvalue_fmt'),
        'summary_label': formats.get('summary_label_fmt'),
        'summary_label_wrap': formats.get('summary_label_wrap_fmt'),
        'summary_value': formats.get('summary_value_fmt'),
        'summary_value_wrap': formats.get('summary_value_wrap_fmt'),
        'overview_value': formats.get('overview_value_fmt'),
        'takeaway_label': formats.get('takeaway_label_fmt'),
        'takeaway_value': formats.get('takeaway_value_fmt'),
        'hyperlink': formats.get('hyperlink_fmt'),
    }

    if hasattr(worksheet, 'hide_gridlines'):
        worksheet.hide_gridlines(2)

    if hasattr(worksheet, 'set_column'):
        for col, width in GROUP_ANALYSIS_COLUMN_WIDTHS.items():
            worksheet.set_column(col, col, width, header_formats['default'])

    freeze_panes = sheet_state.get('freeze_panes')
    if freeze_panes and hasattr(worksheet, 'freeze_panes'):
        worksheet.freeze_panes(*freeze_panes)

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


def _apply_group_analysis_print_layout(worksheet, *, title, last_row, repeat_to_row):
    if worksheet is None:
        return
    target = _get_native_worksheet(worksheet)
    if hasattr(target, 'set_landscape'):
        target.set_landscape()
    if hasattr(target, 'fit_to_pages'):
        target.fit_to_pages(1, 0)
    if hasattr(target, 'set_paper'):
        target.set_paper(1)
    if hasattr(target, 'repeat_rows'):
        target.repeat_rows(0, max(0, int(repeat_to_row)))
    if hasattr(target, 'print_area'):
        target.print_area(0, 0, max(0, int(last_row)), METRIC_TITLE_LAST_COL)
    if hasattr(target, 'set_footer'):
        target.set_footer(f'&L{title}&RPage &P of &N')


def _write_top_guidance_row(worksheet, row, payload, metric_rows):
    formats = _build_formats(worksheet)
    normalized_level = str(payload.get('analysis_level') or 'light').strip().lower()
    guidance = 'Tip: use the +/- outline controls on the left to expand metric details.'
    if metric_rows:
        guidance = f'{guidance} Low-priority no-difference metrics start collapsed.'
    if normalized_level == 'standard':
        guidance = f'{guidance} Plots are on the Group Analysis Plots sheet.'

    _merge_row(worksheet, row, 0, 2, 'Tip', formats.get('detail_label_fmt'))
    _merge_row(worksheet, row, 3, 11, guidance, formats.get('detail_note_fmt'))
    if normalized_level == 'standard':
        if hasattr(worksheet, 'write_url'):
            worksheet.write_url(
                row,
                12,
                "internal:'Group Analysis Plots'!A1",
                formats.get('hyperlink_fmt'),
                'Open plots sheet',
            )
        else:
            worksheet.write(row, 12, 'Open plots sheet', formats.get('hyperlink_fmt'))
    _set_row_height(
        worksheet,
        row,
        max(
            28,
            _estimate_wrapped_row_height(
                [
                    {'value': guidance, 'width': _column_span_width(3, 11), 'wrap': True},
                ],
                minimum=28,
                line_height=12,
                padding=6,
            ),
        ),
        formats.get('detail_note_fmt'),
    )
    return row + 1


def _write_dashboard_row(worksheet, row, payload, metric_rows):
    formats = _build_formats(worksheet)
    diagnostics = payload.get('diagnostics') or {}
    analysis_level = _format_analysis_level_label(payload.get('analysis_level'))
    effective_scope = str(payload.get('effective_scope') or 'n/a').replace('_', ' ').title()
    status_label = str(payload.get('status') or 'ready').strip().upper() or 'READY'
    status_counts = _build_metric_status_counts(metric_rows)
    coverage_text = 'Coverage unavailable'
    coverage_parts = []
    group_count = diagnostics.get('group_count')
    reference_count = diagnostics.get('reference_count')
    if group_count is not None:
        coverage_parts.append(f"{int(group_count)} group{'s' if int(group_count) != 1 else ''}")
    if reference_count is not None:
        coverage_parts.append(f"{int(reference_count)} reference{'s' if int(reference_count) != 1 else ''}")
    if coverage_parts:
        coverage_text = ' across '.join(coverage_parts)
    metric_count = len(metric_rows)
    watch_summary = _build_watch_summary(payload, metric_rows)
    top_focus = _truncate_text(_build_compact_priority_metrics_summary(metric_rows, limit=2), max_chars=88)
    warning_count = int((diagnostics.get('warning_summary') or {}).get('count') or 0)

    status_card = '\n'.join([
        'STATUS',
        status_label.title(),
        f'{analysis_level} | {effective_scope}',
    ])
    coverage_card = '\n'.join([
        'COVERAGE',
        coverage_text,
        f'{metric_count} metric{"s" if metric_count != 1 else ""}',
    ])
    difference_card = '\n'.join([
        'DIFFERENCE',
        f"{status_counts['DIFFERENCE']} metric{'s' if status_counts['DIFFERENCE'] != 1 else ''}",
    ])
    caution_card = '\n'.join([
        'CAUTION / REVIEW',
        f"{status_counts['CAUTION']} metric{'s' if status_counts['CAUTION'] != 1 else ''}",
        f'{warning_count} warning{"s" if warning_count != 1 else ""}',
    ])
    clear_card = '\n'.join([
        'NO DIFFERENCE',
        f"{status_counts['NO DIFFERENCE']} metric{'s' if status_counts['NO DIFFERENCE'] != 1 else ''}",
    ])
    focus_lines = ['NEXT', f'Top: {top_focus}']
    if watch_summary:
        focus_lines.append(f"Watch: {_truncate_text(watch_summary, max_chars=90)}")
    focus_card = '\n'.join(focus_lines)

    _merge_row(worksheet, row, 0, 2, status_card, formats.get(_card_format_key(status_label)))
    _merge_row(worksheet, row, 3, 5, coverage_card, formats.get('card_default_fmt'))
    _merge_row(worksheet, row, 6, 7, difference_card, formats.get('card_emphasis_fmt'))
    _merge_row(worksheet, row, 8, 9, caution_card, formats.get('card_warning_fmt'))
    _merge_row(worksheet, row, 10, 11, clear_card, formats.get('card_success_fmt'))
    _merge_row(worksheet, row, 12, 14, focus_card, formats.get('card_default_fmt'))
    _set_row_height(
        worksheet,
        row,
        max(
            52,
            _estimate_wrapped_row_height(
                [
                    {'value': status_card, 'width': _column_span_width(0, 2), 'wrap': True},
                    {'value': coverage_card, 'width': _column_span_width(3, 5), 'wrap': True},
                    {'value': difference_card, 'width': _column_span_width(6, 7), 'wrap': True},
                    {'value': caution_card, 'width': _column_span_width(8, 9), 'wrap': True},
                    {'value': clear_card, 'width': _column_span_width(10, 11), 'wrap': True},
                    {'value': focus_card, 'width': _column_span_width(12, 14), 'wrap': True},
                ],
                minimum=52,
                line_height=12,
                padding=8,
            ),
        ),
    )
    return row + 1


def _write_metric_index(worksheet, row, metric_rows, *, sheet_state=None):
    formats = _build_formats(worksheet)
    _merge_row(worksheet, row, 0, 8, 'Metric index', formats.get('section_fmt'))
    worksheet.write(row, 10, 'Guide', formats.get('detail_label_fmt'))
    if hasattr(worksheet, 'write_url'):
        worksheet.write_url(
            row,
            11,
            GROUP_ANALYSIS_MANUAL_GITHUB_URL,
            formats.get('hyperlink_fmt'),
            'Open Markdown manual',
            'Open the plain-English Group Analysis guide in the GitHub repository.',
        )
        worksheet.write_url(
            row,
            13,
            GROUP_ANALYSIS_MANUAL_PDF_GITHUB_URL,
            formats.get('hyperlink_fmt'),
            'Open PDF manual',
            'Open the printable Group Analysis PDF companion in the GitHub repository.',
        )
    else:
        worksheet.write(row, 11, 'Open Markdown manual', formats.get('hyperlink_fmt'))
        worksheet.write(row, 13, 'Open PDF manual', formats.get('hyperlink_fmt'))
    _set_row_height(worksheet, row, 24, formats.get('section_fmt'))
    row += 1

    header_row = row
    _merge_row(worksheet, row, 0, 0, 'Metric', formats.get('header_fmt'))
    _merge_row(worksheet, row, 1, 1, 'Status', formats.get('header_fmt'))
    _merge_row(worksheet, row, 2, 2, 'Jump', formats.get('header_fmt'))
    _merge_row(worksheet, row, 3, 3, 'Spec', formats.get('header_fmt'))
    _merge_row(worksheet, row, 4, 8, 'Priority signal', formats.get('header_fmt'))
    _merge_row(worksheet, row, 9, 14, 'Next step', formats.get('header_fmt'))
    _set_row_height(worksheet, row, 24, formats.get('header_fmt'))
    row += 1

    first_data_row = row
    for metric_row in metric_rows:
        metric_name = str(metric_row.get('metric') or 'Unknown')
        status_label = _resolve_metric_index_status(metric_row)
        spec_status_label = metric_row.get('spec_status_label') or get_spec_status_label(metric_row.get('spec_status'))
        review_reason = _truncate_text(_build_metric_priority_reason(metric_row), max_chars=180)
        next_step = _truncate_text(_build_metric_next_step(metric_row), max_chars=180)
        banded = _is_banded_row(row, anchor_row=first_data_row)

        worksheet.write(row, 0, metric_name, _row_format(formats, 'text_left_middle_fmt', 'band_text_left_middle_fmt', banded=banded))
        worksheet.write(row, 1, status_label, formats.get(_status_format_key(status_label)))
        worksheet.write(row, 2, 'Go to metric', _row_format(formats, 'hyperlink_cell_fmt', 'band_hyperlink_cell_fmt', banded=banded))
        worksheet.write(row, 3, spec_status_label, _row_format(formats, 'table_center_wrap_fmt', 'band_table_center_wrap_fmt', banded=banded))
        _merge_row(worksheet, row, 4, 8, review_reason, _row_format(formats, 'detail_value_fmt', 'band_detail_value_fmt', banded=banded))
        _merge_row(worksheet, row, 9, 14, next_step, _row_format(formats, 'detail_note_fmt', 'band_detail_note_fmt', banded=banded))
        _set_row_height(
            worksheet,
            row,
            max(
                26,
                _estimate_wrapped_row_height(
                    [
                        {'value': review_reason, 'width': _column_span_width(4, 8), 'wrap': True},
                        {'value': next_step, 'width': _column_span_width(9, 14), 'wrap': True},
                    ],
                    minimum=26,
                    line_height=12,
                    padding=6,
                ),
            ),
        )
        if sheet_state is not None:
            sheet_state['metric_index_links'].append((row, 2, metric_name))
        row += 1

    return row + SECTION_GAP, {'header_row': header_row, 'first_data_row': first_data_row}


def _apply_metric_pairwise_formats(worksheet, bounds):
    headers = bounds['headers']
    first = bounds['first_data_row']
    last = bounds['last_data_row']
    if first > last:
        return
    formats = _build_formats(worksheet)
    column_lookup = bounds.get('column_lookup') or {}

    def _column_for(*labels):
        for label in labels:
            if label in column_lookup:
                return column_lookup[label]
        for label in labels:
            if label in headers:
                return headers.index(label)
        raise ValueError(f'Missing expected pairwise column: {labels}')

    difference_col = _column_for('Status', 'difference')
    comment_col = _column_for('Comment', 'Action', 'Insight / action', 'caution')
    flags_col = column_lookup.get('Flags')
    if flags_col is None and 'Flags' in headers:
        flags_col = headers.index('Flags')
    pvalue_col = _column_for('adj p-value')
    effect_col = _column_for('effect size')
    delta_mean_col = column_lookup.get('Delta mean')
    if delta_mean_col is None and 'Delta mean' in headers:
        delta_mean_col = headers.index('Delta mean')

    _apply_conditional(worksheet, first, difference_col, last, difference_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='USE CAUTION'))
    _apply_conditional(worksheet, first, difference_col, last, difference_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='APPROXIMATE'))
    _apply_conditional(worksheet, first, comment_col, last, comment_col, _style_rule(formats, 'warning', type='text', criteria='containing', value='Caution:'))
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


def _write_metric_snapshot(worksheet, row, metric_row, capability_summary_text, *, compact=False):
    formats = _build_formats(worksheet)
    status_label = _resolve_metric_index_status(metric_row)
    spec_status_label = metric_row.get('spec_status_label') or get_spec_status_label(metric_row.get('spec_status'))
    restriction_label = _build_metric_index_restriction(metric_row)
    next_step = _truncate_text(_build_metric_next_step(metric_row), max_chars=140 if compact else 220)

    _merge_row(worksheet, row, 0, 2, f'STATUS\n{status_label}', formats.get(_card_format_key(status_label)))
    _merge_row(worksheet, row, 3, 5, f'SPEC\n{spec_status_label}', formats.get('card_default_fmt'))
    _merge_row(worksheet, row, 6, 8, f'MODE\n{restriction_label}', formats.get('card_default_fmt'))
    _merge_row(worksheet, row, 9, 14, f'NEXT STEP\n{next_step}', formats.get('card_emphasis_fmt'))
    _set_row_height(
        worksheet,
        row,
        max(
            36 if compact else 42,
            _estimate_wrapped_row_height(
                [
                    {'value': f'STATUS\n{status_label}', 'width': _column_span_width(0, 2), 'wrap': True},
                    {'value': f'SPEC\n{spec_status_label}', 'width': _column_span_width(3, 5), 'wrap': True},
                    {'value': f'MODE\n{restriction_label}', 'width': _column_span_width(6, 8), 'wrap': True},
                    {'value': f'NEXT STEP\n{next_step}', 'width': _column_span_width(9, 14), 'wrap': True},
                ],
                minimum=36 if compact else 42,
                line_height=12,
                padding=8,
            ),
        ),
    )
    row += 1

    for label, value in _format_metric_highlights(metric_row, capability_summary_text):
        detail_format = formats.get('detail_note_fmt') if label in {'Use caution', 'Recommended action'} else formats.get('detail_value_fmt')
        _merge_row(worksheet, row, 0, 2, label, formats.get('detail_label_fmt'))
        _merge_row(worksheet, row, 3, 14, value, detail_format)
        _set_row_height(worksheet, row, _estimate_span_height(value, 3, 14, minimum=24, line_height=12, padding=6))
        row += 1
    return row + SECTION_GAP


def _write_descriptive_stats_block(worksheet, row, metric_row):
    formats = _build_formats(worksheet)
    section_row = row
    row = _write_section_title(worksheet, row, 'Descriptive stats', cell_format=formats.get('section_fmt'))
    _set_row_height(worksheet, section_row, 22, formats.get('section_fmt'))

    header_row = row
    header_specs = [
        ('Group', 0, 0),
        ('N', 1, 1),
        ('Mean', 2, 2),
        ('Std', 3, 3),
        ('Median', 4, 4),
        ('IQR', 5, 5),
        ('Min', 6, 6),
        ('Max', 7, 7),
        ('Cp', 8, 8),
        ('Capability', 9, 9),
        ('Cap type', 10, 10),
        ('Capability CI', 11, 11),
        ('Fit model', 12, 12),
        ('Fit quality', 13, 13),
        ('Notes', 14, 14),
    ]
    for label, first_col, last_col in header_specs:
        _merge_row(worksheet, header_row, first_col, last_col, label, formats.get('header_fmt'))
    _set_row_height(worksheet, header_row, 24, formats.get('header_fmt'))
    row += 1

    descriptive_rows = metric_row.get('descriptive_stats', []) or []
    if not descriptive_rows:
        _merge_row(worksheet, row, 0, 14, 'No descriptive statistics available.', formats.get('detail_note_fmt'))
        _set_row_height(worksheet, row, 24, formats.get('detail_note_fmt'))
        return row + 1 + SECTION_GAP

    first_data_row = row
    for entry in descriptive_rows:
        capability_ci_text = _format_descriptive_ci(entry)
        notes_text = _format_descriptive_notes(entry)
        banded = _is_banded_row(row, anchor_row=first_data_row)
        worksheet.write(row, 0, entry.get('group'), _row_format(formats, 'text_left_middle_fmt', 'band_text_left_middle_fmt', banded=banded))
        worksheet.write(row, 1, entry.get('n'), _row_format(formats, 'table_center_fmt', 'band_table_center_fmt', banded=banded))
        worksheet.write(row, 2, entry.get('mean'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 3, entry.get('std'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 4, entry.get('median'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 5, entry.get('iqr'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 6, entry.get('min'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 7, entry.get('max'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 8, entry.get('cp'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 9, entry.get('capability'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 10, entry.get('capability_type'), _row_format(formats, 'table_center_wrap_fmt', 'band_table_center_wrap_fmt', banded=banded))
        worksheet.write(row, 11, capability_ci_text or 'N/A', _row_format(formats, 'detail_note_fmt', 'band_detail_note_fmt', banded=banded))
        worksheet.write(row, 12, _format_descriptive_fit_model(entry), _row_format(formats, 'table_center_wrap_fmt', 'band_table_center_wrap_fmt', banded=banded))
        worksheet.write(row, 13, _format_descriptive_fit_quality(entry), _row_format(formats, 'table_center_wrap_fmt', 'band_table_center_wrap_fmt', banded=banded))
        worksheet.write(row, 14, notes_text, _row_format(formats, 'detail_note_fmt', 'band_detail_note_fmt', banded=banded))
        _set_row_height(
            worksheet,
            row,
            max(
                24,
                _estimate_wrapped_row_height(
                    [
                        {'value': capability_ci_text, 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(11, 16), 'wrap': True},
                        {'value': _format_descriptive_fit_model(entry), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(12, 14), 'wrap': True},
                        {'value': _format_descriptive_fit_quality(entry), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(13, 14), 'wrap': True},
                        {'value': notes_text, 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(14, 18), 'wrap': True},
                    ],
                    minimum=24,
                    line_height=12,
                    padding=6,
                ),
            ),
        )
        row += 1
    return row + SECTION_GAP


def _write_pairwise_comparisons_block(worksheet, row, metric_row):
    formats = _build_formats(worksheet)
    section_row = row
    row = _write_section_title(worksheet, row, 'Pairwise comparisons', cell_format=formats.get('section_fmt'))
    _set_row_height(worksheet, section_row, 22, formats.get('section_fmt'))

    header_row = row
    header_specs = [
        ('Group A', 0, 0),
        ('Group B', 1, 1),
        ('adj p-value', 2, 2),
        ('effect size', 3, 3),
        ('Delta mean', 4, 4),
        ('Status', 5, 5),
        ('Flags', 6, 6),
        ('Test', 7, 7),
        ('Why', 8, 8),
        ('Takeaway', 9, 11),
        ('Action', 12, 13),
        ('Comment', 14, 14),
    ]
    headers = [label for label, _first_col, _last_col in header_specs]
    for label, first_col, last_col in header_specs:
        _merge_row(worksheet, header_row, first_col, last_col, label, formats.get('header_fmt'))
    _set_row_height(worksheet, header_row, 24, formats.get('header_fmt'))
    row += 1

    pairwise_rows = metric_row.get('pairwise_rows', []) or []
    if not pairwise_rows:
        _merge_row(worksheet, row, 0, 14, 'No pairwise comparisons available.', formats.get('detail_note_fmt'))
        _set_row_height(worksheet, row, 24, formats.get('detail_note_fmt'))
        return row + 1 + SECTION_GAP

    first_data_row = row
    for entry in pairwise_rows:
        status_label = _coerce_status_label(entry.get('difference_label') or entry.get('difference')) or 'REVIEW'
        banded = _is_banded_row(row, anchor_row=first_data_row)
        takeaway_text = _format_pairwise_takeaway(entry)
        action_text = _format_pairwise_action(entry)
        test_name = _format_pairwise_test_context(entry)
        rationale_text = _format_pairwise_rationale(entry)
        comment_text = _format_pairwise_comment(entry)
        worksheet.write(row, 0, entry.get('group_a'), _row_format(formats, 'text_left_middle_fmt', 'band_text_left_middle_fmt', banded=banded))
        worksheet.write(row, 1, entry.get('group_b'), _row_format(formats, 'text_left_middle_fmt', 'band_text_left_middle_fmt', banded=banded))
        worksheet.write(row, 2, entry.get('adjusted_p_value'), _row_format(formats, 'pvalue_fmt', 'band_pvalue_fmt', banded=banded))
        worksheet.write(row, 3, entry.get('effect_size'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 4, entry.get('delta_mean'), _row_format(formats, 'num_fmt', 'band_num_fmt', banded=banded))
        worksheet.write(row, 5, status_label, formats.get(_status_format_key(status_label)))
        worksheet.write(row, 6, entry.get('flags'), _row_format(formats, 'table_center_wrap_fmt', 'band_table_center_wrap_fmt', banded=banded))
        worksheet.write(row, 7, test_name, _row_format(formats, 'table_center_wrap_fmt', 'band_table_center_wrap_fmt', banded=banded))
        worksheet.write(row, 8, rationale_text, _row_format(formats, 'detail_note_fmt', 'band_detail_note_fmt', banded=banded))
        _merge_row(worksheet, row, 9, 11, takeaway_text, _row_format(formats, 'detail_value_fmt', 'band_detail_value_fmt', banded=banded))
        _merge_row(worksheet, row, 12, 13, action_text or 'No immediate action note.', _row_format(formats, 'detail_note_fmt', 'band_detail_note_fmt', banded=banded))
        worksheet.write(row, 14, comment_text, _row_format(formats, 'detail_note_fmt', 'band_detail_note_fmt', banded=banded))
        _set_row_height(
            worksheet,
            row,
            max(
                24,
                _estimate_wrapped_row_height(
                    [
                        {'value': entry.get('flags'), 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(6, 14), 'wrap': True},
                        {'value': rationale_text, 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(8, 12), 'wrap': True},
                        {'value': takeaway_text, 'width': _column_span_width(9, 11), 'wrap': True},
                        {'value': action_text, 'width': _column_span_width(12, 13), 'wrap': True},
                        {'value': comment_text, 'width': GROUP_ANALYSIS_COLUMN_WIDTHS.get(14, 18), 'wrap': True},
                    ],
                    minimum=24,
                    line_height=12,
                    padding=6,
                ),
            ),
        )
        row += 1

    _apply_metric_pairwise_formats(
        worksheet,
        {
            'headers': headers,
            'column_lookup': {label: first_col for label, first_col, _last_col in header_specs},
            'first_data_row': first_data_row,
            'last_data_row': row - 1,
        },
    )
    return row + SECTION_GAP


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


def _apply_metric_outline(worksheet, first_row, last_row, *, hidden=False):
    if first_row > last_row:
        return
    for outline_row in range(first_row, last_row + 1):
        _set_row_options(
            worksheet,
            outline_row,
            level=1,
            hidden=hidden,
            collapsed=bool(hidden and outline_row == last_row),
        )


def _write_metric_plots_block(worksheet, row, metric_row, *, plot_assets=None, title='Plots'):
    formats = _build_formats(worksheet)
    plot_eligibility = metric_row.get('plot_eligibility') or {}
    metric_assets = _resolve_metric_plot_assets(plot_assets, metric_row.get('metric'))

    section_row = row
    row = _write_section_title(worksheet, row, title, cell_format=formats.get('section_fmt'))
    _set_row_height(worksheet, section_row, 22, formats.get('section_fmt'))
    for plot_key, plot_label in (('violin', 'Violin'), ('histogram', 'Histogram')):
        eligibility = plot_eligibility.get(plot_key) or {}
        eligible = bool(eligibility.get('eligible'))
        skip_reason = str(eligibility.get('skip_reason') or 'ineligible')
        asset = metric_assets.get(plot_key)

        subsection_row = row
        _merge_row(worksheet, subsection_row, 0, 14, plot_label, formats.get('header_fmt'))
        _set_row_height(worksheet, subsection_row, 22, formats.get('header_fmt'))

        if not eligible:
            message = _get_plot_skip_reason_label(skip_reason)
            _merge_row(worksheet, subsection_row + 1, 0, 2, 'Note', formats.get('detail_label_fmt'))
            _merge_row(worksheet, subsection_row + 1, 3, 14, message, formats.get('detail_note_fmt'))
            _set_row_height(worksheet, subsection_row + 1, _estimate_span_height(message, 3, 14, minimum=24, line_height=12, padding=6))
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
            _merge_row(worksheet, subsection_row + 1, 0, 2, 'Note', formats.get('detail_label_fmt'))
            _merge_row(worksheet, subsection_row + 1, 3, 14, message, formats.get('detail_note_fmt'))
            _set_row_height(worksheet, subsection_row + 1, _estimate_span_height(message, 3, 14, minimum=24, line_height=12, padding=6))
            row += 2

    return row + SECTION_GAP


def _write_metric_section_dashboard(worksheet, row, metric_row, *, plot_assets=None, sheet_state=None):
    formats = _build_formats(worksheet)
    status_label = _resolve_metric_index_status(metric_row)
    compact_metric = _is_compact_metric(metric_row)
    metric_title_row = row
    metric_title = _build_metric_anchor_text(metric_row)
    _merge_row(worksheet, row, 0, 2, status_label, formats.get(_status_format_key(status_label)))
    _merge_row(worksheet, row, 3, METRIC_TITLE_LAST_COL, metric_title, formats.get('metric_fmt'))
    _set_row_height(worksheet, row, max(32, _estimate_metric_title_height(metric_title) + 6), formats.get('metric_fmt'))
    if sheet_state is not None:
        sheet_state['metric_anchor_rows'][str(metric_row.get('metric') or 'Unknown')] = metric_title_row
    row += 1

    capability_summary_text = _format_metric_capability_summary(metric_row)
    snapshot_row = row
    row = _write_metric_snapshot(worksheet, row, metric_row, capability_summary_text, compact=compact_metric)
    detail_start_row = snapshot_row + 1 if compact_metric else row
    row = _write_descriptive_stats_block(worksheet, row, metric_row)
    row = _write_pairwise_comparisons_block(worksheet, row, metric_row)

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
        _merge_row(worksheet, row, 0, 2, 'Takeaway', formats.get('takeaway_label_fmt'))
        _merge_row(worksheet, row, 3, 14, takeaway, formats.get('takeaway_value_fmt'))
        _set_row_height(worksheet, row, _estimate_span_height(takeaway, 3, 14, minimum=24, line_height=12, padding=6))
        row += 1

    _apply_metric_outline(worksheet, detail_start_row, row - 1, hidden=compact_metric)

    row += SECTION_GAP
    return row


def write_group_analysis_plots_sheet(worksheet, payload, *, plot_assets=None):
    """Write the standard-level plot appendix for Group Analysis."""
    sheet_state = {
        'title_rows': [],
        'freeze_panes': None,
    }
    row = 0
    title_row = row
    formats = _build_formats(worksheet)
    row = _write_section_title(worksheet, row, 'Group Analysis Plots', merge_to_col=TITLE_LAST_COL, cell_format=formats.get('title_fmt'))
    sheet_state['title_rows'].append(title_row)
    _set_row_height(worksheet, title_row, 28, formats.get('title_fmt'))

    note = 'Plots live on this separate sheet so the main Group Analysis sheet stays compact and decision-first.'
    _merge_row(worksheet, row, 0, 2, 'Note', formats.get('detail_label_fmt'))
    _merge_row(worksheet, row, 3, 11, note, formats.get('detail_note_fmt'))
    if hasattr(worksheet, 'write_url'):
        worksheet.write_url(
            row,
            12,
            "internal:'Group Analysis'!A1",
            formats.get('hyperlink_fmt'),
            'Back to Group Analysis',
        )
    else:
        worksheet.write(row, 12, 'Back to Group Analysis', formats.get('hyperlink_fmt'))
    _set_row_height(worksheet, row, _estimate_span_height(note, 3, 11, minimum=24, line_height=12, padding=6))
    row += 1 + SECTION_GAP

    normalized_level = str(payload.get('analysis_level') or 'light').strip().lower()
    metric_rows = [dict(metric_row) for metric_row in payload.get('metric_rows', [])]
    for metric_row in metric_rows:
        metric_row['index_status'] = _resolve_metric_index_status(metric_row)
        metric_row['analysis_level'] = normalized_level
    metric_rows = _sorted_metric_rows(metric_rows)

    for metric_row in metric_rows:
        status_label = _resolve_metric_index_status(metric_row)
        _merge_row(worksheet, row, 0, 2, status_label, formats.get(_status_format_key(status_label)))
        _merge_row(worksheet, row, 3, 14, f"Metric: {metric_row.get('metric', 'Unknown')}", formats.get('metric_fmt'))
        _set_row_height(worksheet, row, 30, formats.get('metric_fmt'))
        row += 1

        summary_text = _combine_nonempty_lines(
            _format_metric_stat_signal(metric_row),
            _format_metric_capability_summary(metric_row),
        ) or 'No additional plot context available.'
        _merge_row(worksheet, row, 0, 2, 'Summary', formats.get('detail_label_fmt'))
        _merge_row(worksheet, row, 3, 14, summary_text, formats.get('detail_note_fmt'))
        _set_row_height(worksheet, row, _estimate_span_height(summary_text, 3, 14, minimum=24, line_height=12, padding=6))
        row += 1 + SECTION_GAP

        row = _write_metric_plots_block(worksheet, row, metric_row, plot_assets=plot_assets, title='Plots')
        row += SECTION_GAP

    _apply_group_analysis_layout(_get_workbook(worksheet), worksheet, sheet_state)
    _apply_group_analysis_print_layout(worksheet, title='Group Analysis Plots', last_row=row, repeat_to_row=1)


def write_group_analysis_sheet(worksheet, payload, *, plot_assets=None):
    """Write the canonical user-facing Group Analysis worksheet."""
    sheet_state = {
        'title_rows': [],
        'metric_anchor_rows': {},
        'metric_index_links': [],
        'freeze_panes': None,
    }
    row = 0
    title_row = row
    formats = _build_formats(worksheet)
    row = _write_section_title(worksheet, row, 'Group Analysis', merge_to_col=TITLE_LAST_COL, cell_format=formats.get('title_fmt'))
    sheet_state['title_rows'].append(title_row)
    _set_row_height(worksheet, title_row, 28, formats.get('title_fmt'))

    normalized_level = str(payload.get('analysis_level') or 'light').strip().lower()
    metric_rows = [dict(metric_row) for metric_row in payload.get('metric_rows', [])]
    for metric_row in metric_rows:
        metric_row['index_status'] = _resolve_metric_index_status(metric_row)
        metric_row['analysis_level'] = normalized_level
    metric_rows = _sorted_metric_rows(metric_rows)

    row = _write_dashboard_row(worksheet, row, payload, metric_rows)
    row = _write_top_guidance_row(worksheet, row, payload, metric_rows)
    repeat_to_row = row - 1
    if metric_rows:
        row, _index_bounds = _write_metric_index(worksheet, row, metric_rows, sheet_state=sheet_state)
        repeat_to_row = _index_bounds['header_row']
    else:
        row += SECTION_GAP

    for metric_row in metric_rows:
        metric_with_level = dict(metric_row)
        row = _write_metric_section_dashboard(worksheet, row, metric_with_level, plot_assets=plot_assets, sheet_state=sheet_state)

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
                formats.get('hyperlink_cell_fmt'),
                'Go to metric',
            )
        elif hasattr(worksheet, 'write_url'):
            worksheet.write_url(
                link_row,
                link_col,
                f"internal:'Group Analysis'!A{target_row + 1}",
                formats.get('hyperlink_cell_fmt'),
                'Go to metric',
            )

    _apply_group_analysis_layout(_get_workbook(worksheet), worksheet, sheet_state)
    _apply_group_analysis_print_layout(worksheet, title='Group Analysis', last_row=row, repeat_to_row=repeat_to_row)


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
