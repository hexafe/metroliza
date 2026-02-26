import pandas as pd
import numpy as np
from scipy.stats import norm

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
