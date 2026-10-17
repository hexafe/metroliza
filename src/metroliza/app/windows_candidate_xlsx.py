"""Real W07 workbook checks with a separately pinned source-only wrapper.

The operation creates only synthetic source bytes and a new SQLite database
below the caller-owned scratch directory, then uses ``ExportDataThread`` and
its Excel backend.  It has no package or Git-checkout requirement.  The
source wrapper below adds those requirements for engineering evidence only.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import subprocess
from threading import Event
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from defusedxml import ElementTree as SafeET


# These are copied from the retained xlsx-desktop-check oracle, not from the
# workbook generated during this call.  The retained artifact was generated at
# PR #1049 head 7d4d6c9767827d09eaa4ded10be4d9cc580d1a43; this proof targets the
# later fixed source checkout named by SOURCE_HEAD.
SOURCE_HEAD = "b28ac092b7a7450f2b9420959fe0e88d7b40be35"
RETAINED_ORACLE_SHA256 = "ec39dfd2b969b283d7f6086aad612661d8bdc9e1bdeb328f8dd3e2d0d8ba6ca4"
SHEET_NAME = "REF-1"
LABELS = ("=Data!A1 - X", 'Żółć "quotes" - X')
# The production layout appends `` - X`` to the persisted imported header.
# Keep the authored inputs separate from the oracle's expected chart labels.
IMPORTED_HEADERS = ("=Data!A1", 'Żółć "quotes"')
VALUES = (10.1, 10.2)
USL = 10.5
LSL = 9.5
DEADLINE_S = 60.0

NS_MAIN = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_CHART = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
NS_PACKAGE = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class XlsxScenarioFailure(RuntimeError):
    """A bounded source-export operation did not produce the oracle shape."""


_SAFE_FAILURE_CODES = {
    "cancel_outcome",
    "cancel_preservation",
    "cancel_staging_cleanup",
    "active_cancel_operation_not_started",
    "active_cancel_outcome",
    "active_cancel_preservation",
    "active_cancel_request_not_observed",
    "active_cancel_staging_cleanup",
    "active_cancel_thread_deadline",
    "active_cancel_callback_thread",
    "active_cancel_measurement_barrier_missing",
    "chart_count",
    "chart_cache_changed_in_control",
    "chart_value_ranges",
    "complete_outcome",
    "export_deadline",
    "failed_export_preservation",
    "header_imported_as_formula",
    "invalid_zip",
    "limit_series_names",
    "literal_header_value",
    "local_cell_control_accepted",
    "local_cell_control_wrong_rejection",
    "local_chart_block_cells",
    "measurement_header_cell_missing",
    "operation_deadline",
    "oversized_label_accepted",
    "primary_cache_order",
    "primary_cell_order",
    "qt_application_unavailable",
    "rejected_label_message",
    "rejection_preservation",
    "rejection_staging_cleanup",
    "root_missing",
    "scratch_root_invalid",
    "scratch_create_failed",
    "series_cache",
    "series_reference",
    "source_checkout_unavailable",
    "source_checkout_dirty",
    "source_exporter_blob_mismatch",
    "source_exporter_blob_unavailable",
    "source_head_mismatch",
    "source_head_unavailable",
    "title_cache",
    "title_reference",
    "usl_cache",
    "lsl_cache",
    "worksheet_missing",
}
_SAFE_FAILURE_STAGES = frozenset({
    "scratch", "application", "complete_export", "workbook_verify",
    "cell_control", "preservation", "active_cancellation", "deadline",
})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    staging = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    with staging.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    staging.replace(path)


def _safe_failure_code(exc: Exception) -> str:
    """Keep receipts stable and free of runtime paths or exception text."""
    if isinstance(exc, XlsxScenarioFailure) and str(exc) in _SAFE_FAILURE_CODES:
        return str(exc)
    return "operation_failed"


def _source_provenance() -> dict[str, str]:
    """Pin this source-only run to the loaded exporter and its Git checkout."""
    import metroliza.exporting.export_data_thread as export_module

    module_path = Path(export_module.__file__).resolve()
    checkout = next(
        (candidate for candidate in module_path.parents if (candidate / ".git").exists()),
        None,
    )
    if checkout is None:
        raise XlsxScenarioFailure("source_checkout_unavailable")
    completed = subprocess.run(
        ("git", "-C", str(checkout), "rev-parse", "HEAD"),
        check=False, capture_output=True, encoding="utf-8", timeout=5,
    )
    if completed.returncode != 0:
        raise XlsxScenarioFailure("source_head_unavailable")
    observed_head = completed.stdout.strip()
    _require_equal(observed_head, SOURCE_HEAD, "source_head_mismatch")
    clean = subprocess.run(
        ("git", "-C", str(checkout), "status", "--porcelain"),
        check=False, capture_output=True, encoding="utf-8", timeout=5,
    )
    if clean.returncode != 0 or clean.stdout:
        raise XlsxScenarioFailure("source_checkout_dirty")
    relative_module = module_path.relative_to(checkout).as_posix()
    blob = subprocess.run(
        ("git", "-C", str(checkout), "show", f"HEAD:{relative_module}"),
        check=False, capture_output=True, timeout=5,
    )
    if blob.returncode != 0:
        raise XlsxScenarioFailure("source_exporter_blob_unavailable")
    if hashlib.sha256(blob.stdout).hexdigest() != _sha256(module_path):
        raise XlsxScenarioFailure("source_exporter_blob_mismatch")
    blob_id = subprocess.run(
        ("git", "-C", str(checkout), "rev-parse", f"HEAD:{relative_module}"),
        check=False, capture_output=True, encoding="utf-8", timeout=5,
    )
    if blob_id.returncode != 0:
        raise XlsxScenarioFailure("source_exporter_blob_unavailable")
    return {
        "source_head": observed_head,
        "export_data_thread_sha256": _sha256(module_path),
        "export_data_thread_git_blob": blob_id.stdout.strip(),
    }


def _xml(workbook_zip: zipfile.ZipFile, path: str) -> ET.Element:
    return SafeET.fromstring(workbook_zip.read(path), forbid_dtd=True, forbid_entities=True)


def _package_path(base_path: str, target: str) -> str:
    return posixpath.normpath(str(PurePosixPath(PurePosixPath(base_path).parent, target)))


def _sheet_path(workbook_zip: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = _xml(workbook_zip, "xl/workbook.xml")
    relationships = _xml(workbook_zip, "xl/_rels/workbook.xml.rels")
    targets = {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in relationships.findall("r:Relationship", NS_PACKAGE)
    }
    for sheet in workbook.findall("x:sheets/x:sheet", NS_MAIN):
        if sheet.attrib.get("name") == sheet_name:
            return "xl/" + targets[sheet.attrib[f"{{{NS_REL}}}id"]]
    raise XlsxScenarioFailure("worksheet_missing")


def _chart_paths(workbook_zip: zipfile.ZipFile, sheet_path: str) -> list[str]:
    worksheet_rels = _xml(
        workbook_zip, f"xl/worksheets/_rels/{Path(sheet_path).name}.rels"
    )
    drawing_target = next(
        relation.attrib["Target"]
        for relation in worksheet_rels.findall("r:Relationship", NS_PACKAGE)
        if relation.attrib["Type"].endswith("/drawing")
    )
    drawing_path = _package_path(sheet_path, drawing_target)
    drawing_rels = _xml(
        workbook_zip, _package_path(drawing_path, f"_rels/{Path(drawing_path).name}.rels")
    )
    return [
        _package_path(drawing_path, relation.attrib["Target"])
        for relation in drawing_rels.findall("r:Relationship", NS_PACKAGE)
        if relation.attrib["Type"].endswith("/chart")
    ]


def _shared_strings(workbook_zip: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook_zip.namelist():
        return []
    return [
        "".join(node.itertext())
        for node in _xml(workbook_zip, "xl/sharedStrings.xml").findall("x:si", NS_MAIN)
    ]


def _cell_value(worksheet: ET.Element, cell_reference: str, shared_strings: list[str]) -> str:
    cell = worksheet.find(f".//x:c[@r='{cell_reference}']", NS_MAIN)
    if cell is None:
        raise XlsxScenarioFailure("measurement_header_cell_missing")
    value = cell.findtext("x:v", namespaces=NS_MAIN)
    if cell.attrib.get("t") == "s":
        return shared_strings[int(value)]
    if cell.attrib.get("t") == "inlineStr":
        inline = cell.find("x:is", NS_MAIN)
        return "" if inline is None else "".join(inline.itertext())
    return "" if value is None else value


def _require_equal(actual: Any, expected: Any, check: str) -> None:
    if actual != expected:
        raise XlsxScenarioFailure(check)


def _persist_measurement(repository: Any, source_dir: Path, *, report_id: int, sample: int, headers: tuple[str, ...], measurement: float) -> None:
    source_path = source_dir / f"report-{report_id}.pdf"
    source_path.write_bytes(f"synthetic-xlsx-report-{report_id}".encode("ascii"))
    repository.persist_parsed_report(
        source_path=source_path,
        parser_id="cmm",
        parser_version="1.0",
        template_family="cmm_pdf_header_box",
        template_variant="cmm_pdf_header_box_serial_variant",
        parse_status="parsed_with_warnings",
        metadata={
            "reference": SHEET_NAME,
            "reference_raw": SHEET_NAME,
            "report_date": f"2024-01-{report_id:02d}",
            "part_name": "Synthetic part",
            "revision": "A",
            "sample_number": str(sample),
            "sample_number_kind": "explicit_sample_number",
            "stats_count_raw": str(sample),
            "stats_count_int": sample,
            "operator_name": "Synthetic",
            "comment": None,
        },
        measurements=[{
            "page_number": 1,
            "row_order": row_order,
            "header": header,
            "section_name": header,
            "feature_label": header,
            "characteristic_name": "LOC",
            "characteristic_family": "LOC",
            "description": "Synthetic feature",
            "ax": "X",
            "nominal": 10.0,
            "tol_plus": 0.5,
            "tol_minus": -0.5,
            "bonus": 0.0,
            "meas": measurement,
            "dev": measurement - 10.0,
            "outtol": 0,
            "is_nok": False,
            "status_code": "ok",
        } for row_order, header in enumerate(headers, start=1)],
        candidates=[],
        warnings=[],
        metadata_version="report_metadata_v1",
        metadata_profile_id="cmm_pdf_header_box",
        metadata_profile_version="1",
        page_count=1,
        measurement_count=len(headers),
        has_nok=False,
        nok_count=0,
        metadata_confidence=0.9,
        identity_hash=f"xlsx-synthetic-{report_id}",
    )


def _make_thread(database: Path, workbook: Path, headers: tuple[str, ...], *, group_headers=False) -> Any:
    """Seed a new synthetic database and return the actual exporter thread."""
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.reports.report_repository import ReportRepository
    from metroliza.reports.report_schema import ensure_report_schema

    ensure_report_schema(str(database))
    repository = ReportRepository(str(database))
    sources = database.parent / f"{database.stem}-sources"
    sources.mkdir()
    report_id = 0
    # The cancellation scenario still exports every header, but two synthetic
    # reports can carry its two samples without 192 independent SQLite commits.
    header_groups = (headers,) if group_headers else ((header,) for header in headers)
    for group in header_groups:
        for sample, value in enumerate(VALUES, start=1):
            report_id += 1
            _persist_measurement(
                repository, sources, report_id=report_id, sample=sample,
                headers=group, measurement=value,
            )
    request = ExportRequest(
        paths=AppPaths(db_file=str(database), excel_file=str(workbook)),
        options=ExportOptions(generate_summary_sheet=False),
    )
    return ExportDataThread(request)


def _verify_chart(chart: ET.Element, worksheet: ET.Element, *, header_cell: str, label: str, data_column: str, summary_column: str, strings: list[str]) -> None:
    expected_ref = f"'{SHEET_NAME}'!${data_column}$21"
    _require_equal(_cell_value(worksheet, header_cell, strings), label, "literal_header_value")
    header_node = worksheet.find(f".//x:c[@r='{header_cell}']", NS_MAIN)
    if header_node is None or header_node.find("x:f", NS_MAIN) is not None:
        raise XlsxScenarioFailure("header_imported_as_formula")
    _require_equal(
        [node.text for node in chart.findall(".//c:title//c:strRef/c:f", NS_CHART)],
        [expected_ref], "title_reference",
    )
    _require_equal(
        [node.text for node in chart.findall(".//c:ser/c:tx/c:strRef/c:f", NS_CHART)],
        [expected_ref], "series_reference",
    )
    _require_equal(
        [node.text for node in chart.findall(".//c:title//c:strCache/c:pt/c:v", NS_CHART)],
        [label], "title_cache",
    )
    _require_equal(
        [node.text for node in chart.findall(".//c:ser/c:tx/c:strRef/c:strCache/c:pt/c:v", NS_CHART)],
        [label], "series_cache",
    )
    expected_ranges = [
        f"'{SHEET_NAME}'!${summary_column}22:{summary_column}23",
        f"'{SHEET_NAME}'!${data_column}22:{data_column}23",
        f"'{SHEET_NAME}'!${summary_column}22:{summary_column}23",
        f"'{SHEET_NAME}'!${chr(ord(data_column) + 1)}22:{chr(ord(data_column) + 1)}23",
        f"'{SHEET_NAME}'!${summary_column}22:{summary_column}23",
        f"'{SHEET_NAME}'!${chr(ord(data_column) + 2)}22:{chr(ord(data_column) + 2)}23",
    ]
    _require_equal(
        [node.text for node in chart.findall(".//c:numRef/c:f", NS_CHART)],
        expected_ranges, "chart_value_ranges",
    )
    series = chart.findall(".//c:ser", NS_CHART)
    _require_equal(
        [item.findtext("c:tx/c:v", namespaces=NS_CHART) for item in series[1:]],
        ["USL", "LSL"], "limit_series_names",
    )
    _require_equal(
        [node.text for node in series[0].findall("c:val/c:numRef/c:numCache/c:pt/c:v", NS_CHART)],
        ["10.1", "10.2"], "primary_cache_order",
    )
    _require_equal(
        [_cell_value(worksheet, f"{data_column}{row}", strings) for row in (22, 23)],
        ["10.1", "10.2"], "primary_cell_order",
    )
    expected_cells = {
        f"{summary_column}21": "Sample #",
        f"{data_column}21": label,
        f"{chr(ord(data_column) + 1)}21": "USL",
        f"{chr(ord(data_column) + 2)}21": "LSL",
        f"{summary_column}22": "1",
        f"{data_column}22": "10.1",
        f"{chr(ord(data_column) + 1)}22": "10.5",
        f"{chr(ord(data_column) + 2)}22": "9.5",
        f"{summary_column}23": "2",
        f"{data_column}23": "10.2",
        f"{chr(ord(data_column) + 1)}23": "10.5",
        f"{chr(ord(data_column) + 2)}23": "9.5",
    }
    _require_equal(
        {cell: _cell_value(worksheet, cell, strings) for cell in expected_cells},
        expected_cells, "local_chart_block_cells",
    )
    for item, expected, check in zip(series[1:], ("10.5", "9.5"), ("usl_cache", "lsl_cache"), strict=True):
        _require_equal(
            [node.text for node in item.findall("c:val/c:numRef/c:numCache/c:pt/c:v", NS_CHART)],
            [expected, expected], check,
        )


def _verify_workbook(workbook: Path) -> dict[str, Any]:
    with zipfile.ZipFile(workbook) as archive:
        if archive.testzip() is not None:
            raise XlsxScenarioFailure("invalid_zip")
        sheet_path = _sheet_path(archive, SHEET_NAME)
        worksheet = _xml(archive, sheet_path)
        strings = _shared_strings(archive)
        charts = _chart_paths(archive, sheet_path)
        _require_equal(len(charts), 2, "chart_count")
        chart_details = (("C21", LABELS[0], "C", "B"), ("H21", LABELS[1], "H", "G"))
        for chart_path, detail in zip(charts, chart_details, strict=True):
            _verify_chart(_xml(archive, chart_path), worksheet, header_cell=detail[0], label=detail[1], data_column=detail[2], summary_column=detail[3], strings=strings)
    return {
        "workbook": workbook.name,
        "sha256": _sha256(workbook),
        "bytes": workbook.stat().st_size,
        "charts": 2,
    }


def _verify_local_cell_negative_control(workbook: Path) -> None:
    """Prove that chart caches cannot hide a changed local measurement cell."""
    corrupted = workbook.with_name("corrupt-local-cell.xlsx")
    with zipfile.ZipFile(workbook) as original:
        sheet_path = _sheet_path(original, SHEET_NAME)
        chart_path = _chart_paths(original, sheet_path)[0]
        chart_bytes = original.read(chart_path)
        with zipfile.ZipFile(corrupted, "w") as rewritten:
            for item in original.infolist():
                payload = original.read(item.filename)
                if item.filename == sheet_path:
                    worksheet = SafeET.fromstring(payload, forbid_dtd=True, forbid_entities=True)
                    cell = worksheet.find(".//x:c[@r='C22']", NS_MAIN)
                    if cell is None:
                        raise XlsxScenarioFailure("measurement_header_cell_missing")
                    cell.find("x:v", NS_MAIN).text = "999"
                    payload = ET.tostring(worksheet, encoding="utf-8", xml_declaration=True)
                rewritten.writestr(item, payload)
    with zipfile.ZipFile(corrupted) as changed:
        _require_equal(changed.read(chart_path), chart_bytes, "chart_cache_changed_in_control")
    try:
        _verify_workbook(corrupted)
    except XlsxScenarioFailure as exc:
        _require_equal(str(exc), "primary_cell_order", "local_cell_control_wrong_rejection")
    else:
        raise XlsxScenarioFailure("local_cell_control_accepted")


def _directory_snapshot(path: Path) -> tuple[str, ...]:
    return tuple(sorted(entry.name for entry in path.iterdir()))


def _verify_preservation(scratch: Path, workbook: Path) -> dict[str, str]:
    """Exercise real backend cancellation and validation without replacing output."""
    from metroliza.exporting.execution import ExportOutcomeKind

    completed = workbook.read_bytes()
    cancelled = _make_thread(scratch / "cancelled.sqlite", workbook, ("Cancelled",))
    cancelled.export_canceled = True
    before_cancel = _directory_snapshot(scratch)
    cancelled_outcome = cancelled.get_export_backend().run(cancelled)
    _require_equal(cancelled_outcome.kind, ExportOutcomeKind.CANCELED, "cancel_outcome")
    _require_equal(workbook.read_bytes(), completed, "cancel_preservation")
    _require_equal(_directory_snapshot(scratch), before_cancel, "cancel_staging_cleanup")

    rejected = _make_thread(scratch / "rejected.sqlite", workbook, ("x" * 32768,))
    before_rejection = _directory_snapshot(scratch)
    try:
        rejected.get_export_backend().run(rejected)
    except ValueError as exc:
        _require_equal(
            str(exc), "Measurement chart label must contain 1 to 32767 characters",
            "rejected_label_message",
        )
    else:
        raise XlsxScenarioFailure("oversized_label_accepted")
    _require_equal(workbook.read_bytes(), completed, "rejection_preservation")
    _require_equal(_directory_snapshot(scratch), before_rejection, "rejection_staging_cleanup")
    return {
        "pre_cancelled_export_preserves_workbook": "passed",
        "oversized_label_rejection_preserves_workbook": "passed",
    }


def _require_active_cancellation_result(
    active: Any,
    progress_values: list[int],
    cancellation_observation: dict[str, int | bool],
    measurement_progress_paused: Event,
) -> None:
    from metroliza.exporting.export_outcomes import ExportRunStatus

    if not progress_values or progress_values[0] != 0:
        raise XlsxScenarioFailure("active_cancel_operation_not_started")
    if not cancellation_observation.get("running_before_stop"):
        raise XlsxScenarioFailure("active_cancel_request_not_observed")
    if not cancellation_observation.get("application_thread"):
        raise XlsxScenarioFailure("active_cancel_callback_thread")
    if not measurement_progress_paused.is_set():
        raise XlsxScenarioFailure("active_cancel_measurement_barrier_missing")
    if (
        active.export_run_result is None
        or active.export_run_result.status is not ExportRunStatus.CANCELLED
    ):
        raise XlsxScenarioFailure("active_cancel_outcome")


def _verify_active_cancellation(scratch: Path, workbook: Path, application: Any) -> dict[str, str]:
    """Cancel a running real exporter after its measurement stage begins."""
    from PyQt6.QtCore import QThread

    completed = workbook.read_bytes()
    active = _make_thread(
        scratch / "active-cancel.sqlite",
        workbook,
        tuple(f"Active cancellation {index:03d}" for index in range(96)),
        group_headers=True,
    )
    progress_values: list[int] = []
    cancellation_observation: dict[str, int | bool] = {}
    release_progress = Event()
    measurement_progress_paused = Event()
    original_emit_progress = getattr(active, "_emit_progress", None)
    if callable(original_emit_progress):
        def pause_after_real_progress(value: int) -> None:
            previous = getattr(active, "_last_emitted_progress", -1)
            original_emit_progress(value)
            if previous <= 30 < getattr(active, "_last_emitted_progress", -1):
                measurement_progress_paused.set()
                release_progress.wait(DEADLINE_S)

        active._emit_progress = pause_after_real_progress

    def request_cancellation(value: int) -> None:
        progress = int(value)
        progress_values.append(progress)
        # Stage entry is exactly 30; a value above it follows a completed
        # measurement header unit in the real exporter.
        if progress > 30 and not cancellation_observation:
            cancellation_observation["progress"] = progress
            cancellation_observation["running_before_stop"] = active.isRunning()
            cancellation_observation["application_thread"] = QThread.currentThread() == application.thread()
            try:
                active.stop_exporting()
            finally:
                release_progress.set()

    active.update_progress.connect(request_cancellation)
    before_cancel = _directory_snapshot(scratch)
    try:
        active.start()
        deadline = time.monotonic() + DEADLINE_S
        while active.isRunning() and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.002)
        application.processEvents()
        if active.isRunning():
            raise XlsxScenarioFailure("active_cancel_thread_deadline")
    finally:
        release_progress.set()
        if active.isRunning():
            active.stop_exporting()
        # Never unwind or destroy a running QThread. The existing external Job
        # watchdog bounds cleanup if cooperative cancellation cannot complete.
        active.wait()
        active.update_progress.disconnect(request_cancellation)
    _require_active_cancellation_result(
        active, progress_values, cancellation_observation, measurement_progress_paused,
    )
    _require_equal(workbook.read_bytes(), completed, "active_cancel_preservation")
    _require_equal(_directory_snapshot(scratch), before_cancel, "active_cancel_staging_cleanup")
    return {"active_export_cancellation_preserves_workbook": "passed"}


def run_export_checks(scratch_root: str | Path) -> dict[str, Any]:
    """Run W07 export facets without a Git or packaged-runtime assumption.

    The caller supplies an existing, owned directory.  A unique child holds
    the synthetic database, source bytes, and generated workbook.  The 60s
    value is a post-operation acceptance limit; a caller's external Job or
    watchdog is the actual bound for a hung child process.
    """
    root = Path(scratch_root)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        return {
            "schema_version": 1,
            "status": "failed",
            "failure_code": "scratch_root_invalid",
            "relative_artifact_dir": None,
            "facets": {},
        }
    scratch = root / f"xlsx-w07-{uuid.uuid4().hex}"
    try:
        scratch.mkdir()
    except OSError:
        return {
            "schema_version": 1,
            "status": "failed",
            "failure_code": "scratch_create_failed",
            "relative_artifact_dir": None,
            "facets": {},
        }
    started = time.monotonic()
    result: dict[str, Any] = {
        "schema_version": 1,
        "retained_oracle_sha256": RETAINED_ORACLE_SHA256,
        "observed_deadline_s": DEADLINE_S,
        "external_job_bound_required": True,
        "relative_artifact_dir": scratch.name,
        "facets": {
            "literal_chart_titles_series_caches_references": "failed",
            "value_limit_order": "failed",
            "local_chart_cells_and_negative_control": "failed",
            "pre_cancelled_export_preserves_workbook": "failed",
            "active_export_cancellation_preserves_workbook": "failed",
            "oversized_label_rejection_preserves_workbook": "failed",
        },
        "status": "failed",
    }
    stage = "application"
    try:
        # A QCoreApplication is sufficient for the actual QThread signal
        # surface; it does not start a GUI or replace any production worker.
        from PyQt6.QtCore import QCoreApplication
        application = QCoreApplication.instance() or QCoreApplication([])
        if application is None:
            raise XlsxScenarioFailure("qt_application_unavailable")
        workbook = scratch / "literal-measurement-labels.xlsx"
        stage = "complete_export"
        thread = _make_thread(scratch / "complete.sqlite", workbook, IMPORTED_HEADERS)
        outcome = thread.get_export_backend().run(thread)
        from metroliza.exporting.execution import ExportOutcomeKind
        _require_equal(outcome.kind, ExportOutcomeKind.COMPLETED, "complete_outcome")
        stage = "workbook_verify"
        workbook_details = _verify_workbook(workbook)
        result["facets"]["literal_chart_titles_series_caches_references"] = "passed"
        result["facets"]["value_limit_order"] = "passed"
        stage = "cell_control"
        _verify_local_cell_negative_control(workbook)
        result["facets"]["local_chart_cells_and_negative_control"] = "passed"
        stage = "preservation"
        result["facets"].update(_verify_preservation(scratch, workbook))
        stage = "active_cancellation"
        result["facets"].update(_verify_active_cancellation(scratch, workbook, application))
        stage = "deadline"
        if time.monotonic() - started > DEADLINE_S:
            raise XlsxScenarioFailure("operation_deadline")
        result["artifacts"] = {"workbook": workbook_details}
        result["status"] = "passed"
    except Exception as exc:
        result["failure_code"] = _safe_failure_code(exc)
        result["failure_stage"] = stage
    result["elapsed_s"] = round(time.monotonic() - started, 6)
    return result


def run_source_export_proof(scratch_root: str | Path) -> dict[str, Any]:
    """Preflight the accepted checkout, then run its source-only proof."""
    root = Path(scratch_root)
    wrapper_fields = {
        "evidence_kind": "source_engineering_only",
        "packaged": False,
        "expected_source_head": SOURCE_HEAD,
        "module_sha256": _sha256(Path(__file__).resolve()),
    }
    try:
        source = _source_provenance()
    except Exception as exc:
        return {
            "schema_version": 1,
            "status": "failed",
            "failure_code": _safe_failure_code(exc),
            "relative_artifact_dir": None,
            "facets": {},
            **wrapper_fields,
        }
    result = run_export_checks(root)
    result.update(wrapper_fields)
    result["source"] = source
    relative = result.get("relative_artifact_dir")
    if relative:
        _atomic_json(root / relative / "xlsx-w07-source-receipt.json", result)
    return result
