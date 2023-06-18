import fitz
import pandas
import sqlite3
import time
import re
from pathlib import Path


class CMMReport:
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
        self.pdf_raw_text = []
        self.pdf_blocks_text = []
        self.df = pandas.DataFrame()
        self.database = database

        # self.open_database_and_check_filename()
        
    def get_file_path_from_filename(self, pdf_file_path: str):
        """
        Retrieves the file path from the given PDF file path.

        Args:
            pdf_file_path (str): The path of the PDF file.

        Returns:
            str: The absolute parent directory path of the PDF file.

        """
        return str(Path(pdf_file_path).absolute().parent)
   
    def get_file_name_from_filename(self, pdf_file_path: str):
        """
        Retrieves the file name from the given PDF file path.

        Args:
            pdf_file_path (str): The path of the PDF file.

        Returns:
            str: The file name of the PDF file.

        """
        return str(Path(pdf_file_path).name)

    def get_date_from_filename(self):
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
   
    def get_reference_from_filename(self):
        """
        Retrieves the reference from the filename using regular expressions.

        Returns:
            str: The extracted reference from the filename,
            or "REF?" if no reference is found.

        """
        reference_pattern = r"([A-Z][A-Za-z0-9]{4}\d{1,5}(_\d{3})?)|(\d{2}[A-Za-z][._-]?\d{3}[._-]?\d{3})|(216\d{5})"
        reference_match = re.match(reference_pattern, self.pdf_file_name)
        reference_match = reference_match.group(0) if reference_match else "REF?"
        return reference_match

    def open_database_and_check_filename(self):
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

        with sqlite3.connect(self.database) as conn:
            with conn:
                cursor = conn.cursor()

                # Check if 'REPORTS' table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='REPORTS'")
                table_exists = cursor.fetchone()

                if table_exists is None:
                    print("REPORTS table does not exist. Creating...")
                    open_split_to_sql()
                    return

                # Check if the file already exists in the 'REPORTS' table
                cursor.execute('SELECT COUNT(*) FROM REPORTS WHERE FILENAME = ?', (self.pdf_file_name,))
                count = cursor.fetchone()[0]

                if count == 0:
                    # File does not exist in the 'REPORTS' table, import the data
                    open_split_to_sql()
                else:
                    print(f"{self.pdf_file_name} already exists in the database. Skipping the file.")

    def cmm_open(self):
        """
        Method to open the CMM PDF file and store the text inside the pdf_raw_text attribute.

        It uses the PyMuPDF library (fitz) to open the PDF file and extract the text from each page.

        """
        with fitz.open(f"{self.pdf_file_path}\{self.pdf_file_name}") as pdf_report:
            for page in pdf_report:
                page_text = page.get_text().splitlines()
                for line in page_text:
                    self.pdf_raw_text.append(line)

    def show_raw_text(self):
        """
        Method to print the raw text inside the PDF.

        It iterates over each line of text in the pdf_raw_text attribute and prints it.

        """
        for line in self.pdf_raw_text:
            print(line)

    def show_blocks_text(self):
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

    def show_blocks_text2(self):
        """
        Method to print the pdf_blocks_text - blocks of measurements.

        It iterates over each block in the pdf_blocks_text attribute and prints the entire block as a string.
        Each block is surrounded by markers indicating the beginning and end of the block.

        """
        for block in self.pdf_blocks_text:
            print("\n___[BEGINNING OF BLOCK]___")
            print(f"{block}")
            print(f"___[END OF BLOCK ({len(block)=})]___\n")
               
    def split_text_to_blocks(self):
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
                processed_line = [line[0], float(line[1]), float(line[2]), "", float(line[3]), float(line[4]), float(line[5]), float(line[6])]

            elif line[0] == "PR" and len(line) == 7:
                processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

            elif line[0] == "PR" and len(line) == 4:
                processed_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]

            elif line[0] == "PA" and len(line) == 4:
                processed_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]

            elif line[0] == "D1" and len(line) == 5 and line[1].isnumeric():
                processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), "", ""]
                
            return processed_line
       
        def extract_numerical_lines(lines):
            """Creates list with numerical values from the line and calculates how many lines can be skipped"""
            prefixes = ["X", "Y", "Z", "TP", "M", "D", "RN", "DF", "PR", "PA", "D1"]
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
            "D1": 5
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
  
    def to_dict(self):
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

    def to_df(self):
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

    def to_sqlite(self):
        """
        Creates tables (if necessary) and inserts measurements and reports data into an SQLite database.
        """
        # Check if there are measurements data
        if not any(lst[1] for lst in self.pdf_blocks_text):
            print("No measurements data available. Skipping database insertion.")
            return
        
        with sqlite3.connect(self.database) as conn:
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
                                    DATE TEXT
                                )''')

                # Check if the report already exists in the database
                cursor.execute('SELECT COUNT(*) FROM REPORTS WHERE REFERENCE = ? AND FILELOC = ? AND FILENAME = ? AND DATE = ?', 
                            (self.pdf_reference, self.pdf_file_path, self.pdf_file_name, self.pdf_date))
                count = cursor.fetchone()[0]

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
                        cursor.execute('INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE) VALUES (?, ?, ?, ?)', 
                                    (self.pdf_reference, self.pdf_file_path, self.pdf_file_name, self.pdf_date))
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

                        print(f'Report ({self.pdf_file_name}) and measurements inserted into the database.')
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
                    
    def show_df(self):
        """Prints the dataframe with measurements"""
        print(f"{self.df}")
                  
