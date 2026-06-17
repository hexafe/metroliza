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

sys.modules.pop('modules.cmm_report_parser', None)
sys.modules.pop('metroliza.parsing.cmm_report_parser', None)
import modules.cmm_report_parser as cmm_report_parser_module  # noqa: E402
from modules.cmm_schema import ensure_cmm_report_schema  # noqa: E402
from modules.industrial_data_schema import ensure_industrial_data_schema  # noqa: E402
from modules.report_schema import ensure_report_schema  # noqa: E402

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

    def _seed_industrial_schema_for_plan_checks(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO industrial_source_profiles (
                profile_key, profile_name, source_db_alias, database_type,
                source_object_name, allowed_columns_json, created_at, updated_at
            )
            VALUES ('line-a', 'Line A', 'plant_a', 'sqlite', 'events', '[]', '2026-06-17T00:00:00Z', '2026-06-17T00:00:00Z')
            """
        )
        profile_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        for signal_id in range(1, 4):
            conn.execute(
                """
                INSERT INTO industrial_signal_definitions (
                    source_profile_id, signal_key, metric_name, enabled, created_at, updated_at
                )
                VALUES (?, ?, ?, 1, '2026-06-17T00:00:00Z', '2026-06-17T00:00:00Z')
                """,
                (profile_id, f'signal-{signal_id}', f'Metric {signal_id}'),
            )

        for row_number in range(1, 121):
            reference = 'REF_A' if row_number % 2 == 0 else 'REF_B'
            signal_id = (row_number % 3) + 1
            event_time = f'2026-06-{(row_number % 28) + 1:02d}T12:00:00Z'
            conn.execute(
                """
                INSERT INTO industrial_records (
                    source_profile_id, source_db_alias, source_record_key, process_timestamp,
                    reference, part_number, revision, raw_record_json, created_at, updated_at
                )
                VALUES (?, 'plant_a', ?, ?, ?, 'PN-1', 'A', '{}', '2026-06-17T00:00:00Z', '2026-06-17T00:00:00Z')
                """,
                (profile_id, f'record-{row_number:04d}', event_time, reference),
            )
            record_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            conn.execute(
                """
                INSERT INTO industrial_record_values (
                    record_id, field_name, field_value_text, created_at
                )
                VALUES (?, 'trace_code', ?, '2026-06-17T00:00:00Z')
                """,
                (record_id, f'TC-{row_number % 7:03d}'),
            )
            conn.execute(
                """
                INSERT INTO industrial_samples (
                    source_profile_id, signal_id, source_record_key, event_time, ingest_time,
                    metric_name, value, segment_key_json, quality_flags_json
                )
                VALUES (?, ?, ?, ?, '2026-06-17T00:00:00Z', 'diameter', ?, '{}', '[]')
                """,
                (profile_id, signal_id, f'sample-{row_number:04d}', event_time, row_number / 10),
            )
            sample_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            conn.execute(
                """
                INSERT INTO industrial_anomaly_events (
                    sample_id, signal_id, event_time, detector_key, severity, score,
                    observed_value, explanation, status, created_at
                )
                VALUES (?, ?, ?, 'spec_limits', ?, 1.0, ?, 'Synthetic plan check', ?, '2026-06-17T00:00:00Z')
                """,
                (
                    sample_id,
                    signal_id,
                    event_time,
                    'critical' if row_number % 2 == 0 else 'warning',
                    row_number / 10,
                    'open' if row_number % 3 else 'resolved',
                ),
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
                'idx_source_file_locations_latest_active',
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
                'idx_industrial_source_profiles_enabled',
                'idx_industrial_source_profiles_alias',
                'idx_industrial_sync_runs_profile_started',
                'idx_industrial_sync_runs_status',
                'idx_industrial_records_profile_timestamp',
                'idx_industrial_records_reference',
                'idx_industrial_records_reference_time_id',
                'idx_industrial_records_part_revision',
                'idx_industrial_records_serial',
                'idx_industrial_records_batch_lot',
                'idx_industrial_record_values_record_field',
                'idx_industrial_record_values_field_text_record',
                'idx_industrial_join_rules_enabled_priority',
                'idx_industrial_link_candidates_record_status',
                'idx_industrial_link_candidates_report_measurement',
                'idx_industrial_stream_offsets_profile_stream',
                'idx_industrial_realtime_monitor_configs_enabled',
                'idx_industrial_signal_definitions_profile_enabled',
                'idx_industrial_samples_signal_time',
                'idx_industrial_samples_signal_time_desc_value',
                'idx_industrial_samples_profile_time',
                'idx_industrial_samples_profile_signal_time',
                'idx_industrial_detector_configs_enabled',
                'idx_industrial_baselines_signal_segment_created',
                'idx_industrial_anomaly_events_signal_time',
                'idx_industrial_anomaly_events_severity_status_time',
                'idx_industrial_anomaly_events_detector_time',
                'idx_industrial_anomaly_events_status_time_desc',
                'idx_industrial_anomaly_events_signal_status_time_desc',
                'idx_industrial_anomaly_events_sample_detector_unique',
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

    def test_latest_active_source_file_location_lookup_uses_covering_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'locations.db')
            ensure_report_schema(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO source_files (sha256, source_format, discovered_at, is_active)
                    VALUES ('synthetic-sha', 'pdf', '2024-01-01T00:00:00Z', 1)
                    """
                )
                source_file_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                conn.executemany(
                    """
                    INSERT INTO source_file_locations (
                        source_file_id, absolute_path, directory_path, file_name,
                        file_extension, discovered_at, is_active
                    )
                    VALUES (?, ?, ?, ?, 'pdf', ?, ?)
                    """,
                    [
                        (
                            source_file_id,
                            '/synthetic/reports/old.pdf',
                            '/synthetic/reports',
                            'old.pdf',
                            '2024-01-01T00:00:00Z',
                            1,
                        ),
                        (
                            source_file_id,
                            '/synthetic/reports/new.pdf',
                            '/synthetic/reports',
                            'new.pdf',
                            '2024-01-02T00:00:00Z',
                            1,
                        ),
                        (
                            source_file_id,
                            '/synthetic/reports/inactive.pdf',
                            '/synthetic/reports',
                            'inactive.pdf',
                            '2024-01-03T00:00:00Z',
                            0,
                        ),
                    ],
                )

                plan = self._explain(
                    conn,
                    """
                    SELECT selected_location.id
                    FROM source_file_locations selected_location
                    WHERE selected_location.source_file_id = 1
                      AND selected_location.is_active = 1
                    ORDER BY selected_location.discovered_at DESC, selected_location.id DESC
                    LIMIT 1
                    """,
                )
                selected_file_name = conn.execute(
                    """
                    SELECT selected_location.file_name
                    FROM source_file_locations selected_location
                    WHERE selected_location.source_file_id = ?
                      AND selected_location.is_active = 1
                    ORDER BY selected_location.discovered_at DESC, selected_location.id DESC
                    LIMIT 1
                    """,
                    (source_file_id,),
                ).fetchone()[0]

        self.assertIn('idx_source_file_locations_latest_active', plan)
        self.assertNotIn('USE TEMP B-TREE', plan)
        self.assertEqual(selected_file_name, 'new.pdf')

    def test_industrial_large_cache_realtime_and_anomaly_queries_use_speed_indexes(self):
        cache_order_query = """
            SELECT id, reference, process_timestamp
            FROM industrial_records
            ORDER BY reference COLLATE NOCASE, process_timestamp, id
            LIMIT 25
        """
        dynamic_lookup_query = """
            SELECT records.id
            FROM industrial_record_values values_row
            JOIN industrial_records records ON records.id = values_row.record_id
            WHERE values_row.field_name = 'trace_code'
              AND values_row.field_value_text = 'TC-003'
            LIMIT 25
        """
        recent_sample_query = """
            SELECT id, event_time, value
            FROM industrial_samples
            WHERE signal_id = 1
            ORDER BY event_time DESC, id DESC
            LIMIT 50
        """
        open_anomaly_feed_query = """
            SELECT id, event_time, severity
            FROM industrial_anomaly_events
            WHERE status = 'open'
            ORDER BY event_time DESC, id DESC
            LIMIT 100
        """
        signal_open_anomaly_query = """
            SELECT id, event_time, severity
            FROM industrial_anomaly_events
            WHERE signal_id = 1
              AND status = 'open'
            ORDER BY event_time DESC, id DESC
            LIMIT 50
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'industrial_plan_checks.db')
            ensure_industrial_data_schema(db_path)
            with sqlite3.connect(db_path) as conn:
                self._seed_industrial_schema_for_plan_checks(conn)
                cache_order_plan = self._explain(conn, cache_order_query)
                dynamic_lookup_plan = self._explain(conn, dynamic_lookup_query)
                recent_sample_plan = self._explain(conn, recent_sample_query)
                open_anomaly_feed_plan = self._explain(conn, open_anomaly_feed_query)
                signal_open_anomaly_plan = self._explain(conn, signal_open_anomaly_query)

        self.assertIn('idx_industrial_records_reference_time_id', cache_order_plan)
        self.assertNotIn('USE TEMP B-TREE', cache_order_plan)

        self.assertIn('idx_industrial_record_values_field_text_record', dynamic_lookup_plan)

        self.assertIn('idx_industrial_samples_signal_time_desc_value', recent_sample_plan)
        self.assertNotIn('USE TEMP B-TREE', recent_sample_plan)

        self.assertIn('idx_industrial_anomaly_events_status_time_desc', open_anomaly_feed_plan)
        self.assertNotIn('USE TEMP B-TREE', open_anomaly_feed_plan)

        self.assertIn(
            'idx_industrial_anomaly_events_signal_status_time_desc',
            signal_open_anomaly_plan,
        )
        self.assertNotIn('USE TEMP B-TREE', signal_open_anomaly_plan)


if __name__ == '__main__':
    unittest.main()
