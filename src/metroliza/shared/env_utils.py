"""Small helpers for environment-driven feature flags and backend choices."""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import TypeVar


TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})

_T = TypeVar("_T", bound=str)


def env_value(
    name: str,
    *,
    default: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Return a stripped environment value, treating blanks as missing."""

    source = os.environ if env is None else env
    value = source.get(name)
    if value is None:
        return default
    normalized = str(value).strip()
    return normalized if normalized else default


def parse_bool(
    value: object,
    *,
    default: bool = False,
    true_values: set[str] | frozenset[str] | None = None,
    false_values: set[str] | frozenset[str] | None = None,
) -> bool:
    """Parse common boolean-like values with a caller-defined fallback."""

    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    active_true_values = TRUE_VALUES | frozenset(true_values or ())
    active_false_values = FALSE_VALUES | frozenset(false_values or ())
    if normalized in active_true_values:
        return True
    if normalized in active_false_values:
        return False
    return default


def env_bool(
    name: str,
    *,
    default: bool = False,
    env: Mapping[str, str] | None = None,
    true_values: set[str] | frozenset[str] | None = None,
    false_values: set[str] | frozenset[str] | None = None,
) -> bool:
    """Read and parse a boolean environment flag."""

    return parse_bool(
        env_value(name, env=env),
        default=default,
        true_values=true_values,
        false_values=false_values,
    )


def parse_int(value: object, *, default: int | None = None, name: str = "value") -> int | None:
    """Parse an integer value or raise a clear configuration error."""

    if value is None:
        return default
    normalized = str(value).strip()
    if not normalized:
        return default
    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {normalized!r}.") from exc


def env_int(
    name: str,
    *,
    default: int | None = None,
    env: Mapping[str, str] | None = None,
) -> int | None:
    """Read and parse an integer environment variable."""

    return parse_int(env_value(name, env=env), default=default, name=name)


def parse_choice(value: object, *, choices: set[_T] | frozenset[_T], default: _T) -> _T:
    """Normalize a string choice or return the provided default."""

    if value is None:
        return default
    normalized = str(value).strip().lower()
    return normalized if normalized in choices else default


def env_choice(
    name: str,
    *,
    choices: set[_T] | frozenset[_T],
    default: _T,
    env: Mapping[str, str] | None = None,
) -> _T:
    """Read a constrained string choice from the environment."""

    return parse_choice(env_value(name, env=env), choices=choices, default=default)
