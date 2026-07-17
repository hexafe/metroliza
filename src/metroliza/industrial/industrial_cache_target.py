"""Storage target helpers for industrial cache workflows."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import tempfile

from metroliza.reports.db import backup_sqlite_database, sqlite_connection_scope


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
    with sqlite_connection_scope(str(path)) as connection:
        with closing(connection.cursor()) as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            available_tables = {str(row[0]) for row in cursor.fetchall()}
            for table in _DISPOSABLE_DATA_TABLES:
                if table not in available_tables:
                    continue
                cursor.execute(_DISPOSABLE_COUNT_QUERIES[table])
                counts[table] = int(cursor.fetchone()[0])
    return counts


def temporary_cache_has_data(target: IndustrialCacheTarget | None) -> bool:
    """Return whether a temporary target contains user-relevant persisted rows."""

    if target is None or not target.is_temporary:
        return False
    return any(disposable_cache_counts(target.cache_db_file).values())


def persist_temporary_industrial_cache(
    target: IndustrialCacheTarget,
    destination: str | Path,
    *,
    forbidden_destinations: Iterable[str | Path] = (),
) -> IndustrialCacheTarget:
    """Copy a consistent temporary SQLite snapshot into a durable target using backup."""

    if not target.is_temporary:
        raise ValueError("Only a temporary industrial cache can be saved as a durable cache")
    source_path = Path(target.cache_db_file).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if source_path == destination_path:
        raise ValueError("Choose a destination outside the temporary cache")
    reserved_paths = {
        Path(candidate).expanduser().resolve()
        for candidate in forbidden_destinations
        if str(candidate or "").strip()
    }
    if destination_path in reserved_paths:
        raise ValueError(
            "Choose a separate cache archive; an active Metroliza database cannot be replaced"
        )
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    # Build and validate a sibling snapshot first.  Writing directly into an
    # existing destination could corrupt the user's prior cache if backup or
    # validation failed halfway through.
    staging_handle = tempfile.NamedTemporaryFile(
        prefix=f".{destination_path.name}.",
        suffix=".saving",
        dir=destination_path.parent,
        delete=False,
    )
    staging_path = Path(staging_handle.name)
    staging_handle.close()
    try:
        backup_sqlite_database(str(source_path), str(staging_path))
        staging_path.replace(destination_path)
    finally:
        for candidate in (
            staging_path,
            Path(f"{staging_path}-wal"),
            Path(f"{staging_path}-shm"),
        ):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass

    return persistent_industrial_cache_target(destination_path)


__all__ = [
    "IndustrialCacheTarget",
    "cleanup_temporary_industrial_cache",
    "create_temporary_industrial_cache_target",
    "disposable_cache_counts",
    "existing_metroliza_cache_target",
    "persist_temporary_industrial_cache",
    "persistent_industrial_cache_target",
    "temporary_cache_has_data",
]
