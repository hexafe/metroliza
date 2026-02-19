from modules.CMMReportParser import CMMReportParser
from modules.CustomLogger import CustomLogger
from PyQt6.QtCore import QThread, pyqtSignal
from dataclasses import dataclass
from pathlib import Path
from modules.report_fingerprint import build_report_fingerprint, build_parser_fingerprint
from modules.contracts import ParseRequest, validate_parse_request
from modules.db import execute_with_retry


@dataclass(frozen=True)
class ParseBatchResult:
    parsed_files: int
    total_files: int


def build_report_fingerprints_from_rows(rows, should_cancel=lambda: False):
    report_fingerprints = set()
    for row in rows:
        if should_cancel():
            break
        report = {
            'ID': row[0],
            'REFERENCE': row[1],
            'FILELOC': row[2],
            'FILENAME': row[3],
            'DATE': row[4],
            'SAMPLE_NUMBER': row[5],
        }
        report_fingerprints.add(build_report_fingerprint(report))
    return report_fingerprints


def parse_new_reports(
    report_paths,
    report_fingerprints,
    parser_factory,
    persist_report,
    should_cancel=lambda: False,
    on_progress=None,
):
    parsed_files = 0
    total_files = len(report_paths)

    for report in report_paths:
        if should_cancel():
            break

        parser = parser_factory(report)
        fingerprint = build_parser_fingerprint(parser)
        if fingerprint not in report_fingerprints:
            persist_report(parser)
            report_fingerprints.add(fingerprint)
        parsed_files += 1

        if on_progress:
            on_progress(parsed_files, total_files)

    return ParseBatchResult(parsed_files=parsed_files, total_files=total_files)


class ParseReportsThread(QThread):
    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    parsing_finished = pyqtSignal()

    def __init__(self, parse_request: ParseRequest):
        super().__init__()

        validated_request = validate_parse_request(parse_request)

        # Initialize the thread with validated request values
        self.directory = validated_request.source_directory
        self.db_file = validated_request.db_file
        self.parsing_canceled = False

    def get_list_of_reports(self):
        try:
            pdf_files = []
            for path in Path(self.directory).glob("**/*.[Pp][Dd][Ff]"):
                if self.parsing_canceled:
                    break
                if path.is_file() and path.stat().st_size:
                    pdf_files.append(path)
            return pdf_files
        except Exception as e:
            self.log_and_exit(e)

    def get_report_fingerprints_in_database(self):
        try:
            # Create a set to store report fingerprints
            report_fingerprints = set()

            if self.parsing_canceled:
                return report_fingerprints

            table_exists = execute_with_retry(
                self.db_file,
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='REPORTS'",
                retries=5,
                retry_delay_s=1,
            )

            if not table_exists:
                return report_fingerprints

            rows = execute_with_retry(
                self.db_file,
                "SELECT ID, REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER FROM REPORTS",
                retries=5,
                retry_delay_s=1,
            )

            report_fingerprints.update(
                build_report_fingerprints_from_rows(rows, should_cancel=lambda: self.parsing_canceled)
            )

            # Return report fingerprints from fallback path
            return report_fingerprints
        except Exception as e:
            self.log_and_exit(e)

    def stop_parsing(self):
        try:
            # Set the flag to indicate parsing cancellation
            self.parsing_canceled = True
        except Exception as e:
            self.log_and_exit(e)

    def run(self):
        try:
            list_of_reports = self.get_list_of_reports()
            if self.parsing_canceled:
                self.parsing_finished.emit()
                return

            report_fingerprints = self.get_report_fingerprints_in_database()

            result = parse_new_reports(
                list_of_reports,
                report_fingerprints,
                parser_factory=lambda report: CMMReportParser(report, self.db_file),
                persist_report=lambda parser: parser.open_database_and_check_filename(),
                should_cancel=lambda: self.parsing_canceled,
                on_progress=lambda parsed_files, total_files: (
                    self.update_progress.emit(int(parsed_files / total_files * 100) if total_files else 100),
                    self.update_label.emit(f"Parsing file {parsed_files} of {total_files}"),
                ),
            )

            if result.total_files == 0:
                self.update_progress.emit(100)
                self.update_label.emit("No reports found to parse.")

            self.parsing_finished.emit()
        except Exception as e:
            self.log_and_exit(e)
        
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
