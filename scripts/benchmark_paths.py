#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import importlib.machinery
import os
import sys
import tempfile
import time
import types
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import statistics

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.matplotlib_runtime import configure_headless_matplotlib

configure_headless_matplotlib()


def _install_headless_stubs() -> None:
    custom_logger_stub = types.ModuleType('modules.custom_logger')

    class _NoopLogger:
        def __init__(self, *args, **kwargs):
            return None

    def _noop_handle_exception(*args, **kwargs):
        return None

    custom_logger_stub.CustomLogger = _NoopLogger
    custom_logger_stub.handle_exception = _noop_handle_exception
    custom_logger_stub.LOG_ONLY = object()
    sys.modules.setdefault('modules.custom_logger', custom_logger_stub)

    fitz_stub = types.ModuleType('fitz')
    fitz_stub.__spec__ = importlib.machinery.ModuleSpec('fitz', loader=None)
    fitz_stub.open = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('fitz backend unavailable in benchmark harness'))
    sys.modules.setdefault('fitz', fitz_stub)

    if 'PyQt6.QtWidgets' in sys.modules:
        return

    qtcore_stub = types.ModuleType('PyQt6.QtCore')
    qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')
    qtgui_stub = types.ModuleType('PyQt6.QtGui')

    class _DummyThread:
        def __init__(self, *args, **kwargs):
            pass

    class _DummySignal:
        def emit(self, *args, **kwargs):
            return None

        def connect(self, *args, **kwargs):
            return None

    def _dummy_signal(*args, **kwargs):
        return _DummySignal()

    class _DummyCoreApp:
        @staticmethod
        def processEvents():
            return None

    class _DummyTempFile:
        def open(self):
            return True

    class _DummyApplication:
        @staticmethod
        def instance():
            return None

    qtcore_stub.QCoreApplication = _DummyCoreApp
    qtcore_stub.QThread = _DummyThread
    qtcore_stub.pyqtSignal = _dummy_signal
    qtcore_stub.pyqtSlot = lambda *a, **k: (lambda func: func)
    qtcore_stub.Qt = object()
    qtcore_stub.QTemporaryFile = _DummyTempFile
    qtcore_stub.QSize = object
    qtcore_stub.QByteArray = object
    qtcore_stub.QBuffer = object
    qtcore_stub.QIODevice = object

    for attr in (
        'QDialog', 'QVBoxLayout', 'QPushButton', 'QFileDialog', 'QListWidget', 'QMessageBox',
        'QHBoxLayout', 'QGridLayout', 'QProgressBar', 'QInputDialog', 'QLabel', 'QLineEdit', 'QTableWidget',
        'QTableWidgetItem', 'QHeaderView', 'QCheckBox', 'QSizePolicy', 'QWidget', 'QFrame'
    ):
        setattr(qtwidgets_stub, attr, type(attr, (), {}))
    qtwidgets_stub.QApplication = _DummyApplication

    qtgui_stub.QMovie = type('QMovie', (), {})
    qtgui_stub.QImageReader = type('QImageReader', (), {})

    pyqt_stub = types.ModuleType('PyQt6')
    pyqt_stub.QtCore = qtcore_stub
    pyqt_stub.QtWidgets = qtwidgets_stub
    pyqt_stub.QtGui = qtgui_stub

    sys.modules.setdefault('PyQt6', pyqt_stub)
    sys.modules.setdefault('PyQt6.QtCore', qtcore_stub)
    sys.modules.setdefault('PyQt6.QtWidgets', qtwidgets_stub)
    sys.modules.setdefault('PyQt6.QtGui', qtgui_stub)

@dataclass
class ScenarioResult:
    scenario: str
    wall_time_s: float
    stage_timings_s: dict[str, float]
    input_metrics: dict[str, float | int]


def _collect_median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(float(v) for v in values))


def _create_pdf_fixture_dir(base_dir: Path, count: int) -> Path:
    fixture_dir = base_dir / "pdf_reports"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        file_name = f"ABC12{i:03d}_2024-01-{(i % 28) + 1:02d}_{i:03d}.pdf"
        (fixture_dir / file_name).write_bytes(b"%PDF-1.4\n% benchmark placeholder\n")
    return fixture_dir


def _create_export_db_fixture(db_path: Path, *, report_count: int, headers_per_report: int) -> dict[str, int]:
    from modules.report_repository import ReportRepository
    from modules.report_schema import ensure_report_schema

    ensure_report_schema(str(db_path))
    repository = ReportRepository(str(db_path))

    rng = np.random.default_rng(42)
    total_measurement_rows = 0

    for report_index in range(1, report_count + 1):
        reference = f"REF-{((report_index - 1) % 4) + 1}"
        sample_number = str(report_index)
        report_date = f'2024-01-{(report_index % 28) + 1:02d}'
        file_name = f'{reference}_{report_date}_{sample_number}.pdf'
        measurements = []

        for header_idx in range(1, headers_per_report + 1):
            nominal = 10.0 + (header_idx * 0.1)
            measurement = float(nominal + rng.normal(0.0, 0.12))
            dev = measurement - nominal
            outtol = int(abs(dev) > 0.5)
            header = f'FEATURE_{header_idx:02d}'
            measurements.append(
                {
                    'row_order': header_idx,
                    'header': header,
                    'section_name': header,
                    'feature_label': header,
                    'characteristic_name': 'LOC',
                    'characteristic_family': 'LOC',
                    'description': header,
                    'ax': 'X',
                    'nominal': nominal,
                    'tol_plus': 0.5,
                    'tol_minus': -0.5,
                    'bonus': 0.0,
                    'meas': measurement,
                    'dev': dev,
                    'outtol': outtol,
                    'is_nok': bool(outtol),
                    'status_code': 'nok' if outtol else 'ok',
                }
            )
            total_measurement_rows += 1

        repository.persist_parsed_report(
            source_path=Path('/fixtures/reports') / file_name,
            parser_id='benchmark',
            parser_version='benchmark',
            template_family='cmm_pdf_header_box',
            template_variant='benchmark',
            parse_status='parsed',
            metadata={
                'reference': reference,
                'reference_raw': reference,
                'report_date': report_date,
                'sample_number': sample_number,
                'sample_number_kind': 'explicit_sample_number',
                'metadata_json': {'benchmark_fixture': True},
            },
            candidates=(),
            warnings=(),
            measurements=measurements,
            metadata_version='report_metadata_v1',
            page_count=1,
            measurement_count=len(measurements),
            has_nok=any(row['is_nok'] for row in measurements),
            nok_count=sum(1 for row in measurements if row['is_nok']),
            metadata_confidence=1.0,
            identity_hash=f'benchmark:{reference}:{sample_number}',
        )

    return {
        'reports': report_count,
        'headers': headers_per_report,
        'measurement_rows': total_measurement_rows,
    }


def _create_csv_fixture(csv_path: Path, *, row_count: int, data_columns: int) -> dict[str, int]:
    rng = np.random.default_rng(7)
    data = {'PART': [f'P-{index:04d}' for index in range(1, row_count + 1)]}

    for col_idx in range(1, data_columns + 1):
        center = 25.0 + (col_idx * 0.25)
        data[f'DIM_{col_idx:02d}'] = np.round(rng.normal(center, 0.2, size=row_count), 4)

    pd.DataFrame(data).to_csv(csv_path, index=False)
    return {'rows': row_count, 'headers': data_columns + 1}


def _run_excel_export_with_close_timing(thread: Any) -> tuple[bool, dict[str, float]]:
    from modules.export_backends import ExcelExportBackend

    class TimingExcelExportBackend(ExcelExportBackend):
        def __init__(self):
            self.timings = {
                'workbook_close': 0.0,
            }

        def close_writer(self, writer: Any) -> None:
            close_start = time.perf_counter()
            try:
                return super().close_writer(writer)
            finally:
                self.timings['workbook_close'] += time.perf_counter() - close_start

    backend = TimingExcelExportBackend()
    previous_backend = getattr(thread, '_active_backend', None)
    thread._active_backend = backend
    try:
        completed = backend.run(thread)
    finally:
        thread._active_backend = previous_backend
    return bool(completed), dict(backend.timings)


def _run_with_pandas_excel_writer_close_timing(
    operation: Callable[[], Any],
) -> tuple[Any, dict[str, float]]:
    original_excel_writer = pd.ExcelWriter
    original_to_excel = pd.DataFrame.to_excel
    timings = {
        'workbook_sheet_writes': 0.0,
        'workbook_close': 0.0,
    }
    sheet_write_count = 0

    class TimingExcelWriter:
        def __init__(self, *args, **kwargs):
            self._inner = original_excel_writer(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, exc_type, exc_value, traceback):
            close_start = time.perf_counter()
            try:
                return self._inner.__exit__(exc_type, exc_value, traceback)
            finally:
                timings['workbook_close'] += time.perf_counter() - close_start

    def timed_to_excel(self, *args, **kwargs):
        nonlocal sheet_write_count
        write_start = time.perf_counter()
        try:
            return original_to_excel(self, *args, **kwargs)
        finally:
            timings['workbook_sheet_writes'] += time.perf_counter() - write_start
            sheet_write_count += 1

    pd.ExcelWriter = TimingExcelWriter
    pd.DataFrame.to_excel = timed_to_excel
    try:
        result = operation()
    finally:
        pd.ExcelWriter = original_excel_writer
        pd.DataFrame.to_excel = original_to_excel
    timings['workbook_sheet_write_count'] = float(sheet_write_count)
    return result, dict(timings)


def benchmark_parse_path(temp_dir: Path, pdf_count: int) -> ScenarioResult:
    from modules.cmm_report_parser import CMMReportParser
    from modules.cmm_native_parser import get_backend_telemetry_snapshot, reset_backend_telemetry
    from modules.parse_reports_thread import ParseReportsThread, parse_new_reports
    from modules.contracts import ParseRequest

    db_path = temp_dir / 'parse_benchmark.sqlite'
    pdf_dir = _create_pdf_fixture_dir(temp_dir, pdf_count)
    thread = ParseReportsThread(ParseRequest(source_directory=str(pdf_dir), db_file=str(db_path)))

    t0 = time.perf_counter()
    discover_start = time.perf_counter()
    reports = thread.get_list_of_reports()
    discover_s = time.perf_counter() - discover_start

    load_existing_start = time.perf_counter()
    fingerprints = thread.get_report_fingerprints_in_database()
    load_existing_s = time.perf_counter() - load_existing_start

    parse_start = time.perf_counter()
    reset_backend_telemetry()
    parse_result = parse_new_reports(
        report_paths=reports,
        report_fingerprints=fingerprints,
        parser_factory=lambda report: CMMReportParser(str(report), str(db_path)),
        persist_report=lambda _parser: None,
    )
    parse_loop_s = time.perf_counter() - parse_start
    parse_telemetry = get_backend_telemetry_snapshot()
    wall_time_s = time.perf_counter() - t0

    return ScenarioResult(
        scenario='pdf_parse_path',
        wall_time_s=wall_time_s,
        stage_timings_s={
            'discover_reports': discover_s,
            'load_existing_reports': load_existing_s,
            'parse_loop': parse_loop_s,
        },
        input_metrics={
            'rows': parse_result.total_files,
            'headers': 0,
            'chart_count': 0,
            'parse_python_backend_rate': float(parse_telemetry.get('parse', {}).get('python_rate', 0.0)),
            'parse_native_backend_rate': float(parse_telemetry.get('parse', {}).get('native_rate', 0.0)),
            'persistence_python_backend_rate': float(parse_telemetry.get('persistence', {}).get('python_rate', 0.0)),
            'persistence_native_backend_rate': float(parse_telemetry.get('persistence', {}).get('native_rate', 0.0)),
        },
    )


def benchmark_cmm_parser_backend_compare(
    temp_dir: Path,
    *,
    report_count: int,
    measurements_per_report: int,
    benchmark_mode: str = "parse",
) -> ScenarioResult:
    from modules.cmm_native_parser import (
        get_backend_telemetry_snapshot,
        native_backend_available,
        normalize_measurement_rows,
        parse_blocks_with_backend,
        persist_measurement_rows_with_backend_and_telemetry,
        reset_backend_telemetry,
    )

    def _build_report_lines(report_index: int) -> list[str]:
        lines: list[str] = [f"#BENCHMARK HEADER {report_index}", "DIM"]
        for row_index in range(1, measurements_per_report + 1):
            nominal = 10.0 + row_index
            tol = 0.15 + ((row_index % 3) * 0.01)
            measured = nominal + (((row_index % 5) - 2) * 0.01)
            deviation = measured - nominal
            outtol = 1 if abs(deviation) > tol else 0
            lines.append(
                f"X NOM {nominal:.4f} +TOL {tol:.4f} -TOL {-tol:.4f} "
                f"MEAS {measured:.4f} DEV {deviation:.4f} OUTTOL {outtol}"
            )
            if row_index % 12 == 0:
                lines.extend(
                    [
                        "TP MMC +TOL 0.400 BONUS 0.000 MEAS 0.250 DEV 0.250 OUTTOL 0.000",
                    ]
                )
        lines.append("#END")
        return lines

    raw_batches = [_build_report_lines(index) for index in range(1, report_count + 1)]

    report_meta = [
        (
            f"REF-{index:05d}",
            "/bench",
            f"REF-{index:05d}_2024-01-02_{index:04d}.pdf",
            "2024-01-02",
            f"{index:04d}",
        )
        for index in range(1, report_count + 1)
    ]

    # Always benchmark fallback.
    os.environ["METROLIZA_CMM_PARSER_BACKEND"] = "python"
    os.environ["METROLIZA_CMM_PERSIST_BACKEND"] = "python"
    reset_backend_telemetry()
    py_parse_start = time.perf_counter()
    py_parsed_batches = [parse_blocks_with_backend(lines, use_native=False) for lines in raw_batches]
    py_parse_s = time.perf_counter() - py_parse_start
    py_measurements = sum(sum(len(block[1]) for block in parsed) for parsed in py_parsed_batches)
    py_normalize_s = 0.0
    py_persist_s = 0.0
    if benchmark_mode == "stages":
        py_normalize_start = time.perf_counter()
        py_rows = [
            normalize_measurement_rows(
                blocks,
                reference=meta[0],
                fileloc=meta[1],
                filename=meta[2],
                date=meta[3],
                sample_number=meta[4],
                use_native=False,
            )
            for blocks, meta in zip(py_parsed_batches, report_meta)
        ]
        py_normalize_s = time.perf_counter() - py_normalize_start

        py_db = temp_dir / "cmm_backend_benchmark_python.sqlite"
        if py_db.exists():
            py_db.unlink()
        py_persist_start = time.perf_counter()
        for rows in py_rows:
            persist_measurement_rows_with_backend_and_telemetry(str(py_db), rows, use_native=False)
        py_persist_s = time.perf_counter() - py_persist_start
    python_snapshot = get_backend_telemetry_snapshot()

    # Native benchmark only when extension is available.
    native_parse_s: float | None = None
    native_normalize_s = 0.0
    native_persist_s = 0.0
    native_measurements = 0
    native_snapshot = {}
    speedup_ratio = 0.0
    if native_backend_available():
        os.environ["METROLIZA_CMM_PARSER_BACKEND"] = "native"
        os.environ["METROLIZA_CMM_PERSIST_BACKEND"] = "native"
        reset_backend_telemetry()
        native_parse_start = time.perf_counter()
        native_parsed_batches = [parse_blocks_with_backend(lines, use_native=True) for lines in raw_batches]
        native_parse_s = time.perf_counter() - native_parse_start
        native_measurements = sum(sum(len(block[1]) for block in parsed) for parsed in native_parsed_batches)
        if benchmark_mode == "stages":
            native_normalize_start = time.perf_counter()
            native_rows = [
                normalize_measurement_rows(
                    blocks,
                    reference=meta[0],
                    fileloc=meta[1],
                    filename=meta[2],
                    date=meta[3],
                    sample_number=meta[4],
                    use_native=True,
                )
                for blocks, meta in zip(native_parsed_batches, report_meta)
            ]
            native_normalize_s = time.perf_counter() - native_normalize_start

            native_db = temp_dir / "cmm_backend_benchmark_native.sqlite"
            if native_db.exists():
                native_db.unlink()
            native_persist_start = time.perf_counter()
            for rows in native_rows:
                persist_measurement_rows_with_backend_and_telemetry(str(native_db), rows, use_native=True)
            native_persist_s = time.perf_counter() - native_persist_start
        native_snapshot = get_backend_telemetry_snapshot()
        speedup_ratio = (py_parse_s / native_parse_s) if native_parse_s > 0 else 0.0

    return ScenarioResult(
        scenario='cmm_parser_backend_compare',
        wall_time_s=(py_parse_s + py_normalize_s + py_persist_s) + (native_parse_s or 0.0) + native_normalize_s + native_persist_s,
        stage_timings_s={
            'python_backend_parse': py_parse_s,
            'python_backend_normalize': py_normalize_s,
            'python_backend_persist': py_persist_s,
            'native_backend_parse': native_parse_s or 0.0,
            'native_backend_normalize': native_normalize_s,
            'native_backend_persist': native_persist_s,
            'native_speedup_ratio': speedup_ratio,
        },
        input_metrics={
            'rows': py_measurements,
            'headers': report_count,
            'chart_count': 0,
            'native_available': int(native_backend_available()),
            'native_rows': native_measurements,
            'python_parse_backend_rate': float(python_snapshot.get('parse', {}).get('python_rate', 0.0)),
            'native_parse_backend_rate': float(native_snapshot.get('parse', {}).get('native_rate', 0.0)),
            'python_normalize_backend_rate': float(python_snapshot.get('normalize', {}).get('python_rate', 0.0)),
            'native_normalize_backend_rate': float(native_snapshot.get('normalize', {}).get('native_rate', 0.0)),
            'python_normalize_rows': int(python_snapshot.get('normalize', {}).get('rows_python', 0)),
            'native_normalize_rows': int(native_snapshot.get('normalize', {}).get('rows_native', 0)),
            'python_normalize_latency_s': float(python_snapshot.get('normalize', {}).get('latency_python_s', 0.0)),
            'native_normalize_latency_s': float(native_snapshot.get('normalize', {}).get('latency_native_s', 0.0)),
            'python_persistence_rows': int(python_snapshot.get('persistence_rows', {}).get('python', 0)),
            'native_persistence_rows': int(native_snapshot.get('persistence_rows', {}).get('native', 0)),
            'python_persistence_latency_s': float(python_snapshot.get('persistence_rows', {}).get('latency_python_s', 0.0)),
            'native_persistence_latency_s': float(native_snapshot.get('persistence_rows', {}).get('latency_native_s', 0.0)),
            'cmm_benchmark_mode': benchmark_mode,
        },
    )


def benchmark_excel_export_path(temp_dir: Path, report_count: int, headers_per_report: int) -> ScenarioResult:
    from modules.export_data_thread import ExportDataThread
    from modules.contracts import AppPaths, ExportOptions, ExportRequest
    from modules.db import read_sql_dataframe
    from modules.export_query_service import build_measurement_export_dataframe
    from modules.export_summary_utils import compute_measurement_summary, resolve_nominal_and_limits

    db_path = temp_dir / 'export_benchmark.sqlite'
    fixture_metrics = _create_export_db_fixture(db_path, report_count=report_count, headers_per_report=headers_per_report)

    out_xlsx = temp_dir / 'export_benchmark.xlsx'
    request = ExportRequest(
        paths=AppPaths(db_file=str(db_path), excel_file=str(out_xlsx)),
        options=ExportOptions(generate_summary_sheet=False, preset='fast_diagnostics'),
    )
    thread = ExportDataThread(request)

    data_load_start = time.perf_counter()
    loaded_df = build_measurement_export_dataframe(read_sql_dataframe(str(db_path), thread.filter_query))
    data_load_s = time.perf_counter() - data_load_start

    groupby_start = time.perf_counter()
    grouped = loaded_df.groupby(['REFERENCE', 'HEADER - AX'], sort=False)
    for (_reference, _header), group in grouped:
        nom, usl, lsl = resolve_nominal_and_limits(group)
        try:
            nom = float(nom)
            usl = float(usl)
            lsl = float(lsl)
        except (TypeError, ValueError):
            continue
        compute_measurement_summary(group, usl=usl, lsl=lsl, nom=nom)
    groupby_stats_s = time.perf_counter() - groupby_start

    total_run_start = time.perf_counter()
    completed, backend_timings = _run_excel_export_with_close_timing(thread)
    total_run_s = time.perf_counter() - total_run_start

    if not completed:
        raise RuntimeError('Excel export benchmark did not complete successfully.')

    observability_summary = thread.build_export_observability_summary(high_header_threshold=64)
    stage_timings = observability_summary['stage_timings_s']
    backend_counts = observability_summary['chart_backend_distribution']['counts']
    per_chart_medians = observability_summary['per_chart_type_timing_medians_s']
    high_header = observability_summary['high_header_cardinality_scenario']

    return ScenarioResult(
        scenario='excel_export_path',
        wall_time_s=data_load_s + groupby_stats_s + total_run_s,
        stage_timings_s={
            'data_load': data_load_s,
            'groupby_stats': groupby_stats_s,
            'transform_grouping': float(stage_timings.get('transform_grouping', 0.0)),
            'worksheet_write_planning': float(stage_timings.get('worksheet_write_planning', 0.0)),
            'chart_payload_preparation': float(stage_timings.get('chart_payload_preparation', 0.0)),
            'chart_rendering': float(stage_timings.get('chart_rendering', 0.0)),
            'worksheet_writes': float(stage_timings.get('worksheet_writes', 0.0)),
            'workbook_close': float(backend_timings.get('workbook_close', 0.0)),
        },
        input_metrics={
            'rows': fixture_metrics['measurement_rows'],
            'headers': fixture_metrics['headers'],
            'chart_count': fixture_metrics['headers'] * 2,
            'chart_backend_native_count': int(backend_counts.get('native', 0)),
            'chart_backend_matplotlib_count': int(backend_counts.get('matplotlib', 0)),
            'chart_type_median_distribution_s': float(per_chart_medians.get('distribution', 0.0)),
            'chart_type_median_iqr_s': float(per_chart_medians.get('iqr', 0.0)),
            'chart_type_median_histogram_s': float(per_chart_medians.get('histogram', 0.0)),
            'chart_type_median_trend_s': float(per_chart_medians.get('trend', 0.0)),
            'high_header_cardinality_detected': int(bool(high_header.get('detected'))),
            'high_header_cardinality_max_headers': int(high_header.get('max_headers_per_partition', 0)),
        },
    )


def benchmark_export_write_vs_shape_path(temp_dir: Path, report_count: int, headers_per_report: int) -> ScenarioResult:
    """Benchmark data-shaping preprocessing separately from worksheet write-only ops."""
    import xlsxwriter
    from modules.db import read_sql_dataframe
    from modules.export_query_service import build_measurement_export_dataframe
    from modules.report_query_service import build_measurement_export_query
    from modules.export_sheet_writer import (
        build_measurement_write_bundle_cached,
        create_measurement_formats,
        write_measurement_block,
    )

    db_path = temp_dir / 'export_write_vs_shape.sqlite'
    fixture_metrics = _create_export_db_fixture(db_path, report_count=report_count, headers_per_report=headers_per_report)

    data_load_start = time.perf_counter()
    loaded_df = build_measurement_export_dataframe(
        read_sql_dataframe(
            str(db_path),
            build_measurement_export_query(),
        )
    )
    data_load_s = time.perf_counter() - data_load_start

    grouping_start = time.perf_counter()
    grouped = list(loaded_df.groupby(['REFERENCE', 'HEADER - AX'], sort=False))
    grouping_s = time.perf_counter() - grouping_start

    cache: dict[str, Any] = {}
    shape_start = time.perf_counter()
    sort_s = 0.0
    write_bundle_planning_s = 0.0
    shaped = []
    for idx, ((reference, header), group) in enumerate(grouped):
        base_col = idx * 5
        sort_start = time.perf_counter()
        sorted_group = group.sort_values(
            by=['HEADER', 'AX', 'DATE', 'SAMPLE_NUMBER'],
            key=lambda col: col.astype(str).str.lower(),
        )
        sort_s += time.perf_counter() - sort_start
        bundle_start = time.perf_counter()
        write_bundle = build_measurement_write_bundle_cached(header, sorted_group, base_col, cache=cache)
        write_bundle_planning_s += time.perf_counter() - bundle_start
        shaped.append((reference, header, write_bundle))
    shape_s = time.perf_counter() - shape_start

    workbook_setup_start = time.perf_counter()
    write_only_sheet_count = 0
    workbook = xlsxwriter.Workbook(str(temp_dir / 'export_write_vs_shape.xlsx'))
    formats = create_measurement_formats(workbook)
    workbook_setup_s = time.perf_counter() - workbook_setup_start
    worksheet_creation_s = 0.0
    block_write_s = 0.0
    workbook_close_s = 0.0
    try:
        current_reference = None
        worksheet = None
        for reference, _header, write_bundle in shaped:
            if reference != current_reference:
                worksheet_create_start = time.perf_counter()
                worksheet = workbook.add_worksheet(f'REF_{write_only_sheet_count + 1}')
                worksheet_creation_s += time.perf_counter() - worksheet_create_start
                current_reference = reference
                write_only_sheet_count += 1
            block_write_start = time.perf_counter()
            write_measurement_block(worksheet, write_bundle, formats, base_col=write_bundle['measurement_plan']['summary_column'] - 1)
            block_write_s += time.perf_counter() - block_write_start
    finally:
        close_start = time.perf_counter()
        workbook.close()
        workbook_close_s = time.perf_counter() - close_start
    write_only_s = workbook_setup_s + worksheet_creation_s + block_write_s + workbook_close_s

    return ScenarioResult(
        scenario='excel_export_write_vs_shape_path',
        wall_time_s=data_load_s + grouping_s + shape_s + write_only_s,
        stage_timings_s={
            'data_load': data_load_s,
            'dataframe_grouping': grouping_s,
            'data_shaping': shape_s,
            'data_sorting': sort_s,
            'write_bundle_planning': write_bundle_planning_s,
            'data_shaping_overhead': max(0.0, shape_s - sort_s - write_bundle_planning_s),
            'workbook_setup': workbook_setup_s,
            'worksheet_creation': worksheet_creation_s,
            'write_measurement_blocks': block_write_s,
            'write_only_worksheet_ops': write_only_s,
            'workbook_close': workbook_close_s,
            'write_to_shape_ratio': (write_only_s / shape_s) if shape_s > 0 else 0.0,
        },
        input_metrics={
            'rows': fixture_metrics['measurement_rows'],
            'headers': fixture_metrics['headers'],
            'chart_count': 0,
            'header_groups': len(grouped),
            'worksheets': write_only_sheet_count,
        },
    )


def benchmark_export_high_header_cardinality_path(temp_dir: Path, report_count: int, headers_per_report: int) -> ScenarioResult:
    from modules.export_data_thread import ExportDataThread
    from modules.chart_render_service import build_violin_payload_vectorized, resolve_chart_sampling_policy, sample_frame_for_chart
    from modules.contracts import AppPaths, ExportOptions, ExportRequest
    from modules.db import read_sql_dataframe
    from modules.export_query_service import build_measurement_export_dataframe
    from modules.export_summary_utils import build_histogram_density_curve_payload, build_trend_plot_payload

    db_path = temp_dir / 'export_benchmark_high_cardinality.sqlite'
    fixture_metrics = _create_export_db_fixture(db_path, report_count=report_count, headers_per_report=headers_per_report)

    request = ExportRequest(
        paths=AppPaths(db_file=str(db_path), excel_file=str(temp_dir / 'noop.xlsx')),
        options=ExportOptions(generate_summary_sheet=True, preset='full_report', chart_worker_count=2, chart_worker_queue_size=2),
    )
    thread = ExportDataThread(request)

    loaded_df = build_measurement_export_dataframe(read_sql_dataframe(str(db_path), thread.filter_query))
    grouped = list(loaded_df.groupby(['REFERENCE', 'HEADER - AX'], sort=False))

    legacy_start = time.perf_counter()
    legacy_sampling_s = 0.0
    legacy_distribution_payload_s = 0.0
    legacy_histogram_payload_s = 0.0
    legacy_trend_payload_s = 0.0
    for (_reference, _header), group in grouped:
        sampling_start = time.perf_counter()
        sampled = thread._downsample_frame(group, thread._chart_sample_limit())
        legacy_sampling_s += time.perf_counter() - sampling_start
        distribution_key = 'SAMPLE_NUMBER'
        distribution_start = time.perf_counter()
        thread._build_violin_payload(sampled, distribution_key, thread.violin_plot_min_samplesize)
        legacy_distribution_payload_s += time.perf_counter() - distribution_start
        histogram_start = time.perf_counter()
        build_histogram_density_curve_payload(sampled['MEAS'], point_count=100)
        legacy_histogram_payload_s += time.perf_counter() - histogram_start
        trend_start = time.perf_counter()
        build_trend_plot_payload(sampled)
        legacy_trend_payload_s += time.perf_counter() - trend_start
    before_s = time.perf_counter() - legacy_start

    policy = resolve_chart_sampling_policy(density_mode='full')
    new_start = time.perf_counter()
    optimized_sampling_s = 0.0
    optimized_distribution_payload_s = 0.0
    optimized_histogram_payload_s = 0.0
    optimized_trend_payload_s = 0.0
    for (_reference, _header), group in grouped:
        sampling_start = time.perf_counter()
        sampled_distribution = sample_frame_for_chart(group, 'distribution', policy)
        sampled_histogram = sample_frame_for_chart(group, 'histogram', policy)
        sampled_trend = sample_frame_for_chart(group, 'trend', policy)
        optimized_sampling_s += time.perf_counter() - sampling_start
        distribution_key = 'SAMPLE_NUMBER'
        distribution_start = time.perf_counter()
        build_violin_payload_vectorized(sampled_distribution, distribution_key, thread.violin_plot_min_samplesize)
        optimized_distribution_payload_s += time.perf_counter() - distribution_start
        histogram_start = time.perf_counter()
        build_histogram_density_curve_payload(sampled_histogram['MEAS'], point_count=100)
        optimized_histogram_payload_s += time.perf_counter() - histogram_start
        trend_start = time.perf_counter()
        build_trend_plot_payload(sampled_trend)
        optimized_trend_payload_s += time.perf_counter() - trend_start
    after_s = time.perf_counter() - new_start

    return ScenarioResult(
        scenario='excel_export_high_header_cardinality_compare',
        wall_time_s=before_s + after_s,
        stage_timings_s={
            'before_refactor': before_s,
            'before_sampling': legacy_sampling_s,
            'before_distribution_payload': legacy_distribution_payload_s,
            'before_histogram_payload': legacy_histogram_payload_s,
            'before_trend_payload': legacy_trend_payload_s,
            'before_loop_overhead': max(
                0.0,
                before_s
                - legacy_sampling_s
                - legacy_distribution_payload_s
                - legacy_histogram_payload_s
                - legacy_trend_payload_s,
            ),
            'after_refactor': after_s,
            'after_sampling': optimized_sampling_s,
            'after_distribution_payload': optimized_distribution_payload_s,
            'after_histogram_payload': optimized_histogram_payload_s,
            'after_trend_payload': optimized_trend_payload_s,
            'after_loop_overhead': max(
                0.0,
                after_s
                - optimized_sampling_s
                - optimized_distribution_payload_s
                - optimized_histogram_payload_s
                - optimized_trend_payload_s,
            ),
            'speedup_ratio': (before_s / after_s) if after_s > 0 else 0.0,
        },
        input_metrics={
            'rows': fixture_metrics['measurement_rows'],
            'headers': fixture_metrics['headers'],
            'chart_count': fixture_metrics['headers'] * 4,
            'header_groups': len(grouped),
        },
    )




def benchmark_distribution_fit_monte_carlo_path(temp_dir: Path, *, group_count: int, sample_size: int, monte_carlo_samples: int) -> ScenarioResult:
    from modules.distribution_fit_service import (
        _MONTE_CARLO_PVALUE_CACHE_NAMESPACE,
        fit_measurement_distribution,
    )
    from modules.distribution_fit_candidate_native import (
        native_fit_backend_available,
        native_metrics_backend_available,
    )
    from modules.distribution_fit_native import (
        native_ad_ks_backend_available,
        native_monte_carlo_backend_available,
    )

    del temp_dir
    rng = np.random.default_rng(314159)
    groups = [
        np.asarray(rng.normal(loc=10.0 + (idx * 0.05), scale=0.25 + ((idx % 4) * 0.03), size=sample_size), dtype=float)
        for idx in range(group_count)
    ]

    ks_proxy_start = time.perf_counter()
    for values in groups:
        fit_measurement_distribution(values, monte_carlo_gof_samples=0)
    ks_proxy_s = time.perf_counter() - ks_proxy_start

    monte_carlo_start = time.perf_counter()
    for values in groups:
        fit_measurement_distribution(values, monte_carlo_gof_samples=monte_carlo_samples, monte_carlo_seed=2026)
    monte_carlo_s = time.perf_counter() - monte_carlo_start

    memoization_cache: dict[Any, Any] = {}
    monte_carlo_cache_warm_start = time.perf_counter()
    for values in groups:
        fit_measurement_distribution(
            values,
            monte_carlo_gof_samples=monte_carlo_samples,
            monte_carlo_seed=2026,
            memoization_cache=memoization_cache,
        )
    monte_carlo_cache_warm_s = time.perf_counter() - monte_carlo_cache_warm_start

    monte_carlo_cached_refit_start = time.perf_counter()
    for values in groups:
        usl = float(np.mean(values) + (3.0 * np.std(values)))
        fit_measurement_distribution(
            values,
            usl=usl,
            monte_carlo_gof_samples=monte_carlo_samples,
            monte_carlo_seed=2026,
            memoization_cache=memoization_cache,
        )
    monte_carlo_cached_refit_s = time.perf_counter() - monte_carlo_cached_refit_start
    monte_carlo_cache_entries = sum(
        1
        for key in memoization_cache
        if isinstance(key, tuple) and key[:1] == (_MONTE_CARLO_PVALUE_CACHE_NAMESPACE,)
    )

    return ScenarioResult(
        scenario='distribution_fit_monte_carlo_path',
        wall_time_s=ks_proxy_s + monte_carlo_s + monte_carlo_cache_warm_s + monte_carlo_cached_refit_s,
        stage_timings_s={
            'ks_proxy_path': ks_proxy_s,
            'monte_carlo_bootstrap_path': monte_carlo_s,
            'slowdown_ratio': (monte_carlo_s / ks_proxy_s) if ks_proxy_s > 0 else 0.0,
            'monte_carlo_cache_warm_path': monte_carlo_cache_warm_s,
            'monte_carlo_cached_refit_path': monte_carlo_cached_refit_s,
            'cached_refit_vs_uncached_ratio': (monte_carlo_cached_refit_s / monte_carlo_s) if monte_carlo_s > 0 else 0.0,
            'cached_refit_vs_ks_proxy_ratio': (monte_carlo_cached_refit_s / ks_proxy_s) if ks_proxy_s > 0 else 0.0,
        },
        input_metrics={
            'rows': group_count * sample_size,
            'headers': group_count,
            'chart_count': group_count,
            'monte_carlo_cache_entries': monte_carlo_cache_entries,
            'native_monte_carlo_available': int(native_monte_carlo_backend_available()),
            'native_ad_ks_available': int(native_ad_ks_backend_available()),
            'native_candidate_metrics_available': int(native_metrics_backend_available()),
            'native_candidate_fit_available': int(native_fit_backend_available()),
        },
    )


def _collect_distribution_gof_metrics(results: list[dict[str, Any]], *, prefix: str) -> dict[str, int]:
    selected_methods: Counter[str] = Counter()
    selected_policies: Counter[str] = Counter()
    ranking_methods: Counter[str] = Counter()
    effective_sizes: list[int] = []

    for result in results:
        gof_metrics = result.get('gof_metrics') or {}
        selected_methods[str(gof_metrics.get('ad_pvalue_method') or 'unknown')] += 1
        selected_policies[str(gof_metrics.get('ad_sample_policy') or 'unknown')] += 1
        effective_size = gof_metrics.get('ad_effective_sample_size')
        if effective_size is not None:
            effective_sizes.append(int(effective_size))
        for metric in result.get('ranking_metrics') or []:
            ranking_methods[str(metric.get('ad_pvalue_method') or 'unknown')] += 1

    metrics: dict[str, int] = {
        f'{prefix}_selected_count': len(results),
        f'{prefix}_effective_gof_sample_size_min': min(effective_sizes) if effective_sizes else 0,
        f'{prefix}_effective_gof_sample_size_max': max(effective_sizes) if effective_sizes else 0,
    }
    for method, count in selected_methods.items():
        metrics[f'{prefix}_selected_method_{method}'] = int(count)
    for policy, count in selected_policies.items():
        metrics[f'{prefix}_selected_policy_{policy}'] = int(count)
    for method, count in ranking_methods.items():
        metrics[f'{prefix}_ranking_method_{method}'] = int(count)
    return metrics


def benchmark_distribution_fit_gof_policy_compare(
    temp_dir: Path,
    *,
    group_count: int,
    sample_size: int,
    monte_carlo_samples: int,
    gof_max_sample_size: int,
) -> ScenarioResult:
    from modules.distribution_fit_service import fit_measurement_distribution
    from modules.distribution_fit_candidate_native import (
        native_fit_backend_available,
        native_metrics_backend_available,
    )
    from modules.distribution_fit_native import (
        native_ad_ks_backend_available,
        native_monte_carlo_backend_available,
    )

    del temp_dir
    rng = np.random.default_rng(271828)
    groups = [
        np.asarray(
            rng.normal(loc=10.0 + (idx * 0.04), scale=0.3 + ((idx % 5) * 0.04), size=sample_size),
            dtype=float,
        )
        for idx in range(group_count)
    ]

    full_start = time.perf_counter()
    full_results = [
        fit_measurement_distribution(
            values,
            include_kde_reference=False,
            monte_carlo_gof_samples=monte_carlo_samples,
            monte_carlo_seed=2026,
            gof_sample_policy='full',
            gof_max_sample_size=gof_max_sample_size,
        )
        for values in groups
    ]
    full_s = time.perf_counter() - full_start

    auto_start = time.perf_counter()
    auto_results = [
        fit_measurement_distribution(
            values,
            include_kde_reference=False,
            monte_carlo_gof_samples=monte_carlo_samples,
            monte_carlo_seed=2026,
            gof_sample_policy='auto',
            gof_max_sample_size=gof_max_sample_size,
        )
        for values in groups
    ]
    auto_s = time.perf_counter() - auto_start

    memoization_cache: dict[Any, Any] = {}
    auto_cache_warm_start = time.perf_counter()
    for values in groups:
        fit_measurement_distribution(
            values,
            include_kde_reference=False,
            monte_carlo_gof_samples=monte_carlo_samples,
            monte_carlo_seed=2026,
            gof_sample_policy='auto',
            gof_max_sample_size=gof_max_sample_size,
            memoization_cache=memoization_cache,
        )
    auto_cache_warm_s = time.perf_counter() - auto_cache_warm_start

    auto_cached_refit_start = time.perf_counter()
    for values in groups:
        usl = float(np.mean(values) + (3.0 * np.std(values)))
        fit_measurement_distribution(
            values,
            usl=usl,
            include_kde_reference=False,
            monte_carlo_gof_samples=monte_carlo_samples,
            monte_carlo_seed=2026,
            gof_sample_policy='auto',
            gof_max_sample_size=gof_max_sample_size,
            memoization_cache=memoization_cache,
        )
    auto_cached_refit_s = time.perf_counter() - auto_cached_refit_start

    input_metrics = {
        'rows': group_count * sample_size,
        'headers': group_count,
        'chart_count': group_count,
        'full_sample_size': sample_size,
        'requested_gof_max_sample_size': int(gof_max_sample_size),
        'native_monte_carlo_available': int(native_monte_carlo_backend_available()),
        'native_ad_ks_available': int(native_ad_ks_backend_available()),
        'native_candidate_metrics_available': int(native_metrics_backend_available()),
        'native_candidate_fit_available': int(native_fit_backend_available()),
    }
    input_metrics.update(_collect_distribution_gof_metrics(full_results, prefix='full'))
    input_metrics.update(_collect_distribution_gof_metrics(auto_results, prefix='auto'))

    return ScenarioResult(
        scenario='distribution_fit_gof_policy_compare',
        wall_time_s=full_s + auto_s + auto_cache_warm_s + auto_cached_refit_s,
        stage_timings_s={
            'full_monte_carlo_path': full_s,
            'auto_gof_policy_path': auto_s,
            'auto_cache_warm_path': auto_cache_warm_s,
            'auto_cached_refit_path': auto_cached_refit_s,
            'auto_policy_speedup_ratio': (full_s / auto_s) if auto_s > 0 else 0.0,
            'auto_cached_refit_vs_auto_ratio': (auto_cached_refit_s / auto_s) if auto_s > 0 else 0.0,
        },
        input_metrics=input_metrics,
    )


def _coerce_legacy(values: list[Any]) -> np.ndarray:
    numeric_values = np.asarray(values, dtype=object)
    coerced: list[float] = []
    for value in numeric_values:
        try:
            coerced.append(float(value))
        except (TypeError, ValueError):
            coerced.append(np.nan)
    return np.asarray(coerced, dtype=float)


def benchmark_group_preprocess_mixed_types_path(temp_dir: Path, *, group_count: int, values_per_group: int) -> ScenarioResult:
    from modules.group_stats_native import coerce_sequence_to_float64

    del temp_dir
    rng = np.random.default_rng(2026)
    groups: list[list[Any]] = []
    for _ in range(group_count):
        base = rng.normal(10.0, 0.8, size=values_per_group)
        mixed: list[Any] = base.tolist()
        for idx in range(0, values_per_group, 10):
            mixed[idx] = f"{mixed[idx]:.6f}"
        for idx in range(1, values_per_group, 25):
            mixed[idx] = None
        for idx in range(2, values_per_group, 33):
            mixed[idx] = 'bad'
        groups.append(mixed)

    legacy_start = time.perf_counter()
    legacy_total_values = 0
    for group in groups:
        values = _coerce_legacy(group)
        legacy_total_values += int(np.count_nonzero(~np.isnan(values)))
    legacy_s = time.perf_counter() - legacy_start

    optimized_start = time.perf_counter()
    optimized_total_values = 0
    for group in groups:
        values = coerce_sequence_to_float64(group)
        optimized_total_values += int(np.count_nonzero(~np.isnan(values)))
    optimized_s = time.perf_counter() - optimized_start

    if optimized_total_values != legacy_total_values:
        raise RuntimeError('optimized group coercion produced different non-NaN counts')

    return ScenarioResult(
        scenario='group_preprocess_mixed_types_compare',
        wall_time_s=legacy_s + optimized_s,
        stage_timings_s={
            'legacy_coercion': legacy_s,
            'optimized_coercion': optimized_s,
            'speedup_ratio': (legacy_s / optimized_s) if optimized_s > 0 else 0.0,
        },
        input_metrics={
            'rows': group_count * values_per_group,
            'headers': group_count,
            'chart_count': 0,
        },
    )


def benchmark_csv_summary_path(temp_dir: Path, row_count: int, data_columns: int) -> ScenarioResult:
    from modules.industrial_analytics_state import ProductionChartSelection
    import modules.industrial_analytics_workflow as workflow_module

    csv_path = temp_dir / 'summary_fixture.csv'
    output_html = temp_dir / 'summary_dashboard.html'
    output_xlsx = temp_dir / 'summary_output.xlsx'
    fixture_metrics = _create_csv_fixture(csv_path, row_count=row_count, data_columns=data_columns)
    grouping_df = pd.DataFrame(
        {
            'REPORT_ID': np.arange(1, row_count + 1, dtype=int),
            'GROUP': [f'Group {index % 3 + 1}' for index in range(row_count)],
        }
    )

    progress_messages: list[str] = []
    progress_events: list[tuple[float, str]] = []
    direct_timings = {
        'dashboard_manifest': 0.0,
        'dashboard_html_write': 0.0,
        'dashboard_write': 0.0,
        'workbook_export': 0.0,
    }

    original_write_dashboard = workflow_module._write_dashboard
    original_export_tabular_workbook = workflow_module._export_tabular_workbook_with_temp
    original_build_dashboard_manifest = workflow_module.build_production_dashboard_manifest
    original_write_production_dashboard = workflow_module.write_production_dashboard

    def timed_write_dashboard(*args, **kwargs):
        stage_start = time.perf_counter()
        manifest_timing_start = 0.0
        html_write_timing_start = 0.0

        def timed_build_dashboard_manifest(*manifest_args, **manifest_kwargs):
            nonlocal manifest_timing_start
            manifest_timing_start = time.perf_counter()
            try:
                return original_build_dashboard_manifest(*manifest_args, **manifest_kwargs)
            finally:
                direct_timings['dashboard_manifest'] += (
                    time.perf_counter() - manifest_timing_start
                )

        def timed_write_production_dashboard(*dashboard_args, **dashboard_kwargs):
            nonlocal html_write_timing_start
            html_write_timing_start = time.perf_counter()
            try:
                return original_write_production_dashboard(*dashboard_args, **dashboard_kwargs)
            finally:
                direct_timings['dashboard_html_write'] += (
                    time.perf_counter() - html_write_timing_start
                )

        workflow_module.build_production_dashboard_manifest = timed_build_dashboard_manifest
        workflow_module.write_production_dashboard = timed_write_production_dashboard
        try:
            return original_write_dashboard(*args, **kwargs)
        finally:
            direct_timings['dashboard_write'] += time.perf_counter() - stage_start
            workflow_module.build_production_dashboard_manifest = original_build_dashboard_manifest
            workflow_module.write_production_dashboard = original_write_production_dashboard

    def timed_export_tabular_workbook(*args, **kwargs):
        stage_start = time.perf_counter()
        try:
            return original_export_tabular_workbook(*args, **kwargs)
        finally:
            direct_timings['workbook_export'] += time.perf_counter() - stage_start

    def record_progress(message: str) -> None:
        progress_messages.append(str(message))
        progress_events.append((time.perf_counter(), str(message)))

    run_start = time.perf_counter()
    workflow_module._write_dashboard = timed_write_dashboard
    workflow_module._export_tabular_workbook_with_temp = timed_export_tabular_workbook
    try:
        result, writer_timings = _run_with_pandas_excel_writer_close_timing(
            lambda: workflow_module.run_tabular_file_analytics(
                input_file=str(csv_path),
                output_dashboard_file=str(output_html),
                reference_column='PART',
                grouping_df=grouping_df,
                chart_selection=ProductionChartSelection(
                    time_series=True,
                    histogram=True,
                    violin=True,
                    box=True,
                    groupstats=True,
                ),
                output_workbook_file=str(output_xlsx),
                separate_parameter_sheets=True,
                progress_callback=record_progress,
            )
        )
    finally:
        workflow_module._write_dashboard = original_write_dashboard
        workflow_module._export_tabular_workbook_with_temp = original_export_tabular_workbook
    run_s = time.perf_counter() - run_start
    progress_marks: dict[str, float] = {}
    for event_time, message in progress_events:
        if not message.strip():
            continue
        stage_label = message.splitlines()[0].strip()
        progress_marks.setdefault(stage_label, event_time - run_start)
    chart_start_s = progress_marks.get('Writing dashboard...')
    groupstats_start_s = progress_marks.get('Running statistical analysis...')
    workbook_start_s = progress_marks.get('Writing workbook...')
    complete_s = progress_marks.get('Analytics complete', run_s)
    groupstats_analysis_s = (
        max(0.0, (chart_start_s if chart_start_s is not None else complete_s) - groupstats_start_s)
        if groupstats_start_s is not None
        else 0.0
    )
    chart_generation_s = (
        max(0.0, (workbook_start_s if workbook_start_s is not None else complete_s) - chart_start_s)
        if chart_start_s is not None
        else 0.0
    )
    workbook_write_s = (
        max(0.0, complete_s - workbook_start_s)
        if workbook_start_s is not None
        else 0.0
    )

    return ScenarioResult(
        scenario='csv_summary_export_path',
        wall_time_s=run_s,
        stage_timings_s={
            'shared_analytics_total': run_s,
            'groupstats_analysis': groupstats_analysis_s,
            'chart_generation': chart_generation_s,
            'workbook_write': workbook_write_s,
            'dashboard_manifest': float(direct_timings['dashboard_manifest']),
            'dashboard_html_write': float(direct_timings['dashboard_html_write']),
            'dashboard_write': float(direct_timings['dashboard_write']),
            'dashboard_write_overhead': max(
                0.0,
                float(direct_timings['dashboard_write'])
                - float(direct_timings['dashboard_manifest'])
                - float(direct_timings['dashboard_html_write']),
            ),
            'workbook_export': float(direct_timings['workbook_export']),
            'workbook_sheet_writes': float(writer_timings.get('workbook_sheet_writes', 0.0)),
            'workbook_close': float(writer_timings.get('workbook_close', 0.0)),
            'workbook_export_overhead': max(
                0.0,
                float(direct_timings['workbook_export'])
                - float(writer_timings.get('workbook_sheet_writes', 0.0))
                - float(writer_timings.get('workbook_close', 0.0)),
            ),
            'progress_messages': float(len(progress_messages)),
        },
        input_metrics={
            'rows': fixture_metrics['rows'],
            'headers': fixture_metrics['headers'],
            'chart_count': min(data_columns, 5) * 4,
            'dashboard_bytes': output_html.stat().st_size if output_html.exists() else 0,
            'dashboard_html_bytes': result.html_dashboard_html_bytes,
            'dashboard_interactive_chart_count': result.html_dashboard_interactive_chart_count,
            'dashboard_plotly_spec_count': result.html_dashboard_plotly_spec_count,
            'dashboard_embedded_plotly_spec_count': result.html_dashboard_embedded_plotly_spec_count,
            'dashboard_plotly_serialized_json_bytes': (
                result.html_dashboard_plotly_serialized_json_bytes
            ),
            'dashboard_embedded_plotly_serialized_json_bytes': (
                result.html_dashboard_embedded_plotly_serialized_json_bytes
            ),
            'dashboard_plotly_budget_over': int(
                result.html_dashboard_plotly_budget_status == 'over_budget'
            ),
            'workbook_bytes': output_xlsx.stat().st_size if output_xlsx.exists() else 0,
            'workbook_sheet_write_count': int(writer_timings.get('workbook_sheet_write_count', 0)),
            'analytics_rows': result.row_count,
            'analytics_metrics': result.metric_count,
            'groupstats_metric_count': result.groupstats_metric_count,
        },
    )


def benchmark_production_dashboard_workbook_path(
    temp_dir: Path,
    *,
    row_count: int,
    metric_count: int,
) -> ScenarioResult:
    from modules.industrial_analytics_dashboard import (
        build_production_dashboard_manifest,
        write_production_dashboard,
    )
    from modules.industrial_analytics_service import aggregate_production_frame
    from modules.industrial_analytics_state import (
        ProductionAggregationState,
        ProductionChartSelection,
        ProductionMetricSelection,
    )
    from modules.industrial_analytics_workbook import export_production_analytics_workbook

    rng = np.random.default_rng(20260520)
    safe_row_count = max(1, int(row_count))
    safe_metric_count = max(1, int(metric_count))
    data: dict[str, Any] = {
        'process_datetime': pd.date_range(
            '2026-05-01 00:00',
            periods=safe_row_count,
            freq='min',
            tz='UTC',
        ),
        'reference': [f'REF-{index % 32:03d}' for index in range(safe_row_count)],
        'line': [f'L{index % 4 + 1}' for index in range(safe_row_count)],
        'station': [f'S{index % 8 + 1}' for index in range(safe_row_count)],
    }
    metrics: list[ProductionMetricSelection] = []
    for metric_index in range(1, safe_metric_count + 1):
        field_name = f'metric_{metric_index:02d}'
        center = 10.0 + metric_index
        data[field_name] = np.round(
            rng.normal(center, 0.25 + (metric_index * 0.02), size=safe_row_count),
            5,
        )
        metrics.append(
            ProductionMetricSelection(
                field_name,
                display_label=f'Metric {metric_index:02d}',
                lsl=center - 0.8,
                usl=center + 0.8,
            )
        )
    dataframe = pd.DataFrame(data)
    metric_selection = tuple(metrics)
    aggregation = ProductionAggregationState(
        time_bucket='hour',
        aggregation_methods=('mean',),
        group_fields=('line',),
    )
    chart_selection = ProductionChartSelection(
        time_series=True,
        histogram=True,
        violin=True,
        box=True,
        groupstats=False,
    )

    aggregate_start = time.perf_counter()
    aggregated = aggregate_production_frame(dataframe, aggregation, metric_selection)
    aggregate_s = time.perf_counter() - aggregate_start

    manifest_start = time.perf_counter()
    manifest = build_production_dashboard_manifest(
        frame=dataframe,
        metric_selection=metric_selection,
        aggregation_state=aggregation,
        aggregation_result=aggregated,
        chart_selection=chart_selection,
        dashboard_title='Production Analytics Benchmark',
        dashboard_subtitle='Synthetic production dashboard benchmark.',
    )
    manifest_s = time.perf_counter() - manifest_start

    dashboard_start = time.perf_counter()
    dashboard_result = write_production_dashboard(
        manifest,
        temp_dir / 'production_dashboard.html',
    )
    dashboard_s = time.perf_counter() - dashboard_start

    workbook_start = time.perf_counter()
    workbook_result, writer_timings = _run_with_pandas_excel_writer_close_timing(
        lambda: export_production_analytics_workbook(
            dataframe=dataframe,
            metric_selection=metric_selection,
            output_file=temp_dir / 'production_analytics.xlsx',
            aggregation_result=aggregated,
            chart_selection=chart_selection,
            separate_parameter_sheets=True,
            group_fields=aggregation.group_fields,
        )
    )
    workbook_s = time.perf_counter() - workbook_start

    budget = dashboard_result.get('html_dashboard_plotly_budget') or {}
    return ScenarioResult(
        scenario='production_dashboard_workbook_path',
        wall_time_s=aggregate_s + manifest_s + dashboard_s + workbook_s,
        stage_timings_s={
            'aggregation': aggregate_s,
            'dashboard_manifest': manifest_s,
            'dashboard_html_write': dashboard_s,
            'dashboard_write': dashboard_s,
            'workbook_export': workbook_s,
            'workbook_sheet_writes': float(writer_timings.get('workbook_sheet_writes', 0.0)),
            'workbook_close': float(writer_timings.get('workbook_close', 0.0)),
            'workbook_export_overhead': max(
                0.0,
                workbook_s
                - float(writer_timings.get('workbook_sheet_writes', 0.0))
                - float(writer_timings.get('workbook_close', 0.0)),
            ),
        },
        input_metrics={
            'rows': safe_row_count,
            'headers': safe_metric_count,
            'chart_count': int(dashboard_result.get('html_dashboard_chart_count') or 0),
            'dashboard_html_bytes': int(dashboard_result.get('html_dashboard_html_bytes') or 0),
            'dashboard_interactive_chart_count': int(
                dashboard_result.get('html_dashboard_interactive_chart_count') or 0
            ),
            'dashboard_plotly_spec_count': int(
                dashboard_result.get('html_dashboard_plotly_spec_count') or 0
            ),
            'dashboard_embedded_plotly_spec_count': int(
                dashboard_result.get('html_dashboard_embedded_plotly_spec_count') or 0
            ),
            'dashboard_plotly_serialized_json_bytes': int(
                dashboard_result.get('html_dashboard_plotly_serialized_json_bytes') or 0
            ),
            'dashboard_embedded_plotly_serialized_json_bytes': int(
                dashboard_result.get('html_dashboard_embedded_plotly_serialized_json_bytes') or 0
            ),
            'dashboard_plotly_budget_over': int(
                isinstance(budget, dict) and budget.get('status') == 'over_budget'
            ),
            'workbook_sheets': len(workbook_result.sheet_names),
            'workbook_parameter_sheets': int(workbook_result.parameter_sheet_count),
            'workbook_sheet_write_count': int(writer_timings.get('workbook_sheet_write_count', 0)),
            'workbook_bytes': Path(workbook_result.output_file).stat().st_size,
        },
    )


def benchmark_csv_summary_large_data_probe(
    temp_dir: Path,
    *,
    row_count: int,
    data_columns: int,
    search_text: str,
    materialize_columns: int,
) -> ScenarioResult:
    """Probe CSV Summary load/group/filter/materialization costs for release-scale data.

    This scenario is intentionally opt-in. CI can run it with small row counts, while
    release checks can use --large-csv-rows 1000000 --large-csv-columns 20.
    """

    from modules.grouping_filter_core import DataFrameGroupingIndex
    from modules.tabular_analytics_service import (
        build_tabular_grouping_dataframe,
        load_tabular_analytics_files,
        materialize_tabular_dataframe,
    )
    from modules.db import sqlite_connection_scope

    csv_path = temp_dir / 'summary_large_probe.csv'
    fixture_metrics = _create_csv_fixture(csv_path, row_count=row_count, data_columns=data_columns)
    search = str(search_text or '').strip()

    load_start = time.perf_counter()
    loaded = load_tabular_analytics_files((str(csv_path),), reference_column='PART', force_sqlite=True)
    load_s = time.perf_counter() - load_start
    load_timings = dict(getattr(loaded, 'load_timings_s', {}) or {})

    def load_timing(name: str) -> float:
        return float(load_timings.get(name, 0.0) or 0.0)

    csv_load_read_file_s = load_timing('sampling') + load_timing('chunk_read')
    csv_load_normalize_columns_s = (
        load_timing('chunk_normalize') + load_timing('chunk_build_rows')
    )
    csv_load_sqlite_ingest_s = (
        load_timing('sqlite_setup') + load_timing('sqlite_write') + load_timing('indexing')
    )
    csv_load_recorded_s = sum(
        load_timing(name)
        for name in (
            'sampling',
            'sqlite_setup',
            'chunk_read',
            'chunk_normalize',
            'chunk_build_rows',
            'metric_stats',
            'sqlite_write',
            'indexing',
            'metric_candidates',
            'preview',
        )
    )
    csv_load_unattributed_s = max(0.0, load_s - csv_load_recorded_s)

    metric_columns = tuple(
        candidate.field_name
        for candidate in tuple(getattr(loaded, 'metric_candidates', ()))[: max(1, materialize_columns)]
    )
    required_columns = ('source_row_number', 'reference', *metric_columns)
    materialize_start = time.perf_counter()
    materialized = materialize_tabular_dataframe(loaded, required_columns=required_columns)
    materialize_s = time.perf_counter() - materialize_start

    preview_value_rows = 0
    preview_group_total = 0
    row_id_count = 0
    grouping_build_s = 0.0
    value_preview_s = 0.0
    group_preview_s = 0.0
    row_ids_s = 0.0
    sqlite_multi_column_group_preview_s = 0.0
    sqlite_assign_filtered_scope_s = 0.0
    sqlite_use_grouping_sparse_assignment_s = 0.0

    sqlite_store = getattr(loaded, 'sqlite_store', None)
    if sqlite_store is not None:
        value_start = time.perf_counter()
        values, _total_values = sqlite_store.preview_value_rows('reference', search_text=search, limit=100)
        value_preview_s = time.perf_counter() - value_start
        preview_value_rows = len(values)

        group_start = time.perf_counter()
        _group_rows, preview_group_total = sqlite_store.preview_group_rows(
            ('reference',),
            search_text=search,
            limit=100,
        )
        group_preview_s = time.perf_counter() - group_start

        multi_column_start = time.perf_counter()
        multi_group_columns = (
            ('reference', 'dim_01') if 'dim_01' in sqlite_store.columns else ('reference',)
        )
        _multi_group_rows, multi_group_total = sqlite_store.preview_group_rows(
            multi_group_columns,
            search_text=search,
            limit=100,
        )
        sqlite_multi_column_group_preview_s = time.perf_counter() - multi_column_start

        row_id_start = time.perf_counter()
        row_ids = sqlite_store.row_ids_for_group_search(('reference',), search_text=search)
        row_ids_s = time.perf_counter() - row_id_start
        row_id_count = len(row_ids)

        assign_scope_start = time.perf_counter()
        scope_query, scope_params = sqlite_store.source_row_number_query_for_group_search(
            ('reference',),
            search_text=search,
        )
        with sqlite_connection_scope(sqlite_store.path) as connection:
            connection.execute(
                'CREATE TEMP TABLE IF NOT EXISTS bench_group_assignment_scope '
                '(row_id INTEGER PRIMARY KEY)'
            )
            connection.execute('DELETE FROM bench_group_assignment_scope')
            if scope_query:
                connection.execute(
                    'INSERT OR IGNORE INTO bench_group_assignment_scope (row_id) '
                    f'SELECT source_row_number FROM ({scope_query})',
                    scope_params,
                )
            assign_scope_count = int(
                connection.execute('SELECT COUNT(*) FROM bench_group_assignment_scope').fetchone()[0]
                or 0
            )
        sqlite_assign_filtered_scope_s = time.perf_counter() - assign_scope_start

        sparse_start = time.perf_counter()
        sparse_row_ids = row_ids[: min(len(row_ids), 100)]
        sparse_grouping = pd.DataFrame(
            {
                'REPORT_ID': sparse_row_ids,
                'GROUP': ['BENCH'] * len(sparse_row_ids),
            }
        )
        sparse_grouping['GROUP_KEY'] = sparse_grouping['REPORT_ID']
        sqlite_use_grouping_sparse_assignment_s = time.perf_counter() - sparse_start
    else:
        grouping_start = time.perf_counter()
        grouping_frame = build_tabular_grouping_dataframe(loaded.dataframe, selector_columns=('reference',))
        grouping_build_s = time.perf_counter() - grouping_start

        group_start = time.perf_counter()
        index = DataFrameGroupingIndex(grouping_frame, ('PART_NAME',))
        group_rows, preview_group_total = index.preview_rows(search_text=search, limit=100)
        group_preview_s = time.perf_counter() - group_start
        preview_value_rows = len(group_rows)

        row_id_start = time.perf_counter()
        keys = {tuple(row['key']) for row in group_rows}
        row_ids = index.row_ids_for_keys(keys)
        row_ids_s = time.perf_counter() - row_id_start
        row_id_count = len(row_ids)
        multi_group_total = preview_group_total
        assign_scope_count = row_id_count

    total_s = (
        load_s
        + materialize_s
        + grouping_build_s
        + value_preview_s
        + group_preview_s
        + sqlite_multi_column_group_preview_s
        + row_ids_s
        + sqlite_assign_filtered_scope_s
        + sqlite_use_grouping_sparse_assignment_s
    )
    return ScenarioResult(
        scenario='csv_summary_large_data_probe',
        wall_time_s=total_s,
        stage_timings_s={
            'csv_load': load_s,
            'csv_load_read_file': csv_load_read_file_s,
            'csv_load_sampling': load_timing('sampling'),
            'csv_load_chunk_read': load_timing('chunk_read'),
            'csv_load_normalize_columns': csv_load_normalize_columns_s,
            'csv_load_chunk_normalize': load_timing('chunk_normalize'),
            'csv_load_chunk_build_rows': load_timing('chunk_build_rows'),
            'csv_load_metric_stats': load_timing('metric_stats'),
            'csv_load_sqlite_ingest': csv_load_sqlite_ingest_s,
            'csv_load_sqlite_setup': load_timing('sqlite_setup'),
            'csv_load_sqlite_write': load_timing('sqlite_write'),
            'csv_load_indexing': load_timing('indexing'),
            'csv_load_metric_candidates': load_timing('metric_candidates'),
            'csv_load_preview': load_timing('preview'),
            'csv_load_internal_total': load_timing('total'),
            'csv_load_unattributed': csv_load_unattributed_s,
            'materialize_required_columns': materialize_s,
            'grouping_dataframe_build': grouping_build_s,
            'value_preview': value_preview_s,
            'sqlite_value_preview': value_preview_s if sqlite_store is not None else 0.0,
            'group_preview': group_preview_s,
            'sqlite_multi_column_group_preview': sqlite_multi_column_group_preview_s,
            'row_ids_for_search': row_ids_s,
            'sqlite_assign_filtered_scope': sqlite_assign_filtered_scope_s,
            'sqlite_use_grouping_sparse_assignment': sqlite_use_grouping_sparse_assignment_s,
        },
        input_metrics={
            'rows': fixture_metrics['rows'],
            'headers': fixture_metrics['headers'],
            'csv_load_substage_available': 1 if load_timings else 0,
            'storage_mode_sqlite': 1 if sqlite_store is not None else 0,
            'materialized_rows': int(len(materialized.dataframe.index)),
            'materialized_columns': int(len(materialized.dataframe.columns)),
            'preview_value_rows': preview_value_rows,
            'preview_group_total': int(preview_group_total),
            'preview_multi_column_group_total': int(multi_group_total),
            'row_ids_for_search': row_id_count,
            'assign_filtered_scope_rows': int(assign_scope_count),
        },
    )


def benchmark_chart_render_budget_path(temp_dir: Path, *, iterations: int, histogram_points: int) -> ScenarioResult:
    import matplotlib.pyplot as plt
    from modules.chart_renderer import (
        MatplotlibChartRenderer,
        NativeChartRenderer,
        benchmark_histogram_render_runtime,
        native_chart_backend_available,
        build_histogram_native_payload,
    )

    del temp_dir
    rng = np.random.default_rng(20260325)
    values = rng.normal(loc=10.0, scale=0.2, size=max(32, histogram_points))
    payload = build_histogram_native_payload(
        values=values.tolist(),
        lsl=9.5,
        usl=10.5,
        title='Histogram budget benchmark',
        bin_count=24,
        compact_render=True,
    )

    matplotlib_samples: list[float] = []
    native_samples: list[float] = []

    for _ in range(max(1, iterations)):
        mpl_runtime = benchmark_histogram_render_runtime(MatplotlibChartRenderer(), payload, iterations=1)
        matplotlib_samples.append(float(mpl_runtime.get('median_s', 0.0)))
        if native_chart_backend_available():
            native_runtime = benchmark_histogram_render_runtime(NativeChartRenderer(), payload, iterations=1)
            native_samples.append(float(native_runtime.get('median_s', 0.0)))

    matplotlib_median = _collect_median(matplotlib_samples)
    native_median = _collect_median(native_samples)
    regression_ratio = (matplotlib_median / native_median) if native_median > 0 else 0.0

    plt.close('all')
    return ScenarioResult(
        scenario='chart_render_budget_path',
        wall_time_s=float(sum(matplotlib_samples) + sum(native_samples)),
        stage_timings_s={
            'histogram_matplotlib_median_s': matplotlib_median,
            'histogram_native_median_s': native_median,
            'histogram_branch_regression_ratio': regression_ratio,
        },
        input_metrics={
            'rows': int(len(values)),
            'headers': 1,
            'chart_count': int(max(1, iterations) * (2 if native_chart_backend_available() else 1)),
            'histogram_native_available': int(native_chart_backend_available()),
        },
    )


def benchmark_chart_type_native_compare_path(temp_dir: Path, *, chart_type: str, iterations: int) -> ScenarioResult:
    """Benchmark one summary chart type using ExportDataThread timing hooks."""
    from modules.contracts import AppPaths, ExportOptions, ExportRequest
    from modules.export_data_thread import ExportDataThread

    class _BenchWorksheet:
        def write(self, *_args, **_kwargs):
            return None

        def insert_image(self, *_args, **_kwargs):
            return None

    chart_key = str(chart_type).strip().lower()
    if chart_key not in {"distribution", "iqr", "trend", "histogram"}:
        raise ValueError(f"Unsupported chart_type benchmark: {chart_type}")

    header_group = pd.DataFrame(
        {
            "MEAS": np.linspace(9.8, 10.2, 120),
            "NOM": [10.0] * 120,
            "+TOL": [0.2] * 120,
            "-TOL": [-0.2] * 120,
            "SAMPLE_NUMBER": [str(i + 1) for i in range(120)],
            "DATE": ["2024-01-01"] * 120,
        }
    )

    backend_stage_medians: dict[str, float] = {}
    backend_native_counts: dict[str, int] = {}
    backend_chart_medians: dict[str, float] = {}
    original_backend_env = os.environ.get("METROLIZA_CHART_RENDERER_BACKEND")
    try:
        for backend in ("matplotlib", "native"):
            os.environ["METROLIZA_CHART_RENDERER_BACKEND"] = backend
            request = ExportRequest(
                paths=AppPaths(db_file=str(temp_dir / "bench.sqlite"), excel_file=str(temp_dir / "bench.xlsx")),
                options=ExportOptions(generate_summary_sheet=True, preset="fast_diagnostics"),
            )
            thread = ExportDataThread(request)
            thread._optimization_toggles["summary_sheet_minimum_charts"] = {chart_key}
            worksheet = _BenchWorksheet()

            for _ in range(max(1, int(iterations))):
                thread.summary_sheet_fill(worksheet, "BENCH_HEADER", header_group.copy(), col=0)

            summary = thread.build_export_observability_summary()
            backend_stage_medians[backend] = float(summary.get("stage_timings_s", {}).get("chart_rendering", 0.0))
            backend_native_counts[backend] = int(
                summary.get("per_chart_type_backend_distribution", {}).get(chart_key, {}).get("counts", {}).get("native", 0)
            )
            backend_chart_medians[backend] = float(summary.get("per_chart_type_timing_medians_s", {}).get(chart_key, 0.0))
    finally:
        if original_backend_env is None:
            os.environ.pop("METROLIZA_CHART_RENDERER_BACKEND", None)
        else:
            os.environ["METROLIZA_CHART_RENDERER_BACKEND"] = original_backend_env

    native_median = (
        backend_chart_medians.get("native", 0.0)
        if backend_native_counts.get("native", 0) > 0
        else 0.0
    )
    matplotlib_median = backend_chart_medians.get("matplotlib", 0.0)
    speedup = (matplotlib_median / native_median) if native_median > 0 else 0.0
    return ScenarioResult(
        scenario=f"chart_type_native_compare_{chart_key}",
        wall_time_s=float(backend_stage_medians.get("matplotlib", 0.0) + backend_stage_medians.get("native", 0.0)),
        stage_timings_s={
            f"{chart_key}_matplotlib_median_s": matplotlib_median,
            f"{chart_key}_native_median_s": native_median,
            f"{chart_key}_native_speedup_ratio": speedup,
        },
        input_metrics={
            "rows": int(len(header_group)),
            "headers": 1,
            "chart_count": int(max(1, int(iterations)) * 2),
            f"{chart_key}_native_usage_count_matplotlib_backend": int(backend_native_counts.get("matplotlib", 0)),
            f"{chart_key}_native_usage_count_native_backend": int(backend_native_counts.get("native", 0)),
        },
    )


def build_benchmark_run_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    native_count = 0
    matplotlib_count = 0
    chart_type_samples: dict[str, list[float]] = {
        'distribution': [],
        'iqr': [],
        'histogram': [],
        'trend': [],
    }
    high_header_timing = {}
    csv_summary_timing = {}
    production_dashboard_workbook_timing = {}
    for result in results:
        metrics = result.get('input_metrics') or {}
        native_count += int(metrics.get('chart_backend_native_count', 0))
        matplotlib_count += int(metrics.get('chart_backend_matplotlib_count', 0))

        for chart_type in chart_type_samples:
            key = f'chart_type_median_{chart_type}_s'
            if key in metrics:
                chart_type_samples[chart_type].append(float(metrics[key]))

        if result.get('scenario') == 'excel_export_high_header_cardinality_compare':
            high_header_timing = dict(result.get('stage_timings_s') or {})
        if result.get('scenario') == 'csv_summary_export_path':
            csv_summary_timing = dict(result.get('stage_timings_s') or {})
        if result.get('scenario') == 'production_dashboard_workbook_path':
            production_dashboard_workbook_timing = dict(result.get('stage_timings_s') or {})

    total = native_count + matplotlib_count
    return {
        'chart_backend_distribution': {
            'counts': {'native': native_count, 'matplotlib': matplotlib_count},
            'rates': {
                'native': (native_count / total) if total else 0.0,
                'matplotlib': (matplotlib_count / total) if total else 0.0,
            },
        },
        'per_chart_type_timing_medians_s': {
            chart_type: _collect_median(samples)
            for chart_type, samples in chart_type_samples.items()
        },
        'high_header_cardinality_scenario_timing_s': high_header_timing,
        'csv_summary_dashboard_workbook_timing_s': csv_summary_timing,
        'production_dashboard_workbook_timing_s': production_dashboard_workbook_timing,
    }


def _write_outputs(output_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    json_path = output_dir / f'benchmark-{stamp}.json'
    csv_path = output_dir / f'benchmark-{stamp}.csv'

    json_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    with csv_path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=['scenario', 'metric_type', 'metric_name', 'value'])
        writer.writeheader()
        for scenario in payload['results']:
            writer.writerow({'scenario': scenario['scenario'], 'metric_type': 'wall_time_s', 'metric_name': 'total', 'value': scenario['wall_time_s']})
            for metric_name, value in scenario['stage_timings_s'].items():
                writer.writerow({'scenario': scenario['scenario'], 'metric_type': 'stage_timing_s', 'metric_name': metric_name, 'value': value})
            for metric_name, value in scenario['input_metrics'].items():
                writer.writerow({'scenario': scenario['scenario'], 'metric_type': 'input_metric', 'metric_name': metric_name, 'value': value})

    return json_path, csv_path


def main() -> int:
    _install_headless_stubs()

    parser = argparse.ArgumentParser(description='Run lightweight pipeline benchmarks for parse/export flows.')
    parser.add_argument('--output-dir', default='benchmark_results', help='Directory for machine-readable benchmark outputs.')
    parser.add_argument('--pdf-count', type=int, default=80)
    parser.add_argument('--report-count', type=int, default=120)
    parser.add_argument('--headers-per-report', type=int, default=10)
    parser.add_argument('--csv-rows', type=int, default=1500)
    parser.add_argument('--csv-columns', type=int, default=8)
    parser.add_argument('--production-rows', type=int, default=1500)
    parser.add_argument('--production-metrics', type=int, default=3)
    parser.add_argument('--large-csv-rows', type=int, default=1_000_000)
    parser.add_argument('--large-csv-columns', type=int, default=20)
    parser.add_argument('--large-csv-search', default='P-00')
    parser.add_argument('--large-csv-materialize-columns', type=int, default=5)
    parser.add_argument('--fit-group-count', type=int, default=40)
    parser.add_argument('--fit-sample-size', type=int, default=120)
    parser.add_argument('--fit-monte-carlo-samples', type=int, default=250)
    parser.add_argument('--fit-gof-max-sample-size', type=int, default=2000)
    parser.add_argument('--group-preprocess-groups', type=int, default=48)
    parser.add_argument('--group-preprocess-values', type=int, default=20000)
    parser.add_argument('--cmm-bench-report-count', type=int, default=180)
    parser.add_argument('--cmm-bench-measurements-per-report', type=int, default=140)
    parser.add_argument('--chart-render-iterations', type=int, default=5)
    parser.add_argument('--chart-render-histogram-points', type=int, default=4000)
    parser.add_argument('--chart-type-benchmark-iterations', type=int, default=3)
    parser.add_argument(
        '--chart-type-benchmark-chart',
        choices=('distribution', 'iqr', 'trend', 'histogram'),
        default='distribution',
        help='Chart type used by chart_type_native_compare scenario.',
    )
    parser.add_argument('--enforce-chart-render-guardrail', action='store_true')
    parser.add_argument('--chart-render-max-median-regression-ratio', type=float, default=2.5)
    parser.add_argument(
        '--cmm-benchmark-mode',
        choices=('parse', 'stages'),
        default='parse',
        help='CMM backend benchmark mode: parse-only comparison or isolated parse/normalize/persist stages.',
    )
    parser.add_argument('--enforce-cmm-parser-guardrail', action='store_true')
    parser.add_argument('--cmm-native-min-speedup-ratio', type=float, default=1.0)
    parser.add_argument('--cmm-native-min-usage-rate', type=float, default=0.95)
    parser.add_argument(
        '--scenarios',
        nargs='+',
        choices=(
            'pdf_parse_path',
            'excel_export_path',
            'excel_export_write_vs_shape_path',
            'excel_export_high_header_cardinality_compare',
            'csv_summary_export_path',
            'production_dashboard_workbook_path',
            'csv_summary_large_data_probe',
            'distribution_fit_monte_carlo_path',
            'distribution_fit_gof_policy_compare',
            'group_preprocess_mixed_types_compare',
            'cmm_parser_backend_compare',
            'chart_render_budget_path',
            'chart_type_native_compare',
        ),
        help='Optional list of scenario keys to run. Defaults to running all scenarios.',
    )
    args = parser.parse_args()

    scenario_runners = {
        'pdf_parse_path': lambda temp_path: benchmark_parse_path(temp_path, pdf_count=args.pdf_count),
        'excel_export_path': lambda temp_path: benchmark_excel_export_path(
            temp_path, report_count=args.report_count, headers_per_report=args.headers_per_report
        ),
        'excel_export_write_vs_shape_path': lambda temp_path: benchmark_export_write_vs_shape_path(
            temp_path, report_count=args.report_count, headers_per_report=args.headers_per_report
        ),
        'excel_export_high_header_cardinality_compare': lambda temp_path: benchmark_export_high_header_cardinality_path(
            temp_path,
            report_count=max(args.report_count, 100),
            headers_per_report=max(args.headers_per_report, 64),
        ),
        'csv_summary_export_path': lambda temp_path: benchmark_csv_summary_path(
            temp_path, row_count=args.csv_rows, data_columns=args.csv_columns
        ),
        'production_dashboard_workbook_path': lambda temp_path: benchmark_production_dashboard_workbook_path(
            temp_path,
            row_count=max(1, args.production_rows),
            metric_count=max(1, args.production_metrics),
        ),
        'csv_summary_large_data_probe': lambda temp_path: benchmark_csv_summary_large_data_probe(
            temp_path,
            row_count=max(1, args.large_csv_rows),
            data_columns=max(1, args.large_csv_columns),
            search_text=args.large_csv_search,
            materialize_columns=max(1, args.large_csv_materialize_columns),
        ),
        'distribution_fit_monte_carlo_path': lambda temp_path: benchmark_distribution_fit_monte_carlo_path(
            temp_path,
            group_count=args.fit_group_count,
            sample_size=args.fit_sample_size,
            monte_carlo_samples=max(1, args.fit_monte_carlo_samples),
        ),
        'distribution_fit_gof_policy_compare': lambda temp_path: benchmark_distribution_fit_gof_policy_compare(
            temp_path,
            group_count=args.fit_group_count,
            sample_size=args.fit_sample_size,
            monte_carlo_samples=max(1, args.fit_monte_carlo_samples),
            gof_max_sample_size=max(3, args.fit_gof_max_sample_size),
        ),
        'group_preprocess_mixed_types_compare': lambda temp_path: benchmark_group_preprocess_mixed_types_path(
            temp_path,
            group_count=max(1, args.group_preprocess_groups),
            values_per_group=max(10, args.group_preprocess_values),
        ),
        'cmm_parser_backend_compare': lambda temp_path: benchmark_cmm_parser_backend_compare(
            temp_path,
            report_count=max(1, args.cmm_bench_report_count),
            measurements_per_report=max(1, args.cmm_bench_measurements_per_report),
            benchmark_mode=args.cmm_benchmark_mode,
        ),
        'chart_render_budget_path': lambda temp_path: benchmark_chart_render_budget_path(
            temp_path,
            iterations=max(1, args.chart_render_iterations),
            histogram_points=max(32, args.chart_render_histogram_points),
        ),
        'chart_type_native_compare': lambda temp_path: benchmark_chart_type_native_compare_path(
            temp_path,
            chart_type=args.chart_type_benchmark_chart,
            iterations=max(1, args.chart_type_benchmark_iterations),
        ),
    }
    manual_scenarios = {'csv_summary_large_data_probe'}
    selected_scenarios = args.scenarios or [
        scenario for scenario in scenario_runners if scenario not in manual_scenarios
    ]

    with tempfile.TemporaryDirectory(prefix='metroliza-bench-') as temp_dir:
        temp_path = Path(temp_dir)
        results = [scenario_runners[scenario](temp_path) for scenario in selected_scenarios]

    payload = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'config': vars(args),
        'results': [asdict(result) for result in results],
    }
    payload['summary'] = build_benchmark_run_summary(payload['results'])
    json_path, csv_path = _write_outputs(Path(args.output_dir), payload)

    print(f'Benchmark JSON: {json_path}')
    print(f'Benchmark CSV: {csv_path}')

    if args.enforce_cmm_parser_guardrail:
        cmm = next((item for item in payload['results'] if item['scenario'] == 'cmm_parser_backend_compare'), None)
        if cmm is None:
            raise RuntimeError('cmm_parser_backend_compare scenario missing from benchmark payload')

        native_available = int(cmm['input_metrics'].get('native_available', 0)) == 1
        if native_available:
            speedup_ratio = float(cmm['stage_timings_s'].get('native_speedup_ratio', 0.0))
            native_usage_rate = float(cmm['input_metrics'].get('native_parse_backend_rate', 0.0))
            if speedup_ratio < args.cmm_native_min_speedup_ratio:
                raise RuntimeError(
                    f'Native parser speedup ratio {speedup_ratio:.3f} below threshold {args.cmm_native_min_speedup_ratio:.3f}'
                )
            if native_usage_rate < args.cmm_native_min_usage_rate:
                raise RuntimeError(
                    f'Native parser usage rate {native_usage_rate:.3f} below threshold {args.cmm_native_min_usage_rate:.3f}'
                )
            print(
                f"CMM parser guardrail passed: native_speedup_ratio={speedup_ratio:.3f}, "
                f"native_usage_rate={native_usage_rate:.3f}"
            )
        else:
            print('CMM parser guardrail skipped: native parser extension unavailable in this environment.')

    if args.enforce_chart_render_guardrail:
        chart_budget = next((item for item in payload['results'] if item['scenario'] == 'chart_render_budget_path'), None)
        if chart_budget is None:
            raise RuntimeError('chart_render_budget_path scenario missing from benchmark payload')
        native_available = int(chart_budget['input_metrics'].get('histogram_native_available', 0)) == 1
        if native_available:
            regression_ratio = float(chart_budget['stage_timings_s'].get('histogram_branch_regression_ratio', 0.0))
            if regression_ratio > args.chart_render_max_median_regression_ratio:
                raise RuntimeError(
                    f'Chart render median regression ratio {regression_ratio:.3f} exceeded threshold {args.chart_render_max_median_regression_ratio:.3f}'
                )
            print(
                f"Chart render guardrail passed: histogram_branch_regression_ratio={regression_ratio:.3f}"
            )
        else:
            print('Chart render guardrail skipped: native chart extension unavailable in this environment.')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
