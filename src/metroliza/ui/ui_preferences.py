"""Versioned QSettings storage restricted to harmless UI presentation state."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator, TypeVar

from PyQt6.QtCore import QByteArray, QSettings


T = TypeVar("T")
_UI_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
_ALLOWED_ROOTS = frozenset({"windows", "theme", "accessibility", "presentation"})
_SENSITIVE_SEGMENTS = frozenset(
    {
        "credential",
        "credentials",
        "password",
        "passwords",
        "query",
        "secret",
        "secrets",
        "sql",
        "token",
        "tokens",
    }
)


class UiPreferenceKeyError(ValueError):
    """Raised when a key could contain non-UI or sensitive application state."""


class UiPreferences:
    """Read and write versioned UI-only values with safe fallback behavior.

    Values are stored under a schema-specific namespace.  Invalid or future
    schema metadata is never interpreted as the current schema; reads return
    their supplied defaults until a write intentionally activates the current
    namespace.
    """

    VERSION_KEY = "_schema_version"

    def __init__(
        self,
        settings: QSettings,
        *,
        schema_version: int = 1,
        group: str = "metroliza_ui",
    ) -> None:
        if not isinstance(settings, QSettings):
            raise TypeError("UiPreferences requires a QSettings instance.")
        if isinstance(schema_version, bool) or int(schema_version) < 1:
            raise ValueError("UI preference schema version must be a positive integer.")
        if not str(group or "").strip():
            raise ValueError("UI preference group must not be empty.")
        self._settings = settings
        self._schema_version = int(schema_version)
        self._group = str(group).strip()
        self._stored_schema_version: int | None = None
        self._schema_healthy = False
        self._corrupt_keys: set[str] = set()
        self._last_error = ""
        self._inspect_schema()

    @property
    def schema_version(self) -> int:
        return self._schema_version

    @property
    def stored_schema_version(self) -> int | None:
        return self._stored_schema_version

    @property
    def schema_healthy(self) -> bool:
        return self._schema_healthy

    @property
    def corrupt_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._corrupt_keys))

    @property
    def last_error(self) -> str:
        return self._last_error

    def get(
        self,
        key: str,
        default: T,
        *,
        expected_type: type[T] | tuple[type, ...] | None = None,
    ) -> T:
        """Return a typed UI value or the caller's safe default."""

        normalized_key = _validate_ui_key(key)
        if not self._schema_healthy:
            return default
        with self._in_group():
            payload_key = self._payload_key(normalized_key)
            if not self._settings.contains(payload_key):
                return default
            value = self._settings.value(payload_key)
        effective_type = expected_type
        if effective_type is None and default is not None:
            effective_type = type(default)
        if effective_type is not None and not isinstance(value, effective_type):
            self._corrupt_keys.add(normalized_key)
            self._last_error = f"Invalid value type for UI preference {normalized_key!r}."
            return default
        if not _is_safe_ui_value(value):
            self._corrupt_keys.add(normalized_key)
            self._last_error = f"Unsupported value type for UI preference {normalized_key!r}."
            return default
        return value

    def set(self, key: str, value: object) -> bool:
        """Persist a UI-only value, recovering into the current schema if needed."""

        normalized_key = _validate_ui_key(key)
        if not _is_safe_ui_value(value):
            raise TypeError("UI preferences support only scalar, byte-array, and scalar-list values.")
        if not self._ensure_current_schema():
            return False
        with self._in_group():
            self._settings.setValue(self._payload_key(normalized_key), value)
        self._corrupt_keys.discard(normalized_key)
        return self.sync()

    def remove(self, key: str) -> bool:
        normalized_key = _validate_ui_key(key)
        if not self._schema_healthy:
            return False
        with self._in_group():
            self._settings.remove(self._payload_key(normalized_key))
        self._corrupt_keys.discard(normalized_key)
        return self.sync()

    def reset(self) -> bool:
        """Remove this UI group only and initialize a clean current schema."""

        with self._in_group():
            self._settings.remove("")
            self._settings.setValue(self.VERSION_KEY, self._schema_version)
        self._stored_schema_version = self._schema_version
        self._schema_healthy = True
        self._corrupt_keys.clear()
        self._last_error = ""
        return self.sync()

    def sync(self) -> bool:
        self._settings.sync()
        status = self._settings.status()
        if status is QSettings.Status.NoError:
            return True
        self._schema_healthy = False
        self._last_error = f"QSettings status is {status.name}."
        return False

    def _inspect_schema(self) -> None:
        if self._settings.status() is not QSettings.Status.NoError:
            self._last_error = f"QSettings status is {self._settings.status().name}."
            return
        with self._in_group():
            if not self._settings.contains(self.VERSION_KEY):
                self._settings.setValue(self.VERSION_KEY, self._schema_version)
                raw_version: object = self._schema_version
            else:
                raw_version = self._settings.value(self.VERSION_KEY)
        parsed_version = _strict_positive_int(raw_version)
        self._stored_schema_version = parsed_version
        if parsed_version != self._schema_version:
            self._last_error = "UI preference schema is invalid or incompatible."
            return
        self._schema_healthy = self.sync()

    def _ensure_current_schema(self) -> bool:
        if self._schema_healthy:
            return True
        if self._settings.status() is not QSettings.Status.NoError:
            return False
        with self._in_group():
            self._settings.remove(f"v{self._schema_version}")
            self._settings.setValue(self.VERSION_KEY, self._schema_version)
        self._stored_schema_version = self._schema_version
        self._schema_healthy = True
        self._corrupt_keys.clear()
        self._last_error = ""
        return self.sync()

    def _payload_key(self, key: str) -> str:
        return f"v{self._schema_version}/{key}"

    @contextmanager
    def _in_group(self) -> Iterator[None]:
        self._settings.beginGroup(self._group)
        try:
            yield
        finally:
            self._settings.endGroup()


def _validate_ui_key(key: str) -> str:
    normalized = str(key or "").strip()
    if not normalized or _UI_KEY_PATTERN.fullmatch(normalized) is None:
        raise UiPreferenceKeyError("UI preference key must be a slash-separated identifier.")
    segments = tuple(segment.lower() for segment in normalized.split("/"))
    if segments[0] not in _ALLOWED_ROOTS:
        raise UiPreferenceKeyError(
            "UI preference keys must start with windows, theme, accessibility, or presentation."
        )
    if any(segment in _SENSITIVE_SEGMENTS for segment in segments):
        raise UiPreferenceKeyError("Sensitive or domain data cannot be stored as a UI preference.")
    return normalized


def _strict_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed >= 1 else None
    return None


def _is_safe_ui_value(value: object) -> bool:
    if isinstance(value, (str, bool, int, float, bytes, QByteArray)):
        return True
    if isinstance(value, (list, tuple)):
        return all(isinstance(item, (str, bool, int, float, bytes, QByteArray)) for item in value)
    return False


__all__ = ["UiPreferenceKeyError", "UiPreferences"]
