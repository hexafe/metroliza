"""Compare stored CMM structure with the fixed parser; never repair or import.

Usage (from a source checkout with its dependencies installed)::

    PYTHONPATH=src:. python scripts/detect_cmm_page_breaks.py database.db \
        original_folder original_reports.zip --output comparison.json

CSV is selected by a .csv output suffix. The output must not already exist.
Exit 0 means the scan completed (including suspected rows); exit 2 means failure.
Close the app first and use a checkpointed database or an offline copy. Databases
with WAL, SHM or rollback-journal sidecars are refused. SQLite mode=ro and
immutable=1 avoid writes, including sidecar creation; immutable access is safe
only while no other process modifies the database. No schema migration occurs.

The report_metadata_v1 schema stores source_files.sha256: this is the identity,
not the filename or semantic identity_hash. Identical copies are equivalent.
If a stored digest is empty, filename matching is only a fallback: even a unique
name cannot establish content identity, so its verdict remains AMBIGUOUS.
Older schemas without these tables/columns are rejected rather than migrated.
Stored blocks come from raw_report_json.measurement_blocks, not distinct labels
(which can collapse repeated blocks). Missing block provenance is AMBIGUOUS.
EXTRA_BLOCKS_SUSPECTED is a count heuristic, not proof of RC1 causation. MATCH
compares counts only, not measurement values. Single-page PDFs are also counted;
Matched non-CMM reports and parse failures yield OTHER_DIFF with a reason code.
ZIP/TAR sources use the existing bounded safe extractor in temporary directories.
Only filenames, IDs, counts, identity method and reason codes leave the detector.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack, closing, contextmanager, redirect_stderr, redirect_stdout
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import os
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3
from tempfile import TemporaryDirectory

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.preflight import is_supported_report_archive, safe_unpack_report_archive
from metroliza.reports.report_metadata_profiles import DEFAULT_CMM_PDF_HEADER_BOX_PROFILE


@dataclass
class Comparison:
    report_id: int
    file_name: str
    identity: str
    stored_blocks: int | None
    reparsed_blocks: int | None
    stored_measurements: int
    reparsed_measurements: int | None
    verdict: str
    reason: str


class _DetectorCMMParser(CMMReportParser):
    def log_and_exit(self, exception):
        """Keep parser errors headless: the app handler opens a Qt dialog."""
        raise exception


def _basename(value: str) -> str:
    return PureWindowsPath(value).name


@contextmanager
def _quiet_parser():
    previous = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                yield
    finally:
        logging.disable(previous)


def reparse_counts(source: Path) -> tuple[int, int]:
    """Run only parser operations in memory, with no repository/DB connection."""
    with _quiet_parser():
        parser = _DetectorCMMParser(str(source), ":memory:", metadata_parsing_mode="light")
        parser.open_report()
        if not parser.raw_text:
            raise ValueError("PDF_TEXT_UNAVAILABLE")
        parser.split_text_to_blocks()
        parser.add_tolerances()
        return len(parser.blocks_text), len(parser.parse_measurements())


def _source_index(sources: list[Path], stack: ExitStack, temp_dir: Path | None):
    by_hash: dict[str, list[Path]] = defaultdict(list)
    by_name: dict[str, list[Path]] = defaultdict(list)
    for source in sources:
        if source.is_dir():
            root = source
        elif source.is_file() and is_supported_report_archive(source):
            root = Path(stack.enter_context(TemporaryDirectory(dir=temp_dir)))
            safe_unpack_report_archive(source, root)
        else:
            raise ValueError("SOURCE_MUST_BE_FOLDER_OR_ARCHIVE")
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".pdf":
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            by_hash[digest.hexdigest()].append(path)
            by_name[path.name].append(path)
    return by_hash, by_name


@contextmanager
def open_readonly(database: Path):
    """Refuse uncheckpointed/live sidecars; never bootstrap a database schema."""
    database = database.resolve(strict=True)
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("DATABASE_SIDECARS_PRESENT_CLOSE_AND_CHECKPOINT_FIRST")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.row_factory = sqlite3.Row
        yield db


def _classify(result, parser_id, digest, candidates) -> None:
    """Set ``result.verdict``/``reason`` for a report that has source candidates."""
    blocks = result.stored_blocks
    if not digest and len(candidates) != 1:
        result.verdict, result.reason = "AMBIGUOUS", "MULTIPLE_FILENAME_CANDIDATES"
        return
    if parser_id != DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.parser_id:
        result.verdict, result.reason = "OTHER_DIFF", "UNSUPPORTED_PARSER"
        return
    try:
        result.reparsed_blocks, result.reparsed_measurements = reparse_counts(candidates[0])
    except Exception:  # Parser errors must not disclose document text.
        result.verdict, result.reason = "OTHER_DIFF", "PARSE_FAILED"
        return
    if not digest or blocks is None:
        result.verdict, result.reason = "AMBIGUOUS", "WEAK_IDENTITY_OR_MISSING_BLOCK_COUNT"
    elif (blocks, result.stored_measurements) == (result.reparsed_blocks, result.reparsed_measurements):
        result.verdict, result.reason = "MATCH", "COUNTS_EQUAL"
    elif blocks > result.reparsed_blocks:
        result.verdict, result.reason = "EXTRA_BLOCKS_SUSPECTED", "STORED_BLOCK_SURPLUS"
    else:
        result.verdict, result.reason = "OTHER_DIFF", "COUNTS_DIFFER"


def compare_database(database: Path, sources: list[Path], *, temp_dir: Path | None = None):
    """Return one comparison per stored report, including unavailable sources."""
    comparisons = []
    with open_readonly(database) as db, ExitStack() as stack:
        # Fixed SQL only: report schema APIs intentionally are not used, because
        # those can ensure/migrate tables even when called by a read workflow.
        reports = db.execute("""
            SELECT p.id, p.parser_id, p.raw_report_json, s.sha256,
                   (SELECT l.file_name FROM source_file_locations l
                    WHERE l.source_file_id=p.source_file_id
                    ORDER BY l.is_active DESC, l.id DESC LIMIT 1) AS file_name,
                   (SELECT count(*) FROM report_measurements m
                    WHERE m.report_id=p.id) AS measurement_count
            FROM parsed_reports p JOIN source_files s ON s.id=p.source_file_id
            ORDER BY p.id
        """)
        by_hash, by_name = _source_index(sources, stack, temp_dir)
        for report in reports:
            try:
                raw = json.loads(report["raw_report_json"] or "{}")
                blocks = raw.get("measurement_blocks") if isinstance(raw, dict) else None
            except (ValueError, TypeError):
                blocks = None
            if type(blocks) is not int or blocks < 0:
                blocks = None
            name = _basename(report["file_name"] or "")
            digest = report["sha256"]
            identity = "sha256" if digest else "filename_fallback"
            candidates = by_hash.get(digest, []) if digest else by_name.get(name, [])
            result = Comparison(report["id"], name, identity, blocks, None,
                                report["measurement_count"], None, "SOURCE_NOT_FOUND", "NO_SOURCE")
            if not candidates:
                comparisons.append(result)
                continue
            _classify(result, report["parser_id"], digest, candidates)
            comparisons.append(result)
    return comparisons


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("database", type=Path)
    cli.add_argument("sources", type=Path, nargs="+")
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--temp-dir", type=Path)
    args = cli.parse_args(argv)
    try:
        # Exclusive creation also protects symlink/hardlink aliases of the input
        # database and sources; no existing file is ever overwritten.
        if args.output.suffix.lower() not in {".json", ".csv"}:
            raise ValueError("OUTPUT_MUST_BE_JSON_OR_CSV")
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("OUTPUT_ALREADY_EXISTS")
        rows = [asdict(row) for row in compare_database(
            args.database, args.sources, temp_dir=args.temp_dir
        )]
        with args.output.open("x", encoding="utf-8", newline="") as stream:
            if args.output.suffix.lower() == ".json":
                json.dump(rows, stream, indent=2, ensure_ascii=True)
                stream.write("\n")
            else:
                writer = csv.DictWriter(stream, fieldnames=list(Comparison.__dataclass_fields__))
                writer.writeheader()
                writer.writerows(rows)
        print(json.dumps({"reports": len(rows), "verdicts": dict(Counter(
            row["verdict"] for row in rows
        ))}, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error, shutil.ReadError):
        # Do not print exceptions, source paths, hashes, SQL or report contents.
        print("Detection failed: check schema, offline database, sources and output.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
