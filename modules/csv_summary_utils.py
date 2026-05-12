import csv
import json
import logging
from pathlib import Path

import pandas as pd

from modules.stats_utils import safe_process_capability


_SAMPLE_ROWS = 200
_TOP_FULL_READ_CANDIDATES = 2
_BLANK_GROUP_VALUE = "(blank)"


logger = logging.getLogger(__name__)


def _coerce_float(value, default=0.0):
    """Best-effort numeric coercion for user-editable CSV Summary presets."""
    if value is None or value == "":
        return float(default)
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring malformed CSV Summary numeric preset value: %r", value)
        return float(default)


def _score_dataframe(df, numeric_columns_hint=None):
    if df.empty:
        return 0, []

    base_score = len(df.columns) * 10
    row_count = len(df)

    numeric_dtype_columns = list(df.select_dtypes(include='number').columns)
    numeric_cells = row_count * len(numeric_dtype_columns)

    hinted_columns = numeric_columns_hint or [
        column for column in df.columns if column not in numeric_dtype_columns
    ]
    parse_candidates = [
        column
        for column in hinted_columns
        if column in df.columns and column not in numeric_dtype_columns
    ]

    detected_numeric_columns = []
    if parse_candidates:
        coerced = df[parse_candidates].apply(pd.to_numeric, errors='coerce')
        non_na_counts = coerced.notna().sum()
        numeric_cells += int(non_na_counts.sum())
        detected_numeric_columns = [column for column, count in non_na_counts.items() if count > 0]

    return base_score + numeric_cells, detected_numeric_columns


def load_csv_with_fallbacks(file_path, preferred_config=None):
    """Load CSV with delimiter/decimal fallbacks for common manufacturing exports."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    delimiter_candidates = [';', ',', '\t', '|']
    decimal_candidates = [',', '.']

    ordered_candidates = []
    if isinstance(preferred_config, dict):
        preferred_delimiter = preferred_config.get('delimiter')
        preferred_decimal = preferred_config.get('decimal')
        if preferred_delimiter in delimiter_candidates and preferred_decimal in decimal_candidates:
            ordered_candidates.append((preferred_delimiter, preferred_decimal))

    for delimiter in delimiter_candidates:
        for decimal in decimal_candidates:
            pair = (delimiter, decimal)
            if pair not in ordered_candidates:
                ordered_candidates.append(pair)

    sampled_results = []
    for delimiter, decimal in ordered_candidates:
        try:
            sample_df = pd.read_csv(
                path,
                delimiter=delimiter,
                decimal=decimal,
                low_memory=False,
                nrows=_SAMPLE_ROWS,
            )
        except Exception:
            continue

        sample_score, sample_numeric_columns = _score_dataframe(sample_df)
        sampled_results.append(
            {
                'delimiter': delimiter,
                'decimal': decimal,
                'sample_score': sample_score,
                'sample_numeric_columns': sample_numeric_columns,
            }
        )

    if not sampled_results:
        raise ValueError(f"Unable to read CSV file: {file_path}")

    sampled_results.sort(key=lambda item: item['sample_score'], reverse=True)
    narrowed_candidates = sampled_results[:_TOP_FULL_READ_CANDIDATES]

    best_df = None
    best_score = -1
    best_config = None

    for candidate in narrowed_candidates:
        delimiter = candidate['delimiter']
        decimal = candidate['decimal']
        sample_numeric_columns = candidate['sample_numeric_columns']

        try:
            df = pd.read_csv(path, delimiter=delimiter, decimal=decimal, low_memory=False)
        except Exception:
            continue

        score, _ = _score_dataframe(df, numeric_columns_hint=sample_numeric_columns)

        if score > best_score:
            best_df = df
            best_score = score
            best_config = {'delimiter': delimiter, 'decimal': decimal}

    if best_df is None:
        raise ValueError(f"Unable to read CSV file: {file_path}")

    return best_df, best_config


def load_csv_summary_presets(preset_path):
    path = Path(preset_path)
    if not path.exists():
        return {}

    try:
        with path.open('r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "Failed to load CSV summary presets from %s (%s): %s",
            path,
            exc.__class__.__name__,
            exc,
        )
        return {}

    return data if isinstance(data, dict) else {}


def migrate_csv_summary_presets(presets):
    """Migrate legacy CSV Summary presets to the current schema."""
    if not isinstance(presets, dict):
        return {}, True

    migrated = {}
    changed = False

    for key, payload in presets.items():
        if not isinstance(payload, dict):
            changed = True
            continue

        selected_indexes = payload.get('selected_indexes', [])
        if not isinstance(selected_indexes, list):
            selected_indexes = []
            changed = True

        selected_data_columns = payload.get('selected_data_columns', [])
        if not isinstance(selected_data_columns, list):
            selected_data_columns = []
            changed = True

        include_extended_plots = bool(payload.get('include_extended_plots', True))
        summary_only = bool(payload.get('summary_only', False))
        csv_config = payload.get('csv_config', {})
        if not isinstance(csv_config, dict):
            csv_config = {}
            changed = True

        column_spec_limits = normalize_column_spec_limits(
            selected_data_columns,
            payload.get('column_spec_limits', {}),
        )
        plot_toggles = normalize_plot_toggles(
            selected_data_columns,
            payload.get('plot_toggles', {}),
            full_report=include_extended_plots,
        )
        grouping_columns = payload.get('grouping_columns', [])
        if not isinstance(grouping_columns, list):
            grouping_columns = []
            changed = True
        grouping_columns = [str(column) for column in grouping_columns]

        selected_group_keys = payload.get('selected_group_keys', [])
        if not isinstance(selected_group_keys, list):
            selected_group_keys = []
            changed = True
        selected_group_keys = [
            [str(part) for part in key]
            for key in selected_group_keys
            if isinstance(key, list)
        ]

        normalized_payload = {
            'selected_indexes': selected_indexes,
            'selected_data_columns': selected_data_columns,
            'csv_config': csv_config,
            'column_spec_limits': column_spec_limits,
            'include_extended_plots': include_extended_plots,
            'summary_only': summary_only,
            'plot_toggles': plot_toggles,
            'grouping_columns': grouping_columns,
            'selected_group_keys': selected_group_keys,
        }

        if payload != normalized_payload:
            changed = True

        migrated[key] = normalized_payload

    return migrated, changed


def save_csv_summary_presets(preset_path, presets):
    path = Path(preset_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        json.dump(presets, handle, indent=2, sort_keys=True)


def build_csv_summary_preset_key(file_path):
    path = Path(file_path)
    return path.name.lower()


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
    absolute_usl = nom + usl
    absolute_lsl = nom + lsl
    spec_limits_valid = absolute_lsl <= nom <= absolute_usl
    spec_limits_note = '' if spec_limits_valid else 'Invalid spec limits: expected LSL <= NOM <= USL after applying NOM offsets.'

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
            'spec_limits_valid': spec_limits_valid,
            'spec_limits_note': spec_limits_note,
        }

    minimum = round(float(numeric_series.min()), 3)
    average = round(float(numeric_series.mean()), 3)
    maximum = round(float(numeric_series.max()), 3)
    sigma = round(float(numeric_series.std(ddof=1)), 3) if len(numeric_series) > 1 else 0.0

    if spec_limits_valid:
        cp, cpk = safe_process_capability(nom, usl, lsl, sigma, average)
    else:
        cp, cpk = 'N/A', 'N/A'

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
        'spec_limits_valid': spec_limits_valid,
        'spec_limits_note': spec_limits_note,
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


def recommend_extended_plots_default(data_columns, max_full_report_columns=20):
    """Return a default full-report toggle tuned for export size."""
    return len(data_columns or []) <= int(max_full_report_columns)


def estimate_enabled_chart_count(data_columns, plot_toggles, full_report=True, summary_only=False):
    """Estimate how many charts will be generated for a CSV Summary export."""
    if summary_only or not full_report:
        return 0

    toggles = normalize_plot_toggles(data_columns, plot_toggles, full_report=True)
    return sum(
        int(column_toggles.get('histogram', False)) + int(column_toggles.get('boxplot', False))
        for column_toggles in toggles.values()
    )


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


def normalize_column_spec_limits(data_columns, column_spec_limits):
    """Ensure selected columns have numeric NOM/USL/LSL payloads."""
    normalized = {}
    column_spec_limits = column_spec_limits or {}

    for column in (data_columns or []):
        raw_payload = column_spec_limits.get(column, {})
        if not isinstance(raw_payload, dict):
            raw_payload = {}

        normalized[column] = {
            'nom': _coerce_float(raw_payload.get('nom', 0.0)),
            'usl': _coerce_float(raw_payload.get('usl', 0.0)),
            'lsl': _coerce_float(raw_payload.get('lsl', 0.0)),
        }

    return normalized


def normalize_csv_grouping_key(grouping_columns, values):
    """Return a stable display/filter key for a CSV grouping row."""
    grouping_columns = list(grouping_columns or [])
    normalized = []
    for index, _column in enumerate(grouping_columns):
        value = values[index] if index < len(values) else None
        if pd.isna(value):
            normalized.append(_BLANK_GROUP_VALUE)
            continue
        text = str(value).strip()
        normalized.append(text or _BLANK_GROUP_VALUE)
    return tuple(normalized)


def build_csv_grouping_preview(data_frame, grouping_columns):
    """Build unique grouping combinations for the selected CSV columns."""
    if data_frame is None or not grouping_columns:
        return []
    grouping_columns = [column for column in (grouping_columns or []) if column in data_frame.columns]
    if not grouping_columns:
        return []

    preview_frame = data_frame[grouping_columns].copy()
    for column in grouping_columns:
        preview_frame[column] = preview_frame[column].map(
            lambda value: normalize_csv_grouping_key([column], [value])[0]
        )
    preview_frame["_row_count"] = 1
    grouped = (
        preview_frame.groupby(grouping_columns, dropna=False, sort=True)["_row_count"]
        .sum()
        .reset_index()
    )
    rows = []
    for record in grouped.to_dict("records"):
        key = tuple(str(record[column]) for column in grouping_columns)
        rows.append(
            {
                "key": key,
                "label": " | ".join(key),
                "row_count": int(record["_row_count"]),
            }
        )
    return rows


def filter_csv_summary_by_group_keys(data_frame, grouping_columns, selected_group_keys):
    """Filter CSV Summary rows to selected grouping-key combinations."""
    if data_frame is None:
        return data_frame
    grouping_columns = [column for column in (grouping_columns or []) if column in data_frame.columns]
    selected_keys = {
        tuple(str(part) for part in list(key))
        for key in (selected_group_keys or [])
        if isinstance(key, (list, tuple)) and len(key) == len(grouping_columns)
    }
    if not grouping_columns or not selected_keys:
        return data_frame.copy()

    key_frame = data_frame[grouping_columns].copy()
    for column in grouping_columns:
        key_frame[column] = key_frame[column].map(
            lambda value: normalize_csv_grouping_key([column], [value])[0]
        )
    row_keys = key_frame.apply(lambda row: tuple(str(row[column]) for column in grouping_columns), axis=1)
    return data_frame.loc[row_keys.isin(selected_keys)].copy()


def parse_delimiter_with_sniffer(file_path):
    """Best-effort delimiter detection used for UX diagnostics."""
    with open(file_path, 'r', encoding='utf-8', newline='') as handle:
        sample = handle.read(4096)
    try:
        dialect = csv.Sniffer().sniff(sample)
        return dialect.delimiter
    except Exception:
        return None
