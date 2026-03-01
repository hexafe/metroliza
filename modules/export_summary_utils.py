import pandas as pd
import numpy as np
from scipy.stats import norm
import math

from modules.stats_utils import safe_process_capability


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
    }


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


def build_trend_plot_payload(header_group: pd.DataFrame):
    """Return x/y points and sparse labels for the summary trend plot."""
    measurements = list(header_group['MEAS'])
    sample_labels = list(header_group['SAMPLE_NUMBER'])
    return {
        'x': list(range(len(measurements))),
        'y': measurements,
        'labels': build_sparse_unique_labels(sample_labels),
    }


def build_histogram_density_curve_payload(measurements, point_count=100):
    """Return x/y density curve data for histogram overlays, if available."""
    mu, std = norm.fit(measurements)
    if std <= 0:
        return None

    x_min = float(np.min(measurements))
    x_max = float(np.max(measurements))
    x_values = np.linspace(x_min, x_max, point_count)
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

    if label_count <= 6 and max_length <= 10:
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
    if force_sparse or label_count > thinning_threshold:
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
