import csv
from pathlib import Path

import pandas as pd

from modules.stats_utils import safe_process_capability


def load_csv_with_fallbacks(file_path):
    """Load CSV with delimiter/decimal fallbacks for common manufacturing exports."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    delimiter_candidates = [';', ',', '\t', '|']
    decimal_candidates = [',', '.']

    best_df = None
    best_score = -1
    best_config = None

    for delimiter in delimiter_candidates:
        for decimal in decimal_candidates:
            try:
                df = pd.read_csv(path, delimiter=delimiter, decimal=decimal, low_memory=False)
            except Exception:
                continue

            if df.empty:
                score = 0
            else:
                numeric_cells = 0
                for col in df.columns:
                    numeric_cells += pd.to_numeric(df[col], errors='coerce').notna().sum()
                score = (len(df.columns) * 10) + numeric_cells

            if score > best_score:
                best_df = df
                best_score = score
                best_config = {'delimiter': delimiter, 'decimal': decimal}

    if best_df is None:
        raise ValueError(f"Unable to read CSV file: {file_path}")

    return best_df, best_config


def resolve_default_data_columns(data_frame, selected_indexes):
    selected_indexes = selected_indexes or []
    index_set = set(selected_indexes)

    numeric_columns = []
    for column in data_frame.columns:
        if column in index_set:
            continue
        coerced = pd.to_numeric(data_frame[column], errors='coerce')
        if coerced.notna().sum() > 0:
            numeric_columns.append(column)

    if numeric_columns:
        return numeric_columns

    # Fallback for edge cases: preserve existing behavior of selecting non-index columns.
    return [column for column in data_frame.columns if column not in index_set]


def compute_column_summary_stats(series, usl=0.0, lsl=0.0, nom=0.0):
    numeric_series = pd.to_numeric(series, errors='coerce').dropna()
    if numeric_series.empty:
        return {
            'sample_size': 0,
            'min': 'N/A',
            'avg': 'N/A',
            'max': 'N/A',
            'std': 'N/A',
            'cp': 'N/A',
            'cpk': 'N/A',
            'usl': usl,
            'lsl': lsl,
            'nom': nom,
        }

    minimum = round(float(numeric_series.min()), 3)
    average = round(float(numeric_series.mean()), 3)
    maximum = round(float(numeric_series.max()), 3)
    sigma = round(float(numeric_series.std(ddof=1)), 3) if len(numeric_series) > 1 else 0.0

    cp, cpk = safe_process_capability(nom, usl, lsl, sigma, average)

    return {
        'sample_size': int(numeric_series.count()),
        'min': minimum,
        'avg': average,
        'max': maximum,
        'std': sigma,
        'cp': cp,
        'cpk': cpk,
        'usl': usl,
        'lsl': lsl,
        'nom': nom,
    }


def build_default_plot_toggles(data_columns, full_report=True):
    """Build per-column plot toggles for CSV Summary export."""
    return {
        column: {
            'histogram': bool(full_report),
            'boxplot': bool(full_report),
        }
        for column in (data_columns or [])
    }


def normalize_plot_toggles(data_columns, plot_toggles, full_report=True):
    """Ensure each selected column has a complete toggle payload."""
    normalized = build_default_plot_toggles(data_columns, full_report=full_report)
    plot_toggles = plot_toggles or {}

    for column in normalized:
        column_payload = plot_toggles.get(column, {})
        if isinstance(column_payload, dict):
            normalized[column]['histogram'] = bool(column_payload.get('histogram', normalized[column]['histogram']))
            normalized[column]['boxplot'] = bool(column_payload.get('boxplot', normalized[column]['boxplot']))

    return normalized


def parse_delimiter_with_sniffer(file_path):
    """Best-effort delimiter detection used for UX diagnostics."""
    with open(file_path, 'r', encoding='utf-8', newline='') as handle:
        sample = handle.read(4096)
    try:
        dialect = csv.Sniffer().sniff(sample)
        return dialect.delimiter
    except Exception:
        return None
