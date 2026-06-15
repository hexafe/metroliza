"""JSON and SQLite storage normalization for industrial payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
import json
import math
from typing import Any


def json_safe_value(value: Any) -> Any:
    """Return a JSON-serializable representation of database driver scalars."""

    if value is None:
        return None
    if isinstance(value, bool | str | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if _is_missing_scalar(value):
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe_value(nested) for key, nested in value.items()}
    if isinstance(value, set | frozenset):
        return [json_safe_value(item) for item in sorted(value, key=repr)]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [json_safe_value(item) for item in value]

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return json_safe_value(item())
        except (TypeError, ValueError):
            pass

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return json_safe_value(tolist())
        except (TypeError, ValueError):
            pass

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return str(isoformat())
        except (TypeError, ValueError):
            pass

    return str(value)


def to_json_storage_text(value: Any) -> str | None:
    """Serialize a value for JSON text columns after scalar normalization."""

    if value is None:
        return None
    return json.dumps(json_safe_value(value), ensure_ascii=False, sort_keys=True)


def to_sqlite_storage_text(value: Any) -> str | None:
    """Normalize a value for SQLite TEXT bindings."""

    safe_value = json_safe_value(value)
    if safe_value is None:
        return None
    if isinstance(safe_value, dict | list):
        return json.dumps(safe_value, ensure_ascii=False, sort_keys=True)
    return str(safe_value)


def _is_missing_scalar(value: Any) -> bool:
    try:
        if value != value:
            return True
    except (TypeError, ValueError):
        pass

    module_name = type(value).__module__
    if not module_name.startswith(("numpy", "pandas")):
        return False
    try:
        import pandas as pd
    except Exception:
        return False
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(missing, bool):
        return missing
    if type(missing).__module__.startswith("numpy") and type(missing).__name__ == "bool_":
        return bool(missing)
    return False
