"""Six closed main Reports HTML cases for the existing package core gate.

Only the already imported two-report public synthetic fixture is accepted. No
external scenario/options selector is added; the core driver's Job owns timeout
and cleanup, as it does for the existing synchronous workbook export.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from metroliza.reports.db import sqlite_connection_scope, sqlite_readonly_connection_scope

CASES = ("normal_html", "normal_xlsx_html", "long_html", "long_xlsx_html",
         "target_html", "target_xlsx_html")
FACETS = ("main_html_both_presets", "main_html_long_header", "main_html_offline_assets", "main_html_workbook_numeric_parity")
LONG_HEADER = "L" * 240
LONG_TARGET_STEM = "t" * 245


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic_database(database):
    if any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("main_html_database_not_closed")
    with sqlite_readonly_connection_scope(str(database), immutable=True) as connection:
        rows = connection.execute("SELECT header,ax,nominal,tol_plus,tol_minus,meas,dev,outtol FROM report_measurements ORDER BY id").fetchall()
    if rows != [("SMOKE FEATURE", "X", 10.0, 0.1, -0.1, 10.02, 0.02, 0.0)] * 2:
        raise ValueError("main_html_fixture_mismatch")


def _run_case(database, directory, case):
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.exporting.export_dialog_service import build_validated_export_request
    from metroliza.exporting.export_outcomes import ExportArtifactStatus, ExportRunStatus

    workbook = case.endswith("xlsx_html")
    directory.mkdir()
    target_name = "report.xlsx" if workbook else "dashboard.html"
    if case.startswith("target_"):
        target_name = LONG_TARGET_STEM + (".xlsx" if workbook else ".html")
    target = directory / target_name
    request = build_validated_export_request(
        db_file=str(database), excel_file=str(target),
        selected_preset="full_report" if workbook else "html_dashboard_only",
        export_type="Line", export_target="excel_xlsx" if workbook else "html_dashboard",
        sorting_parameter="Date", violin_input="1", summary_scale_input="0",
        hide_ok_results=False, filter_query=None, grouping_df=None, generate_html_dashboard=True,
    )
    export = ExportDataThread(request)
    export.run()
    result = export.export_run_result
    if result is None or result.status is not ExportRunStatus.COMPLETE or result.diagnostics:
        raise ValueError("main_html_export_incomplete")
    required = {"html_dashboard", "workbook"} if workbook else {"html_dashboard"}
    completed = {item.artifact_id for item in result.artifacts if item.status is ExportArtifactStatus.COMPLETE}
    if not required <= completed:
        raise ValueError("main_html_export_incomplete")
    metadata = export.completion_metadata
    dashboard = Path(metadata["html_dashboard_path"])
    assets = Path(metadata["html_dashboard_assets_path"])
    if (dashboard.parent != directory or assets.parent != directory
            or (not workbook and dashboard != target)
            or (workbook and Path(metadata["local_xlsx_path"]) != target)):
        raise ValueError("main_html_output_identity")
    paths = [dashboard, *sorted(assets.iterdir())]
    if workbook:
        paths.append(target)
    if any(not path.is_file() or path.is_symlink() or path.stat().st_size == 0 for path in paths):
        raise ValueError("main_html_output_missing")
    return paths


def run_main_html_checks(child: Path, database: Path, *, source_sha, packaged: bool) -> dict:
    """Export both presets normally, with a long header, and to 250-byte names."""
    _synthetic_database(database)
    before = _sha(database)
    scratch = child / "main-html"
    scratch.mkdir()
    copies = {}
    for name in ("normal", "long"):
        copied = scratch / (name + ".sqlite")
        shutil.copyfile(database, copied)
        copies[name] = copied
    with sqlite_connection_scope(str(copies["long"])) as connection, connection:
        changed = connection.execute("UPDATE report_measurements SET header=? WHERE header=?", (LONG_HEADER, "SMOKE FEATURE")).rowcount
        if changed != 2:
            raise ValueError("main_html_fixture_mismatch")
    receipt = dict(schema_version=2, source_sha=source_sha,
                   runtime_context="packaged" if packaged else "source", cases={})
    files = []
    for case in CASES:
        paths = _run_case(copies["long" if case.startswith("long_") else "normal"], scratch / case, case)
        receipt["cases"][case] = dict(status="complete", files={
            path.relative_to(scratch).as_posix(): _sha(path) for path in paths
        })
        files.extend(paths)
    if _sha(database) != before:
        raise ValueError("main_html_source_changed")
    output = child / "main-html.zip"
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("receipt.json", json.dumps(receipt, sort_keys=True, allow_nan=False))
        for path in files:
            archive.write(path, path.relative_to(scratch).as_posix())
    return dict(path=output.name, sha256=_sha(output))
