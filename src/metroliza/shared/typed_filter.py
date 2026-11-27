"""Versioned, catalog-bound filter expressions and reference adapters."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, replace
from datetime import date
from fnmatch import fnmatchcase
from functools import lru_cache
import json
import operator as comparison
import sqlite3
from typing import Any, Generator, Iterable, Literal, Mapping, Protocol

from metroliza.shared.datetime_parsing import parse_datetime_literal
from metroliza.shared.finite_numeric import finite_numeric_source, sqlite_prefer_integer_source
from metroliza.shared.grouping_filter_core import (
    DataFrameFilterSpec,
    FilterExpressionGroup,
    build_filter_mask,
    parse_filter_expression,
)
from metroliza.shared.lazy_modules import LazyPandas


FILTER_VERSION = 1
MAX_FILTER_PREVIEW_ROWS = 1000
FilterKind = Literal["text", "number", "date"]
FilterValue = str | int | float
FilterRowId = int | str
FilterExecutionMode = Literal["in_memory", "sqlite_scan", "sqlite_indexed", "post_filter"]
pd = LazyPandas()

_COMPARISONS = {
    "equals": comparison.eq,
    "not_equals": comparison.ne,
    "less_than": comparison.lt,
    "less_or_equal": comparison.le,
    "greater_than": comparison.gt,
    "greater_or_equal": comparison.ge,
}
_BLANK = frozenset({"is_blank", "is_not_blank"})
_COMMON = _BLANK | {"equals", "not_equals", "in", "not_in"}
_TEXT_OPERATORS = _COMMON | {"contains", "not_contains", "starts_with", "ends_with"}
_ORDERED_OPERATORS = _COMMON | frozenset(_COMPARISONS) | {"between"}
_OPERATORS = {"text": _TEXT_OPERATORS, "number": _ORDERED_OPERATORS, "date": _ORDERED_OPERATORS}
_SYMBOLS = {
    "=": "equals", "!=": "not_equals", "<": "less_than", "<=": "less_or_equal",
    ">": "greater_than", ">=": "greater_or_equal",
}
_NEGATIVE = frozenset({"not_equals", "not_contains", "not_in", "is_blank"})
_GLOB_LITERALS = str.maketrans({"?": "[?]", "[": "[[]", "]": "[]]"})
_SQLITE_FUNCTION = "mz_reference_filter_match"
# Keep right-nested boolean groups within the fixed parser stack of older SQLite builds.
_MAX_DEPTH = 24
_MAX_NODES = 128
_MAX_OPERANDS = 1024


class FilterValidationError(ValueError):
    """A validation failure with a stable code and the affected field/operator."""

    def __init__(self, code: str, detail: str, *, field: str = "", operator: str = ""):
        self.code = code
        self.field = field
        self.operator = operator
        context = f"{field!r} / {operator}: " if operator else f"{field!r}: " if field else ""
        super().__init__(context + detail)


@dataclass(frozen=True)
class FilterField:
    """Stable field ID, display label, logical source and allowed operations."""

    field_id: str
    kind: FilterKind
    label: str
    source: str
    operators: frozenset[str] | None = None

    def __post_init__(self):
        if not _valid_identifier(self.field_id) or self.field_id.strip() != self.field_id:
            raise ValueError(f"Invalid filter field ID: {self.field_id!r}")
        if not all(isinstance(text, str) and text.strip() for text in (self.label, self.source)):
            raise ValueError("A filter field requires a display label and source.")
        defaults = _OPERATORS.get(self.kind)
        if defaults is None:
            raise ValueError(f"Invalid filter field kind: {self.kind!r}")
        allowed = defaults if self.operators is None else frozenset(self.operators)
        if not allowed <= defaults:
            raise ValueError(f"Invalid operators for {self.kind} field {self.field_id!r}")
        object.__setattr__(self, "operators", allowed)


@dataclass(frozen=True)
class FilterCondition:
    """Validated typed leaf produced by the parser or document decoder."""

    column: str
    kind: FilterKind
    operator: str
    values: tuple[FilterValue, ...]
    case_sensitive: bool = False
    wildcards: bool = False
    dayfirst: bool = False

    def mask(self, data_frame):
        try:
            series = data_frame[self.column]
        except KeyError as exc:
            raise FilterValidationError("missing_column", "DataFrame column is missing.", field=self.column) from exc
        if not isinstance(series, pd.Series):
            raise FilterValidationError("ambiguous_column", "DataFrame column is ambiguous.", field=self.column)
        series = series.astype(object)
        matches = _make_matcher(self)
        return pd.Series(
            (matches(value) for value in series.where(series.notna(), None)),
            dtype=bool,
            index=data_frame.index,
        )


@dataclass(frozen=True)
class CompiledSqliteFilter:
    """SQLite WHERE expression with all operands supplied as bound values."""

    sql: str
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class FilterExecution:
    """Where the predicate is evaluated and, for post-filtering, why."""

    mode: FilterExecutionMode
    reason: str = ""

    def __post_init__(self) -> None:
        if self.mode == "post_filter" and not self.reason.strip():
            raise ValueError("Explain why the filter requires post-filtering.")


@dataclass(frozen=True)
class FilterPreview:
    matching_count: int
    sample_row_ids: tuple[FilterRowId, ...]


class PreparedFilter(Protocol):
    """Preview reports an exact count and up to MAX_FILTER_PREVIEW_ROWS ordered row IDs."""

    @property
    def execution(self) -> FilterExecution: ...

    def preview(self, sample_limit: int = 20) -> FilterPreview: ...

    def iter_row_ids(self) -> Generator[FilterRowId, None, None]: ...


class FilterAdapter(Protocol):
    """Bind a validated expression to stable, unique IDs of a single type, sorted ascending."""

    def prepare(self, expression: DataFrameFilterSpec | None) -> PreparedFilter: ...


@dataclass(frozen=True)
class PandasFilterAdapter:
    """Reference source using field IDs as columns and an explicit identity column."""

    frame: Any
    row_id_column: str

    def prepare(self, expression: DataFrameFilterSpec | None) -> PreparedFilter:
        if expression is not None:
            _check_tree_budget(expression, _FilterBudget())
        return _PandasSelection(self.frame, self.row_id_column, expression)


@dataclass(frozen=True)
class _PandasSelection:
    frame: Any
    row_id_column: str
    expression: DataFrameFilterSpec | None
    execution = FilterExecution("in_memory")

    def _selected_ids(self):
        specs = () if self.expression is None else (self.expression,)
        mask = build_filter_mask(self.frame, specs)
        return self.frame.loc[mask, self.row_id_column]

    def preview(self, sample_limit: int = 20) -> FilterPreview:
        _check_sample_limit(sample_limit)
        ids = self._selected_ids()
        sample = tuple(ids.sort_values().iloc[:sample_limit].tolist()) if sample_limit else ()
        return FilterPreview(len(ids), sample)

    def iter_row_ids(self) -> Generator[FilterRowId, None, None]:
        yield from self._selected_ids().sort_values().tolist()


class SqliteFilterAdapter:
    """Reference source over a trusted table or view in a caller-owned connection."""

    def __init__(
        self, connection: sqlite3.Connection, table: str, *, row_id_column: str,
        columns: Mapping[str, str],
    ) -> None:
        if not _valid_identifier(table) or not _valid_identifier(row_id_column):
            raise ValueError("Expected valid SQLite source and identity column names.")
        self._connection = connection
        self._table = _quote(table)
        self._row_id = "source." + _quote(row_id_column)
        self._columns = dict(columns)
        install_typed_filter_sqlite(connection)

    def prepare(self, expression: DataFrameFilterSpec | None) -> PreparedFilter:
        compiled = compile_typed_filter_sqlite(expression, self._columns, table_alias="source")
        scope = f"FROM {self._table} AS source WHERE {compiled.sql}"
        return _SqliteSelection(self._connection, self._row_id, scope, compiled.parameters)


@dataclass(frozen=True)
class _SqliteSelection:
    connection: sqlite3.Connection
    row_id_sql: str
    scope: str
    parameters: tuple[str, ...]
    execution = FilterExecution("sqlite_scan")

    def preview(self, sample_limit: int = 20) -> FilterPreview:
        _check_sample_limit(sample_limit)
        count_sql = "SELECT COUNT(*) " + self.scope
        with closing(self.connection.cursor()) as cursor:
            cursor.row_factory = None
            if sample_limit == 0:
                return FilterPreview(cursor.execute(count_sql, self.parameters).fetchone()[0], ())
            # The independent count and limited, ordered scan share one snapshot.
            preview_sql = self._select_ids(count_sql=count_sql) + " LIMIT ?"
            parameters = (*self.parameters, *self.parameters, sample_limit)
            rows = cursor.execute(preview_sql, parameters).fetchall()
        return FilterPreview(rows[0][1] if rows else 0, tuple(row[0] for row in rows))

    def iter_row_ids(self) -> Generator[FilterRowId, None, None]:
        sql = self._select_ids()
        with closing(self.connection.cursor()) as cursor:
            cursor.row_factory = None
            yield from (row[0] for row in cursor.execute(sql, self.parameters))

    def _select_ids(self, *, count_sql: str | None = None) -> str:
        columns = f"{self.row_id_sql}, ({count_sql})" if count_sql is not None else self.row_id_sql
        order = f"ORDER BY {self.row_id_sql} COLLATE BINARY"
        return " ".join(("SELECT", columns, self.scope, order))


def _check_sample_limit(sample_limit: int) -> None:
    if type(sample_limit) is not int or not 0 <= sample_limit <= MAX_FILTER_PREVIEW_ROWS:
        raise ValueError(f"Use an integer sample limit from zero to {MAX_FILTER_PREVIEW_ROWS}.")


@dataclass
class _FilterBudget:
    nodes: int = 0
    operands: int = 0

    def add_node(self, depth: int = 1) -> None:
        _check_depth(depth)
        self.nodes += 1
        if self.nodes > _MAX_NODES:
            raise FilterValidationError(
                "too_many_nodes", f"Use at most {_MAX_NODES} groups and conditions in total.",
            )

    def add_operands(self, count: int) -> None:
        self.operands += count
        if self.operands > _MAX_OPERANDS:
            raise FilterValidationError("too_many_operands", f"Use at most {_MAX_OPERANDS} filter values in total.")


def _check_depth(depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise FilterValidationError("nested_expression", f"Reduce filter nesting to {_MAX_DEPTH} levels or fewer.")


def _check_token_depth(tokens) -> None:
    depth = 0
    for token in tokens:
        if token.kind == "LPAREN":
            depth += 1
            _check_depth(depth)
        elif token.kind == "RPAREN":
            depth -= 1


def _check_tree_budget(node: DataFrameFilterSpec, budget: _FilterBudget, depth: int = 1) -> None:
    budget.add_node(depth)
    if isinstance(node, FilterExpressionGroup):
        for child in node.children:
            _check_tree_budget(child, budget, depth + 1)
    elif isinstance(node, FilterCondition):
        budget.add_operands(len(node.values))
    else:
        raise TypeError(f"Expected a typed filter, got {type(node).__name__}")


def parse_typed_filter(
    expression: str, fields: Iterable[FilterField], *, dayfirst: bool = False,
) -> DataFrameFilterSpec | None:
    """Apply the Magic grammar with field types chosen by the catalog."""

    catalog = _catalog(fields)
    budget = _FilterBudget()

    def condition(field, operator, values):
        budget.add_node()
        budget.add_operands(len(values))
        item = _resolve_field(field, catalog)
        return _make_condition(
            item, _SYMBOLS.get(operator, operator), values,
            wildcards=item.kind == "text", dayfirst=dayfirst and item.kind == "date",
        )

    root = parse_filter_expression(
        expression, catalog, condition_factory=condition, token_preflight=_check_token_depth,
    ).expression
    if root is not None:
        _check_tree_budget(root, _FilterBudget())
    return root


def dump_typed_filter(expression: DataFrameFilterSpec | None) -> dict[str, Any]:
    """Encode the expression as a locale-independent versioned JSON document."""

    if expression is not None:
        _check_tree_budget(expression, _FilterBudget())
    return {"version": FILTER_VERSION, "expression": _encode(expression) if expression is not None else None}


def load_typed_filter(
    document: Any, fields: Iterable[FilterField], *, remap: Mapping[str, str] | None = None,
) -> DataFrameFilterSpec | None:
    """Bind by exact field ID or explicit remapping, with no label guessing."""

    _require_keys(document, {"version", "expression"})
    if type(document["version"]) is not int or document["version"] != FILTER_VERSION:
        raise FilterValidationError("unsupported_version", "Unsupported filter document version.")
    catalog = _catalog(fields)
    root = document["expression"]
    if root is None:
        return None
    return _decode(root, catalog, remap or {}, {}, _FilterBudget())


def compile_typed_filter_sqlite(
    expression: DataFrameFilterSpec | None, columns: Mapping[str, str], *, table_alias: str,
    numeric_shadows: Mapping[str, str] | None = None,
) -> CompiledSqliteFilter:
    """Compile against trusted SQLite columns and optional already-normalized numeric shadows."""

    if not _valid_identifier(table_alias):
        raise ValueError("Expected a valid SQLite source alias.")
    if expression is not None:
        _check_tree_budget(expression, _FilterBudget())
    params = []
    sql = (_compile_node(expression, columns, _quote(table_alias), params, numeric_shadows or {})
           if expression is not None else "1")
    return CompiledSqliteFilter(sql, tuple(params))


def install_typed_filter_sqlite(connection: sqlite3.Connection) -> None:
    """Install the reference evaluator on this connection only."""

    @lru_cache(maxsize=128)
    def matcher(payload):
        condition = json.loads(payload)
        condition["values"] = tuple(condition["values"])
        return _make_matcher(FilterCondition(column=condition.pop("field"), **condition))

    connection.create_function(
        _SQLITE_FUNCTION, 2, lambda value, payload: int(matcher(payload)(value)), deterministic=True,
    )


def _catalog(fields):
    catalog = {}
    for field in fields:
        if field.field_id in catalog:
            raise FilterValidationError("duplicate_field", "Duplicate filter field ID.", field=field.field_id)
        catalog[field.field_id] = field
    return catalog


def _resolve_field(name, catalog):
    if name in catalog:
        return catalog[name]
    key = name.casefold()
    candidates = [
        field for field in catalog.values()
        if key in (field.field_id.casefold(), field.label.casefold())
    ]
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        raise FilterValidationError("ambiguous_field", "Use the exact field ID.", field=name)
    raise FilterValidationError("missing_field", "Field is missing from the catalog.", field=name)


def _require_keys(value, keys):
    if not isinstance(value, dict) or value.keys() != keys:
        raise FilterValidationError("invalid_document", "Invalid filter document structure.")


def _encode(node):
    if isinstance(node, FilterExpressionGroup):
        return {"operator": node.operator, "children": [_encode(child) for child in node.children]}
    if not isinstance(node, FilterCondition):
        raise TypeError(f"Expected a typed filter, got {type(node).__name__}")
    # Decimal strings preserve UInt64 and binary64 through JSON readers that
    # otherwise round every number to binary64, including JavaScript readers.
    values = [str(value) for value in node.values] if node.kind == "number" else list(node.values)
    return {
        "field": node.column, "kind": node.kind, "operator": node.operator,
        "values": values, "case_sensitive": node.case_sensitive,
        "wildcards": node.wildcards, "dayfirst": node.dayfirst,
    }


def _decode(node, catalog, remap, used_targets, budget, depth=1):
    budget.add_node(depth)
    if isinstance(node, dict) and "children" in node:
        _require_keys(node, {"operator", "children"})
        op, children = node["operator"], node["children"]
        if op not in ("and", "or") or not isinstance(children, list) or not children:
            raise FilterValidationError("invalid_group", "Expected a nonempty AND or OR group.")
        return FilterExpressionGroup(
            op, tuple(_decode(child, catalog, remap, used_targets, budget, depth + 1) for child in children),
        )
    _require_keys(node, {"field", "kind", "operator", "values", "case_sensitive", "wildcards", "dayfirst"})
    field = _bind_field(node, catalog, remap, used_targets)
    values = node["values"]
    if isinstance(values, (list, tuple)):
        budget.add_operands(len(values))
    return _make_condition(
        field, node["operator"], values, case_sensitive=node["case_sensitive"],
        wildcards=node["wildcards"], dayfirst=node["dayfirst"],
    )


def _bind_field(node, catalog, remap, used_targets):
    source = node["field"]
    if not _valid_identifier(source):
        raise FilterValidationError("invalid_field", "Expected a valid field ID.")
    target = remap.get(source, source)
    field = catalog.get(target) if _valid_identifier(target) else None
    if field is None:
        raise FilterValidationError("missing_field", "Field is missing. Choose an explicit remap.", field=source)
    if field.kind != node["kind"]:
        raise FilterValidationError("incompatible_type", f"Expected {node['kind']!r}, found {field.kind}.", field=source)
    if used_targets.setdefault(target, source) != source:
        raise FilterValidationError("remap_collision", f"Another saved field already maps to {target!r}.", field=source)
    return field


def _make_condition(field, operator, values, *, case_sensitive=False, wildcards=False, dayfirst=False):
    def error(code, detail):
        return FilterValidationError(code, detail, field=field.field_id, operator=str(operator))

    if not isinstance(operator, str) or operator not in field.operators:
        raise error("unsupported_operator", f"Operator is unavailable for this {field.kind} field.")
    if not isinstance(values, (list, tuple)) or not _valid_arity(operator, len(values)):
        raise error("invalid_arity", "Wrong number of filter values.")
    if not _valid_options(field.kind, case_sensitive, wildcards, dayfirst):
        raise error("invalid_options", f"Invalid options for a {field.kind} field.")
    condition = FilterCondition(field.field_id, field.kind, operator, (), case_sensitive, wildcards, dayfirst)
    canonical = []
    for index, value in enumerate(values):
        normalized = _operand_value(condition, value)
        if normalized is None:
            raise error("invalid_value", f"Value {index + 1} is not a valid {field.kind} operand.")
        canonical.append(normalized)
    return replace(condition, values=tuple(canonical))


def _valid_arity(operator, count):
    if operator in ("in", "not_in"):
        return count >= 1
    return count == (0 if operator in _BLANK else 2 if operator == "between" else 1)


def _valid_options(kind, case_sensitive, wildcards, dayfirst):
    if any(type(flag) is not bool for flag in (case_sensitive, wildcards, dayfirst)):
        return False
    if kind == "text":
        return not dayfirst
    return not (case_sensitive or wildcards) and (kind == "date" or not dayfirst)


def _operand_value(condition, value):
    if condition.kind == "text":
        return value if isinstance(value, str) else None
    if condition.kind == "number" and type(value) not in (int, float, str):
        return None
    return _source_value(condition, value)


def _source_value(condition, value):
    if value is None:
        return None
    if condition.kind == "number":
        return finite_numeric_source(value)
    if condition.kind == "date":
        parsed = parse_datetime_literal(value, dayfirst=condition.dayfirst) if isinstance(value, (str, date)) else None
        return parsed.date().isoformat() if parsed is not None else None
    text = str(value)
    return text if condition.case_sensitive else text.casefold()


def _make_matcher(condition):
    op = condition.operator
    values = tuple(_source_value(condition, value) for value in condition.values)

    def matches(raw):
        value = _source_value(condition, raw)
        if value is None:
            return op in _NEGATIVE
        if op in _BLANK:
            blank = condition.kind == "text" and not value.strip()
            return blank if op == "is_blank" else not blank
        return match_value(value)

    match_value = _value_test(op, values, condition.wildcards) if op not in _BLANK else None
    return matches


def _value_test(op, values, wildcards):
    if op in {"equals", "not_equals", "in", "not_in"}:
        patterns = tuple(value.translate(_GLOB_LITERALS) for value in values if wildcards and "*" in value)
        literals = frozenset(value for value in values if not (wildcards and "*" in value))

        def matches(value):
            found = value in literals or any(fnmatchcase(value, pattern) for pattern in patterns)
            return not found if op in _NEGATIVE else found

        return matches
    if op == "between":
        lower, upper = sorted(values)
        return lambda value: lower <= value <= upper
    test = _COMPARISONS.get(op) or _TEXT_TESTS[op]
    return lambda value: test(value, values[0])


_TEXT_TESTS = {
    "contains": lambda text, part: part in text,
    "not_contains": lambda text, part: part not in text,
    "starts_with": str.startswith,
    "ends_with": str.endswith,
}


def _valid_identifier(value):
    return isinstance(value, str) and bool(value) and "\0" not in value


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _compile_node(node, columns, source, params, numeric_shadows):
    if isinstance(node, FilterExpressionGroup):
        separator = {"and": " AND ", "or": " OR "}[node.operator]
        return "(" + separator.join(
            _compile_node(child, columns, source, params, numeric_shadows) for child in node.children
        ) + ")"
    leaf = _encode(node)
    column = columns.get(node.column)
    if not _valid_identifier(column):
        raise FilterValidationError("missing_column", "No valid SQLite column mapping.", field=node.column)
    params.append(json.dumps(leaf, ensure_ascii=True, allow_nan=False))
    # Qualification also makes a nonexistent column fail, even with SQLite's
    # double-quoted string compatibility enabled.
    value = f"{source}.{_quote(column)}"
    if node.kind == "number" and node.column in numeric_shadows:
        shadow = numeric_shadows[node.column]
        if not _valid_identifier(shadow):
            raise FilterValidationError("missing_column", "No valid SQLite numeric shadow.", field=node.column)
        value = sqlite_prefer_integer_source(value, f"{source}.{_quote(shadow)}")
    return f"{_SQLITE_FUNCTION}({value}, ?)"
