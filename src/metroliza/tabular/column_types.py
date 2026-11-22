"""Explicit CSV Summary column types and a bounded preview of native conversion."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypeAlias, cast

from metroliza.reports.db import quote_identifier, sqlite_readonly_connection_scope

ColumnIdentity: TypeAlias = tuple[str, int]
ColumnType: TypeAlias = Literal["text", "number"]


def normalize_column_types(overrides: Mapping[ColumnIdentity, str] | None) -> dict[ColumnIdentity, ColumnType]:
    if overrides is not None and not isinstance(overrides, Mapping):
        raise ValueError("Nieprawidłowa lista typów kolumn.")
    result: dict[ColumnIdentity, ColumnType] = {}
    for identity, kind in (overrides or {}).items():
        if (not isinstance(identity, tuple) or len(identity) != 2 or not isinstance(identity[0], str)
                or type(identity[1]) is not int or identity[1] < 1 or kind not in ("text", "number")):
            raise ValueError("Nieprawidłowy typ kolumny lub identyfikator nagłówka.")
        result[identity] = cast(ColumnType, kind)
    return result


def column_conversion_examples(loaded, identity: ColumnIdentity, kind: str):
    """Read at most five source values with the exact parsed numbers from the loader."""
    store = loaded.sqlite_store
    field = loaded.source_column_identities[identity]
    numeric = kind == "number" or (kind == "auto" and field in loaded.inferred_metric_columns)
    if store is None:
        return ()
    raw_column = quote_identifier(field)
    converted = quote_identifier(store.numeric_filter_columns[field]) if numeric else raw_column
    table = quote_identifier(store.table_name)
    with sqlite_readonly_connection_scope(store.path) as connection:
        return tuple(connection.execute(f"SELECT {raw_column}, {converted} FROM {table} LIMIT 5"))
