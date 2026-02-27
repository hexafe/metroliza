from xlsxwriter.utility import xl_range


def build_sheet_series_range(sheet_name, first_row, last_row, column_index):
    """Build an absolute worksheet range string for xlsxwriter series definitions."""
    return f"={sheet_name}!${xl_range(first_row, column_index, last_row, column_index)}"


def build_measurement_chart_range_specs(*, sheet_name, first_data_row, last_data_row, x_column, y_column, cache=None):
    """Return worksheet range specs shared by chart backend helpers.

    The optional cache avoids rebuilding identical absolute range strings for repeated
    chart fragments in the same export run.
    """
    if cache is not None:
        range_cache = cache.setdefault('range_specs', {})
        cache_key = (sheet_name, first_data_row, last_data_row, x_column, y_column)
        cached = range_cache.get(cache_key)
        if cached is not None:
            return cached

    range_specs = {
        'data_x': build_sheet_series_range(sheet_name, first_data_row, last_data_row, x_column),
        'data_y': build_sheet_series_range(sheet_name, first_data_row, last_data_row, y_column),
        'usl_y': build_sheet_series_range(sheet_name, 0, 1, y_column),
        'lsl_y': build_sheet_series_range(sheet_name, 2, 3, y_column),
        'limit_x': build_sheet_series_range(sheet_name, first_data_row, first_data_row + 1, x_column),
    }
    if cache is not None:
        range_cache[cache_key] = range_specs
    return range_specs


def _build_limit_series_template(*, limit_name):
    return {
        'name': limit_name,
        'line': {'color': 'red', 'width': 1},
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
    cache=None,
):
    """Build stable chart series definitions for measurement and spec-limit overlays."""
    range_specs = build_measurement_chart_range_specs(
        sheet_name=sheet_name,
        first_data_row=first_data_row,
        last_data_row=last_data_row,
        x_column=x_column,
        y_column=y_column,
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
            'categories': range_specs['limit_x'],
            'values': range_specs['usl_y'],
        },
        {
            **lsl_template,
            'categories': range_specs['limit_x'],
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
        cache=cache,
    )


def build_measurement_chart_format_policy(header):
    """Return chart formatting and insertion policy for one measurement block."""
    return {
        'title': {'name': f'{header}', 'name_font': {'size': 10}},
        'y_axis': {'major_gridlines': {'visible': False}},
        'legend': {'position': 'none'},
        'size': {'width': 240, 'height': 160},
    }



def build_horizontal_limit_line_specs(usl, lsl, *, color='#9b1c1c', linestyle='--', linewidth=1.0):
    """Return deterministic axis-line specs for upper/lower specification limits.

    Input contract:
    - ``usl`` and ``lsl`` are numeric y-values for the two horizontal limits.
    - style kwargs are scalar values applied to both lines.
    """
    return [
        {'y': usl, 'color': color, 'linestyle': linestyle, 'linewidth': linewidth},
        {'y': lsl, 'color': color, 'linestyle': linestyle, 'linewidth': linewidth},
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
    for series_spec in series_specs:
        chart.add_series(series_spec)

    chart_policy = build_measurement_chart_format_policy(header)
    chart.set_title(chart_policy['title'])
    chart.set_y_axis(chart_policy['y_axis'])
    chart.set_legend(chart_policy['legend'])
    chart.set_size(chart_policy['size'])
    worksheet.insert_chart(measurement_plan['chart_insert_row'], chart_anchor_col, chart)
