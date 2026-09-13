"""Finite filter sources and portable SQLite predicates (no connection setup).

Keep signed/unsigned 64-bit integer sources exact and decimal/exponent sources
as binary64. SQLite cannot store UInt64 natively: the normalized SQL expression
uses padded decimal TEXT for that range only, with exact ordered comparisons.
This is a filter adapter, not a persistence format or arbitrary-precision parser.
"""

from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
import math
import struct
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


@lru_cache(maxsize=4096)
def _exact_sql_number(value: int | float) -> str:
    """Avoid SQLite-version-dependent decimal parsing of binary64 literals."""
    if isinstance(value, int):
        return str(value)
    mantissa, exponent = math.frexp(value)
    significand = int(mantissa * 2**53)
    exponent -= 53
    if not significand:
        return "0.0"
    while significand % 2 == 0:
        significand //= 2
        exponent += 1
    terms = [f"CAST({significand} AS REAL)"]
    operator = "*" if exponent >= 0 else "/"
    remaining = abs(exponent)
    while remaining:
        chunk = min(remaining, 52)
        terms.append(f"{operator}{2**chunk}")
        remaining -= chunk
    return "(" + "".join(terms) + ")"


def _decimal_key(value: Fraction) -> tuple[int, int, str]:
    """Exact finite-decimal comparison key for a compile-time binary fraction."""
    if not value:
        return 0, 0, "0"
    sign = -1 if value < 0 else 1
    numerator = abs(value.numerator)
    places = value.denominator.bit_length() - 1
    digits = str(numerator * 5**places)
    return sign, len(digits) - places - 1, digits.rstrip("0")


@lru_cache(maxsize=4096)
def _rounding_interval(value: float) -> tuple[tuple[int, int, str], tuple[int, int, str], bool]:
    """Exact ties-to-even source interval rounding to one binary64 value."""
    center = Fraction.from_float(value)
    previous = math.nextafter(value, -math.inf)
    following = math.nextafter(value, math.inf)
    lower = (center + Fraction.from_float(previous)) / 2 if math.isfinite(previous) else center - 2**970
    upper = (center + Fraction.from_float(following)) / 2 if math.isfinite(following) else center + 2**970
    even = struct.unpack(">Q", struct.pack(">d", value))[0] % 2 == 0
    return _decimal_key(lower), _decimal_key(upper), even


def _key_sql(key: tuple[int, int, str]) -> tuple[str, str, str]:
    sign, exponent, digits = key
    return str(sign), str(exponent), f"'{digits}'"


def _decimal_compare(operator: str, key: tuple[str, str, str]) -> str:
    sign, exponent, digits = key
    reverse = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "=": "=", "!=": "!="}[operator]
    zero = int(operator in {"=", "<=", ">="})
    return (
        f"(CASE WHEN s != {sign} THEN s {operator} {sign} WHEN s = 0 THEN {zero} "
        f"WHEN s < 0 THEN (k,d COLLATE BINARY) {reverse} ({exponent},{digits}) "
        f"ELSE (k,d COLLATE BINARY) {operator} ({exponent},{digits}) END)"
    )


def _decimal_predicate(operator: str, value: int | float) -> str:
    rounded = float(value)
    if rounded != value:
        # A binary64 source cannot equal an integer strictly between floats.
        if operator in {"=", "!="}:
            return str(int(operator == "!="))
        if rounded < value:
            operator = ">" if operator in {">", ">="} else "<="
        else:
            operator = ">=" if operator in {">", ">="} else "<"
    lower, upper, even = _rounding_interval(rounded)
    low = _decimal_compare(">=" if even else ">", _key_sql(lower))
    high = _decimal_compare("<=" if even else "<", _key_sql(upper))
    if operator == "=":
        return f"({low} AND {high})"
    if operator == "!=":
        return f"NOT ({low} AND {high})"
    if operator == "<":
        return f"NOT {low}"
    if operator == ">=":
        return low
    if operator == ">":
        return f"NOT {high}"
    return high


def sqlite_prefer_integer_source(source_sql: str, sidecar_sql: str) -> str:
    """Use retained exact integers, preserving other established sidecar formats."""
    text = f"trim({source_sql}, char(32,9,10,13,11,12))"
    digits = f"CASE WHEN substr({text},1,1) IN ('+','-') THEN substr({text},2) ELSE {text} END"
    return (f"CASE WHEN typeof({source_sql}) = 'integer' OR (typeof({source_sql}) = 'text' "
            f"AND instr({source_sql},char(0)) = 0 AND ({digits}) <> '' "
            f"AND ({digits}) NOT GLOB '*[^0-9]*') THEN {source_sql} ELSE {sidecar_sql} END")


def _sqlite_normalized_source(column_sql: str) -> str:
    """Normalize integer sources and exact decimal comparison keys, without CAST rounding."""
    # OFFSET prevents SQLite flattening from duplicating tokenization and numeric
    # dispatch into every comparison/interval. LIMIT -1 retains every source row.
    _, overflow_exponent, overflow_digits = _rounding_interval(float.fromhex("0x1.fffffffffffffp+1023"))[1]
    return f"""WITH
        _nf_raw(v) AS (SELECT {column_sql}),
        _nf_trim AS (SELECT v, lower(trim(v, char(32,9,10,13,11,12))) AS t FROM _nf_raw),
        _nf_sign AS (SELECT v, t, CASE WHEN substr(t,1,1) IN ('+','-')
            THEN substr(t,2) ELSE t END AS u FROM _nf_trim),
        _nf_parts AS (SELECT v,t,u,instr(u,'e') AS e,
            CASE WHEN instr(u,'e') > 0 THEN substr(u,1,instr(u,'e')-1) ELSE u END AS m,
            substr(u,instr(u,'e')+1) AS x FROM _nf_sign),
        _nf_digits AS (SELECT v,t,u,e,m,x,
            CASE WHEN substr(x,1,1) IN ('+','-') THEN substr(x,2) ELSE x END AS p,
            ltrim(u,'0') AS z, ltrim(replace(m,'.',''),'0') AS q FROM _nf_parts LIMIT -1 OFFSET 0),
        _nf_valid AS (SELECT *,
            typeof(v) = 'text' AND instr(v,char(0)) = 0
                AND m GLOB '*[0-9]*' AND m NOT GLOB '*[^0-9.]*'
                AND length(m)-length(replace(m,'.','')) <= 1
                AND (e = 0 OR (p <> '' AND p NOT GLOB '*[^0-9]*')) AS ok,
            CASE WHEN q = '' THEN 0 ELSE (CASE WHEN e = 0 THEN 0 ELSE CAST(x AS INTEGER) END)
                + length(q) - (CASE WHEN instr(m,'.') > 0 THEN length(m)-instr(m,'.') ELSE 0 END)-1 END AS k,
            CASE WHEN q = '' THEN 0 WHEN substr(t,1,1) = '-' THEN -1 ELSE 1 END AS s
            FROM _nf_digits),
        _nf_numbers AS (SELECT *, CASE
            WHEN typeof(v) IN ('integer','real') THEN CASE WHEN v-v = 0 THEN v END
            WHEN ok AND u NOT GLOB '*[^0-9]*' THEN CASE
                WHEN length(z) < 19 OR (length(z) = 19 AND z <=
                    CASE WHEN substr(t,1,1) = '-' THEN '9223372036854775808' ELSE '9223372036854775807' END)
                    THEN CAST(t AS INTEGER)
                WHEN substr(t,1,1) <> '-' AND (length(z) = 19 OR
                    (length(z) = 20 AND z <= '18446744073709551615'))
                    THEN substr('00000000000000000000' || z, -20)
                END END AS n FROM _nf_valid LIMIT -1 OFFSET 0)
        SELECT n,s,k, CASE WHEN ok AND n IS NULL AND
            (q = '' OR (k,rtrim(q,'0') COLLATE BINARY) < ({overflow_exponent},'{overflow_digits}'))
            THEN CASE WHEN q = '' THEN '0' ELSE rtrim(q,'0') END END AS d FROM _nf_numbers"""


def _sqlite_comparison(operator: str, value: int | float, params: list[Any] | None) -> str:
    if value < 2**63:
        unsigned = "1" if operator in {">", ">=", "!="} else "0"
    elif value >= 2**64:
        unsigned = "1" if operator in {"<", "<=", "!="} else "0"
    else:
        unsigned = f"n COLLATE BINARY {operator} '{int(value):020d}'"
    literal = _exact_sql_number(value)
    if params is not None:
        params.append(value)
        literal = "?"
    return (f"(CASE WHEN d IS NOT NULL THEN {_decimal_predicate(operator, value)} "
            f"WHEN typeof(n) = 'text' THEN {unsigned} ELSE n {operator} {literal} END)")


def sqlite_numeric_filter(
    column_sql: str, operator: str, value: Any = None, second_value: Any = None,
    *, params: list[Any] | None = None,
) -> str:
    """Compile total finite-number predicates using a validated SQL identifier."""
    operator = operator.strip().lower()
    if operator == "is_blank":
        predicate = "n IS NULL AND d IS NULL"
    elif operator == "is_not_blank":
        predicate = "n IS NOT NULL OR d IS NOT NULL"
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


def _decimal_membership(numbers: tuple[int | float, ...]) -> str:
    rows = []
    for value in dict.fromkeys(numbers):
        rounded = float(value)
        if rounded != value:
            continue
        lower, upper, even = _rounding_interval(rounded)
        rows.append("(" + ",".join((*_key_sql(lower), *_key_sql(upper), str(int(even)))) + ")")
    if not rows:
        return "0"
    low = _decimal_compare(">", ("ls", "lk", "ld"))
    high = _decimal_compare("<", ("us", "uk", "ud"))
    low_equal = _decimal_compare("=", ("ls", "lk", "ld"))
    high_equal = _decimal_compare("=", ("us", "uk", "ud"))
    return ("EXISTS(WITH _nf_bounds(ls,lk,ld,us,uk,ud,closed) AS (VALUES " + ",".join(rows) + ") "
            f"SELECT 1 FROM _nf_bounds WHERE ({low} OR (closed AND {low_equal})) "
            f"AND ({high} OR (closed AND {high_equal})))")


def sqlite_numeric_membership(
    column_sql: str, values: tuple[Any, ...], *, negate: bool, params: list[Any] | None = None,
) -> str:
    """Use the same source normalization and equality for numeric IN / NOT IN."""
    if not values:
        raise ValueError("IN filters require at least one value")
    numbers = tuple(_required_literal(value, "IN value") for value in values)
    if params is None:
        values_sql = ",".join(_exact_sql_number(number) for number in numbers)
    else:
        params.extend(numbers)
        values_sql = ",".join("?" for _ in numbers)
    unsigned_values = sorted({f"'{int(number):020d}'" for number in numbers if 2**63 <= number < 2**64})
    unsigned = f"n COLLATE BINARY IN ({','.join(unsigned_values)})" if unsigned_values else "0"
    predicate = (f"COALESCE(CASE WHEN d IS NOT NULL THEN {_decimal_membership(numbers)} "
                 f"WHEN typeof(n) = 'text' THEN {unsigned} ELSE n IN ({values_sql}) END, 0)")
    if negate:
        predicate = f"NOT ({predicate})"
    return f"(SELECT {predicate} FROM ({_sqlite_normalized_source(column_sql)}))"
