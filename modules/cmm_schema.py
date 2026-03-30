"""Shared SQLite schema bootstrap helpers for CMM report ingestion."""

from modules.characteristic_alias_service import ensure_characteristic_alias_table
from modules.db import run_transaction_with_retry


SCHEMA_INDEX_STATEMENTS = (
    'CREATE INDEX IF NOT EXISTS idx_reports_reference ON REPORTS(REFERENCE)',
    'CREATE INDEX IF NOT EXISTS idx_reports_filename ON REPORTS(FILENAME)',
    'CREATE INDEX IF NOT EXISTS idx_reports_date ON REPORTS(DATE)',
    'CREATE INDEX IF NOT EXISTS idx_reports_sample_number ON REPORTS(SAMPLE_NUMBER)',
    'CREATE INDEX IF NOT EXISTS idx_reports_identity ON REPORTS(REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER)',
    'CREATE INDEX IF NOT EXISTS idx_measurements_report_id ON MEASUREMENTS(REPORT_ID)',
    'CREATE INDEX IF NOT EXISTS idx_measurements_report_header_ax ON MEASUREMENTS(REPORT_ID, HEADER, AX)',
    'CREATE INDEX IF NOT EXISTS idx_measurements_header ON MEASUREMENTS(HEADER)',
    'CREATE INDEX IF NOT EXISTS idx_measurements_ax ON MEASUREMENTS(AX)',
)


def ensure_schema_indexes(cursor):
    """Create CMM ingestion indexes in a migration-safe way."""
    for statement in SCHEMA_INDEX_STATEMENTS:
        cursor.execute(statement)


def ensure_cmm_report_schema(database, *, connection=None, retries=4, retry_delay_s=1):
    """Ensure REPORTS/MEASUREMENTS/alias tables and indexes exist."""

    def _ensure_schema(transaction_cursor):
        transaction_cursor.execute(
            '''CREATE TABLE IF NOT EXISTS MEASUREMENTS (
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
        transaction_cursor.execute(
            '''CREATE TABLE IF NOT EXISTS REPORTS (
                                ID INTEGER PRIMARY KEY,
                                REFERENCE TEXT,
                                FILELOC TEXT,
                                FILENAME TEXT,
                                DATE TEXT,
                                SAMPLE_NUMBER TEXT
                            )'''
        )
        ensure_characteristic_alias_table(transaction_cursor)
        ensure_schema_indexes(transaction_cursor)

    run_transaction_with_retry(
        database,
        _ensure_schema,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
