"""Opt-in #1136 source/build-venv comparison of per-report and batch connections.

Run from the repository root with PYTHONPATH=src. Only synthetic fixtures are
used; receipts contain aggregate timings and row counts, never report content.
This is build-venv evidence, not packaged-runtime or antivirus causation proof.
"""

from __future__ import annotations

import argparse
from contextlib import closing, nullcontext
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
from statistics import median
import tempfile
from time import perf_counter
from unittest.mock import patch

from metroliza.parsing import parse_reports_thread
from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
from metroliza.reports import report_repository
from metroliza.reports.import_persist_profile import ImportPersistProfile
from metroliza.shared.parse_contracts import ParseRequest


CLOCK = "2026-01-01T00:00:00+00:00"


def database_snapshot(database):
    """Compare every column/row, including schema state and generated IDs."""
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        # SQLite quotes and serializes every value itself. No dynamic SELECT or
        # timestamp normalization is needed, and schema differences also fail.
        dump = list(connection.iterdump())
        rows = {name: [] for (name,) in tables}
        for line in dump:
            match = re.match(r'^INSERT INTO "((?:[^"]|"")+)"', line)
            if match:
                rows[match[1].replace('""', '"')].append(line)
        return {"tables": rows, "dump": dump}


def _fixed_clock_connection(connect, *args, **kwargs):
    connection = connect(*args, **kwargs)
    # Freeze only generated audit timestamps; business values remain untouched.
    connection.create_function("current_timestamp", 0, lambda: CLOCK)
    return connection


def _run(source, database, lifecycle):
    profile = ImportPersistProfile()
    started = perf_counter()
    preflight = ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode="light"
    )
    preflight_s = perf_counter() - started
    plan = ImportPlan.all_ready(ParseRequest(str(source), str(database), "light", False), preflight)
    worker = parse_reports_thread.ParseReportsThread(plan)
    scope = (
        patch.object(parse_reports_thread, "lazy_sqlite_connection_scope", lambda _db: nullcontext(None))
        if lifecycle == "per_report" else nullcontext()
    )
    with scope, profile.activate():
        started = perf_counter()
        worker.run()
        import_s = perf_counter() - started
    result = worker.last_parse_result
    expected = len(preflight.files)
    if result is None or (result.imported_files, result.failed_files) != (expected, 0):
        raise RuntimeError("synthetic_import_failed")
    return {
        "preflight_s": preflight_s, "import_s": import_s,
        "imported": result.imported_files, "profile": profile.receipt(),
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
    }, database_snapshot(database)


def _qualify_profile(run, count, lifecycle=None):
    calls = run["profile"]["calls"]
    for stage in ("schema_probe", "hash", "row_building", "executemany", "commit", "checkpoint_close"):
        if calls.get(stage, 0) <= 0:
            raise RuntimeError(f"missing_persist_stage:{stage}")
    if calls["hash"] != count:
        raise RuntimeError("in_transaction_hash_count_changed")
    if lifecycle == "batch_connection" and calls.get("checkpoint") != calls["commit"]:
        raise RuntimeError("per_commit_checkpoint_missing")
    settings = run["profile"]["sqlite_settings"]
    if not settings or any((s["journal_mode"], s["synchronous"], s["wal_autocheckpoint"]) != (
        "wal", 1, 1000,
    ) for s in settings):
        raise RuntimeError("sqlite_settings_changed")


def compare(source, root, count, iterations):
    runs = {"per_report": [], "batch_connection": []}
    expected = None
    connect = sqlite3.connect
    with patch.object(sqlite3, "connect", lambda *a, **kw: _fixed_clock_connection(connect, *a, **kw)), patch.object(
        report_repository, "utc_timestamp", lambda: CLOCK
    ), patch.dict(os.environ, {"METROLIZA_IMPORT_PREPARE_WORKERS": "0"}):
        for iteration in range(iterations):
            order = list(runs) if iteration % 2 == 0 else list(reversed(runs))
            for lifecycle in order:
                run, rows = _run(source, root / f"{lifecycle}-{iteration}.sqlite3", lifecycle)
                _qualify_profile(run, count, lifecycle)
                if expected is None:
                    expected = rows
                if rows != expected:
                    raise RuntimeError("persisted_rows_differ")
                runs[lifecycle].append(run)
    return {
        "schema_version": 1, "runtime": "build-venv/source", "platform": platform.system(),
        "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
        "source_sha": os.environ.get("GITHUB_SHA", "not visible"), "cpu_count": os.cpu_count(),
        "reports": count, "iterations": iterations, "all_rows_equal": True,
        "row_counts": {table: len(rows) for table, rows in expected["tables"].items()},
        "audit_clock": CLOCK,
        "antivirus": "not measured; no exclusions changed; Defender causation requires a controlled Windows comparison",
        "runs": runs,
        "medians": {
            mode: {
                "import_s": median(run["import_s"] for run in samples),
                "stages_s": {
                    stage: median(run["profile"]["seconds"].get(stage, 0) for run in samples)
                    for stage in samples[0]["profile"]["seconds"]
                },
            }
            for mode, samples in runs.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reports", type=int, default=200, choices=range(1, 201))
    args = parser.parse_args()
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/pdf/cmm_smoke_fixture.pdf"
    fixture_bytes = fixture.read_bytes()
    with tempfile.TemporaryDirectory(prefix="metroliza-persist-") as directory:
        root = Path(directory)
        source = root / "synthetic"
        source.mkdir()
        for index in range(args.reports):
            (source / f"synthetic-{index:04}.pdf").write_bytes(
                fixture_bytes + f"\n% synthetic-report-{index}\n".encode("ascii")
            )
        receipt = compare(source, root, args.reports, 3)
    receipt["fixture_sha256"] = hashlib.sha256(fixture_bytes).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt["medians"], indent=2))
    assert app is not None  # Retain QApplication through all worker cleanup.


if __name__ == "__main__":
    main()
