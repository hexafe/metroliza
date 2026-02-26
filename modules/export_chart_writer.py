from xlsxwriter.utility import xl_range


def build_sheet_series_range(sheet_name, first_row, last_row, column_index):
    """Build an absolute worksheet range string for xlsxwriter series definitions."""
    return f"={sheet_name}!${xl_range(first_row, column_index, last_row, column_index)}"


def build_measurement_chart_range_specs(*, sheet_name, first_data_row, last_data_row, x_column, y_column):
    """Return worksheet range specs shared by chart backend helpers."""
    return {
        'data_x': build_sheet_series_range(sheet_name, first_data_row, last_data_row, x_column),
        'data_y': build_sheet_series_range(sheet_name, first_data_row, last_data_row, y_column),
        'usl_y': build_sheet_series_range(sheet_name, 0, 1, y_column),
        'lsl_y': build_sheet_series_range(sheet_name, 2, 3, y_column),
        'limit_x': build_sheet_series_range(sheet_name, first_data_row, first_data_row + 1, x_column),
    }


def build_measurement_chart_series_specs(
    *,
    header,
    sheet_name,
    first_data_row,
    last_data_row,
    x_column,
    y_column,
):
    """Build stable chart series definitions for measurement and spec-limit overlays."""
    range_specs = build_measurement_chart_range_specs(
        sheet_name=sheet_name,
        first_data_row=first_data_row,
        last_data_row=last_data_row,
        x_column=x_column,
        y_column=y_column,
    )

    return [
        {
            'name': header,
            'categories': range_specs['data_x'],
            'values': range_specs['data_y'],
        },
        {
            'name': 'USL',
            'categories': range_specs['limit_x'],
            'values': range_specs['usl_y'],
            'line': {'color': 'red', 'width': 1},
            'marker': {'type': 'none'},
            'data_labels': {'value': False},
            'show_legend_key': False,
        },
        {
            'name': 'LSL',
            'categories': range_specs['limit_x'],
            'values': range_specs['lsl_y'],
            'line': {'color': 'red', 'width': 1},
            'marker': {'type': 'none'},
            'data_labels': {'value': False},
            'show_legend_key': False,
        },
    ]


def build_measurement_chart_format_policy(header):
    """Return chart formatting and insertion policy for one measurement block."""
    return {
        'title': {'name': f'{header}', 'name_font': {'size': 10}},
        'y_axis': {'major_gridlines': {'visible': False}},
        'legend': {'position': 'none'},
        'size': {'width': 240, 'height': 160},
    }


def insert_measurement_chart(
    workbook,
    worksheet,
    *,
    chart_type,
    header,
    sheet_name,
    measurement_plan,
    chart_anchor_col,
):
    chart = workbook.add_chart({'type': chart_type})
    series_specs = build_measurement_chart_series_specs(
        header=header,
        sheet_name=sheet_name,
        first_data_row=measurement_plan['data_start_row'],
        last_data_row=measurement_plan['last_data_row'],
        x_column=measurement_plan['summary_column'],
        y_column=measurement_plan['y_column'],
    )
    for series_spec in series_specs:
        chart.add_series(series_spec)

    chart_policy = build_measurement_chart_format_policy(header)
    chart.set_title(chart_policy['title'])
    chart.set_y_axis(chart_policy['y_axis'])
    chart.set_legend(chart_policy['legend'])
    chart.set_size(chart_policy['size'])
    worksheet.insert_chart(measurement_plan['chart_insert_row'], chart_anchor_col, chart)
