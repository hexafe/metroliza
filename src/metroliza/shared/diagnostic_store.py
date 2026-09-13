"""Private, bounded storage for validated local diagnostic incidents."""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import io
import json
import os
import re
import stat
import time
import uuid
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from metroliza.shared.diagnostic_incident import (
    MAX_INCIDENT_BYTES,
    DiagnosticIncident,
    IncidentValidationError,
    decode_incident,
    encode_incident,
)


MAX_REPORTS = 20
MAX_MARKERS = 32
MAX_STORE_BYTES = 32 * 1024 * 1024
MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000
MAX_SCAN_ENTRIES = 256
LOCK_TIMEOUT_SECONDS = 0.25
_UUID_HEX = re.compile(r"[0-9a-f]{32}\Z")
_BUILD_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_REPORT_NAME = re.compile(r"incident-([0-9a-f]{32})\.json\Z")
_MARKER_NAME = re.compile(r"marker-([0-9a-f]{32})\.json\Z")
_STAGE_NAME = re.compile(r"\.stage-[0-9a-f]{32}\.tmp\Z")
_LOCK_NAME = ".diagnostic-store.lock"


class StoreStatus(str, Enum):
    PUBLISH_INCOMPLETE = "publish_incomplete"
    SAVED = "saved"
    AVAILABLE = "available"
    EXPORTED = "exported"
    MARKER_STARTED = "marker_started"
    MARKER_AUTHENTICATED = "marker_authenticated"
    MARKER_CLEAN_ENDED = "marker_clean_ended"
    MARKER_RETAINED = "marker_retained"
    MARKER_RESOLVED = "marker_resolved"
    CANCELLED = "cancelled"
    INVALID = "invalid"
    NOT_FOUND = "not_found"
    LOCK_UNAVAILABLE = "lock_unavailable"
    ROOT_UNAVAILABLE = "root_unavailable"
    QUOTA_EXCEEDED = "quota_exceeded"
    IO_FAILED = "io_failed"
    DESTINATION_EXISTS = "destination_exists"


@dataclass(frozen=True, slots=True)
class StoreResult:
    status: StoreStatus
    report_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ReportRecord:
    report_id: uuid.UUID
    created_at_ms: int
    build_git_sha: str
    size_bytes: int
    lost_history: bool


@dataclass(frozen=True, slots=True)
class ReportListResult:
    status: StoreStatus
    reports: tuple[ReportRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class IncidentLoadResult:
    status: StoreStatus
    incident: DiagnosticIncident | None = None


@dataclass(frozen=True, slots=True)
class UncleanSession:
    session_id: uuid.UUID
    created_at_ms: int
    build_git_sha: str
    state: str = "unclean_unknown"


@dataclass(frozen=True, slots=True)
class UncleanSessionListResult:
    status: StoreStatus
    sessions: tuple[UncleanSession, ...] = ()


@dataclass(frozen=True, slots=True)
class _Inventory:
    reports: tuple[Path, ...]
    markers: tuple[Path, ...]
    staging: tuple[Path, ...]
    total_bytes: int


def _default_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base or not Path(base).is_absolute():
            raise OSError("diagnostic_root_unavailable")
        return Path(base) / "Metroliza" / "diagnostics"
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home and Path(state_home).is_absolute():
        return Path(state_home) / "metroliza" / "diagnostics"
    home = os.environ.get("HOME")
    if not home or not Path(home).is_absolute():
        raise OSError("diagnostic_root_unavailable")
    return Path(home) / ".local" / "state" / "metroliza" / "diagnostics"


def _is_reparse_or_link(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _existing_ancestors_safe(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return False
        if _is_reparse_or_link(metadata):
            return False
    return True


def _apply_windows_private_acl(path: Path) -> bool:
    if os.name != "nt":
        return True
    descriptor = ctypes.c_void_p()
    convert = ctypes.windll.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    ]
    convert.restype = ctypes.c_int
    if not convert("D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;OW)", 1, ctypes.byref(descriptor), None):
        return False
    try:
        information = 0x00000004 | 0x80000000
        apply_security = ctypes.windll.advapi32.SetFileSecurityW
        apply_security.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
        apply_security.restype = ctypes.c_int
        return bool(apply_security(str(path), information, descriptor))
    finally:
        ctypes.windll.kernel32.LocalFree(descriptor)


def _ensure_private_root(path: Path) -> bool:
    if not path.is_absolute() or not _existing_ancestors_safe(path):
        return False
    try:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            if not current.exists():
                current.mkdir(mode=0o700, exist_ok=True)
        if not _existing_ancestors_safe(path):
            return False
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or _is_reparse_or_link(metadata):
            return False
        if os.name != "nt":
            if metadata.st_uid != os.getuid():
                return False
            path.chmod(0o700)
            if stat.S_IMODE(path.stat().st_mode) != 0o700:
                return False
        return _apply_windows_private_acl(path)
    except OSError:
        return False


def _open_flags(base: int) -> int:
    return base | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)


def _safe_file_bytes(path: Path, maximum: int) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or _is_reparse_or_link(before)
        or before.st_nlink != 1
        or before.st_size < 0
        or before.st_size > maximum
    ):
        raise OSError("unsafe_diagnostic_file")
    if os.name != "nt" and before.st_uid != os.getuid():
        raise OSError("unsafe_diagnostic_file")
    descriptor = os.open(path, _open_flags(os.O_RDONLY))
    try:
        after = os.fstat(descriptor)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_nlink != 1
            or not stat.S_ISREG(after.st_mode)
        ):
            raise OSError("unsafe_diagnostic_file")
        data = bytearray()
        while len(data) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > maximum or len(data) != after.st_size:
            raise OSError("unsafe_diagnostic_file")
        return bytes(data)
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)


class _StoreLock:
    def __init__(self, root: Path) -> None:
        self.path = root / _LOCK_NAME
        self.descriptor: int | None = None

    def acquire(self) -> bool:
        try:
            descriptor = os.open(self.path, _open_flags(os.O_RDWR | os.O_CREAT), 0o600)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                os.close(descriptor)
                return False
            if os.name != "nt" and metadata.st_uid != os.getuid():
                os.close(descriptor)
                return False
            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt

                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.descriptor = descriptor
                    return True
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        os.close(descriptor)
                        return False
                    time.sleep(0.01)
        except OSError:
            return False

    def release(self) -> None:
        if self.descriptor is None:
            return
        descriptor, self.descriptor = self.descriptor, None
        with contextlib.suppress(OSError):
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(descriptor)


def _parse_id(value: uuid.UUID | str) -> uuid.UUID:
    if type(value) is uuid.UUID:
        identifier = value
    elif type(value) is str and _UUID_HEX.fullmatch(value) is not None:
        identifier = uuid.UUID(hex=value)
    else:
        raise ValueError("invalid_diagnostic_identifier")
    if identifier.version != 4 or identifier.variant != uuid.RFC_4122:
        raise ValueError("invalid_diagnostic_identifier")
    return identifier


def _build_sha_value(value: object) -> str:
    if type(value) is not str or (value != "unknown" and _BUILD_SHA.fullmatch(value) is None):
        raise ValueError("invalid_build_identity")
    return value


def _write_stage(root: Path, data: bytes) -> Path:
    path = root / f".stage-{uuid.uuid4().hex}.tmp"
    descriptor = os.open(path, _open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL), 0o600)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset : offset + 65536])
        os.fsync(descriptor)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        with contextlib.suppress(OSError):
            path.unlink()
        raise
    else:
        os.close(descriptor)
    return path


def _publish_stage(stage: Path, final: Path) -> tuple[int, int]:
    if final.exists() or final.is_symlink():
        raise FileExistsError("diagnostic_target_exists")
    staged = stage.lstat()
    identity = (staged.st_dev, staged.st_ino)
    os.link(stage, final, follow_symlinks=False)
    try:
        stage.unlink()
        if os.name != "nt":
            descriptor = os.open(final.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        metadata = final.lstat()
        if (
            (metadata.st_dev, metadata.st_ino) != identity
            or metadata.st_nlink != 1
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise OSError("diagnostic_publication_alias")
        return identity
    except OSError:
        _unlink_if_identity(final, identity)
        if final.exists() and stage.exists():
            with contextlib.suppress(OSError):
                stage.unlink()
            _unlink_if_identity(final, identity)
        raise


def _unlink_if_identity(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        metadata = path.lstat()
        if (metadata.st_dev, metadata.st_ino) == identity:
            path.unlink()
    except OSError:
        pass


def _read_incident_file(path: Path) -> tuple[DiagnosticIncident, tuple[int, int]]:
    before = path.lstat()
    identity = before.st_dev, before.st_ino
    incident = decode_incident(_safe_file_bytes(path, MAX_INCIDENT_BYTES))
    after = path.lstat()
    if (after.st_dev, after.st_ino) != identity:
        raise OSError("diagnostic_file_changed")
    return incident, identity


def _lost_history(incident: DiagnosticIncident) -> bool:
    if incident.observation.source_dropped or not incident.observation.source_loss_known:
        return True
    if incident.observation.channel.value != "complete":
        return True
    payload = (
        vars(incident.ring_loss)
        if hasattr(incident.ring_loss, "__dict__")
        else {
            field: getattr(incident.ring_loss, field)
            for field in incident.ring_loss.__dataclass_fields__
        }
    )
    return any(value for key, value in payload.items() if key != "counters_saturated") or bool(
        payload["counters_saturated"]
    )


def _valid_inventory_metadata(metadata: os.stat_result) -> bool:
    return (stat.S_ISREG(metadata.st_mode) and not _is_reparse_or_link(metadata)
            and metadata.st_nlink == 1 and metadata.st_size >= 0
            and (os.name == "nt" or metadata.st_uid == os.getuid()))


class IncidentStore:
    """Serialize incident and marker operations under one private local lock."""

    def __init__(self, root: Path | None = None) -> None:
        if root is not None:
            self.root: Path | None = Path(root)
            return
        try:
            self.root = _default_root()
        except OSError:
            self.root = None

    def _inventory(self) -> _Inventory | None:
        reports: list[Path] = []
        markers: list[Path] = []
        staging: list[Path] = []
        total = 0
        try:
            with os.scandir(self.root) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_SCAN_ENTRIES:
                        return None
                    if entry.name == _LOCK_NAME:
                        continue
                    path = Path(entry.path)
                    metadata = entry.stat(follow_symlinks=False)
                    if not _valid_inventory_metadata(metadata):
                        return None
                    if _REPORT_NAME.fullmatch(entry.name):
                        reports.append(path)
                    elif _MARKER_NAME.fullmatch(entry.name):
                        markers.append(path)
                    elif _STAGE_NAME.fullmatch(entry.name):
                        staging.append(path)
                    else:
                        return None
                    total += metadata.st_size
                    if total > MAX_STORE_BYTES:
                        return None
        except OSError:
            return None
        return _Inventory(tuple(reports), tuple(markers), tuple(staging), total)

    def _cleanup_inactive(self, inventory: _Inventory, *, marker_headroom: bool = False) -> bool:
        try:
            for path in inventory.staging:
                _safe_file_bytes(path, MAX_INCIDENT_BYTES)
                path.unlink()
            clean_markers: list[tuple[int, Path]] = []
            for path in inventory.markers:
                marker = _decode_marker(_safe_file_bytes(path, 4096))
                if marker["phase"] == "clean_ended":
                    clean_markers.append((marker["created_at_ms"], path))
            clean_markers.sort(key=lambda item: (item[0], item[1].name))
            remove_count = max(0, len(clean_markers) - 20)
            if marker_headroom and len(inventory.markers) - remove_count >= MAX_MARKERS:
                remove_count += 1
            for _created_at, path in clean_markers[:remove_count]:
                path.unlink()
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _cleanup_expired_reports(self, inventory: _Inventory, now_ms: int) -> bool:
        removed = False
        try:
            for path in inventory.reports:
                incident, identity = _read_incident_file(path)
                match = _REPORT_NAME.fullmatch(path.name)
                if match is None or incident.report_id.hex != match.group(1):
                    return False
                if incident.created_at_ms > now_ms + 300_000:
                    return False
                if now_ms - incident.created_at_ms > MAX_AGE_MS:
                    _unlink_if_identity(path, identity)
                    if path.exists():
                        return False
                    removed = True
            if removed and os.name != "nt":
                descriptor = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return True
        except (OSError, IncidentValidationError):
            return False

    @contextlib.contextmanager
    def _locked(self):
        if self.root is None or not _ensure_private_root(self.root):
            yield StoreStatus.ROOT_UNAVAILABLE
            return
        lock = _StoreLock(self.root)
        if not lock.acquire():
            yield StoreStatus.LOCK_UNAVAILABLE
            return
        try:
            yield StoreStatus.AVAILABLE
        finally:
            lock.release()

    def publish(self, incident: DiagnosticIncident | bytes) -> StoreResult:
        try:
            validated = decode_incident(incident) if type(incident) is bytes else incident
            encoded = encode_incident(validated)
        except (IncidentValidationError, TypeError, AttributeError):
            return StoreResult(StoreStatus.INVALID)
        now_ms = time.time_ns() // 1_000_000
        if (
            validated.created_at_ms > now_ms + 300_000
            or now_ms - validated.created_at_ms > MAX_AGE_MS
        ):
            return StoreResult(StoreStatus.INVALID)
        with self._locked() as status:
            if status is not StoreStatus.AVAILABLE:
                return StoreResult(status)
            inventory = self._inventory()
            if inventory is None:
                return StoreResult(StoreStatus.ROOT_UNAVAILABLE)
            if not self._cleanup_expired_reports(inventory, now_ms):
                return StoreResult(StoreStatus.INVALID)
            inventory = self._inventory()
            if inventory is None:
                return StoreResult(StoreStatus.ROOT_UNAVAILABLE)
            if len(inventory.reports) >= MAX_REPORTS:
                return StoreResult(StoreStatus.QUOTA_EXCEEDED)
            if len(inventory.markers) > MAX_MARKERS:
                return StoreResult(StoreStatus.QUOTA_EXCEEDED)
            if (
                len(encoded) > MAX_INCIDENT_BYTES
                or inventory.total_bytes + len(encoded) > MAX_STORE_BYTES
            ):
                return StoreResult(StoreStatus.QUOTA_EXCEEDED)
            return self._publish_validated_incident(validated, encoded)

    def _publish_validated_incident(self, validated: DiagnosticIncident, encoded: bytes) -> StoreResult:
        final = self.root / f"incident-{validated.report_id.hex}.json"
        stage: Path | None = None
        published_identity: tuple[int, int] | None = None
        try:
            stage = _write_stage(self.root, encoded)
            if decode_incident(_safe_file_bytes(stage, MAX_INCIDENT_BYTES)) != validated:
                raise OSError("staged_incident_invalid")
            published_identity = _publish_stage(stage, final)
            if decode_incident(_safe_file_bytes(final, MAX_INCIDENT_BYTES)) != validated:
                raise OSError("published_incident_invalid")
            return StoreResult(StoreStatus.SAVED, validated.report_id)
        except FileExistsError:
            return StoreResult(StoreStatus.INVALID)
        except (OSError, IncidentValidationError):
            _unlink_if_identity(final, published_identity)
            return StoreResult(StoreStatus.IO_FAILED)
        finally:
            if stage is not None and stage.exists() and not final.exists():
                with contextlib.suppress(OSError):
                    stage.unlink()

    def list_reports(self) -> ReportListResult:
        with self._locked() as status:
            if status is not StoreStatus.AVAILABLE:
                return ReportListResult(status)
            inventory = self._inventory()
            if inventory is None or len(inventory.reports) > MAX_REPORTS:
                return ReportListResult(StoreStatus.ROOT_UNAVAILABLE)
            records: list[ReportRecord] = []
            now_ms = time.time_ns() // 1_000_000
            for path in inventory.reports:
                try:
                    incident, identity = _read_incident_file(path)
                    match = _REPORT_NAME.fullmatch(path.name)
                    if match is None or incident.report_id.hex != match.group(1):
                        raise IncidentValidationError("invalid diagnostic incident")
                    if now_ms - incident.created_at_ms > MAX_AGE_MS:
                        _unlink_if_identity(path, identity)
                        if path.exists():
                            raise OSError("expired_incident_cleanup_failed")
                        continue
                    records.append(
                        ReportRecord(
                            incident.report_id,
                            incident.created_at_ms,
                            incident.build_git_sha,
                            len(encode_incident(incident)),
                            _lost_history(incident),
                        )
                    )
                except (OSError, IncidentValidationError):
                    return ReportListResult(StoreStatus.INVALID)
            records.sort(
                key=lambda record: (record.created_at_ms, record.report_id.hex), reverse=True
            )
            return ReportListResult(StoreStatus.AVAILABLE, tuple(records))

    def load(self, report_id: uuid.UUID | str) -> IncidentLoadResult:
        try:
            identifier = _parse_id(report_id)
        except ValueError:
            return IncidentLoadResult(StoreStatus.INVALID)
        with self._locked() as status:
            if status is not StoreStatus.AVAILABLE:
                return IncidentLoadResult(status)
            path = self.root / f"incident-{identifier.hex}.json"
            try:
                incident, _identity = _read_incident_file(path)
                if incident.report_id != identifier:
                    return IncidentLoadResult(StoreStatus.INVALID)
                now_ms = time.time_ns() // 1_000_000
                if (
                    incident.created_at_ms > now_ms + 300_000
                    or now_ms - incident.created_at_ms > MAX_AGE_MS
                ):
                    return IncidentLoadResult(StoreStatus.INVALID)
                return IncidentLoadResult(StoreStatus.AVAILABLE, incident)
            except FileNotFoundError:
                return IncidentLoadResult(StoreStatus.NOT_FOUND)
            except (OSError, IncidentValidationError):
                return IncidentLoadResult(StoreStatus.INVALID)

    def export(self, report_id: uuid.UUID | str, destination: Path | None) -> StoreResult:
        try:
            identifier = _parse_id(report_id)
        except ValueError:
            return StoreResult(StoreStatus.INVALID)
        if destination is None:
            return StoreResult(StoreStatus.CANCELLED, identifier)
        target = Path(destination)
        if (
            not target.is_absolute()
            or not target.parent.is_dir()
            or not _existing_ancestors_safe(target.parent)
        ):
            return StoreResult(StoreStatus.ROOT_UNAVAILABLE, identifier)
        if target.exists() or target.is_symlink():
            return StoreResult(StoreStatus.DESTINATION_EXISTS, identifier)
        loaded = self.load(identifier)
        if loaded.status is not StoreStatus.AVAILABLE or loaded.incident is None:
            return StoreResult(loaded.status, identifier)
        incident_bytes = encode_incident(loaded.incident)
        summary = self._summary_bytes(loaded.incident)
        manifest = self._manifest_bytes(incident_bytes, summary)
        bundle = self._bundle_bytes(incident_bytes, manifest, summary)
        stage: Path | None = None
        published_identity: tuple[int, int] | None = None
        try:
            stage = _write_stage(target.parent, bundle)
            published_identity = _publish_stage(stage, target)
            if _safe_file_bytes(target, len(bundle)) != bundle:
                raise OSError("published_export_invalid")
            return StoreResult(StoreStatus.EXPORTED, identifier)
        except FileExistsError:
            return StoreResult(StoreStatus.DESTINATION_EXISTS, identifier)
        except OSError:
            _unlink_if_identity(target, published_identity)
            return StoreResult(StoreStatus.IO_FAILED, identifier)
        finally:
            if stage is not None and stage.exists() and not target.exists():
                with contextlib.suppress(OSError):
                    stage.unlink()

    @staticmethod
    def _summary_bytes(incident: DiagnosticIncident) -> bytes:
        payload = {
            "schema_version": 1,
            "report_id": incident.report_id.hex,
            "session_id": incident.session_id.hex,
            "created_at_ms": incident.created_at_ms,
            "build_git_sha": incident.build_git_sha,
            "launch": incident.observation.launch.value,
            "handshake": incident.observation.handshake.value,
            "channel": incident.observation.channel.value,
            "exit_code": incident.observation.exit_code,
            "termination": incident.observation.termination.value,
            "native_stack": "unavailable",
            "event_count": len(incident.events),
            "lost_history": _lost_history(incident),
        }
        return json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")

    @staticmethod
    def _manifest_bytes(incident: bytes, summary: bytes) -> bytes:
        payload = {
            "schema_version": 1,
            "bundle_format": "metroliza_safe_incident_v1",
            "files": [
                {
                    "name": "incident.json",
                    "size_bytes": len(incident),
                    "sha256": hashlib.sha256(incident).hexdigest(),
                },
                {
                    "name": "summary.json",
                    "size_bytes": len(summary),
                    "sha256": hashlib.sha256(summary).hexdigest(),
                },
            ],
        }
        return json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")

    @staticmethod
    def _bundle_bytes(incident: bytes, manifest: bytes, summary: bytes) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as bundle:
            for name, data in (
                ("incident.json", incident),
                ("manifest.json", manifest),
                ("summary.json", summary),
            ):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                bundle.writestr(info, data)
        return output.getvalue()

    def begin_session(
        self, session_id: uuid.UUID | str, build_git_sha: str = "unknown"
    ) -> StoreResult:
        try:
            identifier = _parse_id(session_id)
            build_sha = _build_sha_value(build_git_sha)
            process_start_id = _process_start_identity(os.getpid())
            if process_start_id is None:
                raise ValueError("process_identity_unavailable")
        except ValueError:
            return StoreResult(StoreStatus.INVALID)
        payload = _marker_bytes(
            identifier,
            build_sha,
            os.getpid(),
            process_start_id,
            "started",
            time.time_ns() // 1_000_000,
        )
        with self._locked() as status:
            if status is not StoreStatus.AVAILABLE:
                return StoreResult(status)
            inventory = self._inventory()
            if inventory is None:
                return StoreResult(StoreStatus.ROOT_UNAVAILABLE)
            if not self._cleanup_inactive(inventory, marker_headroom=True):
                return StoreResult(StoreStatus.IO_FAILED)
            inventory = self._inventory()
            if inventory is None:
                return StoreResult(StoreStatus.ROOT_UNAVAILABLE)
            if (
                len(inventory.markers) >= MAX_MARKERS
                or inventory.total_bytes + len(payload) > MAX_STORE_BYTES
            ):
                return StoreResult(StoreStatus.QUOTA_EXCEEDED)
            return self._publish_marker(identifier, payload)

    def _publish_marker(self, identifier: uuid.UUID, payload: bytes) -> StoreResult:
        final = self.root / f"marker-{identifier.hex}.json"
        stage: Path | None = None
        try:
            stage = _write_stage(self.root, payload)
            _publish_stage(stage, final)
            return StoreResult(StoreStatus.MARKER_STARTED)
        except FileExistsError:
            return StoreResult(StoreStatus.INVALID)
        except OSError:
            return StoreResult(StoreStatus.IO_FAILED)
        finally:
            if stage is not None and stage.exists() and not final.exists():
                with contextlib.suppress(OSError):
                    stage.unlink()

    def authenticate_session(self, session_id: uuid.UUID | str) -> StoreResult:
        return self._replace_marker_phase(
            session_id,
            expected_phases=("started",),
            phase="authenticated",
            result_status=StoreStatus.MARKER_AUTHENTICATED,
        )

    def end_session(self, session_id: uuid.UUID | str, clean: bool) -> StoreResult:
        try:
            identifier = _parse_id(session_id)
        except ValueError:
            return StoreResult(StoreStatus.INVALID)
        if type(clean) is not bool:
            return StoreResult(StoreStatus.INVALID)
        if not clean:
            return self._replace_marker_phase(
                identifier,
                expected_phases=("started", "authenticated"),
                phase=None,
                result_status=StoreStatus.MARKER_RETAINED,
            )
        return self._replace_marker_phase(
            identifier,
            expected_phases=("authenticated",),
            phase="clean_ended",
            result_status=StoreStatus.MARKER_CLEAN_ENDED,
        )

    def resolve_session(
        self,
        session_id: uuid.UUID | str,
        report_id: uuid.UUID | str,
    ) -> StoreResult:
        try:
            session = _parse_id(session_id)
            report = _parse_id(report_id)
        except ValueError:
            return StoreResult(StoreStatus.INVALID)
        with self._locked() as lock_status:
            if lock_status is not StoreStatus.AVAILABLE:
                return StoreResult(lock_status)
            report_path = self.root / f"incident-{report.hex}.json"
            marker_path = self.root / f"marker-{session.hex}.json"
            try:
                incident, _identity = _read_incident_file(report_path)
                marker = _decode_marker(_safe_file_bytes(marker_path, 4096))
                if incident.report_id != report or incident.session_id != session:
                    return StoreResult(StoreStatus.INVALID)
                if marker["session_id"] != session.hex or marker["phase"] == "clean_ended":
                    return StoreResult(StoreStatus.INVALID)
                marker_path.unlink()
                if os.name != "nt":
                    descriptor = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                return StoreResult(StoreStatus.MARKER_RESOLVED, report)
            except FileNotFoundError:
                return StoreResult(StoreStatus.NOT_FOUND)
            except (OSError, IncidentValidationError, ValueError, KeyError, TypeError):
                return StoreResult(StoreStatus.IO_FAILED)

    @staticmethod
    def _owns_marker(marker: dict, identifier: uuid.UUID, expected_phases: tuple[str, ...]) -> bool:
        return (marker["session_id"] == identifier.hex
                and marker["supervisor_pid"] == os.getpid()
                and marker["process_start_id"] == _process_start_identity(os.getpid())
                and marker["phase"] in expected_phases)

    def _replace_marker_phase(
        self,
        session_id: uuid.UUID | str,
        *,
        expected_phases: tuple[str, ...],
        phase: str | None,
        result_status: StoreStatus,
    ) -> StoreResult:
        try:
            identifier = _parse_id(session_id)
        except ValueError:
            return StoreResult(StoreStatus.INVALID)
        with self._locked() as lock_status:
            if lock_status is not StoreStatus.AVAILABLE:
                return StoreResult(lock_status)
            path = self.root / f"marker-{identifier.hex}.json"
            try:
                marker = _decode_marker(_safe_file_bytes(path, 4096))
                if not self._owns_marker(marker, identifier, expected_phases):
                    return StoreResult(StoreStatus.INVALID)
                if phase is None:
                    return StoreResult(result_status)
                replacement = _marker_bytes(
                    identifier,
                    marker["build_git_sha"],
                    marker["supervisor_pid"],
                    marker["process_start_id"],
                    phase,
                    marker["created_at_ms"],
                )
                stage = _write_stage(self.root, replacement)
                try:
                    os.replace(stage, path)
                    if os.name != "nt":
                        descriptor = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                finally:
                    if stage.exists():
                        stage.unlink()
                return StoreResult(result_status)
            except FileNotFoundError:
                return StoreResult(StoreStatus.NOT_FOUND)
            except (OSError, ValueError):
                return StoreResult(StoreStatus.IO_FAILED)

    def list_unclean_sessions(self) -> UncleanSessionListResult:
        with self._locked() as status:
            if status is not StoreStatus.AVAILABLE:
                return UncleanSessionListResult(status)
            inventory = self._inventory()
            if inventory is None or len(inventory.markers) > MAX_MARKERS:
                return UncleanSessionListResult(StoreStatus.ROOT_UNAVAILABLE)
            sessions: list[UncleanSession] = []
            for path in inventory.markers:
                try:
                    marker = _decode_marker(_safe_file_bytes(path, 4096))
                    match = _MARKER_NAME.fullmatch(path.name)
                    if match is None or marker["session_id"] != match.group(1):
                        raise ValueError("invalid_marker")
                    if marker["phase"] == "clean_ended":
                        continue
                    identity = _process_start_identity(marker["supervisor_pid"])
                    if identity is not None and identity == marker["process_start_id"]:
                        continue
                    sessions.append(
                        UncleanSession(
                            uuid.UUID(hex=marker["session_id"]),
                            marker["created_at_ms"],
                            marker["build_git_sha"],
                        )
                    )
                except (OSError, ValueError, KeyError, TypeError):
                    return UncleanSessionListResult(StoreStatus.INVALID)
            sessions.sort(key=lambda item: (item.created_at_ms, item.session_id.hex), reverse=True)
            return UncleanSessionListResult(StoreStatus.AVAILABLE, tuple(sessions))


def _marker_bytes(
    session_id: uuid.UUID,
    build_git_sha: str,
    supervisor_pid: int,
    process_start_id: int,
    phase: str,
    created_at_ms: int,
) -> bytes:
    payload = {
        "schema_version": 1,
        "session_id": session_id.hex,
        "build_git_sha": _build_sha_value(build_git_sha),
        "supervisor_pid": supervisor_pid,
        "process_start_id": process_start_id,
        "phase": phase,
        "created_at_ms": created_at_ms,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode(
        "ascii"
    )
    if len(encoded) > 4096:
        raise ValueError("invalid_marker")
    return encoded


def _decode_marker(data: bytes) -> dict[str, object]:
    if not data or len(data) > 4096:
        raise ValueError("invalid_marker")
    value = json.loads(data.decode("ascii"))
    keys = {
        "schema_version",
        "session_id",
        "build_git_sha",
        "supervisor_pid",
        "process_start_id",
        "phase",
        "created_at_ms",
    }
    if type(value) is not dict or set(value) != keys:
        raise ValueError("invalid_marker")
    if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
        raise ValueError("invalid_marker")
    _parse_id(value["session_id"])
    _build_sha_value(value["build_git_sha"])
    for key in ("supervisor_pid", "process_start_id", "created_at_ms"):
        if type(value[key]) is not int or not 0 <= value[key] <= 2**63 - 1:
            raise ValueError("invalid_marker")
    if (
        value["phase"] not in ("started", "authenticated", "clean_ended")
        or type(value["phase"]) is not str
    ):
        raise ValueError("invalid_marker")
    canonical = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode(
        "ascii"
    )
    if canonical != data:
        raise ValueError("invalid_marker")
    return value


def _process_start_identity(pid: int) -> int | None:
    if type(pid) is not int or pid <= 0:
        return None
    if os.name == "nt":
        return _windows_process_start_identity(pid)
    path = Path("/proc") / str(pid) / "stat"
    try:
        data = path.read_bytes()
        if len(data) > 4096:
            return None
        closing = data.rfind(b")")
        if closing < 0:
            return None
        fields = data[closing + 2 :].split()
        value = int(fields[19])
        return value if value >= 0 else None
    except (OSError, ValueError, IndexError):
        return None


def _windows_process_start_identity(pid: int) -> int | None:
    from ctypes import wintypes

    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel.CloseHandle(handle)
