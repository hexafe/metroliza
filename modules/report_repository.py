"""Transactional repository helpers for report ingestion storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
from typing import Any, Iterable

from modules.db import run_transaction_with_retry
from modules.report_schema import ensure_report_schema


SEMANTIC_DUPLICATE_WARNING_CODE = "semantic_duplicate_identity_hash_detected"


@dataclass(frozen=True)
class SourceFileRecord:
    """Physical source-file descriptor keyed by content hash."""

    id: int
    sha256: str
    absolute_path: str
    directory_path: str
    file_name: str
    file_extension: str
    source_format: str


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp suitable for SQLite text columns."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compute_sha256(file_path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Compute the SHA-256 digest for a file path."""

    digest = hashlib.sha256()
    with open(file_path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_source_format(file_path: str | Path) -> str:
    """Infer a neutral source format from a file suffix."""

    suffix = Path(file_path).suffix.lower().lstrip(".")
    return suffix or "unknown"


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)

    result: dict[str, Any] = {}
    for name in dir(value):
        if name.startswith("_"):
            continue
        try:
            attr_value = getattr(value, name)
        except Exception:
            continue
        if callable(attr_value):
            continue
        result[name] = attr_value
    return result


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _coerce_bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ReportRepository:
    """Persistence facade for the report metadata schema."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_report_schema(self.database, connection=self.connection)

    def upsert_source_file(
        self,
        source_path: str | Path,
        *,
        sha256: str | None = None,
        source_format: str | None = None,
        discovered_at: str | None = None,
        ingested_at: str | None = None,
    ) -> SourceFileRecord:
        """Insert or refresh source content and its path location."""

        path = Path(source_path).resolve()
        stat_result = path.stat() if path.is_file() else None
        digest = sha256 or (
            compute_sha256(path)
            if stat_result is not None
            else hashlib.sha256(str(path).encode("utf-8")).hexdigest()
        )
        detected_format = source_format or infer_source_format(path)
        discovered_value = discovered_at or utc_timestamp()
        modified_at = (
            datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if stat_result is not None
            else None
        )

        def _upsert(cursor) -> SourceFileRecord:
            cursor.execute(
                """
                INSERT INTO source_files (
                    sha256, file_size_bytes, source_format, discovered_at, ingested_at, is_active
                )
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(sha256) DO UPDATE SET
                    file_size_bytes = excluded.file_size_bytes,
                    source_format = excluded.source_format,
                    discovered_at = excluded.discovered_at,
                    ingested_at = COALESCE(excluded.ingested_at, source_files.ingested_at),
                    is_active = 1
                """,
                (digest, stat_result.st_size if stat_result is not None else None, detected_format, discovered_value, ingested_at),
            )
            cursor.execute("SELECT id FROM source_files WHERE sha256 = ?", (digest,))
            source_file_id = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO source_file_locations (
                    source_file_id,
                    absolute_path,
                    directory_path,
                    file_name,
                    file_extension,
                    file_modified_at,
                    discovered_at,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(source_file_id, absolute_path) DO UPDATE SET
                    directory_path = excluded.directory_path,
                    file_name = excluded.file_name,
                    file_extension = excluded.file_extension,
                    file_modified_at = excluded.file_modified_at,
                    discovered_at = excluded.discovered_at,
                    is_active = 1
                """,
                (
                    source_file_id,
                    str(path),
                    str(path.parent),
                    path.name,
                    path.suffix.lower(),
                    modified_at,
                    discovered_value,
                ),
            )
            return SourceFileRecord(
                id=source_file_id,
                sha256=digest,
                absolute_path=str(path),
                directory_path=str(path.parent),
                file_name=path.name,
                file_extension=path.suffix.lower(),
                source_format=detected_format,
            )

        return run_transaction_with_retry(self.database, _upsert, connection=self.connection)

    def upsert_parsed_report(
        self,
        *,
        source_file_id: int,
        parser_id: str,
        template_family: str,
        parse_status: str,
        parser_version: str | None = None,
        template_variant: str | None = None,
        parse_started_at: str | None = None,
        parse_finished_at: str | None = None,
        parse_duration_ms: int | None = None,
        page_count: int | None = None,
        measurement_count: int = 0,
        has_nok: bool = False,
        nok_count: int = 0,
        metadata_confidence: float | None = None,
        identity_hash: str | None = None,
        raw_report_json: Any = None,
    ) -> int:
        """Create or replace the parsed-report process row for one source file."""

        now = utc_timestamp()

        def _upsert(cursor) -> int:
            cursor.execute(
                """
                INSERT INTO parsed_reports (
                    source_file_id,
                    parser_id,
                    parser_version,
                    template_family,
                    template_variant,
                    parse_status,
                    parse_started_at,
                    parse_finished_at,
                    parse_duration_ms,
                    page_count,
                    measurement_count,
                    has_nok,
                    nok_count,
                    metadata_confidence,
                    identity_hash,
                    raw_report_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_file_id) DO UPDATE SET
                    parser_id = excluded.parser_id,
                    parser_version = excluded.parser_version,
                    template_family = excluded.template_family,
                    template_variant = excluded.template_variant,
                    parse_status = excluded.parse_status,
                    parse_started_at = excluded.parse_started_at,
                    parse_finished_at = excluded.parse_finished_at,
                    parse_duration_ms = excluded.parse_duration_ms,
                    page_count = excluded.page_count,
                    measurement_count = excluded.measurement_count,
                    has_nok = excluded.has_nok,
                    nok_count = excluded.nok_count,
                    metadata_confidence = excluded.metadata_confidence,
                    identity_hash = excluded.identity_hash,
                    raw_report_json = excluded.raw_report_json,
                    updated_at = excluded.updated_at
                """,
                (
                    int(source_file_id),
                    parser_id,
                    parser_version,
                    template_family,
                    template_variant,
                    parse_status,
                    parse_started_at,
                    parse_finished_at,
                    parse_duration_ms,
                    page_count,
                    int(measurement_count),
                    _coerce_bool_int(has_nok),
                    int(nok_count),
                    metadata_confidence,
                    identity_hash,
                    _to_json(raw_report_json),
                    now,
                    now,
                ),
            )
            cursor.execute("SELECT id FROM parsed_reports WHERE source_file_id = ?", (int(source_file_id),))
            report_id = int(cursor.fetchone()[0])
            cursor.execute("DELETE FROM report_measurements WHERE report_id = ?", (report_id,))
            cursor.execute("DELETE FROM report_metadata_candidates WHERE report_id = ?", (report_id,))
            cursor.execute("DELETE FROM report_metadata_warnings WHERE report_id = ?", (report_id,))
            return report_id

        return run_transaction_with_retry(self.database, _upsert, connection=self.connection)

    def replace_report_metadata(
        self,
        report_id: int,
        metadata: Any,
        *,
        metadata_version: str,
        metadata_profile_id: str | None = None,
        metadata_profile_version: str | None = None,
    ) -> None:
        """Replace canonical selected metadata for a parsed report."""

        metadata_map = _as_mapping(metadata)
        metadata_json = metadata_map.get("metadata_json")
        if metadata_json is None:
            metadata_json = {
                key: value
                for key, value in metadata_map.items()
                if key not in {"warnings"}
                and isinstance(value, (str, int, float, bool, type(None), list, tuple, dict))
            }

        def _replace(cursor) -> None:
            cursor.execute(
                """
                INSERT INTO report_metadata (
                    report_id,
                    reference,
                    reference_raw,
                    report_date,
                    report_time,
                    part_name,
                    revision,
                    sample_number,
                    sample_number_kind,
                    stats_count_raw,
                    stats_count_int,
                    operator_name,
                    comment,
                    metadata_version,
                    metadata_profile_id,
                    metadata_profile_version,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    reference = excluded.reference,
                    reference_raw = excluded.reference_raw,
                    report_date = excluded.report_date,
                    report_time = excluded.report_time,
                    part_name = excluded.part_name,
                    revision = excluded.revision,
                    sample_number = excluded.sample_number,
                    sample_number_kind = excluded.sample_number_kind,
                    stats_count_raw = excluded.stats_count_raw,
                    stats_count_int = excluded.stats_count_int,
                    operator_name = excluded.operator_name,
                    comment = excluded.comment,
                    metadata_version = excluded.metadata_version,
                    metadata_profile_id = excluded.metadata_profile_id,
                    metadata_profile_version = excluded.metadata_profile_version,
                    metadata_json = excluded.metadata_json
                """,
                (
                    int(report_id),
                    metadata_map.get("reference"),
                    metadata_map.get("reference_raw"),
                    metadata_map.get("report_date"),
                    metadata_map.get("report_time"),
                    metadata_map.get("part_name"),
                    metadata_map.get("revision"),
                    metadata_map.get("sample_number"),
                    metadata_map.get("sample_number_kind"),
                    metadata_map.get("stats_count_raw"),
                    metadata_map.get("stats_count_int"),
                    metadata_map.get("operator_name"),
                    metadata_map.get("comment"),
                    metadata_version,
                    metadata_profile_id,
                    metadata_profile_version,
                    _to_json(metadata_json),
                ),
            )

        run_transaction_with_retry(self.database, _replace, connection=self.connection)

    def replace_metadata_candidates(self, report_id: int, candidates: Iterable[Any]) -> None:
        """Replace persisted metadata candidates for a parsed report."""

        rows = []
        created_at = utc_timestamp()
        for candidate in candidates:
            rows.append(
                (
                    int(report_id),
                    _get_value(candidate, "field_name"),
                    _get_value(candidate, "raw_value"),
                    _get_value(candidate, "normalized_value"),
                    _get_value(candidate, "source_type"),
                    _get_value(candidate, "source_detail"),
                    _get_value(candidate, "page_number"),
                    _get_value(candidate, "region_name"),
                    _get_value(candidate, "label_text"),
                    _get_value(candidate, "rule_id"),
                    float(_get_value(candidate, "confidence", 0.0)),
                    _coerce_bool_int(_get_value(candidate, "selected", _get_value(candidate, "is_selected", False))),
                    _get_value(candidate, "evidence_text"),
                    created_at,
                )
            )

        def _replace(cursor) -> None:
            cursor.execute("DELETE FROM report_metadata_candidates WHERE report_id = ?", (int(report_id),))
            cursor.executemany(
                """
                INSERT INTO report_metadata_candidates (
                    report_id,
                    field_name,
                    raw_value,
                    normalized_value,
                    source_type,
                    source_detail,
                    page_number,
                    region_name,
                    label_text,
                    rule_id,
                    confidence,
                    is_selected,
                    evidence_text,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        run_transaction_with_retry(self.database, _replace, connection=self.connection)

    def replace_metadata_warnings(self, report_id: int, warnings: Iterable[Any]) -> None:
        """Replace persisted metadata warnings for a parsed report."""

        rows = []
        created_at = utc_timestamp()
        for warning in warnings:
            details = _get_value(warning, "details", _get_value(warning, "details_json"))
            rows.append(
                (
                    int(report_id),
                    _get_value(warning, "code"),
                    _get_value(warning, "field_name"),
                    _get_value(warning, "severity", "warning"),
                    _get_value(warning, "message"),
                    _to_json(details),
                    created_at,
                )
            )

        def _replace(cursor) -> None:
            cursor.execute("DELETE FROM report_metadata_warnings WHERE report_id = ?", (int(report_id),))
            cursor.executemany(
                """
                INSERT INTO report_metadata_warnings (
                    report_id,
                    code,
                    field_name,
                    severity,
                    message,
                    details_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        run_transaction_with_retry(self.database, _replace, connection=self.connection)

    def append_metadata_warning(self, report_id: int, warning: Any) -> None:
        """Append one metadata warning without replacing existing warning rows."""

        created_at = utc_timestamp()
        details = _get_value(warning, "details", _get_value(warning, "details_json"))

        def _insert(cursor) -> None:
            cursor.execute(
                """
                INSERT INTO report_metadata_warnings (
                    report_id,
                    code,
                    field_name,
                    severity,
                    message,
                    details_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(report_id),
                    _get_value(warning, "code"),
                    _get_value(warning, "field_name"),
                    _get_value(warning, "severity", "warning"),
                    _get_value(warning, "message"),
                    _to_json(details),
                    created_at,
                ),
            )

        run_transaction_with_retry(self.database, _insert, connection=self.connection)

    def replace_measurements(self, report_id: int, measurements: Iterable[Any]) -> None:
        """Replace flat measurements for a parsed report."""

        rows = []
        for row_order, measurement in enumerate(measurements, start=1):
            explicit_order = _get_value(measurement, "row_order")
            outtol = _coerce_float(_get_value(measurement, "outtol"))
            is_nok = _get_value(measurement, "is_nok")
            if is_nok is None:
                is_nok = bool(outtol is not None and outtol > 0)
            status_code = _get_value(measurement, "status_code")
            if not status_code:
                status_code = "nok" if is_nok else "ok"
            rows.append(
                (
                    int(report_id),
                    _coerce_int(_get_value(measurement, "page_number")),
                    int(explicit_order if explicit_order is not None else row_order),
                    _get_value(measurement, "header"),
                    _get_value(measurement, "section_name"),
                    _get_value(measurement, "feature_label"),
                    _get_value(measurement, "characteristic_name"),
                    _get_value(measurement, "characteristic_family"),
                    _get_value(measurement, "description"),
                    _get_value(measurement, "ax"),
                    _coerce_float(_get_value(measurement, "nominal", _get_value(measurement, "nom"))),
                    _coerce_float(_get_value(measurement, "tol_plus")),
                    _coerce_float(_get_value(measurement, "tol_minus")),
                    _coerce_float(_get_value(measurement, "bonus")),
                    _coerce_float(_get_value(measurement, "meas")),
                    _coerce_float(_get_value(measurement, "dev")),
                    outtol,
                    _coerce_bool_int(is_nok),
                    status_code,
                    _to_json(_get_value(measurement, "raw_measurement_json", _as_mapping(measurement))),
                )
            )

        def _replace(cursor) -> None:
            cursor.execute("DELETE FROM report_measurements WHERE report_id = ?", (int(report_id),))
            cursor.executemany(
                """
                INSERT INTO report_measurements (
                    report_id,
                    page_number,
                    row_order,
                    header,
                    section_name,
                    feature_label,
                    characteristic_name,
                    characteristic_family,
                    description,
                    ax,
                    nominal,
                    tol_plus,
                    tol_minus,
                    bonus,
                    meas,
                    dev,
                    outtol,
                    is_nok,
                    status_code,
                    raw_measurement_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        run_transaction_with_retry(self.database, _replace, connection=self.connection)

    def persist_semantic_duplicate_warnings(self, report_id: int, identity_hash: str | None) -> int:
        """Persist duplicate semantic identity warnings for same-hash reports."""

        if not identity_hash:
            return 0

        created_at = utc_timestamp()

        def _persist(cursor) -> int:
            cursor.execute(
                """
                SELECT other.id
                FROM parsed_reports current
                JOIN parsed_reports other
                  ON other.identity_hash = current.identity_hash
                 AND other.id <> current.id
                 AND other.source_file_id <> current.source_file_id
                WHERE current.id = ?
                  AND current.identity_hash = ?
                """,
                (int(report_id), identity_hash),
            )
            duplicate_ids = [int(row[0]) for row in cursor.fetchall()]
            if not duplicate_ids:
                return 0

            cursor.execute(
                """
                DELETE FROM report_metadata_warnings
                WHERE report_id = ?
                  AND code = ?
                """,
                (int(report_id), SEMANTIC_DUPLICATE_WARNING_CODE),
            )
            cursor.execute(
                """
                INSERT INTO report_metadata_warnings (
                    report_id,
                    code,
                    field_name,
                    severity,
                    message,
                    details_json,
                    created_at
                )
                VALUES (?, ?, NULL, 'warning', ?, ?, ?)
                """,
                (
                    int(report_id),
                    SEMANTIC_DUPLICATE_WARNING_CODE,
                    "Semantic report identity matches another parsed report.",
                    _to_json({"identity_hash": identity_hash, "duplicate_report_ids": duplicate_ids}),
                    created_at,
                ),
            )
            return len(duplicate_ids)

        return run_transaction_with_retry(self.database, _persist, connection=self.connection)

    def persist_parsed_report(
        self,
        *,
        source_path: str | Path,
        source_sha256: str | None = None,
        parser_id: str,
        template_family: str,
        parse_status: str,
        metadata: Any,
        candidates: Iterable[Any],
        warnings: Iterable[Any],
        measurements: Iterable[Any],
        metadata_version: str,
        parser_version: str | None = None,
        template_variant: str | None = None,
        metadata_profile_id: str | None = None,
        metadata_profile_version: str | None = None,
        parse_started_at: str | None = None,
        parse_finished_at: str | None = None,
        parse_duration_ms: int | None = None,
        page_count: int | None = None,
        measurement_count: int = 0,
        has_nok: bool = False,
        nok_count: int = 0,
        metadata_confidence: float | None = None,
        identity_hash: str | None = None,
        raw_report_json: Any = None,
    ) -> int:
        """Persist a full parsed report payload through the repository facade."""

        self.ensure_schema()
        source_record = self.upsert_source_file(source_path, sha256=source_sha256)
        report_id = self.upsert_parsed_report(
            source_file_id=source_record.id,
            parser_id=parser_id,
            parser_version=parser_version,
            template_family=template_family,
            template_variant=template_variant,
            parse_status=parse_status,
            parse_started_at=parse_started_at,
            parse_finished_at=parse_finished_at,
            parse_duration_ms=parse_duration_ms,
            page_count=page_count,
            measurement_count=measurement_count,
            has_nok=has_nok,
            nok_count=nok_count,
            metadata_confidence=metadata_confidence,
            identity_hash=identity_hash,
            raw_report_json=raw_report_json,
        )
        self.replace_report_metadata(
            report_id,
            metadata,
            metadata_version=metadata_version,
            metadata_profile_id=metadata_profile_id,
            metadata_profile_version=metadata_profile_version,
        )
        self.replace_metadata_candidates(report_id, candidates)
        self.replace_metadata_warnings(report_id, warnings)
        self.replace_measurements(report_id, measurements)
        self.persist_semantic_duplicate_warnings(report_id, identity_hash)
        return report_id


def source_path_exists(path: str | Path) -> bool:
    """Return True when a source path exists and is a regular file."""

    try:
        return Path(path).is_file()
    except (OSError, ValueError):
        return False


def source_file_size(path: str | Path) -> int | None:
    """Return a source file size or None when unavailable."""

    try:
        return os.stat(path).st_size
    except (OSError, ValueError):
        return None
