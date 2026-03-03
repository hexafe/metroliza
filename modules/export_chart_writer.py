from xlsxwriter.utility import xl_range, xl_rowcol_to_cell

from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE


CHART_ANCHOR_ROW = 7  # Excel row 8, zero-based for xlsxwriter.
CHART_WIDTH_CM = 11.09
CHART_HEIGHT_CM = 6.83
CM_PER_INCH = 2.54
PIXELS_PER_INCH = 96
HELPER_START_COLUMN = 16381  # XFB..XFD, outside user-visible measurement blocks.


def _cm_to_pixels(cm_value):
    """Convert centimeters to xlsxwriter chart pixel units."""
    return round((cm_value / CM_PER_INCH) * PIXELS_PER_INCH)


def _build_chart_size_policy():
    return {
        'width': _cm_to_pixels(CHART_WIDTH_CM),
        'height': _cm_to_pixels(CHART_HEIGHT_CM),
    }


def _write_limit_series_helper_range(worksheet, measurement_plan, chart_anchor_col):
    """Write a 2-row helper range used to render horizontal USL/LSL lines."""
    chart_index = chart_anchor_col // 5
    helper_first_row = chart_index * 2
    helper_last_row = helper_first_row + 1

    first_data_row = measurement_plan['data_start_row']
    last_data_row = measurement_plan['last_data_row']
    x_column = measurement_plan['summary_column']
    usl_column = measurement_plan['usl_column']
    lsl_column = measurement_plan['lsl_column']

    first_x_ref = xl_rowcol_to_cell(first_data_row, x_column, row_abs=True, col_abs=True)
    last_x_ref = xl_rowcol_to_cell(last_data_row, x_column, row_abs=True, col_abs=True)
    first_usl_ref = xl_rowcol_to_cell(first_data_row, usl_column, row_abs=True, col_abs=True)
    last_usl_ref = xl_rowcol_to_cell(last_data_row, usl_column, row_abs=True, col_abs=True)
    first_lsl_ref = xl_rowcol_to_cell(first_data_row, lsl_column, row_abs=True, col_abs=True)
    last_lsl_ref = xl_rowcol_to_cell(last_data_row, lsl_column, row_abs=True, col_abs=True)

    worksheet.write_formula(helper_first_row, HELPER_START_COLUMN, f'={first_x_ref}')
    worksheet.write_formula(helper_last_row, HELPER_START_COLUMN, f'={last_x_ref}')
    worksheet.write_formula(helper_first_row, HELPER_START_COLUMN + 1, f'={first_usl_ref}')
    worksheet.write_formula(helper_last_row, HELPER_START_COLUMN + 1, f'={last_usl_ref}')
    worksheet.write_formula(helper_first_row, HELPER_START_COLUMN + 2, f'={first_lsl_ref}')
    worksheet.write_formula(helper_last_row, HELPER_START_COLUMN + 2, f'={last_lsl_ref}')
    worksheet.set_column(HELPER_START_COLUMN, HELPER_START_COLUMN + 2, None, None, {'hidden': True})

    return {
        'usl_x': build_sheet_series_range(
            worksheet.name,
            helper_first_row,
            helper_last_row,
            HELPER_START_COLUMN,
        ),
        'usl_y': build_sheet_series_range(
            worksheet.name,
            helper_first_row,
            helper_last_row,
            HELPER_START_COLUMN + 1,
        ),
        'lsl_x': build_sheet_series_range(
            worksheet.name,
            helper_first_row,
            helper_last_row,
            HELPER_START_COLUMN,
        ),
        'lsl_y': build_sheet_series_range(
            worksheet.name,
            helper_first_row,
            helper_last_row,
            HELPER_START_COLUMN + 2,
        ),
    }


def build_sheet_series_range(sheet_name, first_row, last_row, column_index):
    """Build an absolute worksheet range string for xlsxwriter series definitions."""
    return f"={sheet_name}!${xl_range(first_row, column_index, last_row, column_index)}"


def build_measurement_chart_range_specs(*, sheet_name, first_data_row, last_data_row, x_column, y_column, usl_column=None, lsl_column=None, cache=None):
    """Return worksheet range specs shared by chart backend helpers.

    The optional cache avoids rebuilding identical absolute range strings for repeated
    chart fragments in the same export run.
    """
    resolved_usl_column = y_column if usl_column is None else usl_column
    resolved_lsl_column = y_column if lsl_column is None else lsl_column

    if cache is not None:
        range_cache = cache.setdefault('range_specs', {})
        cache_key = (sheet_name, first_data_row, last_data_row, x_column, y_column, resolved_usl_column, resolved_lsl_column)
        cached = range_cache.get(cache_key)
        if cached is not None:
            return cached

    range_specs = {
        'data_x': build_sheet_series_range(sheet_name, first_data_row, last_data_row, x_column),
        'data_y': build_sheet_series_range(sheet_name, first_data_row, last_data_row, y_column),
        # USL/LSL vectors are stored on data rows with values at first/last index
        # and blanks in between, so charts can anchor to explicit columns.
        'usl_x': build_sheet_series_range(sheet_name, first_data_row, last_data_row, x_column),
        'usl_y': build_sheet_series_range(sheet_name, first_data_row, last_data_row, resolved_usl_column),
        'lsl_x': build_sheet_series_range(sheet_name, first_data_row, last_data_row, x_column),
        'lsl_y': build_sheet_series_range(sheet_name, first_data_row, last_data_row, resolved_lsl_column),
    }
    if cache is not None:
        range_cache[cache_key] = range_specs
    return range_specs


def _build_limit_series_template(*, limit_name):
    return {
        'name': limit_name,
        'line': {
            'color': '#c0504b',
            'width': 2,
            # xlsxwriter expresses alpha as transparency; 60% opacity == 40% transparency.
            'transparency': 40,
        },
        'marker': {'type': 'none'},
        'data_labels': {'value': False},
        'show_legend_key': False,
    }

def build_measurement_chart_series_specs(
    *,
    header,
    sheet_name,
    first_data_row,
    last_data_row,
    x_column,
    y_column,
    usl_column=None,
    lsl_column=None,
    cache=None,
):
    """Build stable chart series definitions for measurement and spec-limit overlays."""
    range_specs = build_measurement_chart_range_specs(
        sheet_name=sheet_name,
        first_data_row=first_data_row,
        last_data_row=last_data_row,
        x_column=x_column,
        y_column=y_column,
        usl_column=usl_column,
        lsl_column=lsl_column,
        cache=cache,
    )

    if cache is not None:
        limit_template_cache = cache.setdefault('limit_series_templates', {})
        usl_template = limit_template_cache.setdefault('USL', _build_limit_series_template(limit_name='USL'))
        lsl_template = limit_template_cache.setdefault('LSL', _build_limit_series_template(limit_name='LSL'))
    else:
        usl_template = _build_limit_series_template(limit_name='USL')
        lsl_template = _build_limit_series_template(limit_name='LSL')

    return [
        {
            'name': header,
            'categories': range_specs['data_x'],
            'values': range_specs['data_y'],
        },
        {
            **usl_template,
            'categories': range_specs['usl_x'],
            'values': range_specs['usl_y'],
        },
        {
            **lsl_template,
            'categories': range_specs['lsl_x'],
            'values': range_specs['lsl_y'],
        },
    ]


def build_measurement_chart_series_specs_from_plan(*, header, sheet_name, measurement_plan, cache=None):
    """Build chart series specs from the stable measurement-plan contract."""
    return build_measurement_chart_series_specs(
        header=header,
        sheet_name=sheet_name,
        first_data_row=measurement_plan['data_start_row'],
        last_data_row=measurement_plan['last_data_row'],
        x_column=measurement_plan['summary_column'],
        y_column=measurement_plan['y_column'],
        usl_column=measurement_plan['usl_column'],
        lsl_column=measurement_plan['lsl_column'],
        cache=cache,
    )


def build_measurement_chart_format_policy(header):
    """Return chart formatting and insertion policy for one measurement block."""
    return {
        'title': {'name': f'{header}', 'name_font': {'size': 10}},
        'y_axis': {'major_gridlines': {'visible': False}},
        'legend': {'position': 'none'},
        'size': _build_chart_size_policy(),
    }



def build_horizontal_limit_line_specs(usl, lsl, *, color=None, linestyle='--', linewidth=1.0):
    """Return deterministic axis-line specs for upper/lower specification limits.

    Input contract:
    - ``usl`` and ``lsl`` are numeric y-values for the two horizontal limits.
    - style kwargs are scalar values applied to both lines.
    """
    line_color = color or SUMMARY_PLOT_PALETTE['spec_limit']
    return [
        {'y': usl, 'color': line_color, 'linestyle': linestyle, 'linewidth': linewidth},
        {'y': lsl, 'color': line_color, 'linestyle': linestyle, 'linewidth': linewidth},
    ]

def insert_measurement_chart(
    workbook,
    worksheet,
    *,
    chart_type,
    header,
    sheet_name,
    measurement_plan,
    chart_anchor_col,
    cache=None,
):
    chart = workbook.add_chart({'type': chart_type})
    series_specs = build_measurement_chart_series_specs_from_plan(
        header=header,
        sheet_name=sheet_name,
        measurement_plan=measurement_plan,
        cache=cache,
    )
    helper_range_specs = _write_limit_series_helper_range(worksheet, measurement_plan, chart_anchor_col)
    series_specs[1]['categories'] = helper_range_specs['usl_x']
    series_specs[1]['values'] = helper_range_specs['usl_y']
    series_specs[2]['categories'] = helper_range_specs['lsl_x']
    series_specs[2]['values'] = helper_range_specs['lsl_y']
    for series_spec in series_specs:
        chart.add_series(series_spec)

    chart_policy = build_measurement_chart_format_policy(header)
    chart.set_title(chart_policy['title'])
    chart.set_y_axis(chart_policy['y_axis'])
    chart.set_legend(chart_policy['legend'])
    chart.set_size(chart_policy['size'])
    worksheet.insert_chart(CHART_ANCHOR_ROW, chart_anchor_col, chart)
