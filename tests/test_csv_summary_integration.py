import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

import pandas as pd

_PYQT_MODULE_NAMES = ('PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets')
_ORIGINAL_PYQT_MODULES = {name: sys.modules.get(name) for name in _PYQT_MODULE_NAMES}

try:
    import PyQt6.QtCore  # noqa: F401
    import PyQt6.QtGui  # noqa: F401
    import PyQt6.QtWidgets  # noqa: F401
except ImportError:  # pragma: no cover - exercised only when PyQt6 is unavailable
    _USE_QT_STUBS = True
else:
    _USE_QT_STUBS = False

if _USE_QT_STUBS:
    # Minimal Qt stubs so CSVSummaryDialog can be imported in headless CI.
    qtcore_stub = types.ModuleType('PyQt6.QtCore')


    class _DummyQThread:
        def __init__(self, *args, **kwargs):
            pass


    class _DummySignal:
        def emit(self, *args, **kwargs):
            return None


    def _dummy_pyqt_signal(*args, **kwargs):
        return _DummySignal()


    qtcore_stub.Qt = object()
    qtcore_stub.pyqtSlot = lambda *args, **kwargs: (lambda f: f)
    qtcore_stub.QThread = _DummyQThread
    qtcore_stub.pyqtSignal = _dummy_pyqt_signal
    qtcore_stub.QTemporaryFile = type('QTemporaryFile', (), {})
    qtcore_stub.QSize = type('QSize', (), {})
    qtcore_stub.QByteArray = type('QByteArray', (), {})
    qtcore_stub.QBuffer = type('QBuffer', (), {})
    qtcore_stub.QIODevice = type('QIODevice', (), {})
    sys.modules['PyQt6.QtCore'] = qtcore_stub

    qtgui_stub = types.ModuleType('PyQt6.QtGui')
    qtgui_stub.QMovie = type('QMovie', (), {})
    qtgui_stub.QImageReader = type('QImageReader', (), {})
    sys.modules['PyQt6.QtGui'] = qtgui_stub

    qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')


    class _DummyQFileDialog:
        class Option:
            ReadOnly = 1

        @staticmethod
        def getOpenFileName(*args, **kwargs):
            return "", ""

        @staticmethod
        def getSaveFileName(*args, **kwargs):
            return "", ""


    class _DummyQMessageBox:
        class StandardButton:
            Yes = 1
            No = 2

        @staticmethod
        def warning(*args, **kwargs):
            return None

        @staticmethod
        def information(*args, **kwargs):
            return None

        @staticmethod
        def critical(*args, **kwargs):
            return None

        @staticmethod
        def question(*args, **kwargs):
            return _DummyQMessageBox.StandardButton.No


    for name in [
        'QApplication',
        'QDialog',
        'QFrame',
        'QGridLayout',
        'QVBoxLayout',
        'QPushButton',
        'QListWidget',
        'QHBoxLayout',
        'QProgressBar',
        'QLabel',
        'QLineEdit',
        'QSizePolicy',
        'QTableWidget',
        'QTableWidgetItem',
        'QHeaderView',
        'QCheckBox',
        'QWidget',
    ]:
        setattr(qtwidgets_stub, name, type(name, (), {}))
    qtwidgets_stub.QFileDialog = _DummyQFileDialog
    qtwidgets_stub.QMessageBox = _DummyQMessageBox
    sys.modules['PyQt6.QtWidgets'] = qtwidgets_stub

import modules.csv_summary_dialog as csv_summary_dialog_module  # noqa: E402
from modules.csv_summary_dialog import CSVSummaryDialog, DataProcessingThread  # noqa: E402
from modules.csv_summary_utils import build_default_plot_toggles  # noqa: E402

if _USE_QT_STUBS:
    for module_name, original_module in _ORIGINAL_PYQT_MODULES.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


class CsvSummaryIntegrationTests(unittest.TestCase):
    def test_chart_executor_is_reused_within_run(self):
        worker = DataProcessingThread(
            selected_indexes=['PART'],
            selected_data_columns=['LENGTH'],
            input_file='input.csv',
            output_file='output.xlsx',
            data_frame=pd.DataFrame({'PART': [], 'LENGTH': []}),
            csv_config={'enable_chart_multiprocessing': True},
        )

        created_executors = []
        original_executor_cls = DataProcessingThread._ensure_chart_executor.__globals__['ProcessPoolExecutor']

        class _FakeFuture:
            def __init__(self, value):
                self._value = value

            def result(self):
                return self._value

        class _FakeExecutor:
            def __init__(self, max_workers):
                self.max_workers = max_workers
                self.submit_calls = 0
                self.shutdown_calls = 0
                created_executors.append(self)

            def submit(self, fn, *args, **kwargs):
                self.submit_calls += 1
                return _FakeFuture(fn(*args, **kwargs))

            def shutdown(self, wait=True, cancel_futures=True):
                self.shutdown_calls += 1

        DataProcessingThread._ensure_chart_executor.__globals__['ProcessPoolExecutor'] = _FakeExecutor
        try:
            data = pd.DataFrame({'PART': [f'P{i}' for i in range(3000)], 'LENGTH': [float(i) for i in range(3000)]})

            with tempfile.TemporaryDirectory() as tmpdir:
                worker.output_file = str(Path(tmpdir) / 'reuse.xlsx')
                worker.data_frame = data
                worker.selected_data_columns = ['LENGTH']
                worker.plot_toggles = {'LENGTH': {'histogram': True, 'boxplot': True}}
                worker.run()
        finally:
            DataProcessingThread._ensure_chart_executor.__globals__['ProcessPoolExecutor'] = original_executor_cls

        self.assertEqual(len(created_executors), 1)
        self.assertEqual(created_executors[0].submit_calls, 2)
        self.assertEqual(created_executors[0].shutdown_calls, 1)

    def test_eta_format_includes_minutes_seconds_and_hours(self):
        self.assertEqual(DataProcessingThread._format_eta(None), 'ETA --')
        self.assertEqual(DataProcessingThread._format_eta(59.4), 'ETA 0:59')
        self.assertEqual(DataProcessingThread._format_eta(61.2), 'ETA 1:01')
        self.assertEqual(DataProcessingThread._format_eta(3661.0), 'ETA 1:01:01')

    def test_eta_estimation_uses_processed_columns(self):
        original_perf_counter = DataProcessingThread._estimate_eta_seconds.__globals__['time'].perf_counter
        try:
            DataProcessingThread._estimate_eta_seconds.__globals__['time'].perf_counter = lambda: 25.0
            estimate = DataProcessingThread._estimate_eta_seconds(
                DataProcessingThread,
                start_time=5.0,
                processed_columns=2,
                total_columns=5,
            )
        finally:
            DataProcessingThread._estimate_eta_seconds.__globals__['time'].perf_counter = original_perf_counter

        self.assertEqual(estimate, 30.0)

    def test_csv_summary_export_contains_overview_and_detail_sheet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'summary.xlsx'
            df = pd.DataFrame({'PART': ['A', 'B', 'C'], 'LENGTH': [10.0, 10.1, 10.2]})

            worker = DataProcessingThread(
                selected_indexes=['PART'],
                selected_data_columns=['LENGTH'],
                input_file='input.csv',
                output_file=str(output_file),
                data_frame=df,
                csv_config={'delimiter': ',', 'decimal': '.'},
                column_spec_limits={'LENGTH': {'nom': 10.0, 'usl': 0.5, 'lsl': -0.5}},
                plot_toggles=build_default_plot_toggles(['LENGTH'], full_report=False),
            )
            worker.run()

            self.assertTrue(output_file.exists())
            with zipfile.ZipFile(output_file, 'r') as workbook_zip:
                workbook_xml = workbook_zip.read('xl/workbook.xml').decode('utf-8')

            self.assertIn('CSV_SUMMARY', workbook_xml)
            self.assertIn('LENGTH', workbook_xml)





    def test_csv_summary_boxplot_chart_uses_box_whisker_emulation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'boxplot.xlsx'
            df = pd.DataFrame({'PART': ['A', 'B', 'C', 'D', 'E'], 'LENGTH': [9.8, 10.0, 10.1, 10.2, 10.4]})

            worker = DataProcessingThread(
                selected_indexes=['PART'],
                selected_data_columns=['LENGTH'],
                input_file='input.csv',
                output_file=str(output_file),
                data_frame=df,
                plot_toggles={'LENGTH': {'histogram': False, 'boxplot': True}},
            )
            worker.run()

            self.assertTrue(output_file.exists())
            with zipfile.ZipFile(output_file, 'r') as workbook_zip:
                chart_files = sorted(name for name in workbook_zip.namelist() if name.startswith('xl/charts/chart'))
                chart_payloads = [workbook_zip.read(name).decode('utf-8') for name in chart_files]

            self.assertTrue(any('<c:barChart>' in payload for payload in chart_payloads))
            self.assertTrue(any('<c:errBars>' in payload for payload in chart_payloads))
            self.assertTrue(any('interquartile range' in payload for payload in chart_payloads))
            self.assertTrue(any('boxplot</a:t>' in payload for payload in chart_payloads))
            self.assertTrue(all('boxplot profile' not in payload for payload in chart_payloads))

    def test_csv_summary_canceled_run_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'canceled.xlsx'
            df = pd.DataFrame({'PART': ['A', 'B', 'C'], 'LENGTH': [10.0, 10.1, 10.2]})

            worker = DataProcessingThread(
                selected_indexes=['PART'],
                selected_data_columns=['LENGTH'],
                input_file='input.csv',
                output_file=str(output_file),
                data_frame=df,
            )
            worker.cancel()
            worker.run()

            self.assertFalse(output_file.exists())

    def test_csv_summary_summary_only_mode_skips_detail_sheets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / 'summary_only.xlsx'
            df = pd.DataFrame({'PART': ['A', 'B', 'C'], 'LENGTH': [10.0, 10.1, 10.2]})

            worker = DataProcessingThread(
                selected_indexes=['PART'],
                selected_data_columns=['LENGTH'],
                input_file='input.csv',
                output_file=str(output_file),
                data_frame=df,
                summary_only=True,
            )
            worker.run()

            self.assertTrue(output_file.exists())
            with zipfile.ZipFile(output_file, 'r') as workbook_zip:
                workbook_xml = workbook_zip.read('xl/workbook.xml').decode('utf-8')

            self.assertIn('CSV_SUMMARY', workbook_xml)
            self.assertNotIn('LENGTH', workbook_xml)

if __name__ == '__main__':
    unittest.main()


class _FormulaCaptureWorksheet:
    def __init__(self):
        self.formulas = {}

    def write(self, row, col, value):
        return None

    def write_formula(self, row, col, formula):
        self.formulas[(row, col)] = formula


class CsvSummaryFormulaTests(unittest.TestCase):
    def test_write_summary_data_uses_single_sided_capability_for_near_zero_nom_and_lsl(self):
        worker = DataProcessingThread(
            selected_indexes=['PART'],
            selected_data_columns=['LENGTH'],
            input_file='input.csv',
            output_file='output.xlsx',
            data_frame=pd.DataFrame({'PART': ['A', 'B'], 'LENGTH': [1.0, 1.1]}),
        )
        worksheet = _FormulaCaptureWorksheet()
        selected_data = pd.DataFrame({'PART': ['A', 'B'], 'LENGTH': [1.0, 1.1]})

        worker.write_summary_data(
            worksheet,
            data_column='LENGTH',
            selected_data=selected_data,
            spec_limits={'nom': 1e-13, 'usl': 1.0, 'lsl': -1e-13},
        )

        cp_formula = worksheet.formulas[(7, selected_data.shape[1] + 3)]
        cpk_formula = worksheet.formulas[(8, selected_data.shape[1] + 3)]

        self.assertEqual(cp_formula, '="N/A"')
        self.assertIn('ROUND((', cpk_formula)
        self.assertNotIn('MIN(', cpk_formula)


class _FakeButton:
    def __init__(self, enabled=False):
        self._enabled = bool(enabled)

    def setEnabled(self, value):
        self._enabled = bool(value)

    def isEnabled(self):
        return self._enabled


class _FakeCheckbox:
    def __init__(self, checked=False):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setChecked(self, value):
        self._checked = bool(value)


class _FakeLabel:
    def __init__(self, value=''):
        self.value = value

    def setText(self, value):
        self.value = value

    def text(self):
        return self.value


class _FakePathField(_FakeLabel):
    def __init__(self):
        super().__init__("")
        self.tooltip = ""

    def setToolTip(self, value):
        self.tooltip = value


class CsvSummaryDialogStateTests(unittest.TestCase):
    def _build_dialog_state(self):
        dialog = CSVSummaryDialog.__new__(CSVSummaryDialog)
        dialog.input_file = ""
        dialog.output_file = ""
        dialog.data_frame = None
        dialog.selected_indexes = []
        dialog.selected_data_columns = []
        dialog.column_spec_limits = {}
        dialog.plot_toggles = {}
        dialog.filter_button = _FakeButton()
        dialog.spec_limits_button = _FakeButton()
        dialog.output_button = _FakeButton()
        dialog.start_button = _FakeButton()
        dialog.input_path_field = _FakePathField()
        dialog.output_path_field = _FakePathField()
        dialog.columns_status_label = _FakeLabel()
        dialog.spec_limits_status_label = _FakeLabel()
        dialog.plot_options_status_label = _FakeLabel()
        dialog.readiness_label = _FakeLabel()
        dialog.include_extended_plots = _FakeCheckbox(True)
        dialog.summary_only_checkbox = _FakeCheckbox(False)
        return dialog

    def test_dialog_source_uses_create_summary_and_elastic_sizing(self):
        source = Path(csv_summary_dialog_module.__file__).read_text(encoding='utf-8')
        self.assertIn('QPushButton("Create Summary")', source)
        self.assertIn('configure_window_size(self, minimum=(760, 460), initial=(900, 620))', source)
        self.assertNotIn('setGeometry(', source)
        self.assertNotIn('section_label("Summary configuration")', source)
        self.assertIn('footer_actions.addStretch(1)', source)

    def test_sync_ui_state_blocks_when_output_or_limits_missing_and_unblocks_when_ready(self):
        dialog = self._build_dialog_state()
        dialog._sync_ui_state()

        self.assertFalse(dialog.start_button.isEnabled())
        self.assertEqual("Select an input CSV to begin.", dialog.readiness_label.text())

        dialog.data_frame = object()
        dialog.input_file = '/tmp/input.csv'
        dialog.selected_indexes = ['PART']
        dialog.selected_data_columns = ['LENGTH']
        dialog.column_spec_limits = {'LENGTH': {'nom': 10.0, 'usl': 0.5, 'lsl': 0.6}}
        dialog._sync_ui_state()

        self.assertFalse(dialog.start_button.isEnabled())
        self.assertEqual("Fix invalid spec limits: expected LSL <= NOM <= USL.", dialog.readiness_label.text())

        dialog.column_spec_limits = {'LENGTH': {'nom': 10.0, 'usl': 0.5, 'lsl': -0.5}}
        dialog.output_file = '/tmp/output.xlsx'
        dialog._sync_ui_state()

        self.assertTrue(dialog.start_button.isEnabled())
        self.assertEqual("Ready to create CSV summary workbook.", dialog.readiness_label.text())

    def test_handle_input_button_rejects_non_csv_path_without_mutating_input(self):
        dialog = CSVSummaryDialog.__new__(CSVSummaryDialog)
        dialog.input_file = ""

        original_get_open = csv_summary_dialog_module.QFileDialog.getOpenFileName
        original_warning = csv_summary_dialog_module.QMessageBox.warning
        warnings = []
        try:
            csv_summary_dialog_module.QFileDialog.getOpenFileName = lambda *args, **kwargs: ("/tmp/report.txt", "")
            csv_summary_dialog_module.QMessageBox.warning = lambda *args: warnings.append(args[1:3])
            dialog.handle_input_button()
        finally:
            csv_summary_dialog_module.QFileDialog.getOpenFileName = original_get_open
            csv_summary_dialog_module.QMessageBox.warning = original_warning

        self.assertEqual(dialog.input_file, "")
        self.assertEqual(warnings, [("Invalid input file", "Please select a .csv input file.")])

    def test_handle_output_button_normalizes_extension_to_xlsx(self):
        dialog = CSVSummaryDialog.__new__(CSVSummaryDialog)
        dialog.input_file = "/tmp/input.csv"
        dialog.output_file = ""
        dialog._sync_ui_state = lambda: None

        original_get_save = csv_summary_dialog_module.QFileDialog.getSaveFileName
        try:
            csv_summary_dialog_module.QFileDialog.getSaveFileName = lambda *args, **kwargs: ("/tmp/report.out", "")
            dialog.handle_output_button()
        finally:
            csv_summary_dialog_module.QFileDialog.getSaveFileName = original_get_save

        self.assertEqual(dialog.output_file, "/tmp/report.xlsx")

    def test_handle_output_button_normalizes_uppercase_xlsx_suffix(self):
        dialog = CSVSummaryDialog.__new__(CSVSummaryDialog)
        dialog.input_file = "/tmp/input.csv"
        dialog.output_file = ""
        dialog._sync_ui_state = lambda: None

        original_get_save = csv_summary_dialog_module.QFileDialog.getSaveFileName
        try:
            csv_summary_dialog_module.QFileDialog.getSaveFileName = lambda *args, **kwargs: ("/tmp/report.XLSX", "")
            dialog.handle_output_button()
        finally:
            csv_summary_dialog_module.QFileDialog.getSaveFileName = original_get_save

        self.assertEqual(dialog.output_file, "/tmp/report.xlsx")

    def test_handle_clear_presets_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / ".csv_summary_presets.json"
            preset_path.write_text("{}", encoding="utf-8")

            dialog = CSVSummaryDialog.__new__(CSVSummaryDialog)
            dialog.preset_path = preset_path

            original_question = csv_summary_dialog_module.QMessageBox.question
            original_info = csv_summary_dialog_module.QMessageBox.information
            info_calls = []
            try:
                csv_summary_dialog_module.QMessageBox.question = lambda *args: csv_summary_dialog_module.QMessageBox.StandardButton.No
                csv_summary_dialog_module.QMessageBox.information = lambda *args: info_calls.append(args[1:3])
                dialog.handle_clear_presets_button()
                self.assertTrue(preset_path.exists())

                csv_summary_dialog_module.QMessageBox.question = lambda *args: csv_summary_dialog_module.QMessageBox.StandardButton.Yes
                dialog.handle_clear_presets_button()
            finally:
                csv_summary_dialog_module.QMessageBox.question = original_question
                csv_summary_dialog_module.QMessageBox.information = original_info

            self.assertFalse(preset_path.exists())
            self.assertIn(("Presets cleared", "Saved CSV presets were removed."), info_calls)

    def test_on_data_processing_finished_distinguishes_failure_from_cancellation(self):
        class _FakeLoadingDialog:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        dialog = CSVSummaryDialog.__new__(CSVSummaryDialog)
        dialog.loading_dialog = _FakeLoadingDialog()
        dialog.worker_thread = type("Worker", (), {"canceled": True})()
        dialog.output_file = "/tmp/out.xlsx"

        original_info = csv_summary_dialog_module.QMessageBox.information
        original_critical = csv_summary_dialog_module.QMessageBox.critical
        info_calls = []
        critical_calls = []
        try:
            csv_summary_dialog_module.QMessageBox.information = lambda *args: info_calls.append(args[1:3])
            csv_summary_dialog_module.QMessageBox.critical = lambda *args: critical_calls.append(args[1:3])

            dialog._worker_failed = True
            dialog.on_data_processing_finished()
            self.assertIn(("Processing failed", "CSV summary export failed. Review the log for details and try again."), critical_calls)

            dialog.loading_dialog = _FakeLoadingDialog()
            dialog.worker_thread = type("Worker", (), {"canceled": True})()
            dialog._worker_failed = False
            dialog.on_data_processing_finished()
        finally:
            csv_summary_dialog_module.QMessageBox.information = original_info
            csv_summary_dialog_module.QMessageBox.critical = original_critical

        self.assertIn(("Processing canceled", "Processing has been canceled"), info_calls)
