"""Pure helpers for chart payload shaping used by export orchestration."""

import math


LOW_N_WARNING_THRESHOLD = 25
LOW_N_SEVERE_THRESHOLD = 10


def _is_numeric(value):
    return isinstance(value, (int, float))


def _is_zeroish(value, tolerance=1e-12):
    return _is_numeric(value) and abs(float(value)) <= tolerance


def _resolve_spec_type(summary_stats):
    explicit_spec_type = str(summary_stats.get('spec_type') or '').strip().lower()
    if explicit_spec_type in {'one_sided_upper', 'one-sided upper', 'upper'}:
        return 'one-sided upper'
    if explicit_spec_type in {'one_sided_lower', 'one-sided lower', 'lower'}:
        return 'one-sided lower'

    nom_value = summary_stats.get('nom')
    usl_value = summary_stats.get('usl')
    lsl_value = summary_stats.get('lsl')
    cp_value = summary_stats.get('cp')

    if isinstance(cp_value, str):
        if _is_zeroish(nom_value) and _is_zeroish(lsl_value) and _is_numeric(usl_value) and float(usl_value) > 0:
            return 'one-sided upper'
        if _is_zeroish(nom_value) and _is_zeroish(usl_value) and _is_numeric(lsl_value) and float(lsl_value) < 0:
            return 'one-sided lower'
        if _is_numeric(usl_value) and not _is_numeric(lsl_value):
            return 'one-sided upper'
        if _is_numeric(lsl_value) and not _is_numeric(usl_value):
            return 'one-sided lower'
        if _is_numeric(usl_value):
            return 'one-sided upper'

    return 'two-sided'


def _resolve_sample_confidence(sample_size):
    n = max(0, int(sample_size or 0))
    if n <= 0:
        return {
            'sample_size': n,
            'is_low_n': False,
            'severity': 'none',
            'badge': '',
            'rationale': '',
        }
    if n < LOW_N_SEVERE_THRESHOLD:
        return {
            'sample_size': n,
            'is_low_n': True,
            'severity': 'severe',
            'badge': '⚠⚠',
            'rationale': 'n<10: capability and fit estimates are highly unstable.',
        }
    if n < LOW_N_WARNING_THRESHOLD:
        return {
            'sample_size': n,
            'is_low_n': True,
            'severity': 'warning',
            'badge': '⚠',
            'rationale': 'n<25: capability and fit estimates have broad uncertainty.',
        }
    return {
        'sample_size': n,
        'is_low_n': False,
        'severity': 'none',
        'badge': '',
        'rationale': '',
    }


def _approx_uncertainty_band(value, sample_size):
    if isinstance(value, str):
        return 'N/A'
    n = max(1, int(sample_size or 1))
    baseline = abs(float(value)) if float(value) != 0 else 1.0
    margin = 1.96 * baseline / math.sqrt(n)
    return f"±{margin:.2f} (approx 95% band)"


def build_histogram_table_data(summary_stats):
    """Build stable, display-ready statistics rows and row metadata for histograms."""

    def _rounded_or_text(value, digits):
        return value if isinstance(value, str) else round(value, digits)

    sample_size = summary_stats.get('sample_size', 0)
    sample_confidence = _resolve_sample_confidence(sample_size)
    spec_type = _resolve_spec_type(summary_stats)
    cpk_label = 'Cpk'
    cpk_value = summary_stats.get('cpk')

    if spec_type == 'one-sided upper':
        sigma_value = summary_stats.get('sigma')
        average_value = summary_stats.get('average')
        usl_value = summary_stats.get('usl')
        cpk_label = 'Cpu'
        if all(_is_numeric(item) for item in (sigma_value, average_value, usl_value)) and sigma_value > 0:
            cpk_value = (usl_value - average_value) / (3 * sigma_value)
    elif spec_type == 'one-sided lower':
        sigma_value = summary_stats.get('sigma')
        average_value = summary_stats.get('average')
        lsl_value = summary_stats.get('lsl')
        cpk_label = 'Cpl'
        if all(_is_numeric(item) for item in (sigma_value, average_value, lsl_value)) and sigma_value > 0:
            cpk_value = (average_value - lsl_value) / (3 * sigma_value)

    cp_display_value = _rounded_or_text(summary_stats['cp'], 2)
    cpk_display_value = _rounded_or_text(cpk_value, 2)

    cp_label = 'Cp'
    if spec_type != 'two-sided':
        cp_label = 'Cp (not defined for one-sided) ⓘ'
        cp_display_value = 'N/A'

    resolved_cpk_label = cpk_label
    if sample_confidence['is_low_n'] and sample_confidence['severity'] == 'severe':
        if not isinstance(cp_display_value, str):
            cp_display_value = f"{cp_display_value:.2f} (Low-confidence estimate)"
        if not isinstance(cpk_display_value, str):
            cpk_display_value = f"{cpk_display_value:.2f} (Low-confidence estimate)"

    table_rows = [
        ('Min', round(summary_stats['minimum'], 3)),
        ('Max', round(summary_stats['maximum'], 3)),
        ('Mean', round(summary_stats['average'], 3)),
        ('Median', round(summary_stats['median'], 3)),
        ('Std Dev', round(summary_stats['sigma'], 3)),
        ('Spec type', spec_type),
        (cp_label, cp_display_value),
        (resolved_cpk_label, cpk_display_value),
    ]
    if sample_confidence['is_low_n']:
        uncertainty_rows = []
        if spec_type == 'two-sided':
            uncertainty_rows.append((f"{cp_label} uncertainty", _approx_uncertainty_band(summary_stats['cp'], sample_size)))
        uncertainty_rows.append((f"{resolved_cpk_label} uncertainty", _approx_uncertainty_band(cpk_value, sample_size)))
        table_rows.extend([
            (f"Confidence {sample_confidence['badge']}", f"Low-confidence estimate (n={sample_confidence['sample_size']})"),
        ])
        table_rows.extend(uncertainty_rows)

    table_rows.extend([
        ('Samples', round(summary_stats['sample_size'], 1)),
        ('NOK', round(summary_stats['nok_count'], 1)),
        ('NOK %', f"{summary_stats['nok_pct'] * 100:.2f}%"),
    ])

    return {
        'rows': table_rows,
        'summary_metrics': {
            'observed_nok_count': summary_stats.get('observed_nok_count', summary_stats.get('nok_count')),
            'observed_nok_pct': summary_stats.get('observed_nok_pct', summary_stats.get('nok_pct')),
            'estimated_nok_pct': summary_stats.get('estimated_nok_pct'),
            'estimated_nok_ppm': summary_stats.get('estimated_nok_ppm'),
            'estimated_yield_pct': summary_stats.get('estimated_yield_pct'),
        },
        'sample_confidence': sample_confidence,
        'capability_rows': {
            'Cp': {
                'label': cp_label,
                'display_value': cp_display_value,
                'classification_value': 'N/A' if spec_type != 'two-sided' else _rounded_or_text(summary_stats['cp'], 2),
            },
            'Cpk': {
                'label': resolved_cpk_label,
                'display_value': cpk_display_value,
                'classification_value': _rounded_or_text(cpk_value, 2),
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
