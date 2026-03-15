"""Pure helpers for chart payload shaping used by export orchestration."""

from modules.stats_utils import compute_capability_confidence_intervals
from modules.stats_number_formatting import (
    format_capability_index,
    format_measurement_value,
    format_percent_from_ratio,
)


LOW_N_WARNING_THRESHOLD = 25
LOW_N_SEVERE_THRESHOLD = 10
NOK_DISCREPANCY_WARNING_ABS_THRESHOLD = 0.02


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
            'badge': '!!',
            'rationale': 'n<10: capability and fit estimates are highly unstable.',
        }
    if n < LOW_N_WARNING_THRESHOLD:
        return {
            'sample_size': n,
            'is_low_n': True,
            'severity': 'warning',
            'badge': '!',
            'rationale': 'n<25: capability and fit estimates have broad uncertainty.',
        }
    return {
        'sample_size': n,
        'is_low_n': False,
        'severity': 'none',
        'badge': '',
        'rationale': '',
    }


def _compute_nok_discrepancy_metrics(observed_nok_pct, estimated_nok_pct):
    observed = float(observed_nok_pct) if _is_numeric(observed_nok_pct) else None
    estimated = float(estimated_nok_pct) if _is_numeric(estimated_nok_pct) else None
    if observed is None or estimated is None:
        return {
            'abs_diff': None,
            'abs_diff_pp': None,
            'rel_diff': None,
            'threshold_abs': NOK_DISCREPANCY_WARNING_ABS_THRESHOLD,
            'is_warning': False,
        }

    abs_diff = abs(observed - estimated)
    if abs(observed) <= 1e-12:
        rel_diff = 0.0 if abs_diff <= 1e-12 else None
    else:
        rel_diff = abs_diff / abs(observed)

    return {
        'abs_diff': abs_diff,
        'abs_diff_pp': abs_diff * 100.0,
        'rel_diff': rel_diff,
        'threshold_abs': NOK_DISCREPANCY_WARNING_ABS_THRESHOLD,
        'is_warning': abs_diff > NOK_DISCREPANCY_WARNING_ABS_THRESHOLD,
    }


def _format_ci_bounds(interval):
    if not isinstance(interval, dict):
        return 'N/A'
    lower = interval.get('lower')
    upper = interval.get('upper')
    if not _is_numeric(lower) or not _is_numeric(upper):
        return 'N/A'
    return f"[{lower:.2f}, {upper:.2f}]"


def _append_ci(display_value, interval):
    if display_value == 'N/A':
        return 'N/A'
    ci_text = _format_ci_bounds(interval)
    if ci_text == 'N/A':
        return display_value
    return f'{display_value} {ci_text}'


def build_histogram_table_data(summary_stats):
    """Build stable, display-ready statistics rows and row metadata for histograms."""

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

    cp_display_value = format_capability_index(summary_stats['cp'])
    cpk_display_value = format_capability_index(cpk_value)
    include_capability_ci = bool(summary_stats.get('include_capability_ci', True))
    capability_ci = summary_stats.get('capability_ci')
    if not isinstance(capability_ci, dict):
        capability_ci = compute_capability_confidence_intervals(
            sample_size=sample_size,
            cp=summary_stats.get('cp') if spec_type == 'two-sided' else None,
            cpk=cpk_value,
        )
    cp_ci = capability_ci.get('cp') if isinstance(capability_ci, dict) else None
    cpk_ci = capability_ci.get('cpk') if isinstance(capability_ci, dict) else None

    cp_label = 'Cp'
    include_cp_row = spec_type == 'two-sided'

    resolved_cpk_label = cpk_label
    if include_capability_ci and include_cp_row:
        cp_display_value = _append_ci(cp_display_value, cp_ci)
    if include_capability_ci:
        cpk_display_value = _append_ci(cpk_display_value, cpk_ci)

    if sample_confidence['is_low_n'] and sample_confidence['severity'] == 'severe':
        if include_cp_row and cp_display_value != 'N/A':
            cp_display_value = f"{_append_ci(format_capability_index(summary_stats['cp']), cp_ci)} (Low-confidence estimate)"
        if cpk_display_value != 'N/A':
            cpk_display_value = f"{_append_ci(format_capability_index(cpk_value), cpk_ci)} (Low-confidence estimate)"

    table_rows = [
        ('Min', format_measurement_value(summary_stats['minimum'])),
        ('Max', format_measurement_value(summary_stats['maximum'])),
        ('Mean', format_measurement_value(summary_stats['average'])),
        ('Median', format_measurement_value(summary_stats['median'])),
        ('Std Dev', format_measurement_value(summary_stats['sigma'])),
    ]
    if include_cp_row:
        table_rows.append((cp_label, cp_display_value))
    table_rows.append((resolved_cpk_label, cpk_display_value))

    observed_nok_pct = summary_stats.get('observed_nok_pct', summary_stats.get('nok_pct'))
    estimated_nok_pct = summary_stats.get('estimated_nok_pct')
    discrepancy_metrics = _compute_nok_discrepancy_metrics(observed_nok_pct, estimated_nok_pct)

    table_rows.extend([
        ('Samples', format_measurement_value(summary_stats['sample_size'])),
        ('NOK', format_measurement_value(summary_stats['nok_count'])),
        ('NOK %', format_percent_from_ratio(summary_stats['nok_pct'], decimals=2)),
    ])

    raw_rows = [
        ('Min', summary_stats['minimum']),
        ('Max', summary_stats['maximum']),
        ('Mean', summary_stats['average']),
        ('Median', summary_stats['median']),
        ('Std Dev', summary_stats['sigma']),
        ('Samples', summary_stats['sample_size']),
        ('NOK', summary_stats['nok_count']),
        ('NOK %', summary_stats['nok_pct']),
    ]
    if include_cp_row:
        raw_rows.insert(5, (cp_label, summary_stats['cp']))
    raw_rows.insert(6 if include_cp_row else 5, (resolved_cpk_label, cpk_value))

    return {
        'rows': table_rows,
        'raw_rows': raw_rows,
        'summary_metrics': {
            'observed_nok_count': summary_stats.get('observed_nok_count', summary_stats.get('nok_count')),
            'observed_nok_pct': observed_nok_pct,
            'estimated_nok_pct': estimated_nok_pct,
            'estimated_nok_ppm': summary_stats.get('estimated_nok_ppm'),
            'estimated_yield_pct': summary_stats.get('estimated_yield_pct'),
            'nok_pct_abs_diff': discrepancy_metrics['abs_diff'],
            'nok_pct_abs_diff_pp': discrepancy_metrics['abs_diff_pp'],
            'nok_pct_rel_diff': discrepancy_metrics['rel_diff'],
            'nok_pct_discrepancy_threshold': discrepancy_metrics['threshold_abs'],
            'nok_pct_discrepancy_warning': discrepancy_metrics['is_warning'],
        },
        'sample_confidence': sample_confidence,
        'capability_rows': {
            'Cp': {
                'label': cp_label,
                'display_value': cp_display_value,
                'classification_value': 'N/A' if spec_type != 'two-sided' else summary_stats['cp'],
                'raw_value': summary_stats['cp'],
                'ci': cp_ci,
                'ci_display': _format_ci_bounds(cp_ci),
            },
            'Cpk': {
                'label': resolved_cpk_label,
                'display_value': cpk_display_value,
                'classification_value': cpk_value,
                'raw_value': cpk_value,
                'ci': cpk_ci,
                'ci_display': _format_ci_bounds(cpk_ci),
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
