import importlib.machinery
import sqlite3
import tempfile
import types
import sys
import unittest
from pathlib import Path

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

custom_logger_stub = types.ModuleType('modules.custom_logger')
custom_logger_stub.CustomLogger = type('CustomLogger', (), {'__init__': lambda self, *args, **kwargs: None})
sys.modules.setdefault('modules.custom_logger', custom_logger_stub)

fitz_stub = types.ModuleType('fitz')
fitz_stub.__spec__ = importlib.machinery.ModuleSpec('fitz', loader=None)
sys.modules.setdefault('fitz', fitz_stub)
pymupdf_stub = types.ModuleType('pymupdf')
pymupdf_stub.__spec__ = importlib.machinery.ModuleSpec('pymupdf', loader=None)
sys.modules.setdefault('pymupdf', pymupdf_stub)

import modules.cmm_report_parser as cmm_report_parser_module  # noqa: E402

CMMReportParser = cmm_report_parser_module.CMMReportParser


class TestSchemaIndexQueryPlans(unittest.TestCase):
    def _insert_report(self, db_path: str, reference: str, sample_number: str, day: int) -> None:
        parser = CMMReportParser(f'{reference}_2024-02-{day:02d}_{sample_number}.pdf', db_path)
        parser.pdf_reference = reference
        parser.pdf_file_path = '/tmp/reports'
        parser.pdf_file_name = f'{reference}_2024-02-{day:02d}_{sample_number}.pdf'
        parser.pdf_date = f'2024-02-{day:02d}'
        parser.pdf_sample_number = sample_number
        parser.pdf_blocks_text = [
            (
                ['FEATURE A'],
                [
                    ['AX-001', 10.0, 0.1, -0.1, 0.0, 10.01, 0.01, 0.0],
                    ['AX-002', 20.0, 0.1, -0.1, 0.0, 20.01, 0.01, 0.0],
                ],
            )
        ]
        parser.to_sqlite()

    def _create_schema_without_indexes(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            '''CREATE TABLE REPORTS (
                ID INTEGER PRIMARY KEY,
                REFERENCE TEXT,
                FILELOC TEXT,
                FILENAME TEXT,
                DATE TEXT,
                SAMPLE_NUMBER TEXT
            )'''
        )
        conn.execute(
            '''CREATE TABLE MEASUREMENTS (
                ID INTEGER PRIMARY KEY,
                AX TEXT,
                NOM REAL,
                "+TOL" REAL,
                "-TOL" REAL,
                BONUS REAL,
                MEAS REAL,
                DEV REAL,
                OUTTOL REAL,
                HEADER TEXT,
                REPORT_ID INTEGER,
                FOREIGN KEY (REPORT_ID) REFERENCES REPORTS(ID)
            )'''
        )

    def _seed_schema_for_plan_checks(self, conn: sqlite3.Connection) -> None:
        for i in range(1, 61):
            reference = 'REF_A' if i % 2 == 0 else 'REF_B'
            sample_number = f'{i:03d}'
            day = (i % 28) + 1
            filename = f'{reference}_2024-02-{day:02d}_{sample_number}.pdf'
            conn.execute(
                'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                (reference, '/tmp/reports', filename, f'2024-02-{day:02d}', sample_number),
            )
            report_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            conn.execute(
                'INSERT INTO MEASUREMENTS (AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER, REPORT_ID) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                ('AX-001', 10.0, 0.1, -0.1, 0.0, 10.01, 0.01, 0.0, 'FEATURE A', report_id),
            )
            conn.execute(
                'INSERT INTO MEASUREMENTS (AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER, REPORT_ID) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                ('AX-002', 20.0, 0.1, -0.1, 0.0, 20.01, 0.01, 0.0, 'FEATURE A', report_id),
            )
        conn.commit()

    def _explain(self, conn: sqlite3.Connection, query: str) -> str:
        rows = conn.execute(f'EXPLAIN QUERY PLAN {query}').fetchall()
        return ' | '.join(str(row[-1]) for row in rows)

    def test_to_sqlite_creates_all_expected_indexes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'indexed.db')
            self._insert_report(db_path, 'REF01', '001', 1)

            with sqlite3.connect(db_path) as conn:
                actual_index_names = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'").fetchall()
                }

            expected_index_names = {
                'idx_reports_reference',
                'idx_reports_filename',
                'idx_reports_date',
                'idx_reports_sample_number',
                'idx_reports_identity',
                'idx_measurements_report_id',
                'idx_measurements_report_header_ax',
                'idx_measurements_header',
                'idx_measurements_ax',
            }
            self.assertEqual(actual_index_names, expected_index_names)

    def test_query_plans_use_indexes_for_filter_and_grouping_patterns(self):
        filter_join_query = """
            SELECT MEASUREMENTS.AX, MEASUREMENTS.HEADER, REPORTS.REFERENCE, REPORTS.DATE
            FROM MEASUREMENTS
            JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
            WHERE REPORTS.REFERENCE IN ('REF_A')
              AND REPORTS.DATE >= '2024-02-10'
              AND REPORTS.DATE <= '2024-02-20'
              AND MEASUREMENTS.HEADER IN ('FEATURE A')
              AND MEASUREMENTS.AX IN ('AX-001')
        """
        group_dialog_query = (
            'SELECT DISTINCT REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER '
            'FROM REPORTS WHERE REFERENCE = "REF_A" ORDER BY DATE'
        )
        duplicate_guard_query = (
            "SELECT COUNT(*) FROM REPORTS "
            "WHERE REFERENCE='REF_A' AND FILELOC='/tmp/reports' AND "
            "FILENAME='REF_A_2024-02-10_010.pdf' AND DATE='2024-02-10' AND SAMPLE_NUMBER='010'"
        )
        measurement_summary_query = """
            SELECT REPORT_ID, HEADER, AX, COUNT(MEAS)
            FROM MEASUREMENTS
            WHERE REPORT_ID IN (1, 2, 3, 4, 5)
            GROUP BY REPORT_ID, HEADER, AX
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            no_index_db = Path(temp_dir) / 'no_indexes.db'
            indexed_db = Path(temp_dir) / 'indexed.db'

            with sqlite3.connect(no_index_db) as conn:
                self._create_schema_without_indexes(conn)
                self._seed_schema_for_plan_checks(conn)
                no_index_filter_plan = self._explain(conn, filter_join_query)
                no_index_group_plan = self._explain(conn, group_dialog_query)
                no_index_duplicate_plan = self._explain(conn, duplicate_guard_query)
                no_index_summary_plan = self._explain(conn, measurement_summary_query)

            for i in range(1, 61):
                reference = 'REF_A' if i % 2 == 0 else 'REF_B'
                sample_number = f'{i:03d}'
                day = (i % 28) + 1
                self._insert_report(str(indexed_db), reference, sample_number, day)

            with sqlite3.connect(indexed_db) as conn:
                indexed_filter_plan = self._explain(conn, filter_join_query)
                indexed_group_plan = self._explain(conn, group_dialog_query)
                indexed_duplicate_plan = self._explain(conn, duplicate_guard_query)
                indexed_summary_plan = self._explain(conn, measurement_summary_query)

        self.assertIn('SCAN MEASUREMENTS', no_index_filter_plan)
        self.assertIn('idx_measurements_ax', indexed_filter_plan)

        self.assertIn('USE TEMP B-TREE FOR DISTINCT', no_index_group_plan)
        self.assertIn('idx_reports_identity', indexed_group_plan)

        self.assertIn('SCAN REPORTS', no_index_duplicate_plan)
        self.assertIn('idx_reports_identity', indexed_duplicate_plan)

        self.assertIn('SCAN MEASUREMENTS', no_index_summary_plan)
        self.assertIn('idx_measurements_report_header_ax', indexed_summary_plan)


if __name__ == '__main__':
    unittest.main()
