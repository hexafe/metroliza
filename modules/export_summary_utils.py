import pandas as pd
import numpy as np
from scipy.stats import gaussian_kde, norm, shapiro, johnsonsu, skewnorm, halfnorm, foldnorm, gamma, weibull_min, lognorm
import math
import re
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE

from modules.stats_utils import is_one_sided_geometric_tolerance, safe_process_capability


_INTEGER_PATTERN = re.compile(r'^[+-]?\d+$')

_DISTRIBUTION_BY_NAME = {
    'norm': norm,
    'skewnorm': skewnorm,
    'johnsonsu': johnsonsu,
    'halfnorm': halfnorm,
    'foldnorm': foldnorm,
    'gamma': gamma,
    'weibull_min': weibull_min,
    'lognorm': lognorm,
}


def normalize_plot_axis_values(values):
    """Normalize string-based axis values into numeric or datetime types when parseable."""
    normalized = []
    for value in values:
        if not isinstance(value, str):
            normalized.append(value)
            continue

        text = value.strip()
        if text == '':
            normalized.append(value)
            continue

        if _INTEGER_PATTERN.match(text):
            try:
                normalized.append(int(text))
                continue
            except (TypeError, ValueError):
                pass

        try:
            normalized.append(float(text))
            continue
        except (TypeError, ValueError):
            pass

        try:
            parsed_datetime = pd.to_datetime(text, errors='raise')
            normalized.append(parsed_datetime.to_pydatetime())
            continue
        except (TypeError, ValueError):
            normalized.append(value)

    return normalized


def resolve_nominal_and_limits(header_group: pd.DataFrame):
    nom = round(header_group['NOM'].iloc[0], 3)
    upper_tolerance = round(header_group['+TOL'].iloc[0], 3)
    lower_tolerance = round(header_group['-TOL'].iloc[0], 3) if header_group['-TOL'].iloc[0] else 0

    return {
        'nom': nom,
        'usl': nom + upper_tolerance,
        'lsl': nom + lower_tolerance,
    }


def compute_measurement_summary(header_group: pd.DataFrame, usl: float, lsl: float, nom: float):
    meas = header_group['MEAS']
    sigma = meas.std()
    average = meas.mean()
    sample_size = meas.count()
    nok_count = header_group[(meas > usl) | (meas < lsl)]['MEAS'].count()

    cp, cpk = safe_process_capability(nom, usl, lsl, sigma, average)
    one_sided_mode = bool(is_one_sided_geometric_tolerance(nom, lsl))
    normality = compute_normality_status(meas, one_sided=one_sided_mode, location_bound=lsl)

    return {
        'minimum': meas.min(),
        'maximum': meas.max(),
        'sigma': sigma,
        'average': average,
        'median': meas.median(),
        'cp': cp,
        'cpk': cpk,
        'sample_size': sample_size,
        'nok_count': nok_count,
        'nok_pct': (nok_count / sample_size) if sample_size else 0,
        'observed_nok_count': nok_count,
        'observed_nok_pct': (nok_count / sample_size) if sample_size else 0,
        'estimated_nok_pct': None,
        'estimated_nok_ppm': None,
        'estimated_yield_pct': None,
        'normality_status': normality['status'],
        'normality_text': normality['text'],
        'normality_test_name': normality.get('test_name', 'Shapiro'),
        'normality_p_value': normality.get('p_value'),
    }


def compute_estimated_tail_metrics(distribution_fit_result, *, lsl=None, usl=None):
    """Estimate NOK/yield metrics from selected fitted model CDF tails."""
    selected_model = (distribution_fit_result or {}).get('selected_model') or {}
    model_name = selected_model.get('model')
    params = selected_model.get('params')
    dist = _DISTRIBUTION_BY_NAME.get(model_name)

    if dist is None or not params:
        return {
            'estimated_nok_pct': None,
            'estimated_nok_ppm': None,
            'estimated_yield_pct': None,
            'estimated_tail_below_lsl': None,
            'estimated_tail_above_usl': None,
        }

    try:
        below_lsl = None if lsl is None else float(np.clip(dist.cdf(lsl, *params), 0.0, 1.0))
        above_usl = None if usl is None else float(np.clip(1.0 - dist.cdf(usl, *params), 0.0, 1.0))
    except Exception:
        return {
            'estimated_nok_pct': None,
            'estimated_nok_ppm': None,
            'estimated_yield_pct': None,
            'estimated_tail_below_lsl': None,
            'estimated_tail_above_usl': None,
        }

    if lsl is not None and usl is not None:
        outside_probability = float(np.clip((below_lsl or 0.0) + (above_usl or 0.0), 0.0, 1.0))
    elif usl is not None:
        outside_probability = float(np.clip(above_usl or 0.0, 0.0, 1.0))
    elif lsl is not None:
        outside_probability = float(np.clip(below_lsl or 0.0, 0.0, 1.0))
    else:
        outside_probability = None

    return {
        'estimated_nok_pct': outside_probability,
        'estimated_nok_ppm': None if outside_probability is None else outside_probability * 1_000_000.0,
        'estimated_yield_pct': None if outside_probability is None else (1.0 - outside_probability),
        'estimated_tail_below_lsl': below_lsl,
        'estimated_tail_above_usl': above_usl,
    }


def compute_normality_status(measurements, *, one_sided=False, location_bound=None):
    """Classify measurement normality using Shapiro-Wilk when applicable."""
    numeric_measurements = pd.to_numeric(pd.Series(measurements), errors='coerce').dropna().to_numpy(dtype=float)
    sample_size = int(numeric_measurements.size)

    if one_sided:
        return {
            'status': 'not_applicable',
            'test_name': 'One-sided tolerance model',
            'p_value': None,
            'text': 'One-sided tolerance\nNormality not applicable',
        }

    unknown_payload = {
        'status': 'unknown',
        'test_name': 'Shapiro',
        'p_value': None,
        'text': 'Shapiro p = N/A\nUnknown',
    }
    if sample_size < 3 or sample_size > 5000:
        return unknown_payload

    sigma = float(np.std(numeric_measurements, ddof=1))
    if np.isclose(sigma, 0.0):
        return unknown_payload

    try:
        _statistic, p_value = shapiro(numeric_measurements)
    except Exception:
        return unknown_payload

    if p_value >= 0.05:
        return {'status': 'normal', 'test_name': 'Shapiro', 'p_value': float(p_value), 'text': f'Shapiro p = {p_value:.4f}\nNormal'}
    return {'status': 'not_normal', 'test_name': 'Shapiro', 'p_value': float(p_value), 'text': f'Shapiro p = {p_value:.4f}\nNon-normal'}


def build_sparse_unique_labels(labels):
    """Return labels with repeated values blanked for clearer x-axis display."""
    seen = set()
    sparse_labels = []
    for label in labels:
        if label in seen:
            sparse_labels.append('')
            continue
        seen.add(label)
        sparse_labels.append(label)
    return sparse_labels


def build_summary_panel_labels(labels, *, grouping_active=False):
    """Return summary-panel labels using one strategy across chart types.

    When grouping is active, labels stay dense so group names remain visible.
    Otherwise, repeated sample labels are blanked for readability.
    """
    normalized_labels = [str(label) if label is not None else '' for label in labels]
    if grouping_active:
        return normalized_labels
    return build_sparse_unique_labels(normalized_labels)


def build_trend_plot_payload(header_group: pd.DataFrame, *, grouping_active=False, label_column=None):
    """Return x/y points and dense labels for the summary trend plot."""
    measurements = normalize_plot_axis_values(list(header_group['MEAS']))
    resolved_label_column = label_column
    if resolved_label_column is None:
        resolved_label_column = 'GROUP' if grouping_active and 'GROUP' in header_group.columns else 'SAMPLE_NUMBER'

    if resolved_label_column in header_group.columns:
        raw_labels = list(header_group[resolved_label_column])
    else:
        raw_labels = list(range(1, len(measurements) + 1))

    dense_labels = [str(label) if label is not None else '' for label in raw_labels]

    return {
        'x': list(range(len(measurements))),
        'y': measurements,
        'labels': dense_labels,
    }


def build_histogram_density_curve_payload(measurements, point_count=100, *, mode='normal_fit'):
    """Return x/y density curve data for histogram overlays, if available."""
    normalized_measurements = normalize_plot_axis_values(list(measurements))
    numeric_measurements = pd.to_numeric(pd.Series(normalized_measurements), errors='coerce').dropna().to_numpy(dtype=float)
    if numeric_measurements.size == 0:
        return None

    x_min = float(np.min(numeric_measurements))
    x_max = float(np.max(numeric_measurements))
    if np.isclose(x_min, x_max):
        return None

    x_values = np.linspace(x_min, x_max, point_count)
    if mode == 'kde':
        if numeric_measurements.size < 2:
            return None
        try:
            kde = gaussian_kde(numeric_measurements)
            y_values = kde(x_values)
        except Exception:
            return None
    else:
        mu, std = norm.fit(numeric_measurements)
        if std <= 0:
            return None
        y_values = norm.pdf(x_values, mu, std)

    return {
        'x': x_values,
        'y': y_values,
    }


def apply_shared_x_axis_label_strategy(
    ax,
    labels,
    *,
    positions=None,
    truncate_labels=True,
    max_label_chars=18,
    thinning_threshold=24,
    target_tick_count=16,
    tick_padding=6,
    force_sparse=False,
    allow_thinning=True,
):
    """Apply a consistent x-axis label strategy for dense categorical charts."""
    if ax is None:
        return

    safe_labels = [str(label) if label is not None else '' for label in labels]
    if not safe_labels:
        return

    if positions is None:
        positions = list(range(len(safe_labels)))

    if len(positions) != len(safe_labels):
        raise ValueError("positions and labels must have the same length")

    max_length = max((len(label) for label in safe_labels), default=0)
    label_count = len(safe_labels)

    if not allow_thinning and (label_count > 16 or max_length > 18):
        rotation = 90
    elif label_count <= 6 and max_length <= 10:
        rotation = 0
    elif label_count <= 12 and max_length <= 20:
        rotation = 30
    elif label_count <= 24 and max_length <= 28:
        rotation = 45
    else:
        rotation = 90

    def _truncate(label):
        if not truncate_labels:
            return label
        if max_label_chars < 2 or len(label) <= max_label_chars:
            return label
        return f"{label[:max_label_chars - 1]}…"

    display_labels = [_truncate(label) for label in safe_labels]

    indices = list(range(label_count))
    if allow_thinning and (force_sparse or label_count > thinning_threshold):
        step = max(1, int(math.ceil(label_count / max(target_tick_count, 1))))
        indices = [idx for idx in indices if idx % step == 0]
        if (label_count - 1) not in indices:
            indices.append(label_count - 1)

    display_positions = [positions[idx] for idx in indices]
    display_text = [display_labels[idx] for idx in indices]
    horizontal_alignment = 'center' if rotation == 0 else 'right'

    ax.set_xticks(display_positions)
    ax.set_xticklabels(display_text)
    for tick in ax.get_xticklabels():
        tick.set_rotation(rotation)
        tick.set_horizontalalignment(horizontal_alignment)
        tick.set_rotation_mode('anchor')

    ax.tick_params(axis='x', pad=tick_padding)


def render_tolerance_band(ax, nom, lsl, usl, one_sided=False, orientation='horizontal'):
    """Render a subtle tolerance band for summary charts."""
    if ax is None:
        return None

    band_kwargs = {
        'alpha': 0.08,
        'color': SUMMARY_PLOT_PALETTE['sigma_band'],
        'zorder': 0,
    }

    if orientation == 'vertical':
        lower, upper = (0, usl) if one_sided else (lsl, usl)
        return ax.axvspan(lower, upper, **band_kwargs)

    lower, upper = (0, usl) if one_sided else (lsl, usl)
    return ax.axhspan(lower, upper, **band_kwargs)


def render_spec_reference_lines(ax, nom, lsl, usl, orientation='horizontal', include_nominal=True):
    """Render nominal and spec-limit reference lines for summary charts."""
    if ax is None:
        return []

    line_kwargs = {
        'color': SUMMARY_PLOT_PALETTE['spec_limit'],
        'linewidth': 1.5,
        'alpha': 0.8,
        'zorder': 3,
    }
    nominal_kwargs = {**line_kwargs, 'linestyle': '--'}

    lines = []

    if lsl is not None:
        if orientation == 'vertical':
            lines.append(ax.axvline(lsl, ymin=0, ymax=0.92, **line_kwargs))
        else:
            lines.append(ax.axhline(lsl, **line_kwargs))

    if usl is not None:
        if orientation == 'vertical':
            lines.append(ax.axvline(usl, ymin=0, ymax=0.92, **line_kwargs))
        else:
            lines.append(ax.axhline(usl, **line_kwargs))

    if include_nominal and nom is not None:
        if orientation == 'vertical':
            lines.append(ax.axvline(nom, ymin=0, ymax=0.92, **nominal_kwargs))
        else:
            lines.append(ax.axhline(nom, **nominal_kwargs))

    return lines


def build_tolerance_reference_legend_handles(*, include_nominal=True):
    """Return legend handles for tolerance bands and spec-reference lines."""
    handles = [
        Patch(
            facecolor=SUMMARY_PLOT_PALETTE['sigma_band'],
            edgecolor='none',
            alpha=0.08,
            label='Tolerance band',
        ),
        Line2D([0], [0], color=SUMMARY_PLOT_PALETTE['spec_limit'], linewidth=1.0, label='LSL'),
        Line2D([0], [0], color=SUMMARY_PLOT_PALETTE['spec_limit'], linewidth=1.0, label='USL'),
    ]
    if include_nominal:
        handles.append(Line2D([0], [0], color=SUMMARY_PLOT_PALETTE['spec_limit'], linestyle='--', linewidth=1.0, label='Nominal'))
    return handles
