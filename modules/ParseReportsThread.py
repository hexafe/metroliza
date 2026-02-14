from modules.CMMReportParser import CMMReportParser
from modules.CustomLogger import CustomLogger
from PyQt6.QtCore import QThread, pyqtSignal
import sqlite3
import time
from pathlib import Path
from modules.report_fingerprint import build_report_fingerprint, build_parser_fingerprint


class ParseReportsThread(QThread):
    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    parsing_finished = pyqtSignal()

    def __init__(self, directory, db_file):
        super().__init__()

        # Initialize the thread with the provided directory and database file
        self.directory = directory
        self.db_file = db_file
        self.parsing_canceled = False

    def get_list_of_reports(self):
        try:
            pdf_files = []
            for path in Path(self.directory).glob("**/*.[Pp][Dd][Ff]"):
                if path.is_file() and path.stat().st_size:
                    pdf_files.append(path)
            return pdf_files
        except Exception as e:
            self.log_and_exit(e)

    def get_report_fingerprints_in_database(self):
        try:
            # Create a set to store report fingerprints
            report_fingerprints = set()

            # Connect to the SQLite database
            with sqlite3.connect(self.db_file) as conn:
                # Create a cursor object
                with conn:
                    # Retry mechanism for handling database lock
                    max_retry_attempts = 5
                    retry_delay = 1  # seconds
                    retry_attempt = 1
                    while retry_attempt <= max_retry_attempts:
                        try:
                            cursor = conn.cursor()

                            # Check if 'REPORTS' table exists
                            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='REPORTS'")
                            result = cursor.fetchone()

                            if result:
                                # 'REPORTS' table exists, fetch report identity columns
                                cursor.execute("SELECT ID, REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER FROM REPORTS")
                                rows = cursor.fetchall()

                                for row in rows:
                                    report = {
                                        'ID': row[0],
                                        'REFERENCE': row[1],
                                        'FILELOC': row[2],
                                        'FILENAME': row[3],
                                        'DATE': row[4],
                                        'SAMPLE_NUMBER': row[5],
                                    }
                                    report_fingerprints.add(build_report_fingerprint(report))

                            # Return report fingerprints
                            return report_fingerprints

                        except sqlite3.OperationalError as e:
                            error_message = str(e)
                            if 'database is locked' in error_message:
                                print(f"Database is locked. Retrying attempt {retry_attempt}...")
                                retry_attempt += 1
                                time.sleep(retry_delay)
                            else:
                                print(f"Error occurred: {error_message}.")  # Handle other database errors

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
            # Get the list of reports from the provided directory
            list_of_reports = self.get_list_of_reports()
            report_fingerprints = self.get_report_fingerprints_in_database()
            total_files = len(list_of_reports)
            parsed_files = 0

            # Loop through each report and parse it
            for report in list_of_reports:
                if self.parsing_canceled:
                    break

                cmm_report = CMMReportParser(report, self.db_file)
                fingerprint = build_parser_fingerprint(cmm_report)
                if fingerprint not in report_fingerprints:
                    cmm_report.open_database_and_check_filename()
                    report_fingerprints.add(fingerprint)
                parsed_files += 1

                # Calculate the percentage of parsed files and emit the progress signal
                percentage = int(parsed_files / total_files * 100)
                self.update_progress.emit(percentage)

                # Update the label with the current parsing status
                self.update_label.emit(f"Parsing file {parsed_files} of {total_files}")

            # Emit the signal indicating that parsing has finished
            self.parsing_finished.emit()
        except Exception as e:
            self.log_and_exit(e)
        
    def log_and_exit(self, exception):
        CustomLogger(exception)
