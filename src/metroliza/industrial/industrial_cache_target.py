"""Storage target helpers for industrial cache workflows."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile

from metroliza.reports.db import SQLiteFileBinding, backup_sqlite_database, sqlite_query_only_connection_scope
from metroliza.shared.sqlite_snapshot import (
    atomic_publish_no_replace,
    is_symlink_or_reparse,
    publish_database_snapshot,
    resolved_database_leaf,
)


# Operator data only: derived CSV Summary tables (metadata, value facets) are
# rebuilt from these rows and alone never need a save-or-discard decision.
_DISPOSABLE_COUNT_QUERIES = {
    "industrial_source_profiles": "SELECT COUNT(*) FROM industrial_source_profiles",
    "industrial_sync_runs": "SELECT COUNT(*) FROM industrial_sync_runs",
    "industrial_sync_staging_records": "SELECT COUNT(*) FROM industrial_sync_staging_records",
    "industrial_records": "SELECT COUNT(*) FROM industrial_records",
    "industrial_record_values": "SELECT COUNT(*) FROM industrial_record_values",
    "industrial_join_rules": "SELECT COUNT(*) FROM industrial_join_rules",
    "industrial_link_candidates": "SELECT COUNT(*) FROM industrial_link_candidates",
    "industrial_stream_offsets": "SELECT COUNT(*) FROM industrial_stream_offsets",
    "industrial_realtime_monitor_configs": (
        "SELECT COUNT(*) FROM industrial_realtime_monitor_configs"
    ),
    "industrial_signal_definitions": "SELECT COUNT(*) FROM industrial_signal_definitions",
    "industrial_samples": "SELECT COUNT(*) FROM industrial_samples",
    "industrial_detector_configs": "SELECT COUNT(*) FROM industrial_detector_configs",
    "industrial_baselines": "SELECT COUNT(*) FROM industrial_baselines",
    "industrial_anomaly_events": "SELECT COUNT(*) FROM industrial_anomaly_events",
    "industrial_realtime_stream_events": (
        "SELECT COUNT(*) FROM industrial_realtime_stream_events"
    ),
    "industrial_realtime_consumer_offsets": (
        "SELECT COUNT(*) FROM industrial_realtime_consumer_offsets"
    ),
    "industrial_realtime_dead_letters": (
        "SELECT COUNT(*) FROM industrial_realtime_dead_letters"
    ),
    "industrial_realtime_source_health": (
        "SELECT COUNT(*) FROM industrial_realtime_source_health"
    ),
    "industrial_model_artifacts": "SELECT COUNT(*) FROM industrial_model_artifacts",
}
_DISPOSABLE_DATA_TABLES = tuple(_DISPOSABLE_COUNT_QUERIES)
_SQLITE_DESTINATION_SUFFIXES = (".db", ".sqlite", ".sqlite3")
_PUBLICATION_PLATFORM = os.name
_is_symlink_or_reparse = is_symlink_or_reparse  # Also used by tabular output publication.


@dataclass(frozen=True)
class IndustrialCacheTarget:
    """Resolved SQLite target for cached industrial rows."""

    mode: str
    cache_db_file: str
    report_db_file: str | None = None
    is_temporary: bool = False

    @property
    def is_report_database(self) -> bool:
        return bool(self.report_db_file)

    @property
    def storage_label(self) -> str:
        if self.mode == "temporary":
            return "Temporary cache"
        if self.mode == "persistent":
            return "Industrial cache DB"
        return "Metroliza DB"

    @property
    def status_prefix(self) -> str:
        if self.mode == "temporary":
            return "Temporary industrial cache"
        if self.mode == "persistent":
            return "Industrial cache database"
        return "Metroliza database industrial cache"


def create_temporary_industrial_cache_target() -> IndustrialCacheTarget:
    """Create a session-scoped SQLite cache file for industrial rows."""

    temp = tempfile.NamedTemporaryFile(
        prefix="metroliza-industrial-cache-",
        suffix=".sqlite",
        delete=False,
    )
    temp.close()
    return IndustrialCacheTarget(
        mode="temporary",
        cache_db_file=temp.name,
        report_db_file=None,
        is_temporary=True,
    )


def existing_metroliza_cache_target(db_file: str | Path) -> IndustrialCacheTarget:
    path = str(db_file)
    return IndustrialCacheTarget(
        mode="existing_metroliza",
        cache_db_file=path,
        report_db_file=path,
        is_temporary=False,
    )


def persistent_industrial_cache_target(db_file: str | Path) -> IndustrialCacheTarget:
    """Return a persistent industrial cache target without report-link context."""

    path = str(db_file)
    return IndustrialCacheTarget(
        mode="persistent",
        cache_db_file=path,
        report_db_file=None,
        is_temporary=False,
    )


def cleanup_temporary_industrial_cache(target: IndustrialCacheTarget | None) -> None:
    """Remove temp SQLite cache files owned by the industrial dialog."""

    if target is None or not target.is_temporary:
        return
    for candidate in (
        Path(target.cache_db_file),
        Path(f"{target.cache_db_file}-wal"),
        Path(f"{target.cache_db_file}-shm"),
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def disposable_cache_counts(database: str | Path) -> dict[str, int]:
    """Return persisted operator-data counts without creating or migrating a database."""

    path = Path(database)
    if not path.is_file():
        return {table: 0 for table in _DISPOSABLE_DATA_TABLES}

    counts = {table: 0 for table in _DISPOSABLE_DATA_TABLES}
    with sqlite_query_only_connection_scope(str(path)) as connection:
        with closing(connection.cursor()) as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            available_tables = {str(row[0]) for row in cursor.fetchall()}
            for table in _DISPOSABLE_DATA_TABLES:
                if table not in available_tables:
                    continue
                cursor.execute(_DISPOSABLE_COUNT_QUERIES[table])
                counts[table] = int(cursor.fetchone()[0])
    return counts


def temporary_cache_contents_summary(counts: dict[str, int]) -> str:
    """Describe retained source records/events/samples without summing EAV rows."""

    if counts.get("unreadable_industrial_cache"):
        return "unknown contents (the temporary cache could not be read)"
    if counts.get("unreadable_realtime_session"):
        return "unknown contents (the temporary realtime session could not be read)"
    units = (
        ("industrial_records", "cached source row(s)"),
        ("industrial_realtime_stream_events", "realtime event(s)"),
        ("industrial_samples", "signal sample(s)"),
    )
    parts = [f"{counts[table]:,} {label}" for table, label in units if counts.get(table)]
    return ", ".join(parts) + " and related data" if parts else "stored configuration or other industrial data"


def temporary_cache_has_data(target: IndustrialCacheTarget | None) -> bool:
    """Return whether a temporary target contains user-relevant persisted rows."""

    if target is None or not target.is_temporary:
        return False
    return any(disposable_cache_counts(target.cache_db_file).values())


def resolve_industrial_cache_destination(destination: str | Path) -> Path:
    """Return the absolute, extension-normalized final cache path."""

    candidate = Path(destination).expanduser()
    if not candidate.name.lower().endswith(_SQLITE_DESTINATION_SUFFIXES):
        candidate = Path(f"{candidate}.db")
    return resolved_database_leaf(candidate)


def _atomic_publish_no_replace(staging_path: Path, destination_path: Path) -> None:
    atomic_publish_no_replace(staging_path, destination_path, platform=_PUBLICATION_PLATFORM)


def persist_temporary_industrial_cache(
    target: IndustrialCacheTarget,
    destination: str | Path,
    *,
    forbidden_destinations: Iterable[str | Path] = (),
) -> IndustrialCacheTarget:
    """Copy a consistent temporary SQLite snapshot into a durable target using backup."""

    if not target.is_temporary:
        raise ValueError("Only a temporary industrial cache can be saved as a durable cache")
    result = publish_verified_database_copy(
        target.cache_db_file, destination, forbidden_destinations=forbidden_destinations,
    )
    return persistent_industrial_cache_target(result)


def publish_verified_database_copy(
    source: str | Path,
    destination: str | Path,
    *,
    forbidden_destinations: Iterable[str | Path] = (),
    validate=None,
    source_binding: SQLiteFileBinding | None = None,
) -> Path:
    """Publish a verified SQLite snapshot to an unused path."""
    if source_binding is not None:
        source_binding.require(source)
    source_path = source_binding.path if source_binding is not None else Path(source).expanduser().resolve()
    destination_path = resolve_industrial_cache_destination(destination)
    forbidden_paths = tuple(
        resolved_database_leaf(candidate)
        for candidate in forbidden_destinations
        if str(candidate or "").strip()
    )
    def write_snapshot(staging):
        if source_binding is None:
            backup_sqlite_database(str(source_path), str(staging))
        else:
            backup_sqlite_database(str(source), str(staging), source_binding=source_binding)

    return publish_database_snapshot(
        source_path,
        destination_path,
        write_snapshot=write_snapshot,
        validate=validate,
        forbidden_paths=forbidden_paths,
        platform=_PUBLICATION_PLATFORM,
        publish=_atomic_publish_no_replace,
    )


__all__ = [
    "IndustrialCacheTarget",
    "cleanup_temporary_industrial_cache",
    "create_temporary_industrial_cache_target",
    "disposable_cache_counts",
    "existing_metroliza_cache_target",
    "persist_temporary_industrial_cache",
    "persistent_industrial_cache_target",
    "resolve_industrial_cache_destination",
    "temporary_cache_has_data",
    "temporary_cache_contents_summary",
]
