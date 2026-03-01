#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import importlib.machinery
import sys
import tempfile
import time
import types
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_headless_stubs() -> None:
    custom_logger_stub = types.ModuleType('modules.CustomLogger')

    class _NoopLogger:
        def __init__(self, *args, **kwargs):
            return None

    def _noop_handle_exception(*args, **kwargs):
        return None

    custom_logger_stub.CustomLogger = _NoopLogger
    custom_logger_stub.handle_exception = _noop_handle_exception
    custom_logger_stub.LOG_ONLY = object()
    sys.modules.setdefault('modules.CustomLogger', custom_logger_stub)

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

    qtcore_stub.QCoreApplication = _DummyCoreApp
    qtcore_stub.QThread = _DummyThread
    qtcore_stub.pyqtSignal = _dummy_signal
    qtcore_stub.pyqtSlot = lambda *a, **k: (lambda func: func)
    qtcore_stub.Qt = object()
    qtcore_stub.QTemporaryFile = _DummyTempFile
    qtcore_stub.QSize = object

    for attr in (
        'QDialog', 'QVBoxLayout', 'QPushButton', 'QFileDialog', 'QListWidget', 'QMessageBox',
        'QHBoxLayout', 'QProgressBar', 'QLabel', 'QTableWidget', 'QTableWidgetItem',
        'QHeaderView', 'QCheckBox'
    ):
        setattr(qtwidgets_stub, attr, type(attr, (), {}))

    qtgui_stub.QMovie = type('QMovie', (), {})

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


def _create_pdf_fixture_dir(base_dir: Path, count: int) -> Path:
    fixture_dir = base_dir / "pdf_reports"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        file_name = f"ABC12{i:03d}_2024-01-{(i % 28) + 1:02d}_{i:03d}.pdf"
        (fixture_dir / file_name).write_bytes(b"%PDF-1.4\n% benchmark placeholder\n")
    return fixture_dir


def _create_export_db_fixture(db_path: Path, *, report_count: int, headers_per_report: int) -> dict[str, int]:
    from modules.db import execute_with_retry

    execute_with_retry(
        str(db_path),
        'CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REFERENCE TEXT, FILELOC TEXT, FILENAME TEXT, DATE TEXT, SAMPLE_NUMBER TEXT)',
    )
    execute_with_retry(
        str(db_path),
        'CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REPORT_ID INTEGER, AX TEXT, NOM REAL, "+TOL" REAL, "-TOL" REAL, BONUS REAL, MEAS REAL, DEV REAL, OUTTOL INTEGER, HEADER TEXT)',
    )

    rng = np.random.default_rng(42)
    total_measurement_rows = 0

    for report_index in range(1, report_count + 1):
        reference = f"REF-{((report_index - 1) % 4) + 1}"
        sample_number = str(report_index)
        execute_with_retry(
            str(db_path),
            'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
            (
                reference,
                '/fixtures/reports',
                f'{reference}_2024-01-{(report_index % 28) + 1:02d}_{sample_number}.pdf',
                f'2024-01-{(report_index % 28) + 1:02d}',
                sample_number,
            ),
        )
        report_id = execute_with_retry(str(db_path), 'SELECT MAX(ID) FROM REPORTS')[0][0]

        for header_idx in range(1, headers_per_report + 1):
            nominal = 10.0 + (header_idx * 0.1)
            measurement = float(nominal + rng.normal(0.0, 0.12))
            dev = measurement - nominal
            outtol = int(abs(dev) > 0.5)
            execute_with_retry(
                str(db_path),
                'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (report_id, 'X', nominal, 0.5, -0.5, 0.0, measurement, dev, outtol, f'FEATURE_{header_idx:02d}'),
            )
            total_measurement_rows += 1

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


def benchmark_parse_path(temp_dir: Path, pdf_count: int) -> ScenarioResult:
    from modules.CMMReportParser import CMMReportParser
    from modules.ParseReportsThread import ParseReportsThread, parse_new_reports
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
    parse_result = parse_new_reports(
        report_paths=reports,
        report_fingerprints=fingerprints,
        parser_factory=lambda report: CMMReportParser(str(report), str(db_path)),
        persist_report=lambda _parser: None,
    )
    parse_loop_s = time.perf_counter() - parse_start
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
        },
    )


def benchmark_excel_export_path(temp_dir: Path, report_count: int, headers_per_report: int) -> ScenarioResult:
    from modules.ExportDataThread import ExportDataThread
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

    import modules.ExportDataThread as export_module
    original_insert_chart = export_module.insert_measurement_chart
    chart_seconds = 0.0

    def timed_insert_chart(*args, **kwargs):
        nonlocal chart_seconds
        chart_start = time.perf_counter()
        try:
            return original_insert_chart(*args, **kwargs)
        finally:
            chart_seconds += time.perf_counter() - chart_start

    export_module.insert_measurement_chart = timed_insert_chart
    total_run_start = time.perf_counter()
    try:
        completed = thread.get_export_backend().run(thread)
    finally:
        export_module.insert_measurement_chart = original_insert_chart
    total_run_s = time.perf_counter() - total_run_start

    if not completed:
        raise RuntimeError('Excel export benchmark did not complete successfully.')

    workbook_write_s = max(0.0, total_run_s - chart_seconds)

    return ScenarioResult(
        scenario='excel_export_path',
        wall_time_s=data_load_s + groupby_stats_s + total_run_s,
        stage_timings_s={
            'data_load': data_load_s,
            'groupby_stats': groupby_stats_s,
            'chart_generation': chart_seconds,
            'workbook_write': workbook_write_s,
        },
        input_metrics={
            'rows': fixture_metrics['measurement_rows'],
            'headers': fixture_metrics['headers'],
            'chart_count': fixture_metrics['headers'] * 2,
        },
    )


def benchmark_export_high_header_cardinality_path(temp_dir: Path, report_count: int, headers_per_report: int) -> ScenarioResult:
    from modules.ExportDataThread import ExportDataThread
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
    for (_reference, _header), group in grouped:
        sampled = thread._downsample_frame(group, thread._chart_sample_limit())
        distribution_key = 'SAMPLE_NUMBER'
        thread._build_violin_payload(sampled, distribution_key, thread.violin_plot_min_samplesize)
        build_histogram_density_curve_payload(sampled['MEAS'], point_count=100)
        build_trend_plot_payload(sampled)
    before_s = time.perf_counter() - legacy_start

    policy = resolve_chart_sampling_policy(density_mode='full')
    new_start = time.perf_counter()
    for (_reference, _header), group in grouped:
        sampled_distribution = sample_frame_for_chart(group, 'distribution', policy)
        sampled_histogram = sample_frame_for_chart(group, 'histogram', policy)
        sampled_trend = sample_frame_for_chart(group, 'trend', policy)
        distribution_key = 'SAMPLE_NUMBER'
        build_violin_payload_vectorized(sampled_distribution, distribution_key, thread.violin_plot_min_samplesize)
        build_histogram_density_curve_payload(sampled_histogram['MEAS'], point_count=100)
        build_trend_plot_payload(sampled_trend)
    after_s = time.perf_counter() - new_start

    return ScenarioResult(
        scenario='excel_export_high_header_cardinality_compare',
        wall_time_s=before_s + after_s,
        stage_timings_s={
            'before_refactor': before_s,
            'after_refactor': after_s,
            'speedup_ratio': (before_s / after_s) if after_s > 0 else 0.0,
        },
        input_metrics={
            'rows': fixture_metrics['measurement_rows'],
            'headers': fixture_metrics['headers'],
            'chart_count': fixture_metrics['headers'] * 4,
        },
    )


def benchmark_csv_summary_path(temp_dir: Path, row_count: int, data_columns: int) -> ScenarioResult:
    from modules.CSVSummaryDialog import DataProcessingThread, load_csv_with_fallbacks

    class BenchmarkCSVThread(DataProcessingThread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.chart_seconds = 0.0

        def add_xy_chart(self, worksheet, data_column, col, selected_data, writer, sheet_name):
            start = time.perf_counter()
            try:
                return super().add_xy_chart(worksheet, data_column, col, selected_data, writer, sheet_name)
            finally:
                self.chart_seconds += time.perf_counter() - start

        def add_histogram_chart(self, worksheet, data_column, col, selected_data, writer, sheet_name):
            start = time.perf_counter()
            try:
                return super().add_histogram_chart(worksheet, data_column, col, selected_data, writer, sheet_name)
            finally:
                self.chart_seconds += time.perf_counter() - start

        def add_boxplot_chart(self, worksheet, data_column, col, selected_data, writer, sheet_name):
            start = time.perf_counter()
            try:
                return super().add_boxplot_chart(worksheet, data_column, col, selected_data, writer, sheet_name)
            finally:
                self.chart_seconds += time.perf_counter() - start

    csv_path = temp_dir / 'summary_fixture.csv'
    output_xlsx = temp_dir / 'summary_output.xlsx'
    fixture_metrics = _create_csv_fixture(csv_path, row_count=row_count, data_columns=data_columns)

    load_start = time.perf_counter()
    loaded_df, csv_config = load_csv_with_fallbacks(str(csv_path))
    data_load_s = time.perf_counter() - load_start

    selected_indexes = ['PART']
    selected_data_columns = [f'DIM_{idx:02d}' for idx in range(1, data_columns + 1)]
    spec_limits = {
        column: {'nom': 25.0, 'usl': 0.5, 'lsl': -0.5}
        for column in selected_data_columns
    }

    import modules.CSVSummaryDialog as csv_module
    stats_seconds = 0.0
    workbook_write_seconds = 0.0
    original_stats = csv_module.compute_column_summary_stats
    original_to_excel = pd.DataFrame.to_excel

    def timed_stats(*args, **kwargs):
        nonlocal stats_seconds
        start = time.perf_counter()
        try:
            return original_stats(*args, **kwargs)
        finally:
            stats_seconds += time.perf_counter() - start

    def timed_to_excel(self, *args, **kwargs):
        nonlocal workbook_write_seconds
        start = time.perf_counter()
        try:
            return original_to_excel(self, *args, **kwargs)
        finally:
            workbook_write_seconds += time.perf_counter() - start

    csv_module.compute_column_summary_stats = timed_stats
    pd.DataFrame.to_excel = timed_to_excel

    worker = BenchmarkCSVThread(
        selected_indexes=selected_indexes,
        selected_data_columns=selected_data_columns,
        input_file=str(csv_path),
        output_file=str(output_xlsx),
        data_frame=loaded_df,
        csv_config=csv_config,
        column_spec_limits=spec_limits,
        summary_only=False,
    )

    run_start = time.perf_counter()
    try:
        worker.run()
    finally:
        csv_module.compute_column_summary_stats = original_stats
        pd.DataFrame.to_excel = original_to_excel

    run_s = time.perf_counter() - run_start
    if worker.canceled:
        raise RuntimeError('CSV summary benchmark ended in canceled state.')

    chart_s = worker.chart_seconds
    workbook_write_s = max(workbook_write_seconds, max(0.0, run_s - chart_s - stats_seconds))

    return ScenarioResult(
        scenario='csv_summary_export_path',
        wall_time_s=data_load_s + run_s,
        stage_timings_s={
            'data_load': data_load_s,
            'groupby_stats': stats_seconds,
            'chart_generation': chart_s,
            'workbook_write': workbook_write_s,
        },
        input_metrics={
            'rows': fixture_metrics['rows'],
            'headers': fixture_metrics['headers'],
            'chart_count': data_columns * 3,
        },
    )


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
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix='metroliza-bench-') as temp_dir:
        temp_path = Path(temp_dir)
        results = [
            benchmark_parse_path(temp_path, pdf_count=args.pdf_count),
            benchmark_excel_export_path(temp_path, report_count=args.report_count, headers_per_report=args.headers_per_report),
            benchmark_export_high_header_cardinality_path(
                temp_path,
                report_count=max(args.report_count, 100),
                headers_per_report=max(args.headers_per_report, 64),
            ),
            benchmark_csv_summary_path(temp_path, row_count=args.csv_rows, data_columns=args.csv_columns),
        ]

    payload = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'config': vars(args),
        'results': [asdict(result) for result in results],
    }
    json_path, csv_path = _write_outputs(Path(args.output_dir), payload)

    print(f'Benchmark JSON: {json_path}')
    print(f'Benchmark CSV: {csv_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
