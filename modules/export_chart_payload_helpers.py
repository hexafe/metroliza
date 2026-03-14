"""Pure helpers for chart payload shaping used by export orchestration."""


def build_histogram_table_data(summary_stats):
    """Build stable, display-ready statistics rows and row metadata for histograms."""

    def _rounded_or_text(value, digits):
        return value if isinstance(value, str) else round(value, digits)

    cp_value = summary_stats.get('cp')
    cpk_label = 'Cpk'
    cpk_value = summary_stats.get('cpk')
    if isinstance(cp_value, str):
        sigma_value = summary_stats.get('sigma')
        average_value = summary_stats.get('average')
        usl_value = summary_stats.get('usl')
        if all(isinstance(item, (float, int)) for item in (sigma_value, average_value, usl_value)) and sigma_value > 0:
            cpk_label = 'Cpk+'
            cpk_value = (usl_value - average_value) / (3 * sigma_value)

    cp_display_value = _rounded_or_text(summary_stats['cp'], 2)
    cpk_display_value = _rounded_or_text(cpk_value, 2)

    table_rows = [
        ('Min', round(summary_stats['minimum'], 3)),
        ('Max', round(summary_stats['maximum'], 3)),
        ('Mean', round(summary_stats['average'], 3)),
        ('Median', round(summary_stats['median'], 3)),
        ('Std Dev', round(summary_stats['sigma'], 3)),
        ('Cp', cp_display_value),
        (cpk_label, cpk_display_value),
        ('Samples', round(summary_stats['sample_size'], 1)),
        ('NOK', round(summary_stats['nok_count'], 1)),
        ('NOK %', f"{summary_stats['nok_pct'] * 100:.2f}%"),
    ]

    return {
        'rows': table_rows,
        'capability_rows': {
            'Cp': {
                'label': 'Cp',
                'display_value': cp_display_value,
                'classification_value': cp_display_value,
            },
            'Cpk': {
                'label': cpk_label,
                'display_value': cpk_display_value,
                'classification_value': cpk_display_value,
            },
        },
    }


def build_histogram_table_render_data(table_data, *, three_column=False):
    """Build render rows for histogram summary tables."""

    if three_column:
        return [[label, '', value] for label, value in table_data]

    return list(table_data)


def compute_scaled_y_limits(current_limits, scale_factor):
    """Return y-axis limits expanded by a symmetric scale factor."""
    y_min, y_max = current_limits
    data_range = y_max - y_min
    padding = scale_factor * data_range / 2
    return y_min - padding, y_max + padding


def resolve_summary_annotation_strategy(*, x_point_count):
    """Resolve a low-overhead annotation strategy based on x-axis point density."""
    safe_points = max(0, int(x_point_count))
    if safe_points >= 60:
        return {
            'label_mode': 'sparse',
            'annotation_mode': 'static_compact',
            'show_violin_legend': False,
        }
    if safe_points >= 24:
        return {
            'label_mode': 'adaptive',
            'annotation_mode': 'static_compact',
            'show_violin_legend': True,
        }
    return {
        'label_mode': 'adaptive',
        'annotation_mode': 'dynamic',
        'show_violin_legend': True,
    }
