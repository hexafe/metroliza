import importlib.metadata
import importlib.util
import logging
import re
from pathlib import Path

import pandas

from modules.CustomLogger import CustomLogger
from modules.cmm_native_parser import parse_blocks_with_backend
from modules.cmm_parsing import add_tolerances_to_blocks
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


class CMMReportParser:
    """Class to parse and convert PDF CMM report."""

    def __init__(self, pdf_file_path: str, database: str, connection=None):
        """
        Initializes an instance of the CMMReport class.
        Args:
            pdf_file_path (str): The path of the PDF file.
            database (str): The path of the database.
        """
        self.pdf_file_path = self.get_file_path_from_filename(pdf_file_path)
        self.pdf_file_name = self.get_file_name_from_filename(pdf_file_path)
        self.pdf_date = self.get_date_from_filename()
        self.pdf_reference = self.get_reference_from_filename()
        self.pdf_sample_number = self.get_sample_number_from_file()
        self.pdf_raw_text = []
        self.pdf_blocks_text = []
        self.df = pandas.DataFrame()
        self.database = database
        self.connection = connection

        # self.open_database_and_check_filename()

    def get_file_path_from_filename(self, pdf_file_path: str):
        try:
            """
            Retrieves the file path from the given PDF file path.
            Args:
                pdf_file_path (str): The path of the PDF file.
            Returns:
                str: The absolute parent directory path of the PDF file.
            """
            return str(Path(pdf_file_path).absolute().parent)
        except Exception as e:
            self.log_and_exit(e)

    def get_file_name_from_filename(self, pdf_file_path: str):
        try:
            """
            Retrieves the file name from the given PDF file path.
            Args:
                pdf_file_path (str): The path of the PDF file.
            Returns:
                str: The file name of the PDF file.
            """
            return str(Path(pdf_file_path).name)
        except Exception as e:
            self.log_and_exit(e)

    def get_date_from_filename(self):
        try:
            """
            Retrieves the date from the filename using regular expressions.
            Returns:
                str: The extracted date from the filename in the format "YYYY-MM-DD",
                or "0000-00-00" if no date is found.
            """
            date_pattern = r"\d{4}[- _/\.]\d{1,2}[- _/\.]\d{1,2}"
            date_match = re.findall(date_pattern, self.pdf_file_name)
            date_match = date_match[-1] if date_match else "0000.00.00"
            date_match = date_match.replace(".", "-").replace("_", "-").replace("/", "-")
            return date_match
        except Exception as e:
            self.log_and_exit(e)
    
    def get_sample_number_from_file(self):
        try:
            """
            Retrieves the sample number from the filename using regular expressions.
            Returns:
                str: The extracted sample number from the filename,
                or "0000" if no sample number is found.
            """
            pattern = r"\d{4}[- _/\.]\d{1,2}[- _/\.]\d{1,2}_(.*?)\.(?i:pdf)"
            match = re.search(pattern, self.pdf_file_name)
            if match:
                return match.group(1)
            return "0000"
        except Exception as e:
            self.log_and_exit(e)

    def get_reference_from_filename(self):
        try:
            """
            Retrieves the reference from the filename using regular expressions.
            Returns:
                str: The extracted reference from the filename,
                or "REF" if no reference is found.
            """
            reference_pattern = r"([A-Z][A-Za-z0-9]{4}\d{1,5}(_\d{3})?)|(\d{2}[A-Za-z][._-]?\d{3}[._-]?\d{3})|(216\d{5})"
            reference_match = re.match(reference_pattern, self.pdf_file_name)
            reference_match = reference_match.group(0) if reference_match else "REF"
            return reference_match
        except Exception as e:
            self.log_and_exit(e)

    def open_database_and_check_filename(self):
        try:
            """
            Checks if the opened file is already present in the database and performs appropriate actions.
            If the 'REPORTS' table does not exist in the database, it creates the table and imports the data.
            If the file is not present in the 'REPORTS' table, it imports the data.
            If the file already exists in the 'REPORTS' table, it skips the file.
            """
            def open_split_to_sql():
                # Helper function to open, split, and import data to the SQLite database
                self.cmm_open()
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
                (self.pdf_file_name,),
                connection=self.connection,
            )
            count = count_rows[0][0] if count_rows else 0

            if count == 0:
                # File does not exist in the 'REPORTS' table, import the data
                open_split_to_sql()
            else:
                logger.info("Report '%s' already exists in the database; skipping.", self.pdf_file_name)
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

    def cmm_open(self):
        try:
            """
            Method to open the CMM PDF file and store the text inside the pdf_raw_text attribute.
            It uses the PyMuPDF library (fitz) to open the PDF file and extract the text from each page.
            """
            pdf_backend = self._require_pdf_backend()
            pdf_path = Path(self.pdf_file_path) / self.pdf_file_name
            with pdf_backend.open(str(pdf_path)) as pdf_report:
                for page in pdf_report:
                    page_text = page.get_text().splitlines()
                    for line in page_text:
                        self.pdf_raw_text.append(line)
        except Exception as e:
            self.log_and_exit(e)

    def show_raw_text(self):
        try:
            """
            Method to print the raw text inside the PDF.
            It iterates over each line of text in the pdf_raw_text attribute and prints it.
            """
            for line in self.pdf_raw_text:
                logger.debug("%s", line)
        except Exception as e:
            self.log_and_exit(e)

    def show_blocks_text(self):
        try:
            """
            Method to print the pdf_blocks_text - blocks of measurements.
            It iterates over each block in the pdf_blocks_text attribute and prints each line within the block.
            Each block is surrounded by markers indicating the beginning and end of the block.
            """
            for block in self.pdf_blocks_text:
                logger.debug("___[BEGINNING OF BLOCK]___")
                for line in block:
                    logger.debug("%s (len(line)=%s)", line, len(line))
                logger.debug("___[END OF BLOCK (len(block)=%s)]___", len(block))
        except Exception as e:
            self.log_and_exit(e)

    def show_blocks_text2(self):
        try:
            """
            Method to print the pdf_blocks_text - blocks of measurements.
            It iterates over each block in the pdf_blocks_text attribute and prints the entire block as a string.
            Each block is surrounded by markers indicating the beginning and end of the block.
            """
            for block in self.pdf_blocks_text:
                logger.debug("___[BEGINNING OF BLOCK]___")
                logger.debug("%s", block)
                logger.debug("___[END OF BLOCK (len(block)=%s)]___", len(block))
        except Exception as e:
            self.log_and_exit(e)

    def split_text_to_blocks(self):
        try:
            """Method to split raw text from pdf to blocks - split by measurements"""
            self.pdf_blocks_text = parse_blocks_with_backend(self.pdf_raw_text, use_native=False)
        except Exception as e:
            self.log_and_exit(e)

    def add_tolerances(self):
        try:
            self.pdf_blocks_text = add_tolerances_to_blocks(self.pdf_blocks_text)
        except Exception as e:
            self.log_and_exit(e)

    def to_dict(self):
        try:
            """
            Converts the parsed CMM report data into a dictionary.
            Returns:
                dict: A dictionary containing the parsed CMM report data.
            """
            cmm_report_dict = {
                "file_name": self.pdf_file_name,
                "date": self.pdf_date,
                "reference": self.pdf_reference,
                "blocks": []
            }

            for block in self.pdf_blocks_text:
                block_dict = {
                    "header_comment": block[0],
                    "dimensions": block[1:]
                }
                cmm_report_dict["blocks"].append(block_dict)

            return cmm_report_dict
        except Exception as e:
            self.log_and_exit(e)

    def to_df(self):
        try:
            """This method converts blocks to dataframe"""
            df_list = []
            for block in self.pdf_blocks_text:
                header = ""
                for sublist in block[0]:
                    if isinstance(sublist, str):
                        header += sublist
                        header += ", "
                    else:
                        for item in sublist:
                            if isinstance(item, str):
                                header += item
                                header += ", "
                header = header[:-2]
                columns = ['AX', 'NOM', '+TOL', '-TOL', 'BONUS', 'MEAS', 'DEV', 'OUTTOL']
                df = pandas.DataFrame(block[1], columns=columns)
                df['Header'] = header
                df['Reference'] = self.pdf_references
                df['File location'] = self.pdf_file_path
                df['File name'] = self.pdf_file_name
                df['Date'] = self.pdf_date
                df_list.append(df)

            if df_list:
                self.df = pandas.concat(df_list)
        except Exception as e:
            self.log_and_exit(e)

    def to_sqlite(self):
        try:
            """
            Creates tables (if necessary) and inserts measurements and reports data into an SQLite database.
            """
            # Check if there are measurements data
            if not any(lst[1] for lst in self.pdf_blocks_text):
                logger.warning(
                    "Report '%s' has no measurements data; skipping database insertion.",
                    self.pdf_file_name,
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

                ensure_schema_indexes(transaction_cursor)

                transaction_cursor.execute(
                    'SELECT COUNT(*) FROM REPORTS WHERE REFERENCE = ? AND FILELOC = ? AND FILENAME = ? AND DATE = ? AND SAMPLE_NUMBER = ?',
                    (self.pdf_reference, self.pdf_file_path, self.pdf_file_name, self.pdf_date, self.pdf_sample_number),
                )
                count_rows = transaction_cursor.fetchall()
                count = count_rows[0][0] if count_rows else 0

                if count > 0:
                    return False

                transaction_cursor.execute(
                    'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                    (self.pdf_reference, self.pdf_file_path, self.pdf_file_name, self.pdf_date, self.pdf_sample_number),
                )
                report_id = transaction_cursor.lastrowid

                for lst in self.pdf_blocks_text:
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
                logger.info("Report '%s' measurements inserted into the database.", self.pdf_file_name)
                return

            logger.info("Report '%s' already exists in the database.", self.pdf_file_name)
            return
        except Exception as e:
            self.log_and_exit(e)

    def show_df(self):
        try:
            """Prints the dataframe with measurements"""
            logger.debug("%s", self.df)
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
