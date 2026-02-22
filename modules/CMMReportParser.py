import importlib.metadata
import importlib.util


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

import pandas
import re
import sqlite3
import time
from pathlib import Path
from modules.CustomLogger import CustomLogger
from modules.db import connect_sqlite, execute_with_retry


class CMMReportParser:
    """Class to parse and convert PDF CMM report."""

    def __init__(self, pdf_file_path: str, database: str):
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
                "SELECT name FROM sqlite_master WHERE type='table' AND name='REPORTS'"
            )

            if not table_exists:
                print("REPORTS table does not exist. Creating...")
                open_split_to_sql()
                return

            # Check if the file already exists in the 'REPORTS' table
            count_rows = execute_with_retry(
                self.database,
                'SELECT COUNT(*) FROM REPORTS WHERE FILENAME = ?',
                (self.pdf_file_name,),
            )
            count = count_rows[0][0] if count_rows else 0

            if count == 0:
                # File does not exist in the 'REPORTS' table, import the data
                open_split_to_sql()
            else:
                print(f"{self.pdf_file_name} already exists in the database. Skipping the file.")
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
                print(line)
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
                print("\n___[BEGINNING OF BLOCK]___")
                for line in block:
                    print(f"{line} ({len(line)=}")
                print(f"___[END OF BLOCK ({len(block)=})]___\n")
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
                print("\n___[BEGINNING OF BLOCK]___")
                print(f"{block}")
                print(f"___[END OF BLOCK ({len(block)=})]___\n")
        except Exception as e:
            self.log_and_exit(e)

    def split_text_to_blocks(self):
        try:
            """Method to split raw text from pdf to blocks - split by measurements"""
            def is_comment_or_header(line):
                """Check if line is a comment or header"""
                return line.startswith(('#', '*'))

            def is_dim_line(line):
                """Check if line is a DIM header"""
                return line.startswith("DIM")

            def process_line(line):
                """Process measurement line"""
                processed_line = []

                if (line[0] == "X" or line[0] == "Y" or line[0] == "Z") and len(line) == 4:
                    processed_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]

                elif (line[0] == "X" or line[0] == "Y" or line[0] == "Z") and len(line) == 7:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                elif line[0] == "TP" and len(line) == 6:
                    processed_line = [line[0], float(line[1]), float(line[2]), "", float(line[3]), float(line[4]), float(line[4]), float(line[5])]

                elif line[0] == "TP" and len(line) == 7:
                    processed_line = [line[0], float(line[1]), float(line[2]), "", float(line[3]), float(line[4]), float(line[5]), float(line[6])]

                elif line[0] == "M" and len(line) == 7:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                elif line[0] == "M" and len(line) == 8:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), float(line[4]), float(line[5]), float(line[6]), float(line[7])]

                elif line[0] == "D" and len(line) == 7:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                elif line[0] == "RN" and len(line) == 7:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                elif line[0] == "DF" and len(line) == 8:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), float(line[4]), float(line[5]), float(line[6]), float(line[7])]

                elif line[0] == "DF" and len(line) == 7:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "0", float(line[4]), float(line[5]), float(line[6])]

                elif line[0] == "PR" and len(line) == 7:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                elif line[0] == "PR" and len(line) == 4:
                    processed_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]

                elif line[0] == "PA" and len(line) == 4:
                    processed_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]

                elif line[0] == "D1" and len(line) == 5 and line[1].isnumeric():
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), "", ""]
                
                elif line[0] == "A" and len(line) == 7:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "0", float(line[4]), float(line[5]), float(line[6])]

                return processed_line

            def extract_numerical_lines(lines):
                """Creates list with numerical values from the line and calculates how many lines can be skipped"""
                prefixes = ["X", "Y", "Z", "TP", "M", "D", "RN", "DF", "PR", "PA", "D1", "A"]
                numerical_lines = []
                counter = 0

                for i, line in enumerate(lines):
                    if any(line.startswith(p) for p in prefixes) and not i:
                        numerical_lines.append(line)
                    elif not is_numerical(line):
                        counter = i - 1
                        break
                    else:
                        numerical_lines.append(line)

                return numerical_lines, counter

            def extract_header_comment(lines):
                """Creates list with headers from the lines and calculates how many lines can be skipped"""
                header = []
                counter = 0
                for i, line in enumerate(lines):
                    if not is_dim_line(line):
                        if i:
                            line = line.replace('#', '').replace('*', '')
                        header.append(line)
                    else:
                        counter = i - 1
                        break
                header = " ".join(header)
                return header, counter

            def is_numerical(line):
                try:
                    float(line.strip())
                    return True
                except ValueError:
                    return False

            def is_number(value):
                try:
                    float(value)
                    return True
                except ValueError:
                    return False

            measurement_line_map = {
                "X": 7,
                "Y": 7,
                "Z": 7,
                "TP": 7,
                "M": 8,
                "D": 7,
                "RN": 7,
                "DF": 8,
                "PR": 7,
                "PA": 4,
                "D1": 5,
                "A": 7,
            }
            text_block = []
            dim_block = []
            header_comment = []
            counter = 0

            for index, line in enumerate(self.pdf_raw_text):
                # Skip lines if there is an ongoing counter
                if counter:
                    counter = counter - 1
                    continue

                # Extract header comment if the line is a comment or header
                if is_comment_or_header(line):
                    line, counter = extract_header_comment(self.pdf_raw_text[index:index+10])

                # Check if it's the last line and append the current text block
                if index == len(self.pdf_raw_text) - 1:
                    if text_block:
                        text_block = [header_comment] + [dim_block]
                        self.pdf_blocks_text.append(text_block)
                        text_block, header_comment, dim_block = [], [], []

                # Check if the line is not a comment or header
                if not is_comment_or_header(line):
                    # Skip lines with three words (potential measurement lines)
                    if len(line.split()) == 3:
                        continue

                # Process lines within a text block
                if text_block:
                    if is_comment_or_header(line) or is_dim_line(line):
                        # Check if the line is a comment or header
                        if is_comment_or_header(line) and self.pdf_raw_text[index-1] and is_comment_or_header(self.pdf_raw_text[index-1]):
                            formatted_line = re.sub(r'^[#*/]+', '', line).strip()
                            header_comment.append([formatted_line])

                        # Check if the line is a DIM header
                        if is_dim_line(line) and self.pdf_raw_text[index-1] and not is_comment_or_header(self.pdf_raw_text[index-1]):
                            text_block = [header_comment] + [dim_block]
                            self.pdf_blocks_text.append(text_block)
                            text_block, dim_block = [], []
                            text_block.append(header_comment)

                        # Check if the line is a comment or header
                        if is_comment_or_header(line) and self.pdf_raw_text[index-1] and not is_comment_or_header(self.pdf_raw_text[index-1]):
                            text_block = [header_comment] + [dim_block]
                            self.pdf_blocks_text.append(text_block)
                            text_block, header_comment, dim_block = [], [], []
                            formatted_line = re.sub(r'^[#*/]+', '', line).strip()
                            header_comment.append([formatted_line])
                            text_block.append(header_comment)

                    else:
                        if line in measurement_line_map:
                            # Extract the following lines based on the measurement line map
                            next_lines = self.pdf_raw_text[index:index+measurement_line_map[line]]
                            line_split = []
                            for item in next_lines:
                                line_split.extend(item.split())
                                
                            if line_split[0] == "TP":
                                line_split[1] = "0"
                                if not is_number(line_split[3]):
                                    line_split.pop(3)
                                    line_split.pop(3)
                                    line_split.append(line_split[-1])
                                    if float(line_split[4]) > float(line_split[2]):
                                        line_split.append(str(float(line_split[4]) - float(line_split[2])))
                                    else:
                                        line_split.append("0")
                            next_lines, counter = extract_numerical_lines(line_split)
                            temp_line = process_line(next_lines)
                            if temp_line:
                                dim_block.append(temp_line)

                # Process lines outside a text block
                else:
                    if not self.pdf_blocks_text:
                        # Check if the line is a comment or header
                        if is_comment_or_header(line):
                            formatted_line = re.sub(r'^[#*/]+', '', line).strip()
                            header_comment.append([formatted_line])
                            text_block.append(header_comment)
                        # Check if the line is a DIM header
                        elif is_dim_line(line):
                            header_comment.append("NO HEADER")
                            text_block.append(header_comment)
                    else:
                        # Check if the line is a DIM header or comment
                        if is_dim_line(line) or is_comment_or_header(line):
                            text_block = [header_comment] + [dim_block]
                            self.pdf_blocks_text.append(text_block)
                            text_block, dim_block = [], []
                        # Check if the line is a comment
                        if is_comment_or_header(line):
                            text_block, header_comment, dim_block = [], [], []
                            formatted_line = re.sub(r'^[#*/]+', '', line).strip()
                            header_comment.append([formatted_line])
                            
            self.add_tolerances()
        except Exception as e:
            self.log_and_exit(e)

    def add_tolerances(self):
        try:
            for block in self.pdf_blocks_text:
                tol_plus = 0
                tol_minus = 0
                bonus = 0
                if block[1]:
                    if block[1][-1][0] == 'TP':
                        # Fill -TOL with 0
                        block[1][-1][3] = 0
                        
                        # Get +TOL from TP and apply it as +/- tolerance
                        tol_plus = block[1][-1][2] * 0.5
                        tol_minus = -tol_plus
                        
                        #Get tolerance bonus from TP
                        bonus = block[1][-1][4]
                        
                        for measurement_line in block[1]:
                            if not measurement_line[2]:
                                measurement_line[2] = tol_plus
                                measurement_line[3] = tol_minus
                                measurement_line[4] = bonus
                    else:
                        for measurement_line in block[1]:
                            if not measurement_line[2]:
                                measurement_line[2] = tol_plus
                            elif not measurement_line[3]:
                                measurement_line[3] = tol_minus
                            elif not measurement_line[4]:
                                measurement_line[4] = bonus
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
                print(f"Report ({self.pdf_file_name}) - no measurements data available. Skipping database insertion.")
                return

            with connect_sqlite(self.database) as conn:
                with conn:
                    cursor = conn.cursor()

                    # Create MEASUREMENTS table if it doesn't exist
                    cursor.execute('''CREATE TABLE IF NOT EXISTS MEASUREMENTS (
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

                    # Create REPORTS table if it doesn't exist
                    cursor.execute('''CREATE TABLE IF NOT EXISTS REPORTS (
                                        ID INTEGER PRIMARY KEY,
                                        REFERENCE TEXT,
                                        FILELOC TEXT,
                                        FILENAME TEXT,
                                        DATE TEXT,
                                        SAMPLE_NUMBER TEXT
                                    )''')

                    # Check if the report already exists in the database
                    count_rows = execute_with_retry(
                        self.database,
                        'SELECT COUNT(*) FROM REPORTS WHERE REFERENCE = ? AND FILELOC = ? AND FILENAME = ? AND DATE = ? AND SAMPLE_NUMBER = ?',
                        (self.pdf_reference, self.pdf_file_path, self.pdf_file_name, self.pdf_date, self.pdf_sample_number),
                    )
                    count = count_rows[0][0] if count_rows else 0

                    if count > 0:
                        print(f'Report ({self.pdf_file_name}) already exists in the database.')
                        return

                    # Retry mechanism for handling database lock
                    max_retry_attempts = 5
                    retry_delay = 1  # seconds
                    retry_attempt = 1

                    while retry_attempt <= max_retry_attempts:
                        try:
                            # Attempt to insert report data into the REPORTS table
                            cursor.execute('INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                                        (self.pdf_reference, self.pdf_file_path, self.pdf_file_name, self.pdf_date, self.pdf_sample_number))
                            report_id = cursor.lastrowid

                            # Insert measurements data into the MEASUREMENTS table
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

                                rows = [(None, row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], table_name, report_id) for row in lst[1]]
                                cursor.executemany('INSERT INTO MEASUREMENTS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)

                            print(f'Report ({self.pdf_file_name}) - measurements inserted into the database.')
                            return

                        except sqlite3.OperationalError as e:
                            error_message = str(e)
                            if 'database is locked' in error_message:
                                print(f"Database is locked. Retrying attempt {retry_attempt}...")
                                retry_attempt += 1
                                time.sleep(retry_delay)
                            else:
                                print(f"Error occurred: {error_message}.")  # Handle other database errors

                    print(f"Failed to insert data into the database after {max_retry_attempts} attempts.")
                    return
        except Exception as e:
            self.log_and_exit(e)

    def show_df(self):
        try:
            """Prints the dataframe with measurements"""
            print(f"{self.df}")
        except Exception as e:
            self.log_and_exit(e)
            
    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
