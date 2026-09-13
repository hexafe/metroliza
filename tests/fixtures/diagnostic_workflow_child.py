"""Real selected-import and workbook services on a public synthetic PDF only."""

import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from metroliza.shared.diagnostic_transport import attach_child_recorder
from metroliza.shared.logging_utils import ensure_application_logging


def main():
    recorder = attach_child_recorder()
    ensure_application_logging()
    from metroliza.app.bootstrap import run_application

    if run_application() != 0:
        return 10
    from metroliza.parsing.parse_reports_thread import ParseReportsThread
    from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
    from metroliza.shared.parse_contracts import ParseRequest
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.exporting.contracts import AppPaths, ExportRequest, ExportOptions

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
    worker.run()
    if worker.last_parse_result.imported_files != 1:
        return 11
    with sqlite3.connect(database) as connection:
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
