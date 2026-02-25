import sys
import tempfile
import types
import unittest
from pathlib import Path

from modules.db import execute_with_retry  # noqa: E402


# Stubs for optional GUI/parser dependencies pulled in by thread modules.
qtcore_stub = types.ModuleType('PyQt6.QtCore')


class _DummyThread:
    def __init__(self, *args, **kwargs):
        pass


class _DummyCoreApp:
    @staticmethod
    def processEvents():
        return None


def _dummy_signal(*args, **kwargs):
    class _Signal:
        def emit(self, *a, **k):
            return None

    return _Signal()


qtcore_stub.QCoreApplication = _DummyCoreApp
qtcore_stub.QThread = _DummyThread
qtcore_stub.pyqtSignal = _dummy_signal
sys.modules['PyQt6.QtCore'] = qtcore_stub

custom_logger_stub = types.ModuleType('modules.CustomLogger')


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyLogger
sys.modules['modules.CustomLogger'] = custom_logger_stub

cmm_parser_stub = types.ModuleType('modules.CMMReportParser')
cmm_parser_stub.CMMReportParser = object
sys.modules['modules.CMMReportParser'] = cmm_parser_stub

from modules.ExportDataThread import build_export_dataframe, execute_export_query  # noqa: E402
from modules.ParseReportsThread import parse_new_reports  # noqa: E402


class _FakeParser:
    def __init__(self, report_name: str):
        self.FILE_PATH = report_name
        self.pdf_reference = 'REF-1'
        self.pdf_file_path = '/fake/reports'
        self.pdf_file_name = report_name
        self.pdf_date = '2024-01-01'
        self.pdf_sample_number = report_name.split('.')[0].split('_')[-1]


class TestPhase4ParseToExportHappyPath(unittest.TestCase):
    def test_parse_to_db_to_export_happy_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'metroliza.sqlite')
            execute_with_retry(
                db_path,
                'CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REFERENCE TEXT, FILELOC TEXT, FILENAME TEXT, DATE TEXT, SAMPLE_NUMBER TEXT)',
            )
            execute_with_retry(
                db_path,
                'CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REPORT_ID INTEGER, AX TEXT, NOM REAL, "+TOL" REAL, "-TOL" REAL, BONUS REAL, MEAS REAL, DEV REAL, OUTTOL INTEGER, HEADER TEXT)',
            )

            def persist_report(parser):
                execute_with_retry(
                    db_path,
                    'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                    (
                        parser.pdf_reference,
                        parser.pdf_file_path,
                        parser.pdf_file_name,
                        parser.pdf_date,
                        parser.pdf_sample_number,
                    ),
                )
                report_id = execute_with_retry(db_path, 'SELECT MAX(ID) FROM REPORTS')[0][0]
                execute_with_retry(
                    db_path,
                    'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (report_id, 'X', 10.0, 0.5, -0.5, 0.0, 10.1, 0.1, 0, 'FEATURE_1'),
                )

            parse_result = parse_new_reports(
                report_paths=['part_1.pdf', 'part_2.pdf'],
                report_fingerprints=set(),
                parser_factory=_FakeParser,
                persist_report=persist_report,
            )
            self.assertEqual(parse_result.total_files, 2)
            self.assertEqual(parse_result.parsed_files, 2)

            export_query = '''
                SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL",
                    MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS,
                    MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE,
                    REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE, REPORTS.SAMPLE_NUMBER
                FROM MEASUREMENTS
                JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
                ORDER BY REPORTS.ID
            '''

            rows, columns = execute_export_query(db_path, export_query)
            export_df = build_export_dataframe(rows, columns)

            self.assertEqual(len(export_df), 2)
            self.assertEqual(
                list(export_df.columns),
                [
                    'AX',
                    'NOM',
                    '+TOL',
                    '-TOL',
                    'BONUS',
                    'MEAS',
                    'DEV',
                    'OUTTOL',
                    'HEADER',
                    'REFERENCE',
                    'FILELOC',
                    'FILENAME',
                    'DATE',
                    'SAMPLE_NUMBER',
                ],
            )
            self.assertEqual(export_df['SAMPLE_NUMBER'].tolist(), ['1', '2'])
            self.assertEqual(export_df['MEAS'].tolist(), [10.1, 10.1])


if __name__ == '__main__':
    unittest.main()
