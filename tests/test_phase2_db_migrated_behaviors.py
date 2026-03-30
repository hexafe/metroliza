import tempfile
import importlib.machinery
import sqlite3
import unittest
from pathlib import Path
import sys
import types

qtcore_stub = types.ModuleType('PyQt6.QtCore')
qtcore_stub.Qt = type('Qt', (), {'ItemDataRole': type('ItemDataRole', (), {'UserRole': 0})})
sys.modules.setdefault('PyQt6.QtCore', qtcore_stub)

qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')
for name in [
    'QDialog',
    'QGridLayout',
    'QTableWidget',
    'QTableWidgetItem',
    'QPushButton',
    'QFileDialog',
    'QMessageBox',
]:
    setattr(qtwidgets_stub, name, type(name, (), {}))
sys.modules.setdefault('PyQt6.QtWidgets', qtwidgets_stub)
qtgui_stub = types.ModuleType('PyQt6.QtGui')
sys.modules.setdefault('PyQt6.QtGui', qtgui_stub)

custom_logger_stub = types.ModuleType('modules.custom_logger')
custom_logger_stub.CustomLogger = type('CustomLogger', (), {'__init__': lambda self, *args, **kwargs: None})
sys.modules.setdefault('modules.custom_logger', custom_logger_stub)

fitz_stub = types.ModuleType('fitz')
fitz_stub.__spec__ = importlib.machinery.ModuleSpec('fitz', loader=None)
sys.modules.setdefault('fitz', fitz_stub)
pymupdf_stub = types.ModuleType('pymupdf')
pymupdf_stub.__spec__ = importlib.machinery.ModuleSpec('pymupdf', loader=None)
sys.modules.setdefault('pymupdf', pymupdf_stub)

from modules.cmm_report_parser import CMMReportParser  # noqa: E402
from modules.cmm_schema import ensure_cmm_report_schema  # noqa: E402
from modules.modify_db import ModifyDB  # noqa: E402
from modules.db import execute_with_retry, run_transaction_with_retry  # noqa: E402


class TestPhase2DbMigratedBehaviors(unittest.TestCase):
    def test_modules_use_shared_db_helpers_without_direct_sqlite_connect(self):
        for module_path in Path('modules').glob('*.py'):
            if module_path.name == 'db.py':
                continue
            content = module_path.read_text(encoding='utf-8')
            self.assertNotIn('sqlite3.connect(', content, msg=f'direct sqlite connect found in {module_path}')

    def test_cmm_to_sqlite_remains_duplicate_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'reports.db')
            ensure_cmm_report_schema(db_path)
            parser = CMMReportParser('REF01_2024-01-02_123.pdf', db_path)
            parser.pdf_reference = 'REF01'
            parser.pdf_file_path = '/tmp/reports'
            parser.pdf_file_name = 'REF01_2024-01-02_123.pdf'
            parser.pdf_date = '2024-01-02'
            parser.pdf_sample_number = '123'
            parser.pdf_blocks_text = [
                (
                    ['HEADER A'],
                    [
                        ['1', 10.0, 0.1, -0.1, 0.0, 10.05, 0.05, 0.0],
                    ],
                )
            ]

            parser.to_sqlite()
            parser.to_sqlite()

            reports_count = execute_with_retry(db_path, 'SELECT COUNT(*) FROM REPORTS')[0][0]
            measurements_count = execute_with_retry(db_path, 'SELECT COUNT(*) FROM MEASUREMENTS')[0][0]

            self.assertEqual(reports_count, 1)
            self.assertEqual(measurements_count, 1)

    def test_cmm_schema_bootstrap_initializes_empty_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'bootstrap.db')

            ensure_cmm_report_schema(db_path)

            with sqlite3.connect(db_path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('REPORTS', 'MEASUREMENTS', 'CHARACTERISTIC_ALIASES')"
                    ).fetchall()
                }
                indexes = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
                    ).fetchall()
                }

            self.assertEqual(tables, {'REPORTS', 'MEASUREMENTS', 'CHARACTERISTIC_ALIASES'})
            self.assertIn('idx_reports_identity', indexes)
            self.assertIn('idx_measurements_report_header_ax', indexes)

    def test_cmm_to_sqlite_insert_behavior_unchanged_after_bootstrap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'insert_behavior.db')
            ensure_cmm_report_schema(db_path)

            parser = CMMReportParser('REF02_2024-01-03_321.pdf', db_path)
            parser.pdf_reference = 'REF02'
            parser.pdf_file_path = '/tmp/reports'
            parser.pdf_file_name = 'REF02_2024-01-03_321.pdf'
            parser.pdf_date = '2024-01-03'
            parser.pdf_sample_number = '321'
            parser.pdf_blocks_text = [
                (
                    ['HEADER B'],
                    [
                        ['2', 20.0, 0.2, -0.2, 0.0, 20.05, 0.05, 0.0],
                    ],
                )
            ]

            parser.to_sqlite()

            report_row = execute_with_retry(
                db_path,
                'SELECT REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER FROM REPORTS',
            )
            measurement_row = execute_with_retry(
                db_path,
                'SELECT AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER FROM MEASUREMENTS',
            )

            self.assertEqual(report_row, [('REF02', '/tmp/reports', 'REF02_2024-01-03_321.pdf', '2024-01-03', '321')])
            self.assertEqual(measurement_row, [('2', 20.0, 0.2, -0.2, 0.0, 20.05, 0.05, 0.0, 'HEADER B')])


    def test_to_df_uses_pdf_reference_for_reference_column(self):
        parser = CMMReportParser('REF01_2024-01-02_123.pdf', ':memory:')
        parser.pdf_reference = 'REF_CUSTOM'
        parser.pdf_blocks_text = [
            (
                [['HEADER A']],
                [
                    ['1', 10.0, 0.1, -0.1, 0.0, 10.05, 0.05, 0.0],
                ],
            )
        ]

        parser.to_df()

        self.assertFalse(parser.df.empty)
        self.assertTrue((parser.df['Reference'] == 'REF_CUSTOM').all())

    def test_modifydb_update_batch_rolls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'modify.db')
            execute_with_retry(db_path, 'CREATE TABLE REPORTS (REFERENCE TEXT PRIMARY KEY)')
            execute_with_retry(db_path, "INSERT INTO REPORTS (REFERENCE) VALUES ('A')")
            execute_with_retry(db_path, "INSERT INTO REPORTS (REFERENCE) VALUES ('B')")

            statements = [
                ('UPDATE REPORTS SET REFERENCE = ? WHERE REFERENCE = ?', ('A2', 'A')),
                ('UPDATE MISSING_TABLE SET X = ? WHERE X = ?', ('X2', 'X')),
            ]

            with self.assertRaises(Exception):
                run_transaction_with_retry(
                    db_path,
                    lambda cursor: ModifyDB._apply_update_statements(None, cursor, statements),
                    retries=1,
                    retry_delay_s=0,
                )

            rows = execute_with_retry(db_path, 'SELECT REFERENCE FROM REPORTS ORDER BY REFERENCE')
            self.assertEqual(rows, [('A',), ('B',)])


if __name__ == '__main__':
    unittest.main()
