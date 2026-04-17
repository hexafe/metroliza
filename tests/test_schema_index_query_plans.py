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
from modules.cmm_schema import ensure_cmm_report_schema  # noqa: E402

CMMReportParser = cmm_report_parser_module.CMMReportParser


class TestSchemaIndexQueryPlans(unittest.TestCase):
    def _insert_report(self, db_path: str, reference: str, sample_number: str, day: int) -> None:
        ensure_cmm_report_schema(db_path)
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
            '''CREATE TABLE source_files (
                id INTEGER PRIMARY KEY,
                sha256 TEXT,
                file_size_bytes INTEGER,
                source_format TEXT,
                discovered_at TEXT,
                ingested_at TEXT,
                is_active INTEGER
            )'''
        )
        conn.execute(
            '''CREATE TABLE parsed_reports (
                id INTEGER PRIMARY KEY,
                source_file_id INTEGER,
                parser_id TEXT,
                template_family TEXT,
                template_variant TEXT,
                parse_status TEXT,
                measurement_count INTEGER,
                has_nok INTEGER,
                nok_count INTEGER,
                identity_hash TEXT
            )'''
        )
        conn.execute(
            '''CREATE TABLE report_metadata (
                report_id INTEGER PRIMARY KEY,
                reference TEXT,
                report_date TEXT,
                sample_number TEXT
            )'''
        )
        conn.execute(
            '''CREATE TABLE report_measurements (
                id INTEGER PRIMARY KEY,
                report_id INTEGER,
                header TEXT,
                ax TEXT,
                meas REAL,
                nominal REAL,
                tol_plus REAL,
                tol_minus REAL,
                bonus REAL,
                dev REAL,
                outtol REAL,
                FOREIGN KEY (report_id) REFERENCES parsed_reports(id)
            )'''
        )

    def _seed_schema_for_plan_checks(self, conn: sqlite3.Connection) -> None:
        for i in range(1, 61):
            reference = 'REF_A' if i % 2 == 0 else 'REF_B'
            sample_number = f'{i:03d}'
            day = (i % 28) + 1
            conn.execute(
                """
                INSERT INTO source_files (sha256, source_format, discovered_at, is_active)
                VALUES (?, 'pdf', '2024-01-01T00:00:00Z', 1)
                """,
                (f'sha-{i}',),
            )
            source_file_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            conn.execute(
                """
                INSERT INTO parsed_reports (
                    source_file_id, parser_id, template_family, parse_status,
                    measurement_count, has_nok, nok_count, identity_hash
                )
                VALUES (?, 'parser', 'template', 'parsed', 2, 0, 0, ?)
                """,
                (source_file_id, f'identity-{i}'),
            )
            report_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            conn.execute(
                'INSERT INTO report_metadata (report_id, reference, report_date, sample_number) VALUES (?, ?, ?, ?)',
                (report_id, reference, f'2024-02-{day:02d}', sample_number),
            )
            conn.execute(
                """
                INSERT INTO report_measurements (
                    report_id, ax, nominal, tol_plus, tol_minus, bonus, meas, dev, outtol, header
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (report_id, 'AX-001', 10.0, 0.1, -0.1, 0.0, 10.01, 0.01, 0.0, 'FEATURE A'),
            )
            conn.execute(
                """
                INSERT INTO report_measurements (
                    report_id, ax, nominal, tol_plus, tol_minus, bonus, meas, dev, outtol, header
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (report_id, 'AX-002', 20.0, 0.1, -0.1, 0.0, 20.01, 0.01, 0.0, 'FEATURE A'),
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
                'idx_source_files_sha256',
                'idx_source_file_locations_name',
                'idx_source_file_locations_directory',
                'idx_source_file_locations_source_active',
                'idx_parsed_reports_parser_template',
                'idx_parsed_reports_identity_hash',
                'idx_parsed_reports_status',
                'idx_report_metadata_reference',
                'idx_report_metadata_report_date',
                'idx_report_metadata_sample_number',
                'idx_report_metadata_part_name',
                'idx_report_metadata_revision',
                'idx_report_metadata_stats_count_int',
                'idx_report_metadata_candidates_report_field',
                'idx_report_metadata_candidates_rule',
                'idx_report_metadata_warnings_report',
                'idx_report_metadata_warnings_code',
                'idx_report_measurements_report',
                'idx_report_measurements_report_header_ax',
                'idx_report_measurements_header',
                'idx_report_measurements_ax',
                'idx_report_measurements_status',
                'idx_report_measurements_family',
            }
            self.assertEqual(actual_index_names, expected_index_names)

    def test_query_plans_use_indexes_for_filter_and_grouping_patterns(self):
        filter_join_query = """
            SELECT meas.ax, meas.header, meta.reference, meta.report_date
            FROM report_measurements meas
            JOIN report_metadata meta ON meta.report_id = meas.report_id
            WHERE meta.reference IN ('REF_A')
              AND meta.report_date >= '2024-02-10'
              AND meta.report_date <= '2024-02-20'
              AND meas.header IN ('FEATURE A')
              AND meas.ax IN ('AX-001')
        """
        group_dialog_query = (
            'SELECT DISTINCT reference, report_date, sample_number '
            'FROM report_metadata WHERE reference = "REF_A" ORDER BY report_date'
        )
        duplicate_guard_query = (
            "SELECT COUNT(*) FROM parsed_reports WHERE identity_hash='identity-10'"
        )
        measurement_summary_query = """
            SELECT report_id, header, ax, COUNT(meas)
            FROM report_measurements
            WHERE report_id IN (1, 2, 3, 4, 5)
            GROUP BY report_id, header, ax
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

        self.assertIn('SCAN meas', no_index_filter_plan)
        self.assertTrue(
            'idx_report_measurements_ax' in indexed_filter_plan
            or 'idx_report_metadata_reference' in indexed_filter_plan
        )

        self.assertIn('USE TEMP B-TREE FOR DISTINCT', no_index_group_plan)
        self.assertIn('idx_report_metadata_reference', indexed_group_plan)

        self.assertIn('SCAN parsed_reports', no_index_duplicate_plan)
        self.assertIn('idx_parsed_reports_identity_hash', indexed_duplicate_plan)

        self.assertIn('SCAN report_measurements', no_index_summary_plan)
        self.assertIn('idx_report_measurements_report_header_ax', indexed_summary_plan)


if __name__ == '__main__':
    unittest.main()
