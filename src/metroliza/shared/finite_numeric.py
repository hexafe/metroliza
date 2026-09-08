"""Finite filter sources and portable SQLite predicates (no connection setup).

Keep signed/unsigned 64-bit integer sources exact and decimal/exponent sources
as binary64. SQLite cannot store UInt64 natively: the normalized SQL expression
uses padded decimal TEXT for that range only, with exact ordered comparisons.
This is a filter adapter, not a persistence format or arbitrary-precision parser.
"""

from __future__ import annotations

import math
from numbers import Integral, Real
import re
from typing import Any


_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_UINT64_MAX = 2**64 - 1
_SOURCE_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_INTEGER = re.compile(r"[+-]?[0-9]+")
_SPACE = " \t\n\r\v\f"
_OPERATORS = {
    "equals": "=", "eq": "=", "not_equals": "!=", "ne": "!=",
    "greater_than": ">", "gt": ">", "greater_or_equal": ">=", "gte": ">=",
    "less_than": "<", "lt": "<", "less_or_equal": "<=", "lte": "<=",
}


def finite_numeric_source(value: Any) -> int | float | None:
    """Normalize one supported complete source, without column-wide coercion."""
    if isinstance(value, Integral):
        integer = int(value)
        if _INT64_MIN <= integer <= _UINT64_MAX:
            return integer
    if isinstance(value, Real):
        try:
            number = float(value)
        except OverflowError:
            return None
        return number if math.isfinite(number) else None
    text = str(value).strip(_SPACE)
    if _SOURCE_NUMBER.fullmatch(text) is None:
        return None
    if _INTEGER.fullmatch(text):
        # Bound int parsing even for arbitrarily long strings of leading zeros.
        digits = text.lstrip("+-").lstrip("0") or "0"
        if len(digits) <= 20:
            integer = int(("-" if text.startswith("-") else "") + digits)
            if _INT64_MIN <= integer <= _UINT64_MAX:
                return integer
    number = float(text)
    return number if math.isfinite(number) else None


def parse_numeric_literal(value: Any) -> int | float | None:
    """Retain the existing literal language, preserving signed-64 integers."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    try:
        number = float(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    if _INTEGER.fullmatch(text):
        digits = text.lstrip("+-").lstrip("0") or "0"
        if len(digits) <= 19:
            integer = int(("-" if text.startswith("-") else "") + digits)
            if _INT64_MIN <= integer <= _INT64_MAX:
                return integer
    return number


def _required_literal(value: Any, field_name: str = "value") -> int | float:
    number = parse_numeric_literal(value)
    if number is None:
        raise ValueError(f"{field_name} must be numeric")
    return number


def _sqlite_normalized_source(column_sql: str) -> str:
    """Accept only a trusted, already quoted identifier/expression from adapters."""
    return f"""WITH
        _nf_raw(v) AS (SELECT {column_sql}),
        _nf_trim AS (SELECT v, lower(trim(v, char(32,9,10,13,11,12))) AS t FROM _nf_raw),
        _nf_sign AS (SELECT v, t, CASE WHEN substr(t,1,1) IN ('+','-')
            THEN substr(t,2) ELSE t END AS u FROM _nf_trim),
        _nf_parts AS (SELECT v, t, u, instr(u,'e') AS e,
            CASE WHEN instr(u,'e') > 0 THEN substr(u,1,instr(u,'e')-1) ELSE u END AS m,
            substr(u,instr(u,'e')+1) AS x FROM _nf_sign),
        _nf_digits AS (SELECT v,t,u,e,m,
            CASE WHEN substr(x,1,1) IN ('+','-') THEN substr(x,2) ELSE x END AS p,
            ltrim(u,'0') AS z FROM _nf_parts)
        SELECT CASE
            WHEN typeof(v) IN ('integer','real') THEN
                CASE WHEN v BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308
                    THEN v END
            WHEN typeof(v) = 'text' AND instr(v,char(0)) = 0
                AND m GLOB '*[0-9]*' AND m NOT GLOB '*[^0-9.]*'
                AND length(m)-length(replace(m,'.','')) <= 1
                AND (e = 0 OR (p <> '' AND p NOT GLOB '*[^0-9]*'))
                AND CAST(t AS NUMERIC) BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308
            THEN CASE WHEN substr(t,1,1) <> '-' AND u NOT GLOB '*[^0-9]*'
                AND ((length(z) = 19 AND z >= '9223372036854775808')
                  OR (length(z) = 20 AND z <= '18446744073709551615'))
                THEN substr('00000000000000000000' || z, -20)
                ELSE CAST(t AS NUMERIC) END
            END AS n FROM _nf_digits"""


def _sqlite_comparison(operator: str, value: int | float, params: list[Any] | None) -> str:
    # The TEXT branch is only UInt64 source data. Existing out-of-int64 literals
    # are binary64, hence integral throughout this range. Compare digits exactly.
    if value < 2**63:
        unsigned = "1" if operator in {">", ">=", "!="} else "0"
    elif value >= 2**64:
        unsigned = "1" if operator in {"<", "<=", "!="} else "0"
    else:
        unsigned = f"n COLLATE BINARY {operator} '{int(value):020d}'"
    literal = repr(value)
    if params is not None:
        params.append(value)
        literal = "?"
    return f"(CASE WHEN typeof(n) = 'text' THEN {unsigned} ELSE n {operator} {literal} END)"


def sqlite_numeric_filter(
    column_sql: str, operator: str, value: Any = None, second_value: Any = None,
    *, params: list[Any] | None = None,
) -> str:
    """Compile total finite-number predicates using a validated SQL identifier."""
    operator = operator.strip().lower()
    if operator == "is_blank":
        predicate = "n IS NULL"
    elif operator == "is_not_blank":
        predicate = "n IS NOT NULL"
    elif operator == "between":
        lower, upper = sorted((_required_literal(value), _required_literal(second_value)))
        predicate = f"COALESCE({_sqlite_comparison('>=', lower, params)} AND {_sqlite_comparison('<=', upper, params)}, 0)"
    else:
        sql_operator = _OPERATORS.get(operator)
        if sql_operator is None:
            raise ValueError(f"Unsupported number filter operator: {operator}")
        comparison = _sqlite_comparison(sql_operator, _required_literal(value), params)
        predicate = f"COALESCE({comparison}, {1 if sql_operator == '!=' else 0})"
    return f"(SELECT {predicate} FROM ({_sqlite_normalized_source(column_sql)}))"


def sqlite_numeric_membership(
    column_sql: str, values: tuple[Any, ...], *, negate: bool, params: list[Any] | None = None,
) -> str:
    """Use the same source normalization and equality for numeric IN / NOT IN."""
    if not values:
        raise ValueError("IN filters require at least one value")
    comparisons = [
        _sqlite_comparison("=", _required_literal(value, "IN value"), params) for value in values
    ]
    predicate = "COALESCE((" + " OR ".join(comparisons) + "), 0)"
    if negate:
        predicate = f"NOT ({predicate})"
    return f"(SELECT {predicate} FROM ({_sqlite_normalized_source(column_sql)}))"
