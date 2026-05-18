"""Headless DataFrame grouping and filter helpers.

This module intentionally has no Qt dependencies. It provides the shared
grouping-key index behavior used by CSV-style selectors and reusable filter
specs for tabular DataFrame views.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Literal, Protocol

import pandas as pd


FilterMatchMode = Literal["and", "or"]

_BLANK_GROUP_VALUE = "(blank)"
_SYMBOLIC_FILTER_RE = re.compile(
    r"^\s*(?P<column>.+?)\s*(?P<operator>>=|<=|!=|=|>|<)\s*(?P<value>.+?)\s*$"
)
_FILTER_JOIN_RE = re.compile(r"\s+(AND|OR)\s+", flags=re.IGNORECASE)


@dataclass(frozen=True)
class ParsedFilterExpression:
    """Parsed simple filter expression and match mode."""

    specs: tuple["DataFrameFilterSpec", ...]
    match_mode: FilterMatchMode


def normalize_grouping_key(
    grouping_columns: Iterable[str] | None,
    values: Iterable[Any] | None,
    *,
    blank_value: str = _BLANK_GROUP_VALUE,
) -> tuple[str, ...]:
    """Return a stable display/filter key for one grouping row."""

    columns = list(grouping_columns or [])
    raw_values = list(values or [])
    normalized: list[str] = []
    for index, _column in enumerate(columns):
        value = raw_values[index] if index < len(raw_values) else None
        normalized.append(_normalize_grouping_value(value, blank_value=blank_value))
    return tuple(normalized)


def normalized_grouping_columns(
    data_frame: pd.DataFrame | None,
    grouping_columns: Iterable[str] | None,
) -> tuple[str, ...]:
    """Return requested grouping columns that exist in the frame, preserving order."""

    if not isinstance(data_frame, pd.DataFrame):
        return ()
    return tuple(column for column in (grouping_columns or []) if column in data_frame.columns)


def normalized_grouping_key_frame(
    data_frame: pd.DataFrame | None,
    grouping_columns: Iterable[str] | None,
    *,
    blank_value: str = _BLANK_GROUP_VALUE,
) -> pd.DataFrame:
    """Build normalized string grouping keys for vectorized grouping/filtering."""

    if not isinstance(data_frame, pd.DataFrame):
        return pd.DataFrame()
    columns = normalized_grouping_columns(data_frame, grouping_columns)
    if not columns:
        return pd.DataFrame(index=data_frame.index)
    key_frame = pd.DataFrame(index=data_frame.index)
    for column in columns:
        key_frame[column] = _normalized_grouping_series(data_frame[column], blank_value=blank_value)
    return key_frame


class DataFrameGroupingIndex:
    """Cached grouping-key index for headless DataFrame grouping selectors."""

    def __init__(
        self,
        data_frame: pd.DataFrame | None,
        grouping_columns: Iterable[str] | None,
        *,
        blank_value: str = _BLANK_GROUP_VALUE,
    ) -> None:
        self.data_frame = data_frame if isinstance(data_frame, pd.DataFrame) else pd.DataFrame()
        self.blank_value = str(blank_value)
        self.grouping_columns = normalized_grouping_columns(self.data_frame, grouping_columns)
        self.key_frame = normalized_grouping_key_frame(
            self.data_frame,
            self.grouping_columns,
            blank_value=self.blank_value,
        )
        self._grouped_preview: pd.DataFrame | None = None
        self._row_index: pd.MultiIndex | None = None

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

        filtered = self._search_preview(preview, search_text)
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
        return tuple(row["key"] for row in self._records_to_rows(self._search_preview(preview, search_text)))

    def filter_rows(self, selected_group_keys: Iterable[Iterable[Any]] | None) -> pd.DataFrame:
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

    def count_rows(self, selected_group_keys: Iterable[Iterable[Any]] | None) -> int:
        """Count rows matching selected grouping keys without materializing a copy."""

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

    def child_keys_for_selected(
        self,
        selected_group_keys: Iterable[Iterable[Any]] | None,
    ) -> set[tuple[str, ...]]:
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
        parent_index = DataFrameGroupingIndex(
            self.data_frame,
            parent_columns,
            blank_value=self.blank_value,
        )
        filtered = parent_index.filter_rows(raw_keys)
        child_index = DataFrameGroupingIndex(
            filtered,
            self.grouping_columns,
            blank_value=self.blank_value,
        )
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

    def _row_multi_index(self) -> pd.MultiIndex:
        if self._row_index is None:
            self._row_index = pd.MultiIndex.from_frame(
                self.key_frame.loc[:, list(self.grouping_columns)]
            )
        return self._row_index

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

    def _search_preview(self, preview: pd.DataFrame, search_text: str) -> pd.DataFrame:
        search = str(search_text or "").strip().casefold()
        if not search:
            return preview
        labels = preview["_label"].astype("string").str.casefold()
        return preview.loc[labels.str.contains(search, regex=False, na=False)]

    def _valid_selected_keys(
        self,
        selected_group_keys: Iterable[Iterable[Any]] | None,
    ) -> set[tuple[str, ...]]:
        expected_length = len(self.grouping_columns)
        return {
            tuple(str(part) for part in list(key))
            for key in (selected_group_keys or [])
            if isinstance(key, (list, tuple)) and len(key) == expected_length
        }


class DataFrameFilterSpec(Protocol):
    column: str

    def mask(self, data_frame: pd.DataFrame) -> pd.Series:
        """Return a boolean mask aligned to ``data_frame.index``."""


@dataclass(frozen=True)
class TextFilterSpec:
    """Text filter for one DataFrame column."""

    column: str
    operator: str
    value: str | None = None
    case_sensitive: bool = False

    def mask(self, data_frame: pd.DataFrame) -> pd.Series:
        _require_column(data_frame, self.column)
        operator = self.operator.lower().strip()
        series = data_frame[self.column]
        missing = series.isna()
        text = series.astype("string")
        needle = "" if self.value is None else str(self.value)

        if not self.case_sensitive:
            text = text.str.casefold()
            needle = needle.casefold()

        if operator == "contains":
            return text.str.contains(needle, regex=False, na=False)
        if operator == "not_contains":
            return ~text.str.contains(needle, regex=False, na=False)
        if operator == "equals":
            return text.eq(needle).fillna(False)
        if operator == "not_equals":
            return text.ne(needle).fillna(True)
        if operator == "starts_with":
            return text.str.startswith(needle, na=False)
        if operator == "ends_with":
            return text.str.endswith(needle, na=False)
        if operator == "is_blank":
            return missing | text.fillna("").str.strip().eq("")
        if operator == "is_not_blank":
            return ~(missing | text.fillna("").str.strip().eq(""))
        raise ValueError(f"Unsupported text filter operator: {self.operator}")


@dataclass(frozen=True)
class NumberFilterSpec:
    """Numeric filter for one DataFrame column."""

    column: str
    operator: str
    value: float | int | str | None = None
    second_value: float | int | str | None = None

    def mask(self, data_frame: pd.DataFrame) -> pd.Series:
        _require_column(data_frame, self.column)
        operator = self.operator.lower().strip()
        numbers = pd.to_numeric(data_frame[self.column], errors="coerce")

        if operator == "is_blank":
            return numbers.isna()
        if operator == "is_not_blank":
            return numbers.notna()

        value = _coerce_number(self.value, field_name="value")
        if operator in {"equals", "eq"}:
            return numbers.eq(value).fillna(False)
        if operator in {"not_equals", "ne"}:
            return numbers.ne(value).fillna(True)
        if operator in {"greater_than", "gt"}:
            return numbers.gt(value).fillna(False)
        if operator in {"greater_or_equal", "gte"}:
            return numbers.ge(value).fillna(False)
        if operator in {"less_than", "lt"}:
            return numbers.lt(value).fillna(False)
        if operator in {"less_or_equal", "lte"}:
            return numbers.le(value).fillna(False)
        if operator == "between":
            second_value = _coerce_number(self.second_value, field_name="second_value")
            lower, upper = sorted((value, second_value))
            return numbers.between(lower, upper, inclusive="both").fillna(False)
        raise ValueError(f"Unsupported number filter operator: {self.operator}")


@dataclass(frozen=True)
class DateFilterSpec:
    """Date filter for one DataFrame column."""

    column: str
    operator: str
    value: Any = None
    second_value: Any = None
    dayfirst: bool = False

    def mask(self, data_frame: pd.DataFrame) -> pd.Series:
        _require_column(data_frame, self.column)
        operator = self.operator.lower().strip()
        dates = _coerce_date_series(data_frame[self.column], dayfirst=self.dayfirst)

        if operator == "is_blank":
            return dates.isna()
        if operator == "is_not_blank":
            return dates.notna()

        value = _coerce_date(self.value, dayfirst=self.dayfirst, field_name="value")
        if operator in {"on", "equals", "eq"}:
            return dates.eq(value).fillna(False)
        if operator in {"not_on", "not_equals", "ne"}:
            return dates.ne(value).fillna(True)
        if operator in {"before", "lt"}:
            return dates.lt(value).fillna(False)
        if operator in {"on_or_before", "lte"}:
            return dates.le(value).fillna(False)
        if operator in {"after", "gt"}:
            return dates.gt(value).fillna(False)
        if operator in {"on_or_after", "gte"}:
            return dates.ge(value).fillna(False)
        if operator == "between":
            second_value = _coerce_date(
                self.second_value,
                dayfirst=self.dayfirst,
                field_name="second_value",
            )
            lower, upper = sorted((value, second_value))
            return dates.between(lower, upper, inclusive="both").fillna(False)
        raise ValueError(f"Unsupported date filter operator: {self.operator}")


def build_filter_mask(
    data_frame: pd.DataFrame,
    filter_specs: Iterable[DataFrameFilterSpec] | None,
    *,
    match_mode: FilterMatchMode = "and",
) -> pd.Series:
    """Build a combined boolean mask from text/date/number filter specs."""

    if not isinstance(data_frame, pd.DataFrame):
        raise TypeError("data_frame must be a pandas DataFrame")
    specs = tuple(filter_specs or ())
    mode = _normalize_match_mode(match_mode)
    if not specs:
        return pd.Series(True, index=data_frame.index, dtype=bool)

    masks = [spec.mask(data_frame).reindex(data_frame.index, fill_value=False).astype(bool) for spec in specs]
    combined = masks[0].copy()
    for mask in masks[1:]:
        if mode == "and":
            combined &= mask
        else:
            combined |= mask
    return combined


def apply_filter_specs(
    data_frame: pd.DataFrame,
    filter_specs: Iterable[DataFrameFilterSpec] | None,
    *,
    match_mode: FilterMatchMode = "and",
) -> pd.DataFrame:
    """Return DataFrame rows matching all or any provided filter specs."""

    return data_frame.loc[build_filter_mask(data_frame, filter_specs, match_mode=match_mode)].copy()


def parse_filter_expression(
    expression: str,
    columns: Iterable[str],
    *,
    dayfirst: bool = False,
) -> ParsedFilterExpression:
    """Parse simple ``Column >= value AND Other = value`` filter expressions."""

    text = str(expression or "").strip()
    if not text:
        return ParsedFilterExpression(specs=(), match_mode="and")
    parts = _FILTER_JOIN_RE.split(text)
    terms = parts[0::2]
    joiners = [part.lower() for part in parts[1::2]]
    if "and" in joiners and "or" in joiners:
        raise ValueError("Use only AND or only OR in one grouping filter expression.")
    match_mode: FilterMatchMode = "or" if "or" in joiners else "and"
    specs = tuple(
        _parse_filter_term(term, columns, dayfirst=dayfirst)
        for term in terms
        if str(term or "").strip()
    )
    return ParsedFilterExpression(specs=specs, match_mode=match_mode)


def _parse_filter_term(
    term: str,
    columns: Iterable[str],
    *,
    dayfirst: bool,
) -> DataFrameFilterSpec:
    match = _SYMBOLIC_FILTER_RE.match(str(term or ""))
    if match is None:
        raise ValueError(f"Invalid grouping filter term: {term}")
    column = _resolve_filter_column(match.group("column"), columns)
    operator = match.group("operator")
    value = match.group("value").strip()
    if not value:
        raise ValueError(f"Missing value for grouping filter term: {term}")

    looks_date_like = bool(re.search(r"\d{4}", value) or any(marker in value for marker in ("-", "/", ":")))
    date_value = pd.to_datetime(pd.Series([value]), errors="coerce", dayfirst=dayfirst).iloc[0]
    number_value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if looks_date_like and not pd.isna(date_value):
        return DateFilterSpec(
            column,
            _symbol_to_date_operator(operator),
            value,
            dayfirst=dayfirst,
        )
    if not pd.isna(number_value):
        return NumberFilterSpec(column, _symbol_to_number_operator(operator), value)
    if operator in {"=", "!="}:
        return TextFilterSpec(column, "equals" if operator == "=" else "not_equals", value)
    raise ValueError(f"Operator {operator} requires a numeric or date-like value.")


def _resolve_filter_column(column: str, columns: Iterable[str]) -> str:
    requested = str(column or "").strip()
    column_list = tuple(str(item) for item in columns)
    for candidate in column_list:
        if candidate == requested:
            return candidate
    requested_key = requested.casefold()
    for candidate in column_list:
        if candidate.casefold() == requested_key:
            return candidate
    raise KeyError(f"DataFrame column not found: {requested}")


def _symbol_to_number_operator(operator: str) -> str:
    return {
        "=": "equals",
        "!=": "not_equals",
        ">": "greater_than",
        ">=": "greater_or_equal",
        "<": "less_than",
        "<=": "less_or_equal",
    }[operator]


def _symbol_to_date_operator(operator: str) -> str:
    return {
        "=": "on",
        "!=": "not_on",
        ">": "after",
        ">=": "on_or_after",
        "<": "before",
        "<=": "on_or_before",
    }[operator]


def _normalize_grouping_value(value: Any, *, blank_value: str) -> str:
    if pd.isna(value):
        return blank_value
    text = str(value).strip()
    return text or blank_value


def _normalized_grouping_series(series: pd.Series, *, blank_value: str) -> pd.Series:
    normalized = series.map(lambda value: _normalize_grouping_value(value, blank_value=blank_value))
    return normalized.astype("string")


def _require_column(data_frame: pd.DataFrame, column: str) -> None:
    if column not in data_frame.columns:
        raise KeyError(f"DataFrame column not found: {column}")


def _coerce_number(value: float | int | str | None, *, field_name: str) -> float:
    if value is None:
        raise ValueError(f"{field_name} is required for this number filter")
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        raise ValueError(f"{field_name} must be numeric")
    return float(number)


def _coerce_date(value: Any, *, dayfirst: bool, field_name: str) -> pd.Timestamp:
    if value is None:
        raise ValueError(f"{field_name} is required for this date filter")
    parsed = _coerce_date_series(pd.Series([value]), dayfirst=dayfirst).iloc[0]
    if pd.isna(parsed):
        raise ValueError(f"{field_name} must be date-like")
    return parsed


def _coerce_date_series(series: pd.Series, *, dayfirst: bool) -> pd.Series:
    return series.map(lambda value: pd.to_datetime(value, errors="coerce", dayfirst=dayfirst)).dt.normalize()


def _normalize_match_mode(match_mode: str) -> FilterMatchMode:
    mode = str(match_mode).lower().strip()
    if mode not in {"and", "or"}:
        raise ValueError("match_mode must be 'and' or 'or'")
    return mode  # type: ignore[return-value]
