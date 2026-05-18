import csv
from pathlib import Path

import pandas as pd

from modules.grouping_filter_core import DataFrameGroupingIndex, normalize_grouping_key


_SAMPLE_ROWS = 200
_TOP_FULL_READ_CANDIDATES = 2
_BLANK_GROUP_VALUE = "(blank)"


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

    sampled_results = detect_csv_read_configs(path, preferred_config=preferred_config)
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


def detect_csv_read_configs(file_path, preferred_config=None):
    """Return likely CSV delimiter/decimal configs ordered by sample score."""
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
    return sampled_results


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


def normalize_csv_grouping_key(grouping_columns, values):
    """Return a stable display/filter key for a CSV grouping row."""
    return normalize_grouping_key(grouping_columns, values, blank_value=_BLANK_GROUP_VALUE)


def _normalized_grouping_columns(data_frame, grouping_columns) -> list[str]:
    if data_frame is None:
        return []
    return [column for column in (grouping_columns or []) if column in data_frame.columns]


def _normalized_grouping_series(series: pd.Series) -> pd.Series:
    normalized = series.where(~series.isna(), _BLANK_GROUP_VALUE)
    normalized = normalized.map(lambda value: str(value).strip() or _BLANK_GROUP_VALUE)
    return normalized.astype("string")


def _normalized_grouping_key_frame(data_frame: pd.DataFrame, grouping_columns) -> pd.DataFrame:
    columns = _normalized_grouping_columns(data_frame, grouping_columns)
    if not columns:
        return pd.DataFrame(index=getattr(data_frame, "index", None))
    key_frame = pd.DataFrame(index=data_frame.index)
    for column in columns:
        key_frame[column] = _normalized_grouping_series(data_frame[column])
    return key_frame


class CsvGroupingIndex(DataFrameGroupingIndex):
    """Cached grouping-key index for responsive CSV/Excel filter and grouping dialogs."""


def build_csv_grouping_preview(data_frame, grouping_columns):
    """Build unique grouping combinations for the selected CSV columns."""
    rows, _total = CsvGroupingIndex(data_frame, grouping_columns).preview_rows()
    return rows


def filter_csv_summary_by_group_keys(data_frame, grouping_columns, selected_group_keys):
    """Filter CSV Summary rows to selected grouping-key combinations."""
    if data_frame is None:
        return data_frame
    return CsvGroupingIndex(data_frame, grouping_columns).filter_rows(selected_group_keys)


def parse_delimiter_with_sniffer(file_path):
    """Best-effort delimiter detection used for UX diagnostics."""
    with open(file_path, 'r', encoding='utf-8', newline='') as handle:
        sample = handle.read(4096)
    try:
        dialect = csv.Sniffer().sniff(sample)
        return dialect.delimiter
    except Exception:
        return None
