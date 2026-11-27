import csv
from pathlib import Path

from metroliza.shared.grouping_filter_core import DataFrameGroupingIndex, normalize_grouping_key
from metroliza.shared.lazy_modules import LazyPandas as _LazyPandas
from metroliza.tabular.csv_source_numbers import (
    CsvSourceNumbers,
    CsvSourceSample,
    csv_value_looks_like_identifier,
    is_csv_identifier_header,
    sample_csv_sources,
    validate_csv_width,
)


_BLANK_GROUP_VALUE = "(blank)"


pd = _LazyPandas()


def _csv_text_fields(sample: CsvSourceSample) -> frozenset[int]:
    return frozenset(index for index, header in enumerate(sample.header) if is_csv_identifier_header(header))


def _preferred_csv_config(preferred_config):
    return preferred_config if isinstance(preferred_config, dict) else {}


def load_csv_with_fallbacks(file_path, preferred_config=None):
    """Load CSV with bounded delimiter detection and source-aware numeric conversion."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    preferences = _preferred_csv_config(preferred_config)
    sample = sample_csv_sources(path, preferred_delimiter=preferences.get("delimiter"))[0]
    text_fields = _csv_text_fields(sample)
    conventions, numeric_counts = sample.evidence(text_fields)
    numbers = CsvSourceNumbers(conventions, text_fields)
    width = len(sample.header)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=sample.delimiter)
        next(reader, None)
        rows = []
        for row in reader:
            validate_csv_width(row, width)
            rows.append(row[:width] + [None] * max(width - len(row), 0))

    df = pd.DataFrame(rows, columns=sample.header)
    for index in range(width):
        if index in text_fields:
            continue
        values = [str(value).strip() if value is not None else "" for value in df.iloc[:, index]]
        if any(csv_value_looks_like_identifier(value) for value in values):
            continue
        parsed = numbers.parse_column(index, values)
        if numeric_counts[index] and any(number is not None for number in parsed):
            df.isetitem(index, parsed)
    return df, sample.config(conventions, preferred_decimal=preferences.get("decimal"))


def detect_csv_read_configs(file_path, preferred_config=None):
    """Return likely CSV read configurations ordered by field boundary evidence."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    preferences = _preferred_csv_config(preferred_config)
    results = []
    for sample in sample_csv_sources(path, preferred_delimiter=preferences.get("delimiter")):
        conventions, counts = sample.evidence(_csv_text_fields(sample))
        results.append({
            **sample.config(conventions, preferred_decimal=preferences.get("decimal")),
            "sample_score": len(sample.header) * 10 + sum(counts),
            "sample_numeric_columns": [
                column for column, count in zip(sample.header, counts, strict=True) if count
            ],
        })
    return results


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
