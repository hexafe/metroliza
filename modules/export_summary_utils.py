import pandas as pd
import numpy as np
from scipy.stats import shapiro
import math
import re
import textwrap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE
from modules.distribution_fit_service import (
    build_fit_curve_payload,
    compute_estimated_tail_metrics as compute_fit_tail_metrics,
    resolve_density_curve_sampling as _resolve_density_curve_sampling,
)

from modules.stats_utils import compute_capability_confidence_intervals, is_one_sided_geometric_tolerance, safe_process_capability


_INTEGER_PATTERN = re.compile(r'^[+-]?\d+$')


def resolve_density_curve_sampling(sample_size, *, requested_point_count=100):
    """Backward-compatible export of canonical density sampling policy."""
    return _resolve_density_curve_sampling(
        sample_size,
        requested_point_count=requested_point_count,
    )


def resolve_histogram_bin_count(values, *, min_bins=3, max_bins=48):
    """Resolve a stable histogram bin count using FD/Scott with low-n safeguards."""
    numeric_values = pd.to_numeric(pd.Series(list(values)), errors='coerce').dropna().to_numpy(dtype=float)
    n = int(numeric_values.size)
    if n == 0:
        return {'bin_count': int(min_bins), 'method': 'minimum', 'sample_size': 0}

    data_min = float(np.min(numeric_values))
    data_max = float(np.max(numeric_values))
    data_range = max(0.0, data_max - data_min)

    chosen_bins = None
    chosen_method = 'fallback_sqrt'

    if n >= 2 and data_range > 0:
        q1, q3 = np.percentile(numeric_values, [25, 75])
        iqr = float(q3 - q1)
        std = float(np.std(numeric_values, ddof=1)) if n > 1 else 0.0

        if iqr > 0:
            fd_width = 2.0 * iqr * (n ** (-1.0 / 3.0))
            if np.isfinite(fd_width) and fd_width > 0:
                fd_bins = int(np.ceil(data_range / fd_width))
                if fd_bins > 0:
                    chosen_bins = fd_bins
                    chosen_method = 'freedman_diaconis'

        if chosen_bins is None and std > 0:
            scott_width = 3.5 * std * (n ** (-1.0 / 3.0))
            if np.isfinite(scott_width) and scott_width > 0:
                scott_bins = int(np.ceil(data_range / scott_width))
                if scott_bins > 0:
                    chosen_bins = scott_bins
                    chosen_method = 'scott'

    if chosen_bins is None:
        chosen_bins = int(np.ceil(np.sqrt(n)))

    low_n_upper_bound = 8 if n <= 10 else 12 if n <= 20 else max_bins
    bounded_upper = min(int(max_bins), int(low_n_upper_bound))
    bounded_bins = int(np.clip(chosen_bins, int(min_bins), max(int(min_bins), bounded_upper)))

    return {
        'bin_count': bounded_bins,
        'method': chosen_method,
        'sample_size': n,
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
    capability_ci = compute_capability_confidence_intervals(
        sample_size=sample_size,
        cp=None if cp == 'N/A' else cp,
        cpk=None if cpk == 'N/A' else cpk,
    )
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
        'capability_ci': capability_ci,
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
    """Adapter layer for export summary consumers of canonical fit metrics."""
    return compute_fit_tail_metrics(distribution_fit_result, lsl=lsl, usl=usl)


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


def build_histogram_density_curve_payload(measurements, point_count=100, *, mode='normal_fit', distribution_fit_result=None):
    """Adapter layer for histogram overlay payload formatting."""
    return build_fit_curve_payload(
        measurements,
        point_count=point_count,
        mode=mode,
        distribution_fit_result=distribution_fit_result,
    )


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
    """Apply a consistent categorical x-axis strategy and return layout metadata."""
    if ax is None:
        return

    safe_labels = [str(label) if label is not None else '' for label in labels]
    if not safe_labels:
        return

    if positions is None:
        positions = list(range(len(safe_labels)))

    if len(positions) != len(safe_labels):
        raise ValueError("positions and labels must have the same length")

    strategy = prepare_categorical_x_axis(safe_labels)
    rotation = strategy['rotation']
    label_count = len(safe_labels)
    max_length = max((len(label) for label in safe_labels), default=0)

    # Backward-compatible readability guard: when thinning is explicitly
    # disabled on very dense/long label sets, force 90° rotation so all labels
    # can remain rendered without overlap collapse.
    if not allow_thinning and (label_count > 16 or max_length > 18):
        rotation = 90

    display_labels = list(strategy['processed_labels'])
    if truncate_labels:
        truncated_labels = []
        for label in display_labels:
            plain_label = str(label).replace('\n', ' ')
            if max_label_chars >= 2 and len(plain_label) > max_label_chars:
                plain_label = f"{plain_label[:max_label_chars - 1]}…"
            truncated_labels.append(plain_label)
        display_labels = truncated_labels

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

    ax.tick_params(axis='x', pad=max(tick_padding, strategy['tick_padding']))

    return {
        'rotation': rotation,
        'ha': horizontal_alignment,
        'display_labels': display_text,
        'display_positions': display_positions,
        'recommended_fig_width': strategy['recommended_fig_width'],
        'bottom_margin': strategy['bottom_margin'],
    }


def wrap_tick_label(text: str, *, width: int = 10, max_lines: int = 2) -> str:
    """Wrap a categorical tick label to at most ``max_lines`` lines."""

    safe_text = str(text or '').strip()
    if not safe_text:
        return ''

    normalized = safe_text.replace(' - ', '\n').replace('_', '_\n')
    wrapped_lines = []
    for segment in normalized.splitlines():
        pieces = textwrap.wrap(
            segment,
            width=max(4, int(width)),
            break_long_words=False,
            break_on_hyphens=False,
        ) or ['']
        wrapped_lines.extend(pieces)

    wrapped_lines = wrapped_lines[:max(1, int(max_lines))]
    if not wrapped_lines:
        return safe_text

    joined = '\n'.join(wrapped_lines)
    if len(joined.replace('\n', '')) >= len(safe_text):
        return joined
    return f"{joined.rstrip(' .')}…"


def resolve_extended_chart_fig_width(n_groups: int, *, base_width: float = 6.2, per_group: float = 0.22, max_width: float = 11.0) -> float:
    """Resolve a dynamic figure width for extended categorical charts."""

    group_count = max(0, int(n_groups))
    growth_groups = max(0, group_count - 6)
    candidate = float(base_width) + (growth_groups * float(per_group))
    return min(float(max_width), max(float(base_width), candidate))


def prepare_categorical_x_axis(labels, *, base_fig_width=6.2):
    """Return shared categorical-label layout decisions for extended charts."""

    safe_labels = [str(label) if label is not None else '' for label in labels]
    label_count = len(safe_labels)
    if label_count == 0:
        return {
            'processed_labels': [],
            'rotation': 0,
            'ha': 'center',
            'bottom_margin': 0.16,
            'recommended_fig_width': float(base_fig_width),
            'tick_padding': 6,
        }

    lengths = [len(label.strip()) for label in safe_labels]
    max_length = max(lengths)
    avg_length = sum(lengths) / float(label_count)
    should_wrap = max_length > 14
    wrap_width = 12 if max_length <= 20 else 10
    processed_labels = [wrap_tick_label(label, width=wrap_width, max_lines=2) if should_wrap else label for label in safe_labels]

    if label_count <= 6 and max_length <= 12 and avg_length <= 9:
        rotation = 0
    elif label_count <= 12 and max_length <= 20:
        rotation = 30
    else:
        rotation = 45

    if max_length > 28:
        rotation = 45

    bottom_margin = 0.16
    if rotation == 30:
        bottom_margin = 0.23
    elif rotation == 45:
        bottom_margin = 0.28

    if should_wrap:
        bottom_margin = max(bottom_margin, 0.30 if rotation else 0.22)

    return {
        'processed_labels': processed_labels,
        'rotation': rotation,
        'ha': 'center' if rotation == 0 else 'right',
        'bottom_margin': min(0.35, bottom_margin),
        'recommended_fig_width': resolve_extended_chart_fig_width(label_count, base_width=base_fig_width),
        'tick_padding': 8 if rotation >= 30 else 6,
    }


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
