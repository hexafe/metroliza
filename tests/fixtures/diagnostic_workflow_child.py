"""Real selected-import and workbook services on a public synthetic PDF only."""

import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from metroliza.shared.diagnostic_transport import attach_child_recorder
from metroliza.shared.logging_utils import ensure_application_logging


def main():
    recorder = attach_child_recorder()
    ensure_application_logging()
    from metroliza.app.bootstrap import run_application

    if run_application() != 0:
        return 10
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.parsing.parse_reports_thread import ParseReportsThread
    from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
    from metroliza.shared.parse_contracts import ParseRequest

    scratch = Path(sys.argv[1])
    source = scratch / "reports"
    source.mkdir()
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"
    (source / "SYNTHETIC_PRIVATE_FILENAME.pdf").write_bytes(fixture.read_bytes())
    database, workbook = scratch / "scratch.sqlite", scratch / "scratch.xlsx"
    request = ParseRequest(source_directory=str(source), db_file=str(database), metadata_parsing_mode="light")
    preflight = ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode="light",
    )
    worker = ParseReportsThread(ImportPlan.all_ready(request, preflight))
    if sys.argv[2] == "handled_failure":
        (source / "SYNTHETIC_PRIVATE_FILENAME.pdf").unlink()
    worker.run()
    if sys.argv[2] == "handled_failure":
        if worker.last_parse_result.imported_files != 0:
            return 14
        # Keep the real app alive until the external test has loaded its incident.
        (scratch / "operation_returned").touch()
        deadline = time.monotonic() + 8
        while not (scratch / "finish").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        if recorder is not None:
            recorder.close()
        return 0
    if worker.last_parse_result.imported_files != 1:
        return 11
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            if connection.execute("SELECT COUNT(*) FROM report_measurements").fetchone()[0] < 1:
                return 12
    export = ExportDataThread(ExportRequest(
        paths=AppPaths(db_file=str(database), excel_file=str(workbook)),
        options=ExportOptions(generate_summary_sheet=False),
    ))
    export.run()
    if not workbook.is_file() or export.export_run_result is None:
        return 13
    time.sleep(0.1)
    if sys.argv[2] == "hard_exit":
        os._exit(9)
    if recorder is not None:
        recorder.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
