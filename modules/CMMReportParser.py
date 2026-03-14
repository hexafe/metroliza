"""Parse CMM report files and persist normalized measurements to SQLite.

The parser consumes raw report text, derives metadata from filenames, and writes
rows used by downstream grouping and export workflows.
"""

import importlib.metadata
import importlib.util
import logging
from pathlib import Path

from modules.CustomLogger import CustomLogger
from modules.characteristic_alias_service import (
    ensure_characteristic_alias_schema,
    ensure_characteristic_alias_table,
)
from modules.cmm_native_parser import parse_blocks_with_backend_and_telemetry
from modules.cmm_parsing import add_tolerances_to_blocks
from modules.base_report_parser import BaseReportParser
from modules.db import execute_with_retry, run_transaction_with_retry


logger = logging.getLogger(__name__)


SCHEMA_INDEX_STATEMENTS = (
    'CREATE INDEX IF NOT EXISTS idx_reports_reference ON REPORTS(REFERENCE)',
    'CREATE INDEX IF NOT EXISTS idx_reports_filename ON REPORTS(FILENAME)',
    'CREATE INDEX IF NOT EXISTS idx_reports_date ON REPORTS(DATE)',
    'CREATE INDEX IF NOT EXISTS idx_reports_sample_number ON REPORTS(SAMPLE_NUMBER)',
    'CREATE INDEX IF NOT EXISTS idx_reports_identity ON REPORTS(REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER)',
    'CREATE INDEX IF NOT EXISTS idx_measurements_report_id ON MEASUREMENTS(REPORT_ID)',
    'CREATE INDEX IF NOT EXISTS idx_measurements_header ON MEASUREMENTS(HEADER)',
    'CREATE INDEX IF NOT EXISTS idx_measurements_ax ON MEASUREMENTS(AX)',
)


def ensure_schema_indexes(cursor):
    """Create app indexes in a migration-safe way."""
    for statement in SCHEMA_INDEX_STATEMENTS:
        cursor.execute(statement)


def _resolve_pymupdf_backend_module() -> str | None:
    """Return the import name for a valid PyMuPDF backend, if available."""
    if importlib.util.find_spec("pymupdf") is not None:
        return "pymupdf"

    fitz_distributions = {
        name.lower()
        for name in importlib.metadata.packages_distributions().get("fitz", [])
    }
    if "pymupdf" in fitz_distributions and importlib.util.find_spec("fitz") is not None:
        return "fitz"

    return None


_PYMUPDF_BACKEND_MODULE = _resolve_pymupdf_backend_module()
if _PYMUPDF_BACKEND_MODULE == "pymupdf":
    import pymupdf as fitz
elif _PYMUPDF_BACKEND_MODULE == "fitz":
    import fitz
else:
    fitz = None


class CMMReportParser(BaseReportParser):
    """Class to parse and convert PDF CMM report."""

    def __init__(self, file_path: str, database: str, connection=None):
        """Initialize parser for one CMM report file."""
        super().__init__(file_path=file_path, database=database, connection=connection)
        self.parse_backend_used = "unknown"

    def open_database_and_check_filename(self):
        """Handle `open_database_and_check_filename` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            ensure_characteristic_alias_schema(
                self.database,
                connection=self.connection,
                retries=4,
                retry_delay_s=1,
            )

            """
            Checks if the opened file is already present in the database and performs appropriate actions.
            If the 'REPORTS' table does not exist in the database, it creates the table and imports the data.
            If the file is not present in the 'REPORTS' table, it imports the data.
            If the file already exists in the 'REPORTS' table, it skips the file.
            """
            def open_split_to_sql():
                # Helper function to open, split, and import data to the SQLite database
                self.open_report()
                self.split_text_to_blocks()
                self.to_sqlite()

            # Check if 'REPORTS' table exists
            table_exists = execute_with_retry(
                self.database,
                "SELECT name FROM sqlite_master WHERE type='table' AND name='REPORTS'",
                connection=self.connection,
            )

            if not table_exists:
                logger.info("REPORTS table does not exist; creating schema and importing report data.")
                open_split_to_sql()
                return

            # Check if the file already exists in the 'REPORTS' table
            count_rows = execute_with_retry(
                self.database,
                'SELECT COUNT(*) FROM REPORTS WHERE FILENAME = ?',
                (self.file_name,),
                connection=self.connection,
            )
            count = count_rows[0][0] if count_rows else 0

            if count == 0:
                # File does not exist in the 'REPORTS' table, import the data
                open_split_to_sql()
            else:
                logger.info("Report '%s' already exists in the database; skipping.", self.file_name)
        except Exception as e:
            self.log_and_exit(e)

    def _require_pdf_backend(self):
        if fitz is None:
            raise ImportError(
                "PyMuPDF is required to parse PDF reports. Install `PyMuPDF` (which "
                "provides either the `pymupdf` or `fitz` module) and remove any "
                "conflicting standalone `fitz` package."
            )
        return fitz

    def open_report(self):
        """Handle `cmm_open` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """
            Method to open the CMM PDF file and store the text inside the pdf_raw_text attribute.
            It uses the PyMuPDF library (fitz) to open the PDF file and extract the text from each page.
            """
            pdf_backend = self._require_pdf_backend()
            pdf_path = Path(self.file_path) / self.file_name
            with pdf_backend.open(str(pdf_path)) as pdf_report:
                for page in pdf_report:
                    page_text = page.get_text().splitlines()
                    for line in page_text:
                        self.raw_text.append(line)
        except Exception as e:
            self.log_and_exit(e)


    def cmm_open(self):
        """Backward-compatible alias for open_report."""
        return self.open_report()

    def show_raw_text(self):
        """Handle `show_raw_text` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """
            Method to print the raw text inside the PDF.
            It iterates over each line of text in the pdf_raw_text attribute and prints it.
            """
            for line in self.raw_text:
                logger.debug("%s", line)
        except Exception as e:
            self.log_and_exit(e)

    def show_blocks_text(self):
        """Handle `show_blocks_text` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """
            Method to print the pdf_blocks_text - blocks of measurements.
            It iterates over each block in the pdf_blocks_text attribute and prints each line within the block.
            Each block is surrounded by markers indicating the beginning and end of the block.
            """
            for block in self.blocks_text:
                logger.debug("___[BEGINNING OF BLOCK]___")
                for line in block:
                    logger.debug("%s (len(line)=%s)", line, len(line))
                logger.debug("___[END OF BLOCK (len(block)=%s)]___", len(block))
        except Exception as e:
            self.log_and_exit(e)

    def show_blocks_text2(self):
        """Handle `show_blocks_text2` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """
            Method to print the pdf_blocks_text - blocks of measurements.
            It iterates over each block in the pdf_blocks_text attribute and prints the entire block as a string.
            Each block is surrounded by markers indicating the beginning and end of the block.
            """
            for block in self.blocks_text:
                logger.debug("___[BEGINNING OF BLOCK]___")
                logger.debug("%s", block)
                logger.debug("___[END OF BLOCK (len(block)=%s)]___", len(block))
        except Exception as e:
            self.log_and_exit(e)

    def split_text_to_blocks(self):
        """Handle `split_text_to_blocks` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """Method to split raw text from pdf to blocks - split by measurements"""
            parse_result = parse_blocks_with_backend_and_telemetry(self.pdf_raw_text, use_native=False)
            self.blocks_text = parse_result.blocks
            self.parse_backend_used = parse_result.backend
        except Exception as e:
            self.log_and_exit(e)

    def add_tolerances(self):
        """Handle `add_tolerances` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            self.blocks_text = add_tolerances_to_blocks(self.blocks_text)
        except Exception as e:
            self.log_and_exit(e)

    def to_sqlite(self):
        """Handle `to_sqlite` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """
            Creates tables (if necessary) and inserts measurements and reports data into an SQLite database.
            """
            # Check if there are measurements data
            if not any(lst[1] for lst in self.blocks_text):
                logger.warning(
                    "Report '%s' has no measurements data; skipping database insertion.",
                    self.file_name,
                )
                return

            def create_tables_and_insert_report(transaction_cursor):
                transaction_cursor.execute('''CREATE TABLE IF NOT EXISTS MEASUREMENTS (
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
                                )''')

                transaction_cursor.execute('''CREATE TABLE IF NOT EXISTS REPORTS (
                                    ID INTEGER PRIMARY KEY,
                                    REFERENCE TEXT,
                                    FILELOC TEXT,
                                    FILENAME TEXT,
                                    DATE TEXT,
                                    SAMPLE_NUMBER TEXT
                                )''')

                ensure_characteristic_alias_table(transaction_cursor)

                ensure_schema_indexes(transaction_cursor)

                transaction_cursor.execute(
                    'SELECT COUNT(*) FROM REPORTS WHERE REFERENCE = ? AND FILELOC = ? AND FILENAME = ? AND DATE = ? AND SAMPLE_NUMBER = ?',
                    (self.reference, self.file_path, self.file_name, self.date, self.sample_number),
                )
                count_rows = transaction_cursor.fetchall()
                count = count_rows[0][0] if count_rows else 0

                if count > 0:
                    return False

                transaction_cursor.execute(
                    'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                    (self.reference, self.file_path, self.file_name, self.date, self.sample_number),
                )
                report_id = transaction_cursor.lastrowid

                for lst in self.blocks_text:
                    table_name = ""
                    for sublist in lst[0]:
                        if isinstance(sublist, str):
                            table_name += sublist
                            table_name += ", "
                        else:
                            for item in sublist:
                                if isinstance(item, str):
                                    table_name += item
                                    table_name += ", "

                    table_name = table_name.replace('"', '')
                    table_name = table_name[:-2]

                    rows = [
                        (None, row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], table_name, report_id)
                        for row in lst[1]
                    ]
                    transaction_cursor.executemany(
                        'INSERT INTO MEASUREMENTS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        rows,
                    )

                return True

            was_inserted = run_transaction_with_retry(
                self.database,
                create_tables_and_insert_report,
                connection=self.connection,
                retries=4,
                retry_delay_s=1,
            )
            if was_inserted:
                logger.info("Report '%s' measurements inserted into the database.", self.file_name)
                return

            logger.info("Report '%s' already exists in the database.", self.file_name)
            return
        except Exception as e:
            self.log_and_exit(e)

    def show_df(self):
        """Handle `show_df` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            """Prints the dataframe with measurements"""
            logger.debug("%s", self.df)
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        """Handle `log_and_exit` for `CMMReportParser`.

        Args:
            exception (object): Method input value.

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        CustomLogger(exception, reraise=False)
