from modules.CMMReportParser import CMMReportParser
from PyQt5.QtCore import QThread, pyqtSignal
import sqlite3
import time
from pathlib import Path


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
        pdf_files = []
        for path in Path(self.directory).glob("**/*.[Pp][Dd][Ff]"):
            if path.is_file() and path.stat().st_size:
                pdf_files.append(path)
        return pdf_files

    def get_list_of_reports_in_database(self):
        # Create an empty list to store the reports
        list_of_reports_in_database = []

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
                            # 'REPORTS' table exists, fetch the list of filenames
                            cursor.execute("SELECT FILENAME FROM REPORTS")
                            rows = cursor.fetchall()

                            for row in rows:
                                # Extract report filename
                                filename = row[0]

                                # Append the filename to the list
                                list_of_reports_in_database.append(filename)

                        # Return the list of reports in the database
                        return list_of_reports_in_database

                    except sqlite3.OperationalError as e:
                        error_message = str(e)
                        if 'database is locked' in error_message:
                            print(f"Database is locked. Retrying attempt {retry_attempt}...")
                            retry_attempt += 1
                            time.sleep(retry_delay)
                        else:
                            print(f"Error occurred: {error_message}.")  # Handle other database errors

        # Return the list of reports in the database
        return list_of_reports_in_database

    def stop_parsing(self):
        # Set the flag to indicate parsing cancellation
        self.parsing_canceled = True

    def run(self):
        # Get the list of reports from the provided directory
        list_of_reports = self.get_list_of_reports()
        list_of_parsed_reports = self.get_list_of_reports_in_database()
        total_files = len(list_of_reports)
        parsed_files = 0

        # Loop through each report and parse it
        for report in list_of_reports:
            if self.parsing_canceled:
                break

            if report.name not in list_of_parsed_reports:
                cmm_report = CMMReportParser(report, self.db_file)
                cmm_report.open_database_and_check_filename()
            parsed_files += 1

            # Calculate the percentage of parsed files and emit the progress signal
            percentage = int(parsed_files / total_files * 100)
            self.update_progress.emit(percentage)

            # Update the label with the current parsing status
            self.update_label.emit(f"Parsing file {parsed_files} of {total_files}")

        # Emit the signal indicating that parsing has finished
        self.parsing_finished.emit()