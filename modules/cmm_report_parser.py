"""Parse CMM report files and persist normalized measurements to SQLite.

The parser consumes raw report text, derives metadata from filenames, and writes
rows used by downstream grouping and export workflows.
"""

import logging
import os
from pathlib import Path
from time import perf_counter
from time import strftime

from modules.custom_logger import CustomLogger
from modules.cmm_schema import ensure_cmm_report_schema
from modules.cmm_native_parser import (
    normalize_measurement_rows,
    parse_blocks_with_backend_and_telemetry,
    persist_measurement_rows_with_backend_and_telemetry,
)
from modules.pdf_backend import require_pdf_backend, resolve_pdf_backend_module_name
from modules.cmm_parsing import add_tolerances_to_blocks
from modules.base_report_parser import BaseReportParser
from modules.db import execute_with_retry, run_transaction_with_retry
from modules.parser_plugin_contracts import (
    BaseReportParserPlugin,
    MeasurementBlockV2,
    MeasurementV2,
    ParseMetaV2,
    ParseResultV2,
    PluginManifest,
    ProbeContext,
    ProbeResult,
    ReportInfoV2,
)


logger = logging.getLogger(__name__)

def _resolve_pymupdf_backend_module() -> str | None:
    """Return the import name for a valid PyMuPDF backend, if available."""
    return resolve_pdf_backend_module_name()



def _load_pdf_backend():
    return require_pdf_backend()



class CMMReportParser(BaseReportParser, BaseReportParserPlugin):
    """Class to parse and convert PDF CMM report."""

    manifest = PluginManifest(
        plugin_id="cmm",
        display_name="CMM PDF Parser",
        version="1.0.0",
        supported_formats=("pdf",),
        supported_locales=("*",),
        template_ids=("default",),
        priority=100,
        capabilities={"ocr_required": False, "table_extraction_mode": "mixed"},
    )

    @classmethod
    def probe(cls, input_ref: str | Path, context: ProbeContext) -> ProbeResult:
        """Return parser detection result for a candidate report file."""

        path_text = str(input_ref)
        if path_text.lower().endswith(".pdf"):
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=True,
                confidence=100,
                matched_template_id="default",
                reasons=("pdf_extension",),
            )

        return ProbeResult(
            plugin_id=cls.manifest.plugin_id,
            can_parse=False,
            confidence=0,
            reasons=("unsupported_extension",),
        )

    def __init__(self, file_path: str, database: str, connection=None):
        """Initialize parser for one CMM report file."""
        super().__init__(file_path=file_path, database=database, connection=connection)
        self.parse_backend_used = "unknown"
        self.persistence_backend_used = "unknown"
        self.stage_timings_s: dict[str, float] = {}
        self._prepared_measurement_rows = None

    def open_database_and_check_filename(self):
        """Handle `open_database_and_check_filename` for `CMMReportParser`.

        Args:

        Returns:
            object | None: Method result for caller workflows.

        Side Effects:
            May update UI state, database rows, or in-memory export context.
        """

        try:
            ensure_cmm_report_schema(
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
        return _load_pdf_backend()

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
            parse_start = perf_counter()
            parse_result = parse_blocks_with_backend_and_telemetry(self.pdf_raw_text, use_native=False)
            self.blocks_text = parse_result.blocks
            self.parse_backend_used = parse_result.backend
            self.stage_timings_s["parse_batch_runtime"] = perf_counter() - parse_start
        except Exception as e:
            self.log_and_exit(e)

    def parse_to_v2(self) -> ParseResultV2:
        """Parse report into canonical V2 result."""

        if not self.raw_text:
            self.open_report()
        if not self.blocks_text:
            self.split_text_to_blocks()
            self.add_tolerances()

        blocks_v2: list[MeasurementBlockV2] = []
        for block_index, block in enumerate(self.blocks_text):
            header_tokens = []
            for token in block[0]:
                if isinstance(token, str):
                    header_tokens.append(token)
                elif isinstance(token, list):
                    header_tokens.extend(str(item) for item in token if isinstance(item, str))

            header_normalized = ", ".join(token for token in header_tokens if token)
            dimensions: list[MeasurementV2] = []
            for row in block[1]:
                dimensions.append(
                    MeasurementV2(
                        axis_code=str(row[0]) if len(row) > 0 else "",
                        nominal=row[1] if len(row) > 1 else None,
                        tol_plus=row[2] if len(row) > 2 else None,
                        tol_minus=row[3] if len(row) > 3 else None,
                        bonus=row[4] if len(row) > 4 else None,
                        measured=row[5] if len(row) > 5 else None,
                        deviation=row[6] if len(row) > 6 else None,
                        out_of_tolerance=row[7] if len(row) > 7 else None,
                        raw_tokens=tuple(str(value) for value in row),
                    )
                )

            blocks_v2.append(
                MeasurementBlockV2(
                    header_raw=tuple(header_tokens),
                    header_normalized=header_normalized,
                    dimensions=tuple(dimensions),
                    block_index=block_index,
                )
            )

        return ParseResultV2(
            meta=ParseMetaV2(
                source_file=str(Path(self.file_path) / self.file_name),
                source_format="pdf",
                plugin_id=self.manifest.plugin_id,
                plugin_version=self.manifest.version,
                template_id="default",
                parse_timestamp=strftime("%Y-%m-%dT%H:%M:%SZ"),
                locale_detected=None,
                confidence=100,
            ),
            report=ReportInfoV2(
                reference=self.reference,
                report_date=self.date,
                sample_number=self.sample_number,
                file_name=self.file_name,
                file_path=self.file_path,
            ),
            blocks=tuple(blocks_v2),
        )

    @staticmethod
    def to_legacy_blocks(parse_result_v2: ParseResultV2):
        """Convert V2 blocks back to legacy ``blocks_text`` shape."""

        legacy_blocks = []
        for block in parse_result_v2.blocks:
            header = [list(block.header_raw)]
            rows = []
            for row in block.dimensions:
                rows.append(
                    [
                        row.axis_code,
                        row.nominal,
                        row.tol_plus,
                        row.tol_minus,
                        row.bonus,
                        row.measured,
                        row.deviation,
                        row.out_of_tolerance,
                    ]
                )
            legacy_blocks.append([header, rows])
        return legacy_blocks

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

            use_native_persistence = os.getenv("METROLIZA_CMM_NATIVE_PERSISTENCE", "0").strip() in {"1", "true", "yes", "on"}

            normalize_start = perf_counter()
            normalized_rows = self._normalized_rows_for_persistence(use_native=use_native_persistence)
            self.stage_timings_s["normalize_runtime"] = perf_counter() - normalize_start

            db_write_start = perf_counter()

            def insert_report(transaction_cursor):
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

                transaction_cursor.executemany(
                    'INSERT INTO MEASUREMENTS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    [
                        (
                            None,
                            row[0],
                            row[1],
                            row[2],
                            row[3],
                            row[4],
                            row[5],
                            row[6],
                            row[7],
                            row[8],
                            report_id,
                        )
                        for row in normalized_rows
                    ],
                )

                return True

            if self.connection is None:
                persist_result = persist_measurement_rows_with_backend_and_telemetry(
                    self.database,
                    normalized_rows,
                    use_native=use_native_persistence,
                )
                self.persistence_backend_used = persist_result.backend
                was_inserted = persist_result.inserted
            else:
                was_inserted = run_transaction_with_retry(
                    self.database,
                    insert_report,
                    connection=self.connection,
                    retries=4,
                    retry_delay_s=1,
                )
                self.persistence_backend_used = "python"
            self.stage_timings_s["db_write_runtime"] = perf_counter() - db_write_start
            if was_inserted:
                logger.info("Report '%s' measurements inserted into the database.", self.file_name)
                return

            logger.info("Report '%s' already exists in the database.", self.file_name)
            return
        except Exception as e:
            self.log_and_exit(e)

    def _normalized_rows_for_persistence(self, use_native=False):
        if self._prepared_measurement_rows is not None:
            return self._prepared_measurement_rows

        return normalize_measurement_rows(
            self.blocks_text,
            reference=self.reference,
            fileloc=self.file_path,
            filename=self.file_name,
            date=self.date,
            sample_number=self.sample_number,
            use_native=use_native,
        )

    def prepare_for_two_stage_pipeline(self):
        """Prepare parser state and normalized rows for deferred single-writer persistence.

        This stage performs file open/parsing/token normalization work only and stores
        normalized rows on the parser instance so stage 2 can commit without re-parsing.
        """
        prepare_start = perf_counter()
        if not self.raw_text:
            self.open_report()
        if not self.blocks_text:
            self.split_text_to_blocks()
            self.add_tolerances()

        use_native_persistence = os.getenv("METROLIZA_CMM_NATIVE_PERSISTENCE", "0").strip() in {"1", "true", "yes", "on"}
        normalize_start = perf_counter()
        self._prepared_measurement_rows = normalize_measurement_rows(
            self.blocks_text,
            reference=self.reference,
            fileloc=self.file_path,
            filename=self.file_name,
            date=self.date,
            sample_number=self.sample_number,
            use_native=use_native_persistence,
        )
        self.stage_timings_s["normalize_runtime"] = perf_counter() - normalize_start
        self.stage_timings_s["prepare_pipeline_runtime"] = perf_counter() - prepare_start

    def persist_prepared_report(self):
        """Persist report data prepared during stage 1 of the two-stage pipeline.

        Falls back to legacy open+check behavior when preparation did not complete.
        """
        if not self.blocks_text:
            return self.open_database_and_check_filename()

        return self.to_sqlite()

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
