from xlsxwriter.utility import xl_col_to_name

from modules.export_summary_utils import resolve_nominal_and_limits


def build_spec_limit_anchor_rows(usl, lsl):
    """Return worksheet helper rows for USL/LSL anchor points."""
    return [
        ('USL_MAX', usl),
        ('USL_MIN', usl),
        ('LSL_MAX', lsl),
        ('LSL_MIN', lsl),
    ]


def build_measurement_stat_formulas(summary_col, data_range_y, nom_cell, usl_cell, lsl_cell, nom_value, lsl_value):
    """Build stable worksheet formulas for per-header measurement statistics."""
    usl_formula = f"({summary_col}1 + {summary_col}2)"
    lsl_formula = f"({summary_col}1 + {summary_col}3)"
    sigma_formula = f"({summary_col}7)"
    average_formula = f"({summary_col}5)"

    if nom_value == 0 and lsl_value == 0:
        cpk_formula = f"=ROUND(({usl_formula} - {average_formula})/(3 * {sigma_formula}), 3)"
    else:
        cpk_formula = (
            "=ROUND(MIN( "
            f"({usl_formula} - {average_formula})/(3 * {sigma_formula}), "
            f"({average_formula} - {lsl_formula})/(3 * {sigma_formula}) "
            "), 3)"
        )

    nok_high = f'COUNTIF({data_range_y}, ">"&({nom_cell}+{usl_cell}))'
    nok_low = f'COUNTIF({data_range_y}, "<"&({nom_cell}+{lsl_cell}))'
    nok_cell = f"${summary_col}$10"
    sample_size_cell = f"${summary_col}$12"

    return {
        'min': f"=ROUND(MIN({data_range_y}), 3)",
        'avg': f"=ROUND(AVERAGE({data_range_y}), 3)",
        'max': f"=ROUND(MAX({data_range_y}), 3)",
        'std': f"=ROUND(STDEV({data_range_y}), 3)",
        'cp': f"=ROUND(({usl_formula} - {lsl_formula})/(6 * {sigma_formula}), 3)",
        'cpk': cpk_formula,
        'nok_total': f'={nok_high}+{nok_low}',
        'nok_percent': f"=ROUND(({nok_cell}/{sample_size_cell})*100%, 3)",
        'sample_size': f"=COUNT({data_range_y})",
    }


def build_measurement_stat_row_specs(stat_formulas):
    """Return ordered worksheet row specs for measurement statistics."""
    return [
        ('MIN', stat_formulas['min'], None),
        ('AVG', stat_formulas['avg'], None),
        ('MAX', stat_formulas['max'], None),
        ('STD', stat_formulas['std'], None),
        ('Cp', stat_formulas['cp'], None),
        ('Cpk', stat_formulas['cpk'], None),
        ('NOK number', stat_formulas['nok_total'], None),
        ('NOK %', stat_formulas['nok_percent'], 'percent'),
        ('Sample size', stat_formulas['sample_size'], None),
    ]


def build_measurement_block_plan(*, base_col, sample_size):
    """Return worksheet/chart coordinate plan for one measurement header block."""
    if sample_size < 1:
        raise ValueError('sample_size must be >= 1')

    data_header_row = 20
    data_start_row = data_header_row + 1
    last_data_row = data_start_row + sample_size - 1
    y_column = base_col + 2
    summary_column = base_col + 1

    return {
        'data_header_row': data_header_row,
        'data_start_row': data_start_row,
        'last_data_row': last_data_row,
        'summary_column': summary_column,
        'y_column': y_column,
        'data_range_y': (
            f'{xl_col_to_name(y_column)}{data_start_row + 1}:'
            f'{xl_col_to_name(y_column)}{last_data_row + 1}'
        ),
        'nok_percent_row': 10,
        'chart_insert_row': 12,
    }


def build_measurement_header_block_plan(header_group, base_col):
    """Build a stable per-header worksheet write plan used by export writers."""
    limits = resolve_nominal_and_limits(header_group)
    nom = limits['nom']
    usl = limits['usl']
    lsl = limits['lsl']

    measurement_plan = build_measurement_block_plan(base_col=base_col, sample_size=len(header_group))
    summary_col_name = xl_col_to_name(measurement_plan['summary_column'])

    nom_cell = f'${summary_col_name}$1'
    usl_cell = f'${summary_col_name}$2'
    lsl_cell = f'${summary_col_name}$3'

    stat_formulas = build_measurement_stat_formulas(
        summary_col=summary_col_name,
        data_range_y=measurement_plan['data_range_y'],
        nom_cell=nom_cell,
        usl_cell=usl_cell,
        lsl_cell=lsl_cell,
        nom_value=nom,
        lsl_value=lsl,
    )

    plus_tol = round(usl - nom, 3)
    minus_tol = round(lsl - nom, 3)

    return {
        'nom': nom,
        'plus_tol': plus_tol,
        'minus_tol': minus_tol,
        'usl': usl,
        'lsl': lsl,
        'first_data_row': measurement_plan['data_start_row'],
        'last_data_row': measurement_plan['last_data_row'],
        'summary_column': measurement_plan['summary_column'],
        'y_column': measurement_plan['y_column'],
        'nom_cell': nom_cell,
        'usl_cell': usl_cell,
        'lsl_cell': lsl_cell,
        'stat_rows': build_measurement_stat_row_specs(stat_formulas),
        'spec_limit_rows': build_spec_limit_anchor_rows(usl, lsl),
        'measurement_plan': measurement_plan,
    }


def build_measurement_write_bundle(header, header_group, base_col):
    """Return the write-plan bundle used for one per-header worksheet section."""
    header_plan = build_measurement_header_block_plan(header_group, base_col)
    measurement_plan = header_plan['measurement_plan']

    static_rows = [
        (0, 'NOM', header_plan['nom']),
        (1, '+TOL', header_plan['plus_tol']),
        (2, '-TOL', header_plan['minus_tol']),
    ]

    data_columns = [
        (measurement_plan['data_header_row'], base_col, 'Date', header_group['DATE'], None),
        (measurement_plan['data_header_row'], base_col + 1, 'Sample #', header_group['SAMPLE_NUMBER'], None),
        (measurement_plan['data_header_row'], base_col + 2, header, header_group['MEAS'].round(3), 'wrap'),
    ]

    return {
        'header_plan': header_plan,
        'measurement_plan': measurement_plan,
        'static_rows': static_rows,
        'data_columns': data_columns,
    }


def build_measurement_summary_row_layout(*, base_col, stat_rows, start_row=3):
    """Return stable summary-row coordinates/style for one measurement block."""
    return [
        {
            'row': row_offset,
            'label_col': base_col,
            'value_col': base_col + 1,
            'label': label,
            'formula': formula,
            'style': cell_style,
        }
        for row_offset, (label, formula, cell_style) in enumerate(stat_rows, start=start_row)
    ]


def write_measurement_summary_rows(worksheet, summary_rows, formats):
    """Write summary row labels and formulas using the provided layout specs."""
    for row_spec in summary_rows:
        worksheet.write(row_spec['row'], row_spec['label_col'], row_spec['label'])
        if row_spec['style'] == 'percent':
            worksheet.write_formula(
                row_spec['row'],
                row_spec['value_col'],
                row_spec['formula'],
                formats['percent'],
            )
        else:
            worksheet.write_formula(row_spec['row'], row_spec['value_col'], row_spec['formula'])


def create_measurement_formats(workbook):
    return {
        'default': workbook.add_format({'align': 'center', 'valign': 'vcenter'}),
        'border': workbook.add_format({'align': 'center', 'valign': 'vcenter', 'right': 1}),
        'wrap': workbook.add_format({'align': 'center', 'valign': 'vcenter', 'text_wrap': True}),
        'percent': workbook.add_format({'align': 'center', 'valign': 'vcenter', 'num_format': '0.00%'}),
        'red': workbook.add_format({'bg_color': 'red', 'font_color': 'white', 'align': 'center', 'valign': 'vcenter', 'right': 1}),
    }


def write_measurement_block(worksheet, write_bundle, formats, *, base_col):
    header_plan = write_bundle['header_plan']
    measurement_plan = write_bundle['measurement_plan']

    for row_index, row_label, row_value in write_bundle['static_rows']:
        worksheet.write(row_index, base_col, row_label)
        worksheet.write(row_index, base_col + 1, row_value)

    worksheet.write(0, base_col + 2, header_plan['usl'])
    worksheet.write(1, base_col + 2, header_plan['usl'])
    worksheet.write(2, base_col + 2, header_plan['lsl'])
    worksheet.write(3, base_col + 2, header_plan['lsl'])

    summary_rows = build_measurement_summary_row_layout(base_col=base_col, stat_rows=header_plan['stat_rows'])
    write_measurement_summary_rows(worksheet, summary_rows, formats)

    for data_header_row, data_col, data_label, data_values, data_style in write_bundle['data_columns']:
        if data_style == 'wrap':
            worksheet.write(data_header_row, data_col, data_label, formats['wrap'])
        else:
            worksheet.write(data_header_row, data_col, data_label)
        worksheet.write_column(measurement_plan['data_start_row'], data_col, data_values)

    nom_cell = header_plan['nom_cell']
    usl_cell = header_plan['usl_cell']
    lsl_cell = header_plan['lsl_cell']

    worksheet.conditional_format(
        measurement_plan['data_start_row'],
        measurement_plan['y_column'],
        measurement_plan['last_data_row'],
        measurement_plan['y_column'],
        {'type': 'cell', 'criteria': '>', 'value': f'({nom_cell}+{usl_cell})', 'format': formats['red']},
    )
    worksheet.conditional_format(
        measurement_plan['data_start_row'],
        measurement_plan['y_column'],
        measurement_plan['last_data_row'],
        measurement_plan['y_column'],
        {'type': 'cell', 'criteria': '<', 'value': f'({nom_cell}+{lsl_cell})', 'format': formats['red']},
    )
    worksheet.conditional_format(
        measurement_plan['nok_percent_row'],
        measurement_plan['summary_column'],
        measurement_plan['nok_percent_row'],
        measurement_plan['summary_column'],
        {'type': 'cell', 'criteria': '>', 'value': '0', 'format': formats['red']},
    )

    return measurement_plan
