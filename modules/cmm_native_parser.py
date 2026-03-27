"""Native parsing bridge for CMM block tokenization and row persistence."""

from __future__ import annotations

import os
import sqlite3
import time
from threading import Lock
from typing import Any, Literal, NamedTuple

from modules.cmm_schema import ensure_cmm_report_schema
from modules.cmm_parsing import parse_raw_lines_to_blocks
from modules.db import run_transaction_with_retry

try:
    from _metroliza_cmm_native import (  # type: ignore
        parse_blocks as _native_parse_blocks,
        normalize_measurement_rows as _native_normalize_measurement_rows,
        persist_measurement_rows as _native_persist_measurement_rows,
    )
except Exception:  # pragma: no cover - optional native module
    _native_parse_blocks = None
    _native_normalize_measurement_rows = None
    _native_persist_measurement_rows = None

_BACKEND_TELEMETRY_LOCK = Lock()
_NATIVE_SCHEMA_INIT_LOCK = Lock()
_NATIVE_SCHEMA_INIT_DATABASES: set[str] = set()
_BACKEND_TELEMETRY = {
    "parse": {"native": 0, "python": 0},
    "normalize": {"native": 0, "python": 0},
    "persistence": {"native": 0, "python": 0},
    "normalize_rows": {"native": 0, "python": 0},
    "persistence_rows": {"native": 0, "python": 0},
    "persistence_inserted_rows": {"native": 0, "python": 0},
    "normalize_latency_s": {"native": 0.0, "python": 0.0},
    "persistence_latency_s": {"native": 0.0, "python": 0.0},
}


def _ensure_native_schema_initialized(database: str) -> None:
    """Ensure schema/index bootstrap runs once per database path for native persistence."""
    with _NATIVE_SCHEMA_INIT_LOCK:
        already_initialized = database in _NATIVE_SCHEMA_INIT_DATABASES

    if already_initialized:
        return

    ensure_cmm_report_schema(database, retries=4, retry_delay_s=1)

    with _NATIVE_SCHEMA_INIT_LOCK:
        _NATIVE_SCHEMA_INIT_DATABASES.add(database)


def _record_backend_selection(path: Literal["parse", "normalize", "persistence"], backend: ResolvedBackend) -> None:
    with _BACKEND_TELEMETRY_LOCK:
        _BACKEND_TELEMETRY[path][backend] += 1


def _record_backend_volume(
    path: Literal["normalize_rows", "persistence_rows", "persistence_inserted_rows"],
    backend: ResolvedBackend,
    rows: int,
) -> None:
    with _BACKEND_TELEMETRY_LOCK:
        _BACKEND_TELEMETRY[path][backend] += rows


def _record_backend_latency(
    path: Literal["normalize_latency_s", "persistence_latency_s"],
    backend: ResolvedBackend,
    elapsed_s: float,
) -> None:
    with _BACKEND_TELEMETRY_LOCK:
        _BACKEND_TELEMETRY[path][backend] += elapsed_s


def reset_backend_telemetry() -> None:
    """Reset in-process backend usage telemetry counters."""
    with _BACKEND_TELEMETRY_LOCK:
        for path in _BACKEND_TELEMETRY.values():
            for key in path:
                path[key] = 0
    with _NATIVE_SCHEMA_INIT_LOCK:
        _NATIVE_SCHEMA_INIT_DATABASES.clear()


def get_backend_telemetry_snapshot() -> dict[str, dict[str, float | int]]:
    """Return backend counts/rows/latency rates for parse, normalize, and persistence paths."""
    with _BACKEND_TELEMETRY_LOCK:
        parse_counts = dict(_BACKEND_TELEMETRY["parse"])
        normalize_counts = dict(_BACKEND_TELEMETRY["normalize"])
        persistence_counts = dict(_BACKEND_TELEMETRY["persistence"])
        normalize_rows = dict(_BACKEND_TELEMETRY["normalize_rows"])
        persistence_rows = dict(_BACKEND_TELEMETRY["persistence_rows"])
        persistence_inserted_rows = dict(_BACKEND_TELEMETRY["persistence_inserted_rows"])
        normalize_latency_s = dict(_BACKEND_TELEMETRY["normalize_latency_s"])
        persistence_latency_s = dict(_BACKEND_TELEMETRY["persistence_latency_s"])

    def _with_rates(counts: dict[str, int]) -> dict[str, float | int]:
        total = counts["native"] + counts["python"]
        native_rate = (counts["native"] / total) if total else 0.0
        python_rate = (counts["python"] / total) if total else 0.0
        return {
            "native": counts["native"],
            "python": counts["python"],
            "total": total,
            "native_rate": native_rate,
            "python_rate": python_rate,
        }

    return {
        "parse": _with_rates(parse_counts),
        "normalize": {
            **_with_rates(normalize_counts),
            "rows_total": normalize_rows["native"] + normalize_rows["python"],
            "rows_native": normalize_rows["native"],
            "rows_python": normalize_rows["python"],
            "latency_total_s": normalize_latency_s["native"] + normalize_latency_s["python"],
            "latency_native_s": normalize_latency_s["native"],
            "latency_python_s": normalize_latency_s["python"],
        },
        "persistence": _with_rates(persistence_counts),
        "persistence_rows": {
            "total": persistence_rows["native"] + persistence_rows["python"],
            "native": persistence_rows["native"],
            "python": persistence_rows["python"],
            "inserted_total": persistence_inserted_rows["native"] + persistence_inserted_rows["python"],
            "inserted_native": persistence_inserted_rows["native"],
            "inserted_python": persistence_inserted_rows["python"],
            "latency_total_s": persistence_latency_s["native"] + persistence_latency_s["python"],
            "latency_native_s": persistence_latency_s["native"],
            "latency_python_s": persistence_latency_s["python"],
        },
    }


BackendChoice = Literal["auto", "native", "python"]
ResolvedBackend = Literal["native", "python"]

# Stable flat row schema.
MEASUREMENT_ROW_SCHEMA = (
    "ax",
    "nom",
    "tol_plus",
    "tol_minus",
    "bonus",
    "meas",
    "dev",
    "outtol",
    "header",
    "reference",
    "fileloc",
    "filename",
    "date",
    "sample_number",
)


class ParseBackendResult(NamedTuple):
    blocks: list[list[Any]]
    backend: ResolvedBackend


class PersistBackendResult(NamedTuple):
    inserted: bool
    backend: ResolvedBackend


def _runtime_backend_choice() -> BackendChoice:
    choice = os.getenv("METROLIZA_CMM_PARSER_BACKEND", "auto").strip().lower()
    if choice in {"auto", "native", "python"}:
        return choice
    return "auto"


def _runtime_persistence_backend_choice() -> BackendChoice:
    choice = os.getenv("METROLIZA_CMM_PERSIST_BACKEND", "auto").strip().lower()
    if choice in {"auto", "native", "python"}:
        return choice
    return "auto"


def resolve_cmm_parser_backend(use_native: bool = False) -> ResolvedBackend:
    """Resolve which parser backend should be used for the current runtime."""
    backend = _runtime_backend_choice()

    if backend == "python":
        return "python"

    if backend == "native" or use_native:
        if _native_parse_blocks is None:
            raise RuntimeError("Native CMM parser backend requested but unavailable")
        return "native"

    if _native_parse_blocks is not None:
        return "native"
    return "python"


def resolve_cmm_persistence_backend(use_native: bool = False) -> ResolvedBackend:
    """Resolve which persistence backend should be used."""
    backend = _runtime_persistence_backend_choice()

    if backend == "python":
        return "python"

    if backend == "native" or use_native:
        if _native_persist_measurement_rows is None or _native_normalize_measurement_rows is None:
            raise RuntimeError("Native CMM persistence backend requested but unavailable")
        return "native"

    if _native_persist_measurement_rows is not None and _native_normalize_measurement_rows is not None:
        return "native"
    return "python"


def parse_blocks_with_backend_and_telemetry(
    raw_lines: list[str],
    use_native: bool = False,
) -> ParseBackendResult:
    """Parse blocks and return both output and backend used."""
    resolved_backend = resolve_cmm_parser_backend(use_native=use_native)
    if resolved_backend == "native":
        if _native_parse_blocks is None:
            raise RuntimeError("Native CMM parser backend requested but unavailable")
        _record_backend_selection("parse", "native")
        return ParseBackendResult(blocks=_native_parse_blocks(raw_lines), backend="native")

    _record_backend_selection("parse", "python")
    return ParseBackendResult(blocks=parse_raw_lines_to_blocks(raw_lines), backend="python")


def _normalize_header(block_header: Any) -> str:
    parts: list[str] = []
    for item in block_header:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                if isinstance(nested, str):
                    parts.append(nested)
    return ", ".join(value for value in parts if value).replace('"', '')


def normalize_measurement_rows_python(
    blocks: list[list[Any]],
    *,
    reference: str,
    fileloc: str,
    filename: str,
    date: str,
    sample_number: str,
) -> list[tuple[Any, ...]]:
    """Normalize parsed blocks into stable flat measurement records."""
    rows: list[tuple[Any, ...]] = []
    meta = (reference, fileloc, filename, date, sample_number)
    for block in blocks:
        header = _normalize_header(block[0]) if len(block) > 0 else ""
        for row in block[1] if len(block) > 1 else ():
            if not row:
                normalized = ("", "", "", "", "", "", "", "")
            else:
                row_len = len(row)
                if row_len >= 8:
                    normalized = (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
                elif row_len == 7:
                    normalized = (row[0], row[1], row[2], row[3], row[4], row[5], row[6], "")
                elif row_len == 6:
                    normalized = (row[0], row[1], row[2], row[3], row[4], row[5], "", "")
                elif row_len == 5:
                    normalized = (row[0], row[1], row[2], row[3], row[4], "", "", "")
                elif row_len == 4:
                    normalized = (row[0], row[1], row[2], row[3], "", "", "", "")
                elif row_len == 3:
                    normalized = (row[0], row[1], row[2], "", "", "", "", "")
                elif row_len == 2:
                    normalized = (row[0], row[1], "", "", "", "", "", "")
                else:
                    normalized = (row[0], "", "", "", "", "", "", "")
            rows.append(
                (
                    *normalized,
                    header,
                    *meta,
                )
            )
    return rows


def normalize_measurement_rows(
    blocks: list[list[Any]],
    *,
    reference: str,
    fileloc: str,
    filename: str,
    date: str,
    sample_number: str,
    use_native: bool = False,
) -> list[tuple[Any, ...]]:
    """Normalize parsed blocks into flat rows using selected backend."""
    backend = resolve_cmm_persistence_backend(use_native=use_native)
    _record_backend_selection("normalize", backend)
    started = time.perf_counter()
    if backend == "native":
        if _native_normalize_measurement_rows is None:
            raise RuntimeError("Native measurement row normalization requested but unavailable")
        rows = _native_normalize_measurement_rows(
            blocks,
            reference,
            fileloc,
            filename,
            date,
            sample_number,
        )
    else:
        rows = normalize_measurement_rows_python(
            blocks,
            reference=reference,
            fileloc=fileloc,
            filename=filename,
            date=date,
            sample_number=sample_number,
        )

    _record_backend_latency("normalize_latency_s", backend, time.perf_counter() - started)
    _record_backend_volume("normalize_rows", backend, len(rows))
    return rows


def persist_measurement_rows_python(database: str, rows: list[tuple[Any, ...]]) -> bool:
    """Insert normalized rows into sqlite using Python sqlite3 path."""
    if not rows:
        return False

    first = rows[0]
    report_identity = (first[9], first[10], first[11], first[12], first[13])

    def _insert(cursor):
        cursor.execute(
            'SELECT COUNT(*) FROM REPORTS WHERE REFERENCE = ? AND FILELOC = ? AND FILENAME = ? AND DATE = ? AND SAMPLE_NUMBER = ?',
            report_identity,
        )
        count_rows = cursor.fetchall()
        count = count_rows[0][0] if count_rows else 0
        if count > 0:
            return False

        cursor.execute(
            'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
            report_identity,
        )
        report_id = cursor.lastrowid
        cursor.executemany(
            'INSERT INTO MEASUREMENTS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                (None, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], report_id)
                for r in rows
            ),
        )
        return True

    try:
        return run_transaction_with_retry(database, _insert, retries=4, retry_delay_s=1)
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        ensure_cmm_report_schema(database, retries=4, retry_delay_s=1)
        return run_transaction_with_retry(database, _insert, retries=4, retry_delay_s=1)


def persist_measurement_rows_with_backend_and_telemetry(
    database: str,
    rows: list[tuple[Any, ...]],
    *,
    use_native: bool = False,
) -> PersistBackendResult:
    """Persist normalized rows with optional native DB path."""
    backend = resolve_cmm_persistence_backend(use_native=use_native)
    started = time.perf_counter()
    if backend == "native":
        if _native_persist_measurement_rows is None:
            raise RuntimeError("Native measurement row persistence requested but unavailable")
        _ensure_native_schema_initialized(database)
        _record_backend_selection("persistence", "native")
        inserted = bool(_native_persist_measurement_rows(database, rows))
        _record_backend_latency("persistence_latency_s", "native", time.perf_counter() - started)
        _record_backend_volume("persistence_rows", "native", len(rows))
        if inserted:
            _record_backend_volume("persistence_inserted_rows", "native", len(rows))
        return PersistBackendResult(inserted=inserted, backend="native")

    _record_backend_selection("persistence", "python")
    inserted = persist_measurement_rows_python(database, rows)
    _record_backend_latency("persistence_latency_s", "python", time.perf_counter() - started)
    _record_backend_volume("persistence_rows", "python", len(rows))
    if inserted:
        _record_backend_volume("persistence_inserted_rows", "python", len(rows))
    return PersistBackendResult(inserted=inserted, backend="python")


def parse_blocks_with_backend(raw_lines: list[str], use_native: bool = False) -> list[list[Any]]:
    """Parse blocks with explicit backend selection policy."""
    if not raw_lines:
        return []
    return parse_blocks_with_backend_and_telemetry(raw_lines, use_native=use_native).blocks


def native_backend_available() -> bool:
    return _native_parse_blocks is not None


def native_persistence_backend_available() -> bool:
    return _native_normalize_measurement_rows is not None and _native_persist_measurement_rows is not None
