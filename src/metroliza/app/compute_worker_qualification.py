"""Opt-in synthetic workloads inside the supervised application (#1134)."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import time

GATE = 'METROLIZA_COMPUTE_QUALIFICATION_ROOT'
REPORTS = 200
GROUPS = 40


def write_reports(source: Path) -> None:
    """Generate deterministic, distinct synthetic CMM documents; no external input."""
    from metroliza.parsing.pdf_backend import require_pdf_backend

    backend = require_pdf_backend()
    source.mkdir()
    for index in range(REPORTS):
        lines = ['SYNTHETIC CMM MEASUREMENT REPORT', 'CMM REPORT',
                 'REFERENCE: ABC00100', 'DATE: 2024-02-01', f'SAMPLE: {index + 1:04d}']
        for feature in range(10):
            lines += [f'#FEATURE_{feature:02d}', 'DIM']
            for axis in 'XYZD':
                measured = 10 + ((index * 17 + feature * 3) % 31 - 15) / 200
                lines.append(f'{axis} 10.0000 0.2000 -0.2000 {measured:.4f} {measured - 10:.4f} 0.0000')
        lines.append('#END')
        document = backend.open()
        try:
            for start in range(0, len(lines), 35):
                document.new_page().insert_text((40, 40), '\n'.join(lines[start:start + 35]), fontsize=8)
            document.save(str(source / f'synthetic_{index:03d}.pdf'))
        finally:
            document.close()


def _timed_stage(timings, stage, function):
    def timed(*args, **kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            timings[stage] += time.perf_counter() - started
    return timed


@contextmanager
def _observe_import(timings, hydrated):
    """Measure parent-stage wall time only inside the synthetic smoke workflow."""
    from metroliza.parsing.cmm_report_parser import CMMReportParser
    from metroliza.parsing.import_prepare_pool import ImportPreparePool
    from metroliza.parsing import parse_reports_thread as pipeline

    original_apply = CMMReportParser.apply_prepared_state
    original_parse = pipeline.parse_new_reports

    def apply(parser, state):
        result = original_apply(parser, state)
        hydrated.append(True)
        return result

    def parse(*args, **kwargs):
        kwargs['parser_factory'] = _timed_stage(timings, 'prepare', kwargs['parser_factory'])
        kwargs['persist_report'] = _timed_stage(timings, 'persist', kwargs['persist_report'])
        return original_parse(*args, **kwargs)

    replacements = (
        (CMMReportParser, 'apply_prepared_state', apply),
        (CMMReportParser, 'prepare_for_two_stage_pipeline',
         _timed_stage(timings, 'prepare', CMMReportParser.prepare_for_two_stage_pipeline)),
        (ImportPreparePool, 'apply_to', _timed_stage(timings, 'prepare', ImportPreparePool.apply_to)),
        (pipeline, 'parse_new_reports', parse),
    )
    originals = [(owner, name, getattr(owner, name)) for owner, name, _ in replacements]
    try:
        for owner, name, replacement in replacements:
            setattr(owner, name, replacement)
        yield
    finally:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)


def run_import(source: Path, database: Path) -> dict:
    from metroliza.parsing.parse_reports_thread import ParseReportsThread
    from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
    from metroliza.shared.parse_contracts import ParseRequest

    request = ParseRequest(str(source), str(database), 'light')
    total_started = time.perf_counter()
    started = time.perf_counter()
    preflight = ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode='light')
    timings = {'preflight': time.perf_counter() - started, 'prepare': 0.0, 'persist': 0.0}
    thread = ParseReportsThread(ImportPlan.all_ready(request, preflight))
    hydrated = []
    started = time.perf_counter()
    with _observe_import(timings, hydrated):
        thread.run()
    seconds = time.perf_counter() - started
    timings['other_pipeline'] = max(0.0, seconds - timings['prepare'] - timings['persist'])
    if thread.last_parse_result.imported_files != REPORTS:
        raise ValueError('compute_import_incomplete')
    return {'seconds': seconds, 'total_seconds': time.perf_counter() - total_started,
            'stage_seconds': timings, 'imported': REPORTS, 'hydrated': len(hydrated),
            'timing_scope': 'parent_wall_time_prepare_includes_resolution_and_worker_wait;'
                            'other_pipeline_includes_setup_approval_cleanup;seconds_excludes_preflight'}


def run_export(database: Path, workbook: Path) -> dict:
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.exporting.export_preset_utils import build_export_options_for_preset

    options = build_export_options_for_preset('full_report')
    options['preset'] = 'full_report'
    options['allow_non_essential_chart_skipping'] = False
    thread = ExportDataThread(ExportRequest(
        paths=AppPaths(db_file=str(database), excel_file=str(workbook)), options=ExportOptions(**options)))
    started = time.perf_counter()
    thread.run()
    if not workbook.is_file() or thread._summary_sheet_failed:
        raise ValueError('compute_export_incomplete')
    return {'seconds': time.perf_counter() - started,
            'pool': thread.completion_metadata.get('summary_render_pool', {})}


def run_qualification() -> int:
    if os.environ.get('METROLIZA_STARTUP_SMOKE') != '1' or not os.environ.get(GATE):
        raise ValueError('compute_qualification_gate_required')
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    try:
        return _run_with_application(app)
    finally:
        from metroliza.app.qt_teardown import shutdown_qt

        shutdown_qt(app)


def _run_with_application(app) -> int:
    from metroliza.shared.diagnostic_runtime_audit import wait_for_host_ready

    root = Path(os.environ[GATE])
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError('compute_qualification_root_invalid')
    (root / 'compute-ready').touch(exist_ok=False)
    wait_for_host_ready(seconds=30)
    database, workbook = root / 'result.sqlite3', root / 'result.xlsx'
    if database.exists() or workbook.exists():
        raise ValueError('compute_qualification_outputs_exist')
    imported = run_import(root.parent / 'reports', database)
    exported = run_export(database, workbook)
    # Export is a read-only workflow. The host compares database rows after exit.
    payload = {'schema_version': 1, 'import': imported, 'export': exported, 'packaged': bool(getattr(__import__('sys'), 'frozen', False))}
    with (root / 'compute.json').open('x', encoding='utf-8') as stream:
        json.dump(payload, stream)
    app.processEvents()
    return 0
