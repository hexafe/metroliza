"""Semantic report identity helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from metroliza.reports.db import sqlite_file_identity
from metroliza.reports.report_metadata_models import CanonicalReportMetadata


@dataclass(frozen=True, slots=True)
class ImportedReportBatch:
    """Committed report IDs and verified source digests in one database file."""

    database: Path
    database_identity: tuple[int, int]
    reports: tuple[tuple[int, str], ...]

    def matches_database(self, database: str | Path | None) -> bool:
        if not database:
            return False
        try:
            path = Path(database).resolve()
        except (OSError, RuntimeError):
            return False
        return path == self.database and sqlite_file_identity(path) == self.database_identity


def _normalize_component(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_report_identity_hash(metadata: CanonicalReportMetadata) -> str:
    components = (
        metadata.parser_id,
        metadata.template_family,
        metadata.template_variant,
        metadata.reference,
        metadata.report_date,
        metadata.report_time,
        metadata.part_name,
        metadata.revision,
        metadata.sample_number,
        metadata.page_count,
    )
    payload = "\x1f".join(_normalize_component(component) for component in components)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
