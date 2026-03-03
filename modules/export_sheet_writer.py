from xlsxwriter.utility import xl_col_to_name

from modules.export_summary_utils import resolve_nominal_and_limits
from modules.stats_utils import is_one_sided_geometric_tolerance


def build_spec_limit_anchor_rows(usl, lsl):
    """Deprecated: legacy helper rows are no longer used by chart writers."""
    return []


def build_measurement_stat_formulas(summary_col, stats_col, data_range_y, nom_cell, usl_cell, lsl_cell, nom_value, lsl_value):
    """Build stable worksheet formulas for per-header measurement statistics."""
    usl_formula = f"({summary_col}1 + {summary_col}2)"
    lsl_formula = f"({summary_col}1 + {summary_col}3)"
    sigma_formula = f"({stats_col}4)"
    average_formula = f"({stats_col}2)"

    if is_one_sided_geometric_tolerance(nom_value, lsl_value):
        cp_formula = '="N/A"'
        cpk_formula = f"=ROUND(({usl_formula} - {average_formula})/(3 * {sigma_formula}), 3)"
    else:
        cp_formula = f"=ROUND(({usl_formula} - {lsl_formula})/(6 * {sigma_formula}), 3)"
        cpk_formula = (
            "=ROUND(MIN( "
            f"({usl_formula} - {average_formula})/(3 * {sigma_formula}), "
            f"({average_formula} - {lsl_formula})/(3 * {sigma_formula}) "
            "), 3)"
        )

    nok_high = f'COUNTIF({data_range_y}, ">"&({nom_cell}+{usl_cell}))'
    nok_low = f'COUNTIF({data_range_y}, "<"&({nom_cell}+{lsl_cell}))'
    nok_cell = f"${summary_col}$6"
    sample_size_cell = f"${stats_col}$7"

    return {
        'min': f"=ROUND(MIN({data_range_y}), 3)",
        'avg': f"=ROUND(AVERAGE({data_range_y}), 3)",
        'max': f"=ROUND(MAX({data_range_y}), 3)",
        'std': f"=ROUND(STDEV({data_range_y}), 3)",
        'cp': cp_formula,
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
    stats_label_column = base_col + 2
    stats_value_column = base_col + 3
    usl_column = base_col + 3
    lsl_column = base_col + 4

    return {
        'data_header_row': data_header_row,
        'data_start_row': data_start_row,
        'last_data_row': last_data_row,
        'summary_column': summary_column,
        'stats_label_column': stats_label_column,
        'stats_value_column': stats_value_column,
        'y_column': y_column,
        'usl_column': usl_column,
        'lsl_column': lsl_column,
        'data_range_y': (
            f'{xl_col_to_name(y_column)}{data_start_row + 1}:'
            f'{xl_col_to_name(y_column)}{last_data_row + 1}'
        ),
        'nok_percent_row': 6,
        'chart_insert_row': 12,
    }


def _get_measurement_block_template(*, base_col, sample_size, cache=None):
    """Return cached per-column/per-size fragments for one measurement block.

    Tradeoff: the cache grows with unique ``(base_col, sample_size)`` combinations.
    In normal exports base columns advance by 5 and stay bounded by the header count,
    so this remains small and predictable per export run.
    """
    cache_store = None
    if cache is not None:
        cache_store = cache.setdefault('measurement_block_templates', {})
        cache_key = (base_col, sample_size)
        cached = cache_store.get(cache_key)
        if cached is not None:
            return cached

    measurement_plan = build_measurement_block_plan(base_col=base_col, sample_size=sample_size)
    summary_col_name = xl_col_to_name(measurement_plan['summary_column'])

    template = {
        'measurement_plan': measurement_plan,
        'summary_col_name': summary_col_name,
        'nom_cell': f'${summary_col_name}$1',
        'usl_cell': f'${summary_col_name}$2',
        'lsl_cell': f'${summary_col_name}$3',
        'static_row_labels': ((0, 'NOM'), (1, '+TOL'), (2, '-TOL')),
    }

    if cache_store is not None:
        cache_store[cache_key] = template
    return template


def build_measurement_header_block_plan(header_group, base_col, cache=None):
    """Build a stable per-header worksheet write plan used by export writers."""
    limits = resolve_nominal_and_limits(header_group)
    nom = limits['nom']
    usl = limits['usl']
    lsl = limits['lsl']

    block_template = _get_measurement_block_template(base_col=base_col, sample_size=len(header_group), cache=cache)
    measurement_plan = block_template['measurement_plan']
    summary_col_name = block_template['summary_col_name']

    nom_cell = block_template['nom_cell']
    usl_cell = block_template['usl_cell']
    lsl_cell = block_template['lsl_cell']

    stat_formulas = build_measurement_stat_formulas(
        summary_col=summary_col_name,
        stats_col=xl_col_to_name(measurement_plan['stats_value_column']),
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
        'stat_formulas': stat_formulas,
        'measurement_plan': measurement_plan,
    }


def build_measurement_write_bundle(header, header_group, base_col):
    """Return the write-plan bundle used for one per-header worksheet section."""
    return build_measurement_write_bundle_cached(header, header_group, base_col, cache=None)


def build_measurement_write_bundle_cached(header, header_group, base_col, cache=None):
    """Return the per-header write-plan bundle with optional export-run caching."""
    header_plan = build_measurement_header_block_plan(header_group, base_col, cache=cache)
    measurement_plan = header_plan['measurement_plan']
    block_template = _get_measurement_block_template(base_col=base_col, sample_size=len(header_group), cache=cache)

    static_rows = [
        (row_index, row_label, row_value)
        for (row_index, row_label), row_value in zip(
            block_template['static_row_labels'],
            (header_plan['nom'], header_plan['plus_tol'], header_plan['minus_tol']),
        )
    ]

    row_count = len(header_group)
    usl_vector = [header_plan['usl']] * row_count
    lsl_vector = [header_plan['lsl']] * row_count

    data_columns = [
        (measurement_plan['data_header_row'], base_col, 'Date', header_group['DATE'], None),
        (measurement_plan['data_header_row'], base_col + 1, 'Sample #', header_group['SAMPLE_NUMBER'], None),
        (measurement_plan['data_header_row'], base_col + 2, header, header_group['MEAS'].round(3), 'wrap'),
        (measurement_plan['data_header_row'], base_col + 3, 'USL', usl_vector, None),
        (measurement_plan['data_header_row'], base_col + 4, 'LSL', lsl_vector, None),
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


def build_summary_panel_write_plan(summary_anchors, header):
    """Return deterministic summary-sheet write coordinates for one header panel."""
    header_row, header_col = summary_anchors['header']
    distribution_row, distribution_col = summary_anchors['distribution']
    iqr_row, iqr_col = summary_anchors['iqr']
    histogram_row, histogram_col = summary_anchors['histogram']
    trend_row, trend_col = summary_anchors['trend']

    return {
        'header_cell': {'row': header_row, 'col': header_col, 'value': header},
        'image_slots': {
            'distribution': {'row': distribution_row, 'col': distribution_col},
            'iqr': {'row': iqr_row, 'col': iqr_col},
            'histogram': {'row': histogram_row, 'col': histogram_col},
            'trend': {'row': trend_row, 'col': trend_col},
        },
    }


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

    stat_formulas = header_plan['stat_formulas']
    stats_label_col = measurement_plan['stats_label_column']
    stats_value_col = measurement_plan['stats_value_column']

    worksheet.write(0, base_col, 'NOM')
    worksheet.write(0, base_col + 1, header_plan['nom'])
    worksheet.write(1, base_col, '+TOL')
    worksheet.write(1, base_col + 1, header_plan['plus_tol'])
    worksheet.write(2, base_col, '-TOL')
    worksheet.write(2, base_col + 1, header_plan['minus_tol'])
    worksheet.write(3, base_col, 'USL')
    worksheet.write_formula(3, base_col + 1, f"=({xl_col_to_name(base_col + 1)}1+{xl_col_to_name(base_col + 1)}2)")
    worksheet.write(4, base_col, 'LSL')
    worksheet.write_formula(4, base_col + 1, f"=({xl_col_to_name(base_col + 1)}1+{xl_col_to_name(base_col + 1)}3)")
    worksheet.write(5, base_col, 'NOK number')
    worksheet.write_formula(5, base_col + 1, stat_formulas['nok_total'])
    worksheet.write(6, base_col, 'NOK %')
    worksheet.write_formula(6, base_col + 1, stat_formulas['nok_percent'], formats['percent'])

    worksheet.write(0, stats_label_col, 'MIN')
    worksheet.write_formula(0, stats_value_col, stat_formulas['min'])
    worksheet.write(1, stats_label_col, 'AVG')
    worksheet.write_formula(1, stats_value_col, stat_formulas['avg'])
    worksheet.write(2, stats_label_col, 'MAX')
    worksheet.write_formula(2, stats_value_col, stat_formulas['max'])
    worksheet.write(3, stats_label_col, 'STD')
    worksheet.write_formula(3, stats_value_col, stat_formulas['std'])
    worksheet.write(4, stats_label_col, 'Cp')
    worksheet.write_formula(4, stats_value_col, stat_formulas['cp'])
    worksheet.write(5, stats_label_col, 'Cpk')
    worksheet.write_formula(5, stats_value_col, stat_formulas['cpk'])
    worksheet.write(6, stats_label_col, 'Sample size')
    worksheet.write_formula(6, stats_value_col, stat_formulas['sample_size'])

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
