"""Compatibility wrapper for report metadata persistence.

Persistence ownership stays in :mod:`modules.report_repository`; this module
only preserves a stable import location for callers that still expect a
dedicated metadata persistence layer.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from modules.report_repository import ReportRepository

__all__ = [
    "ReportMetadataPersistence",
    "persist_parsed_report",
]


class ReportMetadataPersistence:
    """Thin delegate around :class:`modules.report_repository.ReportRepository`."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection
        self._repository = ReportRepository(database, connection=connection)

    def ensure_schema(self) -> None:
        return self._repository.ensure_schema()

    def upsert_source_file(
        self,
        source_path: str | Path,
        *,
        sha256: str | None = None,
        source_format: str | None = None,
        discovered_at: str | None = None,
        ingested_at: str | None = None,
    ):
        return self._repository.upsert_source_file(
            source_path,
            sha256=sha256,
            source_format=source_format,
            discovered_at=discovered_at,
            ingested_at=ingested_at,
        )

    def upsert_parsed_report(self, **kwargs) -> int:
        return self._repository.upsert_parsed_report(**kwargs)

    def replace_report_metadata(
        self,
        report_id: int,
        metadata: Any,
        *,
        metadata_version: str,
        metadata_profile_id: str | None = None,
        metadata_profile_version: str | None = None,
    ) -> None:
        return self._repository.replace_report_metadata(
            report_id,
            metadata,
            metadata_version=metadata_version,
            metadata_profile_id=metadata_profile_id,
            metadata_profile_version=metadata_profile_version,
        )

    def replace_metadata_candidates(self, report_id: int, candidates: Iterable[Any]) -> None:
        return self._repository.replace_metadata_candidates(report_id, candidates)

    def replace_metadata_warnings(self, report_id: int, warnings: Iterable[Any]) -> None:
        return self._repository.replace_metadata_warnings(report_id, warnings)

    def replace_measurements(self, report_id: int, measurements: Iterable[Any]) -> None:
        return self._repository.replace_measurements(report_id, measurements)

    def persist_semantic_duplicate_warnings(self, report_id: int, identity_hash: str | None) -> int:
        return self._repository.persist_semantic_duplicate_warnings(report_id, identity_hash)

    def persist_parsed_report(self, **kwargs) -> int:
        return self._repository.persist_parsed_report(**kwargs)


def persist_parsed_report(database: str | Path, *, connection=None, **kwargs) -> int:
    """Persist a parsed report through the repository-backed compatibility layer."""

    return ReportMetadataPersistence(database, connection=connection).persist_parsed_report(**kwargs)
