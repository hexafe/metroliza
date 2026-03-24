"""Native parsing bridge for CMM block tokenization and row persistence."""

from __future__ import annotations

import os
from threading import Lock
from typing import Any, Literal, NamedTuple

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
_BACKEND_TELEMETRY = {
    "parse": {"native": 0, "python": 0},
    "persistence": {"native": 0, "python": 0},
}


def _record_backend_selection(path: Literal["parse", "persistence"], backend: ResolvedBackend) -> None:
    with _BACKEND_TELEMETRY_LOCK:
        _BACKEND_TELEMETRY[path][backend] += 1


def reset_backend_telemetry() -> None:
    """Reset in-process backend usage telemetry counters."""
    with _BACKEND_TELEMETRY_LOCK:
        for path in _BACKEND_TELEMETRY.values():
            for key in path:
                path[key] = 0


def get_backend_telemetry_snapshot() -> dict[str, dict[str, float | int]]:
    """Return backend counts + usage rates for parse and persistence paths."""
    with _BACKEND_TELEMETRY_LOCK:
        parse_counts = dict(_BACKEND_TELEMETRY["parse"])
        persistence_counts = dict(_BACKEND_TELEMETRY["persistence"])

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
        "persistence": _with_rates(persistence_counts),
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
    for block in blocks:
        header = _normalize_header(block[0]) if len(block) > 0 else ""
        for row in block[1] if len(block) > 1 else ():
            rows.append(
                (
                    row[0] if len(row) > 0 else "",
                    row[1] if len(row) > 1 else "",
                    row[2] if len(row) > 2 else "",
                    row[3] if len(row) > 3 else "",
                    row[4] if len(row) > 4 else "",
                    row[5] if len(row) > 5 else "",
                    row[6] if len(row) > 6 else "",
                    row[7] if len(row) > 7 else "",
                    header,
                    reference,
                    fileloc,
                    filename,
                    date,
                    sample_number,
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
    if backend == "native":
        if _native_normalize_measurement_rows is None:
            raise RuntimeError("Native measurement row normalization requested but unavailable")
        return _native_normalize_measurement_rows(
            blocks,
            reference,
            fileloc,
            filename,
            date,
            sample_number,
        )

    return normalize_measurement_rows_python(
        blocks,
        reference=reference,
        fileloc=fileloc,
        filename=filename,
        date=date,
        sample_number=sample_number,
    )


def persist_measurement_rows_python(database: str, rows: list[tuple[Any, ...]]) -> bool:
    """Insert normalized rows into sqlite using Python sqlite3 path."""
    if not rows:
        return False

    first = rows[0]
    report_identity = (first[9], first[10], first[11], first[12], first[13])

    def _insert(cursor):
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS MEASUREMENTS (
                        ID INTEGER PRIMARY KEY,
                        AX TEXT,
                        NOM REAL,
                        "+TOL" REAL,
                        "-TOL" REAL,
                        BONUS REAL,
                        MEAS REAL,
                        DEV REAL,
                        OUTTOL REAL,
                        HEADER TEXT,
                        REPORT_ID INTEGER,
                        FOREIGN KEY (REPORT_ID) REFERENCES REPORTS(ID)
                    )'''
        )
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS REPORTS (
                        ID INTEGER PRIMARY KEY,
                        REFERENCE TEXT,
                        FILELOC TEXT,
                        FILENAME TEXT,
                        DATE TEXT,
                        SAMPLE_NUMBER TEXT
                    )'''
        )
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
            [
                (None, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], report_id)
                for r in rows
            ],
        )
        return True

    return run_transaction_with_retry(database, _insert, retries=4, retry_delay_s=1)


def persist_measurement_rows_with_backend_and_telemetry(
    database: str,
    rows: list[tuple[Any, ...]],
    *,
    use_native: bool = False,
) -> PersistBackendResult:
    """Persist normalized rows with optional native DB path."""
    backend = resolve_cmm_persistence_backend(use_native=use_native)
    if backend == "native":
        if _native_persist_measurement_rows is None:
            raise RuntimeError("Native measurement row persistence requested but unavailable")
        _record_backend_selection("persistence", "native")
        return PersistBackendResult(inserted=bool(_native_persist_measurement_rows(database, rows)), backend="native")

    _record_backend_selection("persistence", "python")
    return PersistBackendResult(inserted=persist_measurement_rows_python(database, rows), backend="python")


def parse_blocks_with_backend(raw_lines: list[str], use_native: bool = False) -> list[list[Any]]:
    """Parse blocks with explicit backend selection policy."""
    return parse_blocks_with_backend_and_telemetry(raw_lines, use_native=use_native).blocks


def native_backend_available() -> bool:
    return _native_parse_blocks is not None


def native_persistence_backend_available() -> bool:
    return _native_normalize_measurement_rows is not None and _native_persist_measurement_rows is not None
