"""Headless DataFrame grouping and filter helpers.

This module intentionally has no Qt dependencies. It provides the shared
grouping-key index behavior used by CSV-style selectors and reusable filter
specs for tabular DataFrame views.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Literal, Mapping, Protocol


FilterMatchMode = Literal["and", "or"]

_BLANK_GROUP_VALUE = "(blank)"

FilterAliases = Mapping[str, str] | Iterable[tuple[str, str]]


class _LazyPandas:
    def __getattr__(self, name):
        import importlib

        return getattr(importlib.import_module("pandas"), name)


pd = _LazyPandas()


@dataclass(frozen=True)
class ParsedFilterExpression:
    """Parsed filter expression and compatibility flat spec view."""

    specs: tuple["DataFrameFilterSpec", ...]
    match_mode: FilterMatchMode
    expression: "DataFrameFilterSpec | None" = None
    expression_mode: bool = False

    def mask(self, data_frame: pd.DataFrame) -> pd.Series:
        """Return the parsed expression mask for ``data_frame``."""

        if self.expression is not None:
            return self.expression.mask(data_frame)
        return build_filter_mask(data_frame, self.specs, match_mode=self.match_mode)


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
        self._row_ids_by_key_cache: dict[str, dict[tuple[str, ...], tuple[int, ...]]] = {}

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

    def row_ids_for_keys(
        self,
        selected_group_keys: Iterable[Iterable[Any]] | None,
        *,
        row_id_column: str = "source_row_number",
    ) -> list[int]:
        """Return source row ids for selected grouping keys using a cached key lookup."""

        selected_keys = self._valid_selected_keys(selected_group_keys)
        if not self.active or not selected_keys:
            return []
        lookup = self._row_ids_by_key_lookup(row_id_column)
        row_ids: list[int] = []
        for key in sorted(selected_keys):
            row_ids.extend(lookup.get(key, ()))
        return row_ids

    def row_ids_by_key(
        self,
        selected_group_keys: Iterable[Iterable[Any]] | None = None,
        *,
        row_id_column: str = "source_row_number",
    ) -> dict[tuple[str, ...], tuple[int, ...]]:
        """Return cached source row ids keyed by normalized grouping key."""

        if not self.active:
            return {}
        lookup = self._row_ids_by_key_lookup(row_id_column)
        if selected_group_keys is None:
            return dict(lookup)
        selected_keys = self._valid_selected_keys(selected_group_keys)
        return {key: lookup.get(key, ()) for key in selected_keys if key in lookup}

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
            self.key_frame.groupby(list(self.grouping_columns), dropna=False, sort=False)
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

    def _row_ids_by_key_lookup(self, row_id_column: str) -> dict[tuple[str, ...], tuple[int, ...]]:
        column = str(row_id_column)
        if column in self._row_ids_by_key_cache:
            return self._row_ids_by_key_cache[column]
        if not self.active or column not in self.data_frame.columns or self.key_frame.empty:
            self._row_ids_by_key_cache[column] = {}
            return self._row_ids_by_key_cache[column]

        row_numbers = pd.to_numeric(self.data_frame[column], errors="coerce")
        valid_mask = row_numbers.notna()
        lookup: dict[tuple[str, ...], list[int]] = {}
        key_rows = self.key_frame.loc[valid_mask, list(self.grouping_columns)].itertuples(
            index=False,
            name=None,
        )
        row_ids = row_numbers.loc[valid_mask].astype(int).tolist()
        for key_values, row_id in zip(key_rows, row_ids, strict=False):
            key = tuple(str(value) for value in key_values)
            lookup.setdefault(key, []).append(int(row_id))
        self._row_ids_by_key_cache[column] = {
            key: tuple(sorted(dict.fromkeys(row_ids)))
            for key, row_ids in lookup.items()
        }
        return self._row_ids_by_key_cache[column]

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
    wildcards: bool = False

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
            if self.wildcards and _has_text_wildcard(needle):
                return _wildcard_text_mask(text, needle)
            return text.eq(needle).fillna(False)
        if operator == "not_equals":
            if self.wildcards and _has_text_wildcard(needle):
                return ~_wildcard_text_mask(text, needle)
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


@dataclass(frozen=True)
class MembershipFilterSpec:
    """Membership filter for one DataFrame column."""

    column: str
    values: tuple[Any, ...]
    negate: bool = False
    case_sensitive: bool = False
    wildcards: bool = True
    dayfirst: bool = False
    operator: str = "in"

    def mask(self, data_frame: pd.DataFrame) -> pd.Series:
        _require_column(data_frame, self.column)
        values = tuple(value for value in self.values if str(value).strip() != "")
        if not values:
            raise ValueError("IN filters require at least one value")

        value_kind = _membership_value_kind(values, dayfirst=self.dayfirst)
        if value_kind == "number":
            numbers = pd.to_numeric(data_frame[self.column], errors="coerce")
            parsed_values = [_coerce_number(value, field_name="IN value") for value in values]
            mask = numbers.isin(parsed_values).fillna(False)
        elif value_kind == "date":
            dates = _coerce_date_series(data_frame[self.column], dayfirst=self.dayfirst)
            parsed_dates = [
                _coerce_date(value, dayfirst=self.dayfirst, field_name="IN value")
                for value in values
            ]
            mask = dates.isin(parsed_dates).fillna(False)
        else:
            text = data_frame[self.column].astype("string")
            normalized_values = tuple(str(value) for value in values)
            if not self.case_sensitive:
                text = text.str.casefold()
                normalized_values = tuple(value.casefold() for value in normalized_values)
            exact_values = {
                value for value in normalized_values if not (self.wildcards and _has_text_wildcard(value))
            }
            mask = text.isin(exact_values).fillna(False) if exact_values else pd.Series(
                False,
                index=data_frame.index,
            )
            if self.wildcards:
                for pattern in normalized_values:
                    if _has_text_wildcard(pattern):
                        mask |= _wildcard_text_mask(text, pattern)
        negate = self.negate or str(self.operator or "").strip().casefold() == "not_in"
        return ~mask if negate else mask


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
    aliases: FilterAliases | None = None,
) -> ParsedFilterExpression:
    """Parse ``Column >= value AND (Other = value OR Third != x*)`` expressions."""

    text = str(expression or "").strip()
    if not text:
        return ParsedFilterExpression(specs=(), match_mode="and")

    parser = _FilterExpressionParser(
        _tokenize_filter_expression(text),
        columns,
        dayfirst=dayfirst,
        aliases=aliases,
    )
    expression_spec = parser.parse()
    specs, match_mode = _flatten_filter_expression(expression_spec)
    return ParsedFilterExpression(
        specs=specs,
        match_mode=match_mode,
        expression=expression_spec,
        expression_mode=True,
    )


def looks_like_filter_expression(expression: str) -> bool:
    """Return whether text appears to contain symbolic filter expression syntax."""

    text = str(expression or "")
    if not text.strip():
        return False
    try:
        tokens = _tokenize_filter_expression(text)
        return any(token.kind == "OP" for token in tokens) or _contains_membership_operator_tokens(tokens)
    except ValueError:
        return _contains_symbolic_operator(text)


def resolve_filter_column(
    column: str,
    columns: Iterable[str],
    *,
    aliases: FilterAliases | None = None,
) -> str:
    """Resolve a typed or displayed filter column name against DataFrame columns."""

    requested = _undelimit_filter_field(str(column or "").strip())
    column_list = tuple(str(item) for item in columns)
    resolved = _find_column_match(requested, column_list)
    if resolved is not None:
        return resolved

    requested_key = requested.casefold()
    for alias, target in _iter_filter_aliases(aliases):
        if str(alias).strip().casefold() != requested_key:
            continue
        target_text = str(target).strip()
        resolved = _find_column_match(target_text, column_list)
        if resolved is None:
            raise KeyError(f"Filter alias {alias!r} points to missing DataFrame column: {target}")
        return resolved

    raise KeyError(f"DataFrame column not found: {requested}")


@dataclass(frozen=True)
class FilterExpressionGroup:
    """Boolean expression group that can be used wherever a filter spec is accepted."""

    operator: FilterMatchMode
    children: tuple[DataFrameFilterSpec, ...]
    column: str = ""

    def mask(self, data_frame: pd.DataFrame) -> pd.Series:
        return build_filter_mask(data_frame, self.children, match_mode=self.operator)


@dataclass(frozen=True)
class _FilterToken:
    kind: str
    value: str
    position: int


class _FilterExpressionParser:
    def __init__(
        self,
        tokens: tuple[_FilterToken, ...],
        columns: Iterable[str],
        *,
        dayfirst: bool,
        aliases: FilterAliases | None,
    ) -> None:
        self._tokens = tokens
        self._index = 0
        self._columns = tuple(columns)
        self._dayfirst = dayfirst
        self._aliases = aliases

    def parse(self) -> DataFrameFilterSpec:
        if not self._tokens:
            raise ValueError("Grouping filter expression is empty.")
        expression = self._parse_or()
        if self._peek() is not None:
            token = self._peek()
            raise ValueError(f"Unexpected token in grouping filter expression: {token.value}")
        return expression

    def _parse_or(self) -> DataFrameFilterSpec:
        node = self._parse_and()
        children = [node]
        while self._match("OR") is not None:
            children.append(self._parse_and())
        if len(children) == 1:
            return node
        return FilterExpressionGroup("or", tuple(children))

    def _parse_and(self) -> DataFrameFilterSpec:
        node = self._parse_primary()
        children = [node]
        while self._match("AND") is not None:
            children.append(self._parse_primary())
        if len(children) == 1:
            return node
        return FilterExpressionGroup("and", tuple(children))

    def _parse_primary(self) -> DataFrameFilterSpec:
        if self._match("LPAREN") is not None:
            expression = self._parse_or()
            if self._match("RPAREN") is None:
                raise ValueError("Missing closing ')' in grouping filter expression.")
            return expression
        return self._parse_condition()

    def _parse_condition(self) -> DataFrameFilterSpec:
        field_tokens: list[_FilterToken] = []
        while (
            (token := self._peek()) is not None
            and token.kind != "OP"
            and not self._is_membership_operator_start()
        ):
            if token.kind in {"AND", "OR", "RPAREN", "LPAREN", "COMMA"}:
                raise ValueError(f"Invalid grouping filter term near: {token.value}")
            field_tokens.append(self._advance())
        if not field_tokens:
            raise ValueError("Missing field name in grouping filter expression.")
        operator_token = self._match("OP")
        if operator_token is None:
            membership_operator = self._match_membership_operator()
            field = _tokens_to_filter_text(field_tokens)
            if membership_operator is None:
                raise ValueError(f"Missing operator for grouping filter field: {field}")
            return _parse_membership_condition(
                field,
                membership_operator,
                self._parse_membership_values(field),
                self._columns,
                dayfirst=self._dayfirst,
                aliases=self._aliases,
            )

        value_tokens: list[_FilterToken] = []
        while (token := self._peek()) is not None and token.kind not in {"AND", "OR", "RPAREN"}:
            if token.kind in {"LPAREN", "OP", "COMMA"}:
                raise ValueError(f"Invalid grouping filter value near: {token.value}")
            value_tokens.append(self._advance())
        if not value_tokens:
            field = _tokens_to_filter_text(field_tokens)
            raise ValueError(f"Missing value for grouping filter field: {field}")

        return _parse_filter_condition(
            _tokens_to_filter_text(field_tokens),
            operator_token.value,
            _tokens_to_filter_text(value_tokens),
            self._columns,
            dayfirst=self._dayfirst,
            aliases=self._aliases,
        )

    def _is_membership_operator_start(self) -> bool:
        token = self._peek()
        if token is None or token.kind != "WORD":
            return False
        keyword = token.value.casefold()
        if keyword == "in":
            return True
        if keyword != "not":
            return False
        next_index = self._index + 1
        if next_index >= len(self._tokens):
            return False
        next_token = self._tokens[next_index]
        return next_token.kind == "WORD" and next_token.value.casefold() == "in"

    def _match_membership_operator(self) -> str | None:
        token = self._peek()
        if token is None or token.kind != "WORD":
            return None
        keyword = token.value.casefold()
        if keyword == "in":
            self._advance()
            return "in"
        if keyword != "not":
            return None
        self._advance()
        next_token = self._peek()
        if next_token is None or next_token.kind != "WORD" or next_token.value.casefold() != "in":
            raise ValueError("Expected IN after NOT in grouping filter expression.")
        self._advance()
        return "not_in"

    def _parse_membership_values(self, field: str) -> tuple[str, ...]:
        if self._match("LPAREN") is None:
            raise ValueError(f"IN filter for grouping filter field {field} requires a parenthesized list.")
        values: list[str] = []
        while True:
            token = self._peek()
            if token is None:
                raise ValueError("Missing closing ')' in grouping filter IN list.")
            if token.kind == "RPAREN":
                if not values:
                    raise ValueError(f"IN filter for grouping filter field {field} requires at least one value.")
                self._advance()
                return tuple(values)

            value_tokens: list[_FilterToken] = []
            while (token := self._peek()) is not None and token.kind not in {"COMMA", "RPAREN"}:
                if token.kind in {"AND", "OR", "LPAREN", "OP"}:
                    raise ValueError(f"Invalid grouping filter IN value near: {token.value}")
                value_tokens.append(self._advance())
            value = _tokens_to_filter_text(value_tokens)
            if not value:
                raise ValueError(f"IN filter for grouping filter field {field} contains an empty value.")
            values.append(value)
            if self._match("COMMA") is not None:
                if self._peek() is None or self._peek().kind == "RPAREN":
                    raise ValueError(f"IN filter for grouping filter field {field} has a trailing comma.")
                continue
            if self._match("RPAREN") is not None:
                return tuple(values)

    def _peek(self) -> _FilterToken | None:
        if self._index >= len(self._tokens):
            return None
        return self._tokens[self._index]

    def _advance(self) -> _FilterToken:
        token = self._tokens[self._index]
        self._index += 1
        return token

    def _match(self, kind: str) -> _FilterToken | None:
        token = self._peek()
        if token is None or token.kind != kind:
            return None
        return self._advance()


def _parse_filter_condition(
    column_text: str,
    operator: str,
    value: str,
    columns: Iterable[str],
    *,
    dayfirst: bool,
    aliases: FilterAliases | None,
) -> DataFrameFilterSpec:
    column = resolve_filter_column(column_text, columns, aliases=aliases)

    looks_date_like = bool(re.search(r"\d{4}", value) or any(marker in value for marker in ("-", "/", ":")))
    date_value = pd.to_datetime(
        pd.Series([value]),
        errors="coerce",
        dayfirst=dayfirst,
        format="mixed",
    ).iloc[0]
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
        return TextFilterSpec(
            column,
            "equals" if operator == "=" else "not_equals",
            value,
            wildcards=True,
        )
    raise ValueError(f"Operator {operator} requires a numeric or date-like value.")


def _parse_membership_condition(
    column_text: str,
    operator: str,
    values: tuple[str, ...],
    columns: Iterable[str],
    *,
    dayfirst: bool,
    aliases: FilterAliases | None,
) -> MembershipFilterSpec:
    column = resolve_filter_column(column_text, columns, aliases=aliases)
    return MembershipFilterSpec(
        column,
        values,
        negate=operator == "not_in",
        wildcards=True,
        dayfirst=dayfirst,
        operator=operator,
    )


def _resolve_filter_column(column: str, columns: Iterable[str]) -> str:
    return resolve_filter_column(column, columns)


def _tokenize_filter_expression(expression: str) -> tuple[_FilterToken, ...]:
    tokens: list[_FilterToken] = []
    index = 0
    text = str(expression or "")
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char == "(":
            tokens.append(_FilterToken("LPAREN", char, index))
            index += 1
            continue
        if char == ")":
            tokens.append(_FilterToken("RPAREN", char, index))
            index += 1
            continue
        if char == ",":
            tokens.append(_FilterToken("COMMA", char, index))
            index += 1
            continue
        two_char = text[index : index + 2]
        if two_char in {">=", "<=", "!="}:
            tokens.append(_FilterToken("OP", two_char, index))
            index += 2
            continue
        if char in {"=", ">", "<"}:
            tokens.append(_FilterToken("OP", char, index))
            index += 1
            continue
        if char in {"'", '"'}:
            value, index = _read_quoted_filter_text(text, index, char, "quoted value")
            tokens.append(_FilterToken("VALUE", value, index))
            continue
        if char == "`":
            value, index = _read_quoted_filter_text(text, index, char, "backtick field")
            tokens.append(_FilterToken("IDENT", value, index))
            continue
        if char == "[":
            value, index = _read_bracket_filter_text(text, index)
            tokens.append(_FilterToken("IDENT", value, index))
            continue

        start = index
        while index < len(text):
            current = text[index]
            if current.isspace() or current in {"(", ")", ",", "`", "[", "'", '"', "=", ">", "<"}:
                break
            if current == "!" and index + 1 < len(text) and text[index + 1] == "=":
                break
            index += 1
        value = text[start:index]
        if not value:
            raise ValueError(f"Invalid character in grouping filter expression: {char}")
        keyword = value.casefold()
        if keyword == "and":
            tokens.append(_FilterToken("AND", value, start))
        elif keyword == "or":
            tokens.append(_FilterToken("OR", value, start))
        else:
            tokens.append(_FilterToken("WORD", value, start))
    return tuple(tokens)


def _read_quoted_filter_text(
    text: str,
    start: int,
    quote: str,
    label: str,
) -> tuple[str, int]:
    value: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            value.append(text[index + 1])
            index += 2
            continue
        if char == quote:
            if index + 1 < len(text) and text[index + 1] == quote:
                value.append(quote)
                index += 2
                continue
            return "".join(value), index + 1
        value.append(char)
        index += 1
    raise ValueError(f"Unterminated {label} in grouping filter expression.")


def _read_bracket_filter_text(text: str, start: int) -> tuple[str, int]:
    value: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "]":
            if index + 1 < len(text) and text[index + 1] == "]":
                value.append(char)
                index += 2
                continue
            return "".join(value), index + 1
        value.append(char)
        index += 1
    raise ValueError("Unterminated bracket field in grouping filter expression.")


def _tokens_to_filter_text(tokens: Iterable[_FilterToken]) -> str:
    return " ".join(token.value for token in tokens).strip()


def _flatten_filter_expression(
    expression: DataFrameFilterSpec,
) -> tuple[tuple[DataFrameFilterSpec, ...], FilterMatchMode]:
    if isinstance(expression, FilterExpressionGroup):
        leaves = _collect_flat_expression_leaves(expression, expression.operator)
        if leaves is not None:
            return tuple(leaves), expression.operator
    return (expression,), "and"


def _collect_flat_expression_leaves(
    expression: DataFrameFilterSpec,
    operator: FilterMatchMode,
) -> list[DataFrameFilterSpec] | None:
    if not isinstance(expression, FilterExpressionGroup):
        return [expression]
    if expression.operator != operator:
        return None

    leaves: list[DataFrameFilterSpec] = []
    for child in expression.children:
        child_leaves = _collect_flat_expression_leaves(child, operator)
        if child_leaves is None:
            return None
        leaves.extend(child_leaves)
    return leaves


def _iter_filter_aliases(aliases: FilterAliases | None) -> tuple[tuple[str, str], ...]:
    if aliases is None:
        return ()
    if isinstance(aliases, Mapping):
        return tuple((str(alias), str(target)) for alias, target in aliases.items())
    return tuple((str(alias), str(target)) for alias, target in aliases)


def _find_column_match(requested: str, columns: Iterable[str]) -> str | None:
    for candidate in columns:
        if candidate == requested:
            return candidate
    requested_key = requested.casefold()
    for candidate in columns:
        if candidate.casefold() == requested_key:
            return candidate
    return None


def _undelimit_filter_field(field: str) -> str:
    text = str(field or "").strip()
    if len(text) >= 2 and text[0] == "`" and text[-1] == "`":
        return text[1:-1].replace("``", "`").strip()
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        return text[1:-1].replace("]]", "]").strip()
    return text


def _contains_symbolic_operator(expression: str) -> bool:
    in_quote: str | None = None
    in_backtick = False
    in_bracket = False
    for index, char in enumerate(expression):
        if in_quote is not None:
            if char == "\\":
                continue
            if char == in_quote:
                in_quote = None
            continue
        if in_backtick:
            if char == "`":
                in_backtick = False
            continue
        if in_bracket:
            if char == "]":
                in_bracket = False
            continue
        if char in {"'", '"'}:
            in_quote = char
            continue
        if char == "`":
            in_backtick = True
            continue
        if char == "[":
            in_bracket = True
            continue
        if char in {"=", ">", "<"}:
            return True
        if char == "!" and index + 1 < len(expression) and expression[index + 1] == "=":
            return True
    return bool(re.search(r"\b(?:not\s+)?in\s*\(", expression, flags=re.IGNORECASE))


def _contains_membership_operator_tokens(tokens: tuple[_FilterToken, ...]) -> bool:
    for index, token in enumerate(tokens):
        if token.kind != "WORD":
            continue
        keyword = token.value.casefold()
        if keyword == "in" and _next_non_word_membership_token_is_list(tokens, index):
            return True
        if keyword == "not" and index + 1 < len(tokens):
            next_token = tokens[index + 1]
            if (
                next_token.kind == "WORD"
                and next_token.value.casefold() == "in"
                and _next_non_word_membership_token_is_list(tokens, index + 1)
            ):
                return True
    return False


def _next_non_word_membership_token_is_list(tokens: tuple[_FilterToken, ...], index: int) -> bool:
    next_index = index + 1
    return next_index < len(tokens) and tokens[next_index].kind == "LPAREN"


def _has_text_wildcard(value: str) -> bool:
    return "*" in str(value)


def _wildcard_text_mask(text: pd.Series, pattern: str) -> pd.Series:
    regex = "^" + ".*".join(re.escape(part) for part in str(pattern).split("*")) + "$"
    return text.str.match(regex, na=False)


def _membership_value_kind(values: tuple[Any, ...], *, dayfirst: bool) -> str:
    if values and all(_looks_date_like(value) for value in values):
        parsed_dates = pd.to_datetime(
            pd.Series(list(values)),
            errors="coerce",
            dayfirst=dayfirst,
            format="mixed",
        )
        if parsed_dates.notna().all():
            return "date"
    parsed_numbers = pd.to_numeric(pd.Series(list(values)), errors="coerce")
    if values and parsed_numbers.notna().all():
        return "number"
    return "text"


def _looks_date_like(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(re.search(r"\d{4}", text) or any(marker in text for marker in ("/", ":")))


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
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=dayfirst, format="mixed")
    if pd.isna(parsed):
        raise ValueError(f"{field_name} must be date-like")
    return pd.Timestamp(parsed).normalize()


def _coerce_date_series(series: pd.Series, *, dayfirst: bool) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=dayfirst, format="mixed").dt.normalize()


def _normalize_match_mode(match_mode: str) -> FilterMatchMode:
    mode = str(match_mode).lower().strip()
    if mode not in {"and", "or"}:
        raise ValueError("match_mode must be 'and' or 'or'")
    return mode  # type: ignore[return-value]
