"""Non-mutating parser preflight for operator review before report import.

The preflight deliberately resolves parsers from file contents and records a
content digest.  Paths and filenames are presentation metadata only; they are
never parser-selection inputs beyond identifying the source container format.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import sqlite3
import stat
import tarfile
from tempfile import TemporaryDirectory
from typing import BinaryIO, Callable, Iterable
import zipfile

from metroliza.parsing import report_parser_factory
from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.parser_plugin_contracts import infer_source_format
from metroliza.parsing.source_inspection import SourceInspectionContext
from metroliza.reports.db import sqlite_readonly_connection_scope
from metroliza.reports.report_metadata_profiles import DEFAULT_CMM_PDF_HEADER_BOX_PROFILE
from metroliza.shared.parse_contracts import ParseRequest, validate_parse_request


_REPORT_EXTENSIONS_BY_SOURCE_FORMAT = {
    "pdf": {".pdf"},
    "excel": {".xls", ".xlsx"},
    "csv": {".csv"},
}
_CURRENT_CMM_METADATA_PARSER_ID = DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.parser_id
_CURRENT_CMM_PARSER_VERSION = getattr(
    getattr(CMMReportParser, "manifest", None),
    "version",
    "1.1.0",
)
_MAX_ARCHIVE_MEMBER_COUNT = 10_000
_MAX_ARCHIVE_MEMBER_BYTES = 1024 * 1024 * 1024
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
_MAX_ARCHIVE_COMPRESSION_RATIO = 500
_ARCHIVE_RATIO_CHECK_MIN_BYTES = 64 * 1024 * 1024
_CURRENT_PARSE_PREFLIGHT_VERSION = "parse-preflight-v1"
_TAR_ARCHIVE_EXTENSIONS_BY_COMPRESSION = {
    "tar": frozenset({".tar"}),
    "gz": frozenset({".tar.gz", ".tgz"}),
    "bz2": frozenset({".tar.bz2", ".tbz2"}),
    "xz": frozenset({".tar.xz", ".txz"}),
    "zst": frozenset({".tar.zst", ".tzst"}),
}


class UnsafeReportArchiveError(shutil.ReadError):
    """Raised when an archive cannot be extracted without escaping its root."""


def _validated_archive_member_parts(member_name: str) -> tuple[str, ...]:
    """Return normalized relative member parts or reject the whole archive.

    Both POSIX and Windows path semantics are checked because archives can be
    prepared on one platform and imported on another.
    """

    name = str(member_name or "")
    normalized = name.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(name)
    normalized_parts = tuple(part for part in posix_path.parts if part not in {"", "."})
    has_windows_unsafe_component = any(
        ":" in part
        or part.endswith((" ", "."))
        or PureWindowsPath(part).is_reserved()
        for part in normalized_parts
    )
    if (
        not name
        or "\x00" in name
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in posix_path.parts
        or has_windows_unsafe_component
    ):
        raise UnsafeReportArchiveError("Archive contains an unsafe entry.")
    return normalized_parts


def _archive_member_target(destination: Path, member_name: str) -> Path:
    """Return a member target proven to remain below ``destination``."""

    parts = _validated_archive_member_parts(member_name)
    if not parts:
        return destination.resolve(strict=False)
    root = destination.resolve(strict=False)
    target = root.joinpath(*parts).resolve(strict=False)
    if not target.is_relative_to(root):
        raise UnsafeReportArchiveError("Archive contains an unsafe entry.")
    return target


def _validate_archive_budget(
    destination: Path,
    member_sizes: Iterable[int],
    *,
    compressed_bytes: int,
) -> None:
    sizes = tuple(max(0, int(size)) for size in member_sizes)
    total_bytes = sum(sizes)
    if (
        len(sizes) > _MAX_ARCHIVE_MEMBER_COUNT
        or any(size > _MAX_ARCHIVE_MEMBER_BYTES for size in sizes)
        or total_bytes > _MAX_ARCHIVE_UNCOMPRESSED_BYTES
    ):
        raise UnsafeReportArchiveError("Archive exceeds safe extraction limits.")
    if (
        total_bytes >= _ARCHIVE_RATIO_CHECK_MIN_BYTES
        and total_bytes > max(1, int(compressed_bytes)) * _MAX_ARCHIVE_COMPRESSION_RATIO
    ):
        raise UnsafeReportArchiveError("Archive exceeds safe extraction limits.")
    try:
        free_bytes = shutil.disk_usage(destination).free
    except OSError:
        return
    reserved_bytes = min(512 * 1024 * 1024, max(64 * 1024 * 1024, free_bytes // 10))
    if total_bytes > max(0, free_bytes - reserved_bytes):
        raise UnsafeReportArchiveError("Archive exceeds safe extraction limits.")


def _copy_archive_member(
    source: BinaryIO,
    target: Path,
    *,
    extracted_bytes: list[int],
    compressed_bytes: int,
) -> None:
    """Materialize one validated member while enforcing actual byte limits.

    Archive metadata is useful for an early rejection but is not trusted as the
    final size authority.  Streaming the payload ourselves also avoids archive
    library extraction APIs whose path handling has varied across runtimes.
    """

    member_bytes = 0
    created = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        output = target.open("xb")
        created = True
        with output:
            while chunk := source.read(1024 * 1024):
                member_bytes += len(chunk)
                extracted_bytes[0] += len(chunk)
                if (
                    member_bytes > _MAX_ARCHIVE_MEMBER_BYTES
                    or extracted_bytes[0] > _MAX_ARCHIVE_UNCOMPRESSED_BYTES
                    or (
                        extracted_bytes[0] >= _ARCHIVE_RATIO_CHECK_MIN_BYTES
                        and extracted_bytes[0]
                        > max(1, int(compressed_bytes)) * _MAX_ARCHIVE_COMPRESSION_RATIO
                    )
                ):
                    raise UnsafeReportArchiveError("Archive exceeds safe extraction limits.")
                output.write(chunk)
    except UnsafeReportArchiveError:
        if created:
            target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if created:
            target.unlink(missing_ok=True)
        raise UnsafeReportArchiveError("Archive contains an unsafe entry.") from exc


def _claim_archive_member(
    destination: Path,
    member_name: str,
    claimed_members: set[tuple[str, ...]],
) -> Path:
    """Reject duplicate and case-colliding paths before writing a member."""

    parts = _validated_archive_member_parts(member_name)
    key = tuple(part.casefold() for part in parts)
    if not key:
        return destination.resolve(strict=False)
    if key in claimed_members:
        raise UnsafeReportArchiveError("Archive contains an unsafe entry.")
    claimed_members.add(key)
    return _archive_member_target(destination, member_name)


def _safe_unpack_zip(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        compressed_bytes = sum(member.compress_size for member in members)
        _validate_archive_budget(
            destination,
            (member.file_size for member in members),
            compressed_bytes=compressed_bytes,
        )
        claimed_members: set[tuple[str, ...]] = set()
        extracted_bytes = [0]
        extraction_plan: list[tuple[zipfile.ZipInfo, Path]] = []
        for member in members:
            target = _claim_archive_member(destination, member.filename, claimed_members)
            unix_mode = (member.external_attr >> 16) & 0xFFFF
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise UnsafeReportArchiveError("Archive contains an unsafe entry.")
            extraction_plan.append((member, target))
        for member, target in extraction_plan:
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            with archive.open(member, "r") as source:
                _copy_archive_member(
                    source,
                    target,
                    extracted_bytes=extracted_bytes,
                    compressed_bytes=compressed_bytes,
                )


def _safe_unpack_tar(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        compressed_bytes = archive_path.stat().st_size
        _validate_archive_budget(
            destination,
            (member.size for member in members),
            compressed_bytes=compressed_bytes,
        )
        claimed_members: set[tuple[str, ...]] = set()
        extracted_bytes = [0]
        extraction_plan: list[tuple[tarfile.TarInfo, Path]] = []
        for member in members:
            target = _claim_archive_member(destination, member.name, claimed_members)
            # Links and special files can escape or mutate the host even when
            # their member names themselves are relative.
            if not (member.isfile() or member.isdir()):
                raise UnsafeReportArchiveError("Archive contains an unsafe entry.")
            extraction_plan.append((member, target))
        for member, target in extraction_plan:
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise UnsafeReportArchiveError("Archive contains an unreadable entry.")
            with source:
                _copy_archive_member(
                    source,
                    target,
                    extracted_bytes=extracted_bytes,
                    compressed_bytes=compressed_bytes,
                )


def safe_unpack_report_archive(
    archive_path: str | Path,
    destination: str | Path,
) -> None:
    """Extract a supported report archive after validating every member.

    Report imports intentionally fail closed for custom archive formats that
    cannot be inspected with the standard ZIP/TAR readers.
    """

    source = Path(archive_path)
    target = Path(destination)
    target_preexisted = target.exists()
    if target_preexisted:
        if target.is_symlink() or not target.is_dir() or any(target.iterdir()):
            raise UnsafeReportArchiveError("Archive destination must be an empty directory.")
    target.parent.mkdir(parents=True, exist_ok=True)

    staging_owner = TemporaryDirectory(prefix=f".{target.name}.extract-", dir=target.parent)
    staging = Path(staging_owner.name)
    try:
        try:
            if zipfile.is_zipfile(source):
                _safe_unpack_zip(source, staging)
            elif tarfile.is_tarfile(source):
                _safe_unpack_tar(source, staging)
            else:
                raise shutil.ReadError("Archive format cannot be extracted safely.")
        except UnsafeReportArchiveError:
            raise
        except (OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile) as exc:
            raise shutil.ReadError("Archive could not be read safely.") from exc

        if target.exists():
            try:
                target.rmdir()
            except OSError as exc:
                raise UnsafeReportArchiveError(
                    "Archive destination changed while extraction was in progress."
                ) from exc
        try:
            staging.replace(target)
        except OSError:
            if target_preexisted and not target.exists():
                target.mkdir(parents=True, exist_ok=True)
            raise
    finally:
        staging_owner.cleanup()


def _tarfile_supports_compression(compression: str) -> bool:
    """Return whether this runtime has a working decoder for ``compression``.

    ``TarFile.OPEN_METH`` only proves that a mode name exists; optional codec
    modules may still be unavailable.  Opening an empty in-memory stream makes
    the active decoder run without reading user data.  A format/read error then
    means the decoder exists, while ``CompressionError`` means it does not.
    """

    if compression == "tar":
        return True
    try:
        with tarfile.open(fileobj=BytesIO(), mode=f"r:{compression}"):
            pass
    except tarfile.CompressionError:
        return False
    except tarfile.TarError:
        return True
    return True


@lru_cache(maxsize=1)
def supported_report_archive_extensions() -> frozenset[str]:
    """Return container endings the active safe readers can actually decode."""

    extensions = {".zip"}
    for compression, compression_extensions in _TAR_ARCHIVE_EXTENSIONS_BY_COMPRESSION.items():
        if _tarfile_supports_compression(compression):
            extensions.update(compression_extensions)
    return frozenset(extensions)


def is_supported_report_archive(path: str | Path) -> bool:
    """Recognize an archive container from its complete, case-insensitive name."""

    filename = Path(path).name.lower()
    return any(filename.endswith(extension) for extension in supported_report_archive_extensions())


class ParsePreflightStatus(str, Enum):
    """Operator-facing classification for one discovered report source."""

    READY = "ready"
    DUPLICATE = "duplicate"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class ParserCandidateEvidence:
    """Content-derived evidence recorded for one parser candidate."""

    parser_id: str
    confidence: int
    can_parse: bool
    outcome: str
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    semantic_row_count: int | None = None


@dataclass(frozen=True)
class ParseFilePreflight:
    """Immutable preflight evidence for one report file."""

    display_name: str
    source_path: str
    status: ParsePreflightStatus
    source_format: str
    fingerprint: str | None
    parser_id: str | None = None
    confidence: int | None = None
    reason_codes: tuple[str, ...] = ()
    candidates: tuple[ParserCandidateEvidence, ...] = ()
    competing_parser_ids: tuple[str, ...] = ()
    registry_generation_id: int | None = None
    diagnostic_detail: str = ""
    occurrence_id: str = ""

    @property
    def is_importable(self) -> bool:
        """Return whether this exact content/parser resolution may be imported."""

        return self.status is ParsePreflightStatus.READY

    @property
    def stable_occurrence_id(self) -> str:
        """Return the source-relative identity used across archive extraction runs."""

        return self.occurrence_id or _normalize_occurrence_id(self.display_name)


@dataclass(frozen=True)
class ParsePreflightResult:
    """Complete, non-mutating scan result for one source/database selection."""

    source_path: str
    database_path: str
    metadata_parsing_mode: str
    files: tuple[ParseFilePreflight, ...]
    cancelled: bool = False
    version: str = _CURRENT_PARSE_PREFLIGHT_VERSION

    def files_with_status(self, status: ParsePreflightStatus) -> tuple[ParseFilePreflight, ...]:
        return tuple(item for item in self.files if item.status is status)

    def count(self, status: ParsePreflightStatus) -> int:
        return sum(item.status is status for item in self.files)

    @property
    def ready_files(self) -> tuple[ParseFilePreflight, ...]:
        return self.files_with_status(ParsePreflightStatus.READY)

    @property
    def ready_fingerprints(self) -> frozenset[str]:
        return frozenset(
            item.fingerprint
            for item in self.ready_files
            if item.fingerprint
        )

    @property
    def expected_fingerprints(self) -> frozenset[str]:
        return frozenset(item.fingerprint for item in self.files if item.fingerprint)

    @property
    def parser_id_by_ready_fingerprint(self) -> dict[str, str]:
        return {
            item.fingerprint: item.parser_id
            for item in self.ready_files
            if item.fingerprint and item.parser_id
        }

    @property
    def parser_approval_by_ready_fingerprint(self) -> dict[str, tuple[str, int | None]]:
        """Return the parser id and exact registry generation approved by the scan."""

        return {
            item.fingerprint: (item.parser_id, item.registry_generation_id)
            for item in self.ready_files
            if item.fingerprint and item.parser_id
        }

    @property
    def status_counts(self) -> dict[ParsePreflightStatus, int]:
        return {status: self.count(status) for status in ParsePreflightStatus}

    @property
    def result_id(self) -> str:
        """Return a deterministic identity for this exact reviewed result."""

        payload = {
            "version": self.version,
            "source_path": str(Path(self.source_path).resolve(strict=False)),
            "database_path": str(Path(self.database_path).resolve(strict=False)),
            "metadata_parsing_mode": self.metadata_parsing_mode,
            "cancelled": self.cancelled,
            "files": [
                {
                    "occurrence_id": item.stable_occurrence_id,
                    "status": item.status.value,
                    "reason_codes": item.reason_codes,
                    "source_format": item.source_format,
                    "fingerprint": item.fingerprint,
                    "parser_id": item.parser_id,
                    "registry_generation_id": item.registry_generation_id,
                }
                for item in self.files
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def atomic_import_candidates(
        self,
        *,
        source_path: str,
        database_path: str,
        metadata_parsing_mode: str,
        registry_generation_id: int | None,
    ) -> tuple[ParseFilePreflight, ...]:
        """Return approved candidates for verification, without reading or writing data.

        DUPLICATE is historical destination evidence, not a complete-graph or
        write decision. Only the atomic repository can make that decision.
        A selected-plan adapter must additionally intersect its selected set.
        """

        if (
            self.cancelled
            or not source_path
            or not database_path
            or registry_generation_id is None
            or not self.matches_request(
                source_path=source_path,
                database_path=database_path,
                metadata_parsing_mode=metadata_parsing_mode,
            )
        ):
            return ()
        return tuple(
            item for item in self.files
            if item.status in (ParsePreflightStatus.READY, ParsePreflightStatus.DUPLICATE)
            and "duplicate_in_selected_source" not in item.reason_codes
            and item.fingerprint
            and item.parser_id
            and item.registry_generation_id == registry_generation_id
        )

    def matches_request(
        self,
        *,
        source_path: str,
        database_path: str,
        metadata_parsing_mode: str,
    ) -> bool:
        """Return whether UI/import inputs still match this scan context."""

        return (
            Path(self.source_path).resolve(strict=False)
            == Path(source_path).resolve(strict=False)
            and Path(self.database_path).resolve(strict=False)
            == Path(database_path).resolve(strict=False)
            and self.metadata_parsing_mode == str(metadata_parsing_mode)
        )


@dataclass(frozen=True)
class SelectedReportIdentity:
    """Content and occurrence identity approved for one selected atomic candidate."""

    occurrence_id: str
    fingerprint: str
    parser_id: str
    registry_generation_id: int


@dataclass(frozen=True)
class ImportPlan:
    """Immutable destination-bound plan for an explicit reviewed report subset."""

    source_path: str
    database_path: str
    metadata_parsing_mode: str
    run_background_metadata_enrichment: bool
    preflight_result: ParsePreflightResult
    preflight_version: str
    preflight_result_id: str
    selected_reports: tuple[SelectedReportIdentity, ...]

    @classmethod
    def from_preflight(
        cls,
        request: ParseRequest,
        preflight_result: ParsePreflightResult,
        *,
        selected_occurrence_ids: Iterable[str],
    ) -> ImportPlan:
        """Build a plan from an explicit set of reviewed occurrence identities."""

        validated_request = validate_parse_request(request)
        if preflight_result.cancelled:
            raise ValueError("A cancelled preflight result cannot be imported.")
        if not preflight_result.matches_request(
            source_path=validated_request.source_directory,
            database_path=validated_request.db_file,
            metadata_parsing_mode=validated_request.metadata_parsing_mode,
        ):
            raise ValueError("Import plan inputs do not match the reviewed preflight result.")
        selected_ids = tuple(
            sorted(
                (str(value) for value in selected_occurrence_ids),
                key=lambda value: (value.casefold(), value),
            )
        )
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("Selected report occurrence identities must be unique.")

        files_by_occurrence = _preflight_files_by_occurrence(preflight_result)
        eligible = {
            item.stable_occurrence_id
            for item in _reviewed_atomic_candidates(preflight_result)
        }
        selected_reports: list[SelectedReportIdentity] = []
        for occurrence_id in selected_ids:
            item = files_by_occurrence.get(occurrence_id)
            if item is None:
                raise ValueError(f"Selected report identity is missing from preflight: {occurrence_id}")
            if occurrence_id not in eligible:
                raise ValueError(f"Selected report is not an atomic import candidate: {occurrence_id}")
            if not item.fingerprint or not item.parser_id or item.registry_generation_id is None:
                raise ValueError(f"Selected READY report has incomplete approval evidence: {occurrence_id}")
            selected_reports.append(
                SelectedReportIdentity(
                    occurrence_id=occurrence_id,
                    fingerprint=item.fingerprint,
                    parser_id=item.parser_id,
                    registry_generation_id=item.registry_generation_id,
                )
            )

        plan = cls(
            source_path=preflight_result.source_path,
            database_path=preflight_result.database_path,
            metadata_parsing_mode=validated_request.metadata_parsing_mode,
            run_background_metadata_enrichment=(
                validated_request.run_background_metadata_enrichment
            ),
            preflight_result=preflight_result,
            preflight_version=preflight_result.version,
            preflight_result_id=preflight_result.result_id,
            selected_reports=tuple(selected_reports),
        )
        return validate_import_plan(plan)

    @classmethod
    def all_ready(
        cls,
        request: ParseRequest,
        preflight_result: ParsePreflightResult,
    ) -> ImportPlan:
        """Compatibility adapter that explicitly selects every READY occurrence."""

        return cls.from_preflight(
            request,
            preflight_result,
            selected_occurrence_ids=(
                item.stable_occurrence_id for item in preflight_result.ready_files
            ),
        )

    @classmethod
    def all_atomic_candidates(
        cls,
        request: ParseRequest,
        preflight_result: ParsePreflightResult,
    ) -> ImportPlan:
        """Explicit compatibility adapter for the current import/verify action."""
        candidates = _reviewed_atomic_candidates(preflight_result)
        generation = report_parser_factory.get_registry_snapshot().generation_id
        if any(item.registry_generation_id != generation for item in candidates):
            raise ValueError("Reviewed parser generation is stale; scan again.")
        return cls.from_preflight(
            request,
            preflight_result,
            selected_occurrence_ids=(item.stable_occurrence_id for item in candidates),
        )


def _reviewed_atomic_candidates(preflight: ParsePreflightResult) -> tuple[ParseFilePreflight, ...]:
    """Use shared eligibility at the recorded generation, without shrinking a plan on drift."""
    generations = {item.registry_generation_id for item in preflight.files}
    return tuple(
        candidate
        for generation in generations
        for candidate in preflight.atomic_import_candidates(
            source_path=preflight.source_path,
            database_path=preflight.database_path,
            metadata_parsing_mode=preflight.metadata_parsing_mode,
            registry_generation_id=generation,
        )
    )


def _normalize_occurrence_id(value: str) -> str:
    normalized = PurePosixPath(str(value).replace(os.sep, "/")).as_posix()
    if normalized in {"", "."} or normalized.startswith("../") or normalized.startswith("/"):
        raise ValueError("Report occurrence identity must be a non-empty relative path.")
    return normalized


def _preflight_files_by_occurrence(
    preflight_result: ParsePreflightResult,
) -> dict[str, ParseFilePreflight]:
    files_by_occurrence: dict[str, ParseFilePreflight] = {}
    for item in preflight_result.files:
        occurrence_id = item.stable_occurrence_id
        if occurrence_id in files_by_occurrence:
            raise ValueError(f"Preflight occurrence identity is not unique: {occurrence_id}")
        files_by_occurrence[occurrence_id] = item
    return files_by_occurrence


def validate_import_plan(plan: ImportPlan) -> ImportPlan:
    """Fail closed unless a plan exactly binds a current non-cancelled preflight."""

    if not isinstance(plan, ImportPlan):
        raise ValueError("Import plan must be provided as an ImportPlan instance.")
    _validate_import_plan_context(plan)
    _validate_selected_reports(plan)
    return plan


def _validate_import_plan_context(plan: ImportPlan) -> None:
    preflight = plan.preflight_result
    if not isinstance(preflight, ParsePreflightResult):
        raise ValueError("Import plan must bind a ParsePreflightResult instance.")
    if not isinstance(preflight.files, tuple):
        raise ValueError("Preflight files must be an immutable tuple.")
    if preflight.cancelled:
        raise ValueError("A cancelled preflight result cannot be imported.")
    if (
        plan.preflight_version != _CURRENT_PARSE_PREFLIGHT_VERSION
        or preflight.version != _CURRENT_PARSE_PREFLIGHT_VERSION
    ):
        raise ValueError("Import plan uses an unsupported preflight version.")
    if plan.preflight_result_id != preflight.result_id:
        raise ValueError("Import plan does not match its reviewed preflight result.")
    if not isinstance(plan.run_background_metadata_enrichment, bool):
        raise ValueError("run_background_metadata_enrichment must be a boolean.")
    if not isinstance(plan.selected_reports, tuple):
        raise ValueError("Import plan selected_reports must be an immutable tuple.")
    if not preflight.matches_request(
        source_path=plan.source_path,
        database_path=plan.database_path,
        metadata_parsing_mode=plan.metadata_parsing_mode,
    ):
        raise ValueError("Import plan inputs do not match the reviewed preflight result.")


def _validate_selected_reports(plan: ImportPlan) -> None:
    files_by_occurrence = _preflight_files_by_occurrence(plan.preflight_result)
    eligible = {
        item.stable_occurrence_id for item in _reviewed_atomic_candidates(plan.preflight_result)
    }
    selected_occurrences: set[str] = set()
    for identity in plan.selected_reports:
        if not isinstance(identity, SelectedReportIdentity):
            raise ValueError("Import plan contains an invalid selected report identity.")
        if identity.occurrence_id in selected_occurrences:
            raise ValueError("Import plan contains duplicate selected report identities.")
        selected_occurrences.add(identity.occurrence_id)
        item = files_by_occurrence.get(identity.occurrence_id)
        if item is None:
            raise ValueError(
                f"Selected report identity is missing from preflight: {identity.occurrence_id}"
            )
        approved_identity = SelectedReportIdentity(
            occurrence_id=item.stable_occurrence_id,
            fingerprint=item.fingerprint or "",
            parser_id=item.parser_id or "",
            registry_generation_id=item.registry_generation_id or 0,
        )
        if identity.occurrence_id not in eligible or identity != approved_identity:
            raise ValueError(
                f"Selected report identity is not an exact atomic approval: {identity.occurrence_id}"
            )


def supported_report_file_extensions() -> set[str]:
    """Return suffixes advertised by the active parser registry."""

    extensions = set(_REPORT_EXTENSIONS_BY_SOURCE_FORMAT["pdf"])
    try:
        snapshot = report_parser_factory.get_registry_snapshot()
    except Exception:
        return extensions
    for registration in snapshot.registrations:
        for source_format in getattr(registration.manifest, "supported_formats", ()) or ():
            extensions.update(
                _REPORT_EXTENSIONS_BY_SOURCE_FORMAT.get(str(source_format).lower(), ())
            )
    return extensions


def load_existing_report_fingerprints(
    database_path: str | Path,
    *,
    metadata_parsing_mode: str,
) -> frozenset[str]:
    """Read existing source digests without creating or migrating a database."""

    path = Path(database_path)
    if not path.is_file():
        return frozenset()

    try:
        with sqlite_readonly_connection_scope(str(path)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if not {"source_files", "parsed_reports"}.issubset(tables):
                return frozenset()

            if metadata_parsing_mode == "light":
                rows = connection.execute(
                    """
                    SELECT sf.sha256
                    FROM source_files sf
                    JOIN parsed_reports pr ON pr.source_file_id = sf.id
                    WHERE sf.is_active = 1
                      AND (pr.parser_id <> ? OR pr.parser_version = ?)
                    """,
                    (_CURRENT_CMM_METADATA_PARSER_ID, _CURRENT_CMM_PARSER_VERSION),
                ).fetchall()
            elif "report_parse_state" in tables:
                rows = connection.execute(
                    """
                    SELECT sf.sha256
                    FROM source_files sf
                    JOIN parsed_reports pr ON pr.source_file_id = sf.id
                    LEFT JOIN report_parse_state rps ON rps.report_id = pr.id
                    WHERE sf.is_active = 1
                      AND (
                        pr.parser_id <> ?
                        OR (
                          pr.parser_version = ?
                          AND rps.header_extraction_mode IS NOT NULL
                          AND rps.header_extraction_mode <> 'none'
                          AND rps.header_ocr_error_code IS NULL
                          AND COALESCE(rps.reference_source, '') <> 'filename_candidate'
                          AND COALESCE(rps.report_date_source, '') <> 'filename_candidate'
                          AND COALESCE(rps.stats_count_source, '') <> 'filename_candidate'
                        )
                      )
                    """,
                    (_CURRENT_CMM_METADATA_PARSER_ID, _CURRENT_CMM_PARSER_VERSION),
                ).fetchall()
            else:
                # An older database needs schema migration before complete-mode
                # duplicate semantics are reliable.  Treat it as ready so the
                # normal importer can migrate and enrich it.
                return frozenset()
    except (OSError, sqlite3.Error):
        return frozenset()

    return frozenset(f"sha256:{row[0]}" for row in rows if row and row[0])


def _candidate_evidence(diagnostics) -> tuple[ParserCandidateEvidence, ...]:
    evidence: list[ParserCandidateEvidence] = []
    for candidate in diagnostics.candidates_considered:
        outcome = getattr(getattr(candidate, "outcome", None), "value", None) or "legacy"
        evidence.append(
            ParserCandidateEvidence(
                parser_id=str(candidate.plugin_id),
                confidence=int(candidate.confidence or 0),
                can_parse=bool(candidate.can_parse),
                outcome=str(outcome),
                reasons=tuple(str(reason) for reason in candidate.reasons or ()),
                warnings=tuple(str(warning) for warning in candidate.warnings or ()),
                semantic_row_count=getattr(candidate, "semantic_row_count", None),
            )
        )
    return tuple(evidence)


def _reason_codes(diagnostics) -> tuple[str, ...]:
    values: list[str] = []
    if diagnostics.rejected_reason:
        values.append(str(diagnostics.rejected_reason))
    selected = diagnostics.selected
    if selected is not None:
        values.extend(str(reason) for reason in selected.reasons or ())
        values.extend(str(warning) for warning in selected.warnings or ())
    elif diagnostics.candidates_considered:
        for candidate in diagnostics.candidates_considered:
            values.extend(str(reason) for reason in candidate.reasons or ())
    return tuple(dict.fromkeys(value for value in values if value))


def _unreadable_entry(display_name: str, source_path: Path, detail: str) -> ParseFilePreflight:
    return ParseFilePreflight(
        display_name=display_name,
        source_path=str(source_path),
        status=ParsePreflightStatus.UNREADABLE,
        source_format=infer_source_format(source_path),
        fingerprint=None,
        reason_codes=("source_unreadable",),
        diagnostic_detail=str(detail),
        occurrence_id=_normalize_occurrence_id(display_name),
    )


class ParsePreflightService:
    """Discover and classify reports without writing to the destination database."""

    def scan_source(
        self,
        *,
        source_path: str | Path,
        database_path: str | Path,
        metadata_parsing_mode: str,
        should_cancel: Callable[[], bool] = lambda: False,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> ParsePreflightResult:
        source = Path(source_path).resolve(strict=False)
        database = Path(database_path).resolve(strict=False)
        existing_fingerprints = load_existing_report_fingerprints(
            database,
            metadata_parsing_mode=metadata_parsing_mode,
        )

        temporary_directory: TemporaryDirectory[str] | None = None
        try:
            scan_root = source
            if source.is_file() and is_supported_report_archive(source):
                temporary_directory = TemporaryDirectory()
                scan_root = Path(temporary_directory.name)
                try:
                    safe_unpack_report_archive(source, scan_root)
                except (OSError, shutil.ReadError, ValueError) as exc:
                    return ParsePreflightResult(
                        source_path=str(source),
                        database_path=str(database),
                        metadata_parsing_mode=str(metadata_parsing_mode),
                        files=(_unreadable_entry(source.name, source, str(exc)),),
                    )

            discovered, discovery_failures = self._discover_files(scan_root)
            total = len(discovered) + len(discovery_failures)
            results: list[ParseFilePreflight] = list(discovery_failures)
            seen_fingerprints: set[str] = set()
            processed = len(discovery_failures)
            if on_progress and discovery_failures:
                on_progress(processed, total, discovery_failures[-1].display_name)

            for path, display_name in discovered:
                if should_cancel():
                    return ParsePreflightResult(
                        source_path=str(source),
                        database_path=str(database),
                        metadata_parsing_mode=str(metadata_parsing_mode),
                        files=tuple(results),
                        cancelled=True,
                    )
                inspected = self._inspect_file(
                    path,
                    display_name=display_name,
                    existing_fingerprints=existing_fingerprints,
                )
                if (
                    inspected.fingerprint in seen_fingerprints
                    and inspected.status in {
                        ParsePreflightStatus.READY,
                        ParsePreflightStatus.DUPLICATE,
                    }
                ):
                    inspected = replace(
                        inspected,
                        status=ParsePreflightStatus.DUPLICATE,
                        reason_codes=tuple(
                            dict.fromkeys(
                                (*inspected.reason_codes, "duplicate_in_selected_source")
                            )
                        ),
                    )
                if inspected.fingerprint:
                    seen_fingerprints.add(inspected.fingerprint)
                results.append(inspected)
                processed += 1
                if on_progress:
                    on_progress(processed, total, display_name)

            return ParsePreflightResult(
                source_path=str(source),
                database_path=str(database),
                metadata_parsing_mode=str(metadata_parsing_mode),
                files=tuple(results),
                cancelled=bool(should_cancel()),
            )
        finally:
            if temporary_directory is not None:
                temporary_directory.cleanup()

    @staticmethod
    def _discover_files(
        scan_root: Path,
    ) -> tuple[list[tuple[Path, str]], list[ParseFilePreflight]]:
        if not scan_root.exists():
            return [], [_unreadable_entry(scan_root.name or str(scan_root), scan_root, "Source does not exist")]

        supported_extensions = supported_report_file_extensions()
        candidates: Iterable[Path]
        candidates = (scan_root,) if scan_root.is_file() else scan_root.rglob("*")
        discovered: list[tuple[Path, str]] = []
        failures: list[ParseFilePreflight] = []
        try:
            for path in candidates:
                if not path.is_file() or path.suffix.lower() not in supported_extensions:
                    continue
                display_name = (
                    path.name
                    if scan_root.is_file()
                    else str(path.relative_to(scan_root))
                )
                try:
                    if path.stat().st_size <= 0:
                        failures.append(_unreadable_entry(display_name, path, "Source file is empty"))
                        continue
                except OSError as exc:
                    failures.append(_unreadable_entry(display_name, path, str(exc)))
                    continue
                discovered.append((path, display_name))
        except OSError as exc:
            failures.append(_unreadable_entry(scan_root.name or str(scan_root), scan_root, str(exc)))
        discovered.sort(key=lambda item: (item[1].casefold(), item[1]))
        return discovered, failures

    @staticmethod
    def _inspect_file(
        path: Path,
        *,
        display_name: str,
        existing_fingerprints: frozenset[str],
    ) -> ParseFilePreflight:
        source_format = infer_source_format(path)
        inspection = SourceInspectionContext.from_path(path, source_format=source_format)
        sha256_value = inspection.sha256
        if not sha256_value:
            return _unreadable_entry(display_name, path, "Could not read source content")
        fingerprint = f"sha256:{sha256_value}"

        try:
            diagnostics = report_parser_factory.resolve_parser_with_diagnostics(
                path,
                source_inspection=inspection,
            )
        except report_parser_factory.ParserAmbiguityError as exc:
            diagnostics = exc.diagnostics
            return ParseFilePreflight(
                display_name=display_name,
                source_path=str(path),
                status=ParsePreflightStatus.AMBIGUOUS,
                source_format=source_format,
                fingerprint=fingerprint,
                reason_codes=_reason_codes(diagnostics),
                candidates=_candidate_evidence(diagnostics),
                competing_parser_ids=tuple(exc.plugin_ids),
                registry_generation_id=diagnostics.registry_generation_id,
                diagnostic_detail=str(exc),
                occurrence_id=_normalize_occurrence_id(display_name),
            )
        except Exception as exc:
            return ParseFilePreflight(
                display_name=display_name,
                source_path=str(path),
                status=ParsePreflightStatus.UNREADABLE,
                source_format=source_format,
                fingerprint=fingerprint,
                reason_codes=("parser_inspection_exception",),
                diagnostic_detail=f"{type(exc).__name__}: {exc}",
                occurrence_id=_normalize_occurrence_id(display_name),
            )

        evidence = _candidate_evidence(diagnostics)
        reason_codes = _reason_codes(diagnostics)
        if diagnostics.selected is None:
            status = (
                ParsePreflightStatus.UNREADABLE
                if diagnostics.rejected_reason == "parser_inspection_failed"
                else ParsePreflightStatus.UNSUPPORTED
            )
            return ParseFilePreflight(
                display_name=display_name,
                source_path=str(path),
                status=status,
                source_format=source_format,
                fingerprint=fingerprint,
                reason_codes=reason_codes,
                candidates=evidence,
                competing_parser_ids=tuple(diagnostics.ambiguous_plugin_ids),
                registry_generation_id=diagnostics.registry_generation_id,
                occurrence_id=_normalize_occurrence_id(display_name),
            )

        selected = diagnostics.selected
        status = (
            ParsePreflightStatus.DUPLICATE
            if fingerprint in existing_fingerprints
            else ParsePreflightStatus.READY
        )
        return ParseFilePreflight(
            display_name=display_name,
            source_path=str(path),
            status=status,
            source_format=source_format,
            fingerprint=fingerprint,
            parser_id=str(selected.plugin_id),
            confidence=int(selected.confidence or 0),
            reason_codes=reason_codes,
            candidates=evidence,
            registry_generation_id=diagnostics.registry_generation_id,
            occurrence_id=_normalize_occurrence_id(display_name),
        )
