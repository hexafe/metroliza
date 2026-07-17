"""File-backed Oznak production-line database source profile configuration."""

from __future__ import annotations

import csv
from collections import OrderedDict
from collections.abc import Sequence
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from metroliza.industrial.industrial_data_repository import (
    IndustrialDataRepository,
    IndustrialSourceProfile,
    looks_sensitive_key,
    utc_timestamp,
)
from metroliza.industrial.industrial_workflow_state import require_identifier


DEFAULT_INDUSTRIAL_SOURCE_CONFIG_PATH = Path.home() / ".metroliza" / "industrial_sources.yaml"
CONFIG_ROOT_KEY = "databases"
_PROFILE_REQUIRED_KEYS = ("type", "host", "port", "database", "table")


class IndustrialSourceConfigError(ValueError):
    """Raised when an industrial source config file is invalid or unsafe."""


def default_industrial_source_config_path() -> Path:
    """Return the default user-editable industrial source config path."""

    return DEFAULT_INDUSTRIAL_SOURCE_CONFIG_PATH


def load_source_profiles_from_config(config_path: str | Path) -> list[IndustrialSourceProfile]:
    """Load non-secret production-line source profiles from an Oznak-style YAML config."""

    path = Path(config_path).expanduser()
    if not path.exists():
        return []
    payload = _read_config_payload(path)
    databases = _databases_mapping(payload, path)
    profiles: list[IndustrialSourceProfile] = []
    for alias, entry in databases.items():
        if not isinstance(entry, Mapping):
            raise IndustrialSourceConfigError(f"Profile '{alias}' in '{path}' must be a mapping.")
        _raise_if_sensitive(entry, profile_alias=str(alias), path=path)
        profiles.append(_profile_from_entry(str(alias), entry, path=path))
    return profiles


def save_source_profiles_to_config(
    config_path: str | Path,
    profiles: Iterable[IndustrialSourceProfile],
) -> None:
    """Replace the config file with the given profile collection."""

    path = Path(config_path).expanduser()
    databases: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for profile in profiles:
        databases[profile.profile_key] = source_profile_to_config_entry(profile)
    _write_config_payload(path, {CONFIG_ROOT_KEY: databases})


def upsert_source_profile_in_config(
    config_path: str | Path,
    profile: IndustrialSourceProfile,
) -> None:
    """Insert or update one source profile in a config file, preserving other entries."""

    path = Path(config_path).expanduser()
    payload: dict[str, Any]
    if path.exists():
        payload = dict(_read_config_payload(path))
        databases = OrderedDict(_databases_mapping(payload, path))
    else:
        payload = {}
        databases = OrderedDict()
    existing = databases.get(profile.profile_key)
    if isinstance(existing, Mapping):
        _raise_if_sensitive(existing, profile_alias=profile.profile_key, path=path)
    databases[profile.profile_key] = source_profile_to_config_entry(
        profile,
        existing=existing if isinstance(existing, Mapping) else None,
    )
    payload[CONFIG_ROOT_KEY] = databases
    _write_config_payload(path, payload)


def import_source_profiles_to_repository(
    config_path: str | Path,
    repository: IndustrialDataRepository,
) -> list[IndustrialSourceProfile]:
    """Load profiles from a config file and upsert them into a Metroliza DB."""

    imported: list[IndustrialSourceProfile] = []
    for profile in load_source_profiles_from_config(config_path):
        imported.append(upsert_source_profile_to_repository(repository, profile))
    return imported


def upsert_source_profile_to_repository(
    repository: IndustrialDataRepository,
    profile: IndustrialSourceProfile,
) -> IndustrialSourceProfile:
    """Persist one file-backed profile into the selected Metroliza report database."""

    return repository.upsert_source_profile(
        profile_key=profile.profile_key,
        profile_name=profile.profile_name,
        source_db_alias=profile.source_db_alias,
        database_type=profile.database_type,
        source_object_name=profile.source_object_name,
        host=profile.host,
        port=profile.port,
        database_name=profile.database_name,
        allowed_columns=profile.allowed_columns,
        timestamp_column=profile.timestamp_column,
        default_pagination_column=profile.default_pagination_column,
        is_enabled=profile.is_enabled,
        order_by_enabled=profile.order_by_enabled,
    )


def source_profile_to_config_entry(
    profile: IndustrialSourceProfile,
    *,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a Metroliza source profile into Oznak `databases` config shape."""

    entry: dict[str, Any] = {}
    if existing:
        entry.update(
            {
                str(key): value
                for key, value in existing.items()
                if not _is_sensitive_key(str(key))
            }
        )
    entry.update(
        {
            "type": profile.database_type,
            "host": profile.host or "",
            "port": int(profile.port) if profile.port is not None else _default_port(profile.database_type),
            "database": profile.database_name or "",
            "table": profile.source_object_name,
        }
    )
    if profile.profile_name and profile.profile_name != profile.profile_key:
        entry["display_name"] = profile.profile_name
    else:
        entry.pop("display_name", None)
    if profile.allowed_columns:
        entry["allowed_columns"] = list(profile.allowed_columns)
    else:
        entry.pop("allowed_columns", None)
    if profile.timestamp_column:
        entry["timestamp_column"] = profile.timestamp_column
    else:
        entry.pop("timestamp_column", None)
    if profile.default_pagination_column:
        entry["pagination_column"] = profile.default_pagination_column
    else:
        entry.pop("pagination_column", None)
    if not profile.order_by_enabled:
        entry["order_by_enabled"] = False
    else:
        entry.pop("order_by_enabled", None)
    return entry


def source_profile_configuration_signature(profile: IndustrialSourceProfile) -> tuple[Any, ...]:
    """Return the durable non-secret fields that identify one profile configuration."""

    return (
        profile.profile_key,
        profile.profile_name,
        profile.source_db_alias,
        profile.database_type,
        profile.host,
        profile.port,
        profile.database_name,
        profile.source_object_name,
        tuple(profile.allowed_columns),
        profile.timestamp_column,
        profile.default_pagination_column,
        bool(profile.is_enabled),
        bool(profile.order_by_enabled),
    )


def build_source_profile(
    *,
    profile_key: str,
    profile_name: str,
    source_db_alias: str,
    database_type: str,
    host: str | None,
    port: int | None,
    database_name: str | None,
    source_object_name: str,
    allowed_columns: Iterable[str] | str | None = None,
    timestamp_column: str | None = None,
    default_pagination_column: str | None = None,
    is_enabled: bool = True,
    order_by_enabled: bool = True,
) -> IndustrialSourceProfile:
    """Build an unsaved source profile after applying shared validation."""

    normalized_key = str(profile_key or "").strip()
    normalized_alias = str(source_db_alias or normalized_key).strip()
    normalized_name = str(profile_name or normalized_key).strip()
    normalized_db_type = str(database_type or "").strip().lower()
    normalized_host = str(host or "").strip()
    normalized_database = str(database_name or "").strip()
    normalized_table = str(source_object_name or "").strip()
    normalized_columns = normalize_source_columns(allowed_columns)
    normalized_timestamp = str(timestamp_column or "").strip() or None
    normalized_pagination = str(default_pagination_column or "").strip() or None

    if normalized_db_type not in {"mysql", "mssql"}:
        raise IndustrialSourceConfigError("Production database type must be mysql or mssql.")
    if not normalized_name:
        raise IndustrialSourceConfigError("Enter a source name.")
    if not normalized_host:
        raise IndustrialSourceConfigError("Enter a production database host.")
    if not normalized_database:
        raise IndustrialSourceConfigError("Enter a production database name.")
    if not normalized_table:
        raise IndustrialSourceConfigError("Enter a production table or view name.")
    if port is None:
        normalized_port = _default_port(normalized_db_type)
    else:
        normalized_port = int(port)
    if normalized_port < 1 or normalized_port > 65535:
        raise IndustrialSourceConfigError("Production database port must be between 1 and 65535.")
    if type(order_by_enabled) is not bool:
        raise IndustrialSourceConfigError("Server ORDER BY setting must be true or false.")

    try:
        for field_name, value in (
            ("source alias", normalized_key),
            ("source database alias", normalized_alias),
            ("database name", normalized_database),
        ):
            require_identifier(field_name, value)
        require_identifier("table/view name", normalized_table)
        for field_name, value in (
            ("record key column", normalized_pagination),
            ("timestamp column", normalized_timestamp),
            *[(f"column '{column}'", column) for column in normalized_columns],
        ):
            if value:
                require_identifier(field_name, value)
    except ValueError as exc:
        raise IndustrialSourceConfigError(str(exc)) from exc

    now = utc_timestamp()
    return IndustrialSourceProfile(
        id=0,
        profile_key=normalized_key,
        profile_name=normalized_name,
        source_db_alias=normalized_alias,
        database_type=normalized_db_type,
        host=normalized_host,
        port=normalized_port,
        database_name=normalized_database,
        source_object_name=normalized_table,
        allowed_columns=normalized_columns,
        timestamp_column=normalized_timestamp,
        default_pagination_column=normalized_pagination,
        is_enabled=bool(is_enabled),
        created_at=now,
        updated_at=now,
        order_by_enabled=bool(order_by_enabled),
    )


def _profile_from_entry(alias: str, entry: Mapping[str, Any], *, path: Path) -> IndustrialSourceProfile:
    missing = [key for key in _PROFILE_REQUIRED_KEYS if key not in entry]
    if missing:
        raise IndustrialSourceConfigError(
            f"Profile '{alias}' in '{path}' is missing required key(s): {', '.join(missing)}."
        )
    return build_source_profile(
        profile_key=alias,
        profile_name=str(entry.get("display_name") or alias),
        source_db_alias=alias,
        database_type=str(entry.get("type") or ""),
        host=str(entry.get("host") or ""),
        port=int(entry["port"]) if entry.get("port") is not None else None,
        database_name=str(entry.get("database") or ""),
        source_object_name=str(entry.get("table") or ""),
        allowed_columns=entry.get("allowed_columns") if "allowed_columns" in entry else (),
        timestamp_column=entry.get("timestamp_column"),
        default_pagination_column=entry.get("pagination_column"),
        order_by_enabled=_bool_config_value(
            entry.get("order_by_enabled", True),
            profile_alias=alias,
            key="order_by_enabled",
            path=path,
        ),
    )


def _read_config_payload(path: Path) -> Mapping[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise IndustrialSourceConfigError(f"Invalid YAML in industrial source config: {path}") from exc
    except OSError as exc:
        raise IndustrialSourceConfigError(f"Could not read industrial source config: {path}") from exc
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise IndustrialSourceConfigError(f"Industrial source config '{path}' must be a mapping.")
    return payload


def _write_config_payload(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(_plain_data(payload), sort_keys=False, allow_unicode=False)
    path.write_text(text, encoding="utf-8")


def _databases_mapping(payload: Mapping[str, Any], path: Path) -> Mapping[str, Any]:
    databases = payload.get(CONFIG_ROOT_KEY)
    if databases is None:
        return {}
    if not isinstance(databases, Mapping):
        raise IndustrialSourceConfigError(
            f"Industrial source config '{path}' must define a top-level 'databases' mapping."
        )
    return databases


def _raise_if_sensitive(entry: Mapping[str, Any], *, profile_alias: str, path: Path) -> None:
    sensitive_paths = sorted(_find_sensitive_paths(entry))
    if sensitive_paths:
        joined = ", ".join(sensitive_paths)
        raise IndustrialSourceConfigError(
            f"Profile '{profile_alias}' in '{path}' contains credential-like key(s): {joined}. "
            "Move credentials to the local credential store or environment variables."
        )


def _find_sensitive_paths(value: Any, *, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if _is_sensitive_key(key_text):
                found.add(path)
            found.update(_find_sensitive_paths(nested, prefix=path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.update(_find_sensitive_paths(nested, prefix=f"{prefix}[{index}]"))
    return found


def _is_sensitive_key(key: str) -> bool:
    return looks_sensitive_key(key)


def _bool_config_value(value: Any, *, profile_alias: str, key: str, path: Path) -> bool:
    if type(value) is bool:
        return value
    raise IndustrialSourceConfigError(
        f"Profile '{profile_alias}' in '{path}' has invalid '{key}': expected true or false."
    )


def normalize_source_columns(columns: Iterable[str] | str | None) -> tuple[str, ...]:
    """Normalize source column input from config files or UI text fields."""

    if columns is None:
        return ()
    if isinstance(columns, str):
        columns = _parse_column_header_string(columns)
    elif isinstance(columns, bytes) or not isinstance(columns, Sequence):
        raise IndustrialSourceConfigError(
            "allowed_columns must be a CSV/header string or a YAML list/sequence of column names."
        )
    if not columns:
        return ()
    seen: set[str] = set()
    normalized: list[str] = []
    for column in columns:
        name = str(column).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    if normalized == ["*"]:
        return ()
    return tuple(normalized)


def _parse_column_header_string(columns: str) -> tuple[str, ...]:
    text = columns.strip()
    if not text or text == "*":
        return ()
    try:
        reader = csv.reader(StringIO(text), skipinitialspace=True, strict=True)
        return tuple(column for row in reader for column in row)
    except csv.Error as exc:
        raise IndustrialSourceConfigError("allowed_columns contains invalid CSV/header text.") from exc


def _default_port(database_type: str) -> int:
    return 3306 if str(database_type).strip().lower() == "mysql" else 1433


def _plain_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_data(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_plain_data(item) for item in value]
    if isinstance(value, list):
        return [_plain_data(item) for item in value]
    return value
