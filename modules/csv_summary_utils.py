import csv
from pathlib import Path
from typing import Any

import pandas as pd


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


class CsvGroupingIndex:
    """Cached grouping-key index for responsive CSV/Excel filter and grouping dialogs."""

    def __init__(self, data_frame: pd.DataFrame | None, grouping_columns):
        self.data_frame = data_frame if isinstance(data_frame, pd.DataFrame) else pd.DataFrame()
        self.grouping_columns = tuple(_normalized_grouping_columns(self.data_frame, grouping_columns))
        self.key_frame = _normalized_grouping_key_frame(self.data_frame, self.grouping_columns)
        self._grouped_preview: pd.DataFrame | None = None
        self._row_index = None

    @property
    def active(self) -> bool:
        return bool(self.grouping_columns)

    @property
    def row_count(self) -> int:
        return int(len(self.data_frame.index))

    def preview_rows(
        self,
        *,
        search_text: str = "",
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return display rows and total match count for the selected grouping columns."""

        if not self.active:
            return [], 0
        preview = self._preview_frame()
        if preview.empty:
            return [], 0
        filtered = preview
        search = str(search_text or "").strip().casefold()
        if search:
            labels = filtered["_label"].astype("string").str.casefold()
            filtered = filtered.loc[labels.str.contains(search, regex=False, na=False)]
        total = int(len(filtered.index))
        offset = max(0, int(offset or 0))
        if offset:
            filtered = filtered.iloc[offset:]
        if limit is not None and int(limit) >= 0:
            filtered = filtered.head(int(limit))
        return self._records_to_rows(filtered), total

    def matching_keys(self, *, search_text: str = "") -> tuple[tuple[str, ...], ...]:
        """Return every grouping key matching the current search text."""

        if not self.active:
            return ()
        preview = self._preview_frame()
        if preview.empty:
            return ()
        filtered = preview
        search = str(search_text or "").strip().casefold()
        if search:
            labels = filtered["_label"].astype("string").str.casefold()
            filtered = filtered.loc[labels.str.contains(search, regex=False, na=False)]
        return tuple(row["key"] for row in self._records_to_rows(filtered))

    def _records_to_rows(self, frame: pd.DataFrame) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in frame.to_dict("records"):
            key = tuple(str(record[column]) for column in self.grouping_columns)
            rows.append(
                {
                    "key": key,
                    "label": str(record["_label"]),
                    "row_count": int(record["_row_count"]),
                }
            )
        return rows

    def filter_rows(self, selected_group_keys) -> pd.DataFrame:
        """Return rows matching selected grouping keys using vectorized key membership."""

        selected_keys = self._valid_selected_keys(selected_group_keys)
        if not self.active or not selected_keys:
            return self.data_frame.copy()
        if len(self.grouping_columns) == 1:
            column = self.grouping_columns[0]
            values = {key[0] for key in selected_keys}
            mask = self.key_frame[column].isin(values)
        else:
            mask = self._row_multi_index().isin(
                pd.MultiIndex.from_tuples(selected_keys, names=list(self.grouping_columns))
            )
        return self.data_frame.loc[mask].copy()

    def count_rows(self, selected_group_keys) -> int:
        """Count rows matching selected grouping keys without materializing a filtered dataframe."""

        selected_keys = self._valid_selected_keys(selected_group_keys)
        if not self.active or not selected_keys:
            return self.row_count
        counts = self._preview_frame().set_index(list(self.grouping_columns))["_row_count"]
        total = 0
        for key in selected_keys:
            lookup_key = key[0] if len(key) == 1 else key
            if lookup_key in counts.index:
                total += int(counts.loc[lookup_key])
        return total

    def child_keys_for_selected(self, selected_group_keys) -> set[tuple[str, ...]]:
        """Return all current grouping keys represented by a parent selection."""

        if not self.active:
            return set()
        raw_keys = {
            tuple(str(part) for part in list(key))
            for key in (selected_group_keys or [])
            if isinstance(key, (list, tuple)) and 0 < len(key) <= len(self.grouping_columns)
        }
        if not raw_keys:
            rows, _total = self.preview_rows()
            return {tuple(row["key"]) for row in rows}
        selected_length = len(next(iter(raw_keys), ()))
        if selected_length >= len(self.grouping_columns):
            return {key for key in raw_keys if len(key) == len(self.grouping_columns)}
        parent_columns = self.grouping_columns[:selected_length]
        parent_index = CsvGroupingIndex(self.data_frame, parent_columns)
        filtered = parent_index.filter_rows(raw_keys)
        child_index = CsvGroupingIndex(filtered, self.grouping_columns)
        rows, _total = child_index.preview_rows()
        return {tuple(row["key"]) for row in rows}

    def _preview_frame(self) -> pd.DataFrame:
        if self._grouped_preview is not None:
            return self._grouped_preview
        if not self.active:
            self._grouped_preview = pd.DataFrame()
            return self._grouped_preview
        grouped = (
            self.key_frame.groupby(list(self.grouping_columns), dropna=False, sort=True)
            .size()
            .reset_index(name="_row_count")
        )
        if grouped.empty:
            grouped["_label"] = pd.Series(dtype="string")
        else:
            grouped["_label"] = grouped.loc[:, list(self.grouping_columns)].agg(" | ".join, axis=1)
        self._grouped_preview = grouped
        return grouped

    def _row_multi_index(self):
        if self._row_index is None:
            self._row_index = pd.MultiIndex.from_frame(self.key_frame.loc[:, list(self.grouping_columns)])
        return self._row_index

    def _valid_selected_keys(self, selected_group_keys) -> set[tuple[str, ...]]:
        expected_length = len(self.grouping_columns)
        return {
            tuple(str(part) for part in list(key))
            for key in (selected_group_keys or [])
            if isinstance(key, (list, tuple)) and len(key) == expected_length
        }


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
