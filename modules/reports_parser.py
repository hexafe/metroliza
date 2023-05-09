import pdfplumber
import fitz
import pandas
import sqlite3
import re
from pathlib import Path


class CMMReport_pdfplumber:
    """Class to parse and conver pdf CMM report"""

    def __init__(self, pdf_file_path: str, database: str):
        """Creates object of CMMReport class"""
        self.pdf_file_path = str(Path(pdf_file_path).absolute().parent)
        self.pdf_file_name = str(Path(pdf_file_path).name)
        self.pdf_raw_text = []
        self.pdf_blocks_text = []
        self.df = pandas.DataFrame()
        self.pdf_date = ""
        self.database = "pdfplumber_" + database

        self.open_database_and_check_filename()
        # self.cmm_open()
        # self.split_text_to_blocks()
        # self.to_sqlite()

    def open_database_and_check_filename(self):
        """Checks if opened file is already in database"""
        def open_split_2sql():
            # pdfplumber_start_time = time.time()
            self.cmm_open_pdfplumber()
            self.split_text_to_blocks_pdfplumber()
            self.to_sqlite()
            # pdfplumber_end_time = time.time()
            # pdfplumber_running_time = pdfplumber_end_time - pdfplumber_start_time
            # print(f"runtime for pdfplumber: {pdfplumber_running_time}s")
            
            # PyMuPDF_start_time = time.time()
            # self.cmm_open_pymupdf()
            # self.split_text_to_blocks_pymupdf()
            # self.to_sqlite()
            # PyMuPDF_end_time = time.time()
            # PyMuPDF_running_time = PyMuPDF_end_time - PyMuPDF_start_time
            # print(f"runtime for PyMuPDF: {PyMuPDF_running_time}s, which is {pdfplumber_running_time/PyMuPDF_running_time}x faster!")
            
        with sqlite3.connect(self.database) as conn:
            with conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='REPORTS'")
                table_exists = cursor.fetchone()

                if table_exists is None:
                    print("REPORTS table does not exist. Creating...")
                    open_split_2sql()
                    return

                cursor.execute('SELECT COUNT(*) FROM REPORTS WHERE FILENAME = ?', (self.pdf_file_name,))
                count = cursor.fetchone()[0]

                if count == 0:
                    open_split_2sql()
                else:
                    print(f"{self.pdf_file_name} already exists in the database. Skipping the file.")

    def cmm_open_pdfplumber(self):
        """Method to open CMM pdf file and store text inside pdf_raw_text attribute"""
        with pdfplumber.open(f"{self.pdf_file_path}\{self.pdf_file_name}") as pdf_report:
            for page in pdf_report.pages:
                page_text = page.extract_text().splitlines()
                for line in page_text:
                    self.pdf_raw_text.append(line)
            date_pattern = r"\d{4}[- _/\.]\d{1,2}[- _/\.]\d{1,2}"
            matches = re.findall(date_pattern, self.pdf_file_name)
            if matches:
                self.pdf_date = matches[-1]
            else:
                self.pdf_date = "0000.00.00"
            self.pdf_date = self.pdf_date.replace(".", "-").replace("_", "-").replace("/", "-")
    
    def show_raw_text(self):
        """Method to print raw text inside pdf"""
        for line in self.pdf_raw_text:
            print(line)

    def show_blocks_text(self):
        """Method to print pdf_blocks_text - blocks of measurements"""
        for block in self.pdf_blocks_text:
            print("\n___[BEGINNING OF BLOCK]___")
            for line in block:
                print(f"{line} ({len(line)=})")
            print(f"___[END OF BLOCK ({len(block)=})]___\n")
            
    def show_blocks_text2(self):
        """Method to print pdf_blocks_text - blocks of measurements"""
        for block in self.pdf_blocks_text:
            print("\n___[BEGINNING OF BLOCK]___")
            print(f"{block}")
            print(f"___[END OF BLOCK ({len(block)=})]___\n")

    def split_text_to_blocks_pdfplumber(self):
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
            
            if line:
                line = line.split()
                line = [item for item in line if not (item.startswith("--") or item.startswith("-#") or item.startswith("#-") or item.startswith("<-"))]

                if (line[0] == "X" or line[0] == "Y" or line[0] == "Z") and len(line) == 4:
                    processed_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]

                elif (line[0] == "X" or line[0] == "Y" or line[0] == "Z") and len(line) == 7:
                    processed_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                elif line[0] == "TP" and len(line) == 7:
                    processed_line = [line[0], "", float(line[2]), "", float(line[3]), float(line[4]), float(line[5]), float(line[6])]

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
        
        text_block = []
        dim_block = []
        header_comment = []
        
        for index, line in enumerate(self.pdf_raw_text):
            if index == len(self.pdf_raw_text) - 1:
                if text_block:
                    text_block = [header_comment] + [dim_block]
                    self.pdf_blocks_text.append(text_block)
                    text_block, header_comment, dim_block = [], [], []
                    
            if not is_comment_or_header(line):
                if len(line.split()) == 3:
                    continue

            if text_block:
                if is_comment_or_header(line) or is_dim_line(line):
                    if is_comment_or_header(line) and self.pdf_raw_text[index-1] and is_comment_or_header(self.pdf_raw_text[index-1]):
                        formatted_line = re.sub(r'^[#*]+', '', line).strip()
                        header_comment.append([formatted_line])
                    
                    if is_dim_line(line) and self.pdf_raw_text[index-1] and not is_comment_or_header(self.pdf_raw_text[index-1]):
                        text_block = [header_comment] + [dim_block]
                        self.pdf_blocks_text.append(text_block)
                        text_block, dim_block = [], []
                        text_block.append(header_comment)
                        
                    if is_comment_or_header(line) and self.pdf_raw_text[index-1] and not is_comment_or_header(self.pdf_raw_text[index-1]):
                        text_block = [header_comment] + [dim_block]
                        self.pdf_blocks_text.append(text_block)
                        text_block, header_comment, dim_block = [], [], []
                        formatted_line = re.sub(r'^[#*]+', '', line).strip()
                        header_comment.append([formatted_line])
                        text_block.append(header_comment)
                    
                else:                  
                    temp_line = process_line(line)
                    if temp_line:
                        dim_block.append(temp_line)
                               
            else:
                if not self.pdf_blocks_text:
                    if is_comment_or_header(line):
                        formatted_line = re.sub(r'^[#*]+', '', line).strip()
                        header_comment.append([formatted_line])
                        text_block.append(header_comment)
                
                else:
                    if is_dim_line(line):
                        text_block = [header_comment] + [dim_block]
                        self.pdf_blocks_text.append(text_block)
                        text_block, dim_block = [], []
                        
                    if is_comment_or_header(line):
                        text_block = [header_comment] + [dim_block]
                        self.pdf_blocks_text.append(text_block)
                        text_block, header_comment, dim_block = [], [], []
                        formatted_line = re.sub(r'^[#*]+', '', line).strip()
                        header_comment.append([formatted_line])
                         
    def to_dict(self):
        pass

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
            df['File location'] = self.pdf_file_path
            df['File name'] = self.pdf_file_name
            df['Date'] = self.pdf_date
            df_list.append(df)

        if df_list:
            self.df = pandas.concat(df_list)
         
    def to_sqlite(self):
        """Creates tables (if necessary) and insert measurements and reports data"""
        with sqlite3.connect(self.database) as conn:
            with conn:
                cursor = conn.cursor()

                cursor.execute('CREATE TABLE IF NOT EXISTS MEASUREMENTS (ID INTEGER PRIMARY KEY, AX TEXT, NOM REAL, "+TOL" REAL, "-TOL" REAL, BONUS REAL, MEAS REAL, DEV REAL, OUTTOL REAL, HEADER TEXT, REPORT_ID INTEGER, FOREIGN KEY (REPORT_ID) REFERENCES REPORTS(ID))')
                cursor.execute('CREATE TABLE IF NOT EXISTS REPORTS (ID INTEGER PRIMARY KEY, FILELOC TEXT, FILENAME TEXT, DATE TEXT)')

                cursor.execute('SELECT COUNT(*) FROM REPORTS WHERE FILELOC = ? AND FILENAME = ? AND DATE = ?', (self.pdf_file_path, self.pdf_file_name, self.pdf_date))
                count = cursor.fetchone()[0]

                if count > 0:
                    print(f'Report ({self.pdf_file_name}) already exists in database.')
                    return

                cursor.execute('INSERT INTO REPORTS (FILELOC, FILENAME, DATE) VALUES (?, ?, ?)', (self.pdf_file_path, self.pdf_file_name, self.pdf_date))
                report_id = cursor.lastrowid

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
                    
                print(f'Report ({self.pdf_file_name}) and measurements inserted into database.')
                           
    def show_df(self):
        """Method to print dataframe with measurements"""
        print(f"{self.df}")
                  
    def export_to_excel(self):
        """Method to export generated DataFrame to Excel file"""
        ###TODO: something more elegant
        self.df.to_excel("dump.xlsx", index=False)

class CMMReport_pymupdf:
    """Class to parse and conver pdf CMM report"""

    def __init__(self, pdf_file_path: str, database: str):
        """Creates object of CMMReport class"""
        self.pdf_file_path = self.get_file_path_from_filename(pdf_file_path)
        self.pdf_file_name = self.get_file_name_from_filename(pdf_file_path)
        self.pdf_date = self.get_date_from_filename()
        self.pdf_reference = self.get_reference_from_filename()
        self.pdf_raw_text = []
        self.pdf_blocks_text = []
        self.df = pandas.DataFrame()
        self.database = database

        self.open_database_and_check_filename()
        # self.cmm_open()
        # self.split_text_to_blocks()
        # self.to_sqlite()
        
    def get_file_path_from_filename(self, pdf_file_path: str):
        """Retrieves date from filename by using regex"""
        return str(Path(pdf_file_path).absolute().parent)
    
    def get_file_name_from_filename(self, pdf_file_path: str):
        """Retrieves date from filename by using regex"""
        return str(Path(pdf_file_path).name)
        
    def get_date_from_filename(self):
        """Retrieves date from filename by using regex"""
        date_pattern = r"\d{4}[- _/\.]\d{1,2}[- _/\.]\d{1,2}"
        date_match = re.findall(date_pattern, self.pdf_file_name)
        date_match = date_match[-1] if date_match else "0000.00.00"
        date_match = date_match.replace(".", "-").replace("_", "-").replace("/", "-")
        return date_match
    
    def get_reference_from_filename(self):
        """Retrieves reference from filename by using regex"""
        reference_pattern = r"([A-Z][A-Za-z0-9]{4}\d{1,5}(_\d{3})?)|(\d{2}[A-Za-z][._-]?\d{3}[._-]?\d{3})|(216\d{5})"
        reference_match = re.match(reference_pattern, self.pdf_file_name)
        reference_match = reference_match.group(0) if reference_match else "REF?"
        return reference_match

    def open_database_and_check_filename(self):
        """Checks if opened file is already in database"""
        def open_split_2sql():
            self.cmm_open_pymupdf()
            self.split_text_to_blocks_pymupdf()
            self.to_sqlite()
            
        with sqlite3.connect(self.database) as conn:
            with conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='REPORTS'")
                table_exists = cursor.fetchone()

                if table_exists is None:
                    print("REPORTS table does not exist. Creating...")
                    open_split_2sql()
                    return

                cursor.execute('SELECT COUNT(*) FROM REPORTS WHERE FILENAME = ?', (self.pdf_file_name,))
                count = cursor.fetchone()[0]

                if count == 0:
                    open_split_2sql()
                else:
                    print(f"{self.pdf_file_name} already exists in the database. Skipping the file.")
 
    def cmm_open_pymupdf(self):
        """Method to open CMM pdf file and store text inside pdf_raw_text attribute"""
        with fitz.open(f"{self.pdf_file_path}\{self.pdf_file_name}") as pdf_report:
            for page in pdf_report:
                page_text = page.get_text().splitlines()
                for line in page_text:
                    self.pdf_raw_text.append(line)

    def show_raw_text(self):
        """Method to print raw text inside pdf"""
        for line in self.pdf_raw_text:
            print(line)

    def show_blocks_text(self):
        """Method to print pdf_blocks_text - blocks of measurements"""
        for block in self.pdf_blocks_text:
            print("\n___[BEGINNING OF BLOCK]___")
            for line in block:
                print(f"{line} ({len(line)=})")
            print(f"___[END OF BLOCK ({len(block)=})]___\n")
            
    def show_blocks_text2(self):
        """Method to print pdf_blocks_text - blocks of measurements"""
        for block in self.pdf_blocks_text:
            print("\n___[BEGINNING OF BLOCK]___")
            print(f"{block}")
            print(f"___[END OF BLOCK ({len(block)=})]___\n")
                        
    def split_text_to_blocks_pymupdf(self):
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
       
        # def extract_numerical_lines(lines):
        #     prefixes = ["X", "Y", "Z", "TP", "M", "D", "RN", "DF", "PR", "PA", "D1"]
        #     numerical_lines = []
        #     counter = 0
        #     for i in range(len(lines)):
        #         line = lines[i]
        #         if any(line.startswith(p) for p in prefixes) and not i:
        #             numerical_lines.append(line)
        #         elif is_numerical(line):
        #             numerical_lines.append(line)
        #         else:
        #             counter = i - 1
        #             break
        #     return numerical_lines, counter
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
            if counter:
                counter = counter - 1
                continue
            if is_comment_or_header(line):
                line, counter = extract_header_comment(self.pdf_raw_text[index:index+10])
            if index == len(self.pdf_raw_text) - 1:
                if text_block:
                    text_block = [header_comment] + [dim_block]
                    self.pdf_blocks_text.append(text_block)
                    text_block, header_comment, dim_block = [], [], []
                    
            if not is_comment_or_header(line):
                if len(line.split()) == 3:
                    continue

            if text_block:
                if is_comment_or_header(line) or is_dim_line(line):
                    if is_comment_or_header(line) and self.pdf_raw_text[index-1] and is_comment_or_header(self.pdf_raw_text[index-1]):
                        formatted_line = re.sub(r'^[#*/]+', '', line).strip()
                        header_comment.append([formatted_line])
                    
                    if is_dim_line(line) and self.pdf_raw_text[index-1] and not is_comment_or_header(self.pdf_raw_text[index-1]):
                        text_block = [header_comment] + [dim_block]
                        self.pdf_blocks_text.append(text_block)
                        text_block, dim_block = [], []
                        text_block.append(header_comment)
                        
                    if is_comment_or_header(line) and self.pdf_raw_text[index-1] and not is_comment_or_header(self.pdf_raw_text[index-1]):
                        text_block = [header_comment] + [dim_block]
                        self.pdf_blocks_text.append(text_block)
                        text_block, header_comment, dim_block = [], [], []
                        formatted_line = re.sub(r'^[#*/]+', '', line).strip()
                        header_comment.append([formatted_line])
                        text_block.append(header_comment)
                    
                else:
                    if line in measurement_line_map:
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
                               
            else:
                if not self.pdf_blocks_text:
                    if is_comment_or_header(line):
                        formatted_line = re.sub(r'^[#*/]+', '', line).strip()
                        header_comment.append([formatted_line])
                        text_block.append(header_comment)
                
                else:
                    if is_dim_line(line):
                        text_block = [header_comment] + [dim_block]
                        self.pdf_blocks_text.append(text_block)
                        text_block, dim_block = [], []
                        
                    if is_comment_or_header(line):
                        text_block = [header_comment] + [dim_block]
                        self.pdf_blocks_text.append(text_block)
                        text_block, header_comment, dim_block = [], [], []
                        formatted_line = re.sub(r'^[#*/]+', '', line).strip()
                        header_comment.append([formatted_line])
    
    def to_dict(self):
        pass

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
        """Creates tables (if necessary) and insert measurements and reports data"""
        with sqlite3.connect(self.database) as conn:
            with conn:
                cursor = conn.cursor()

                cursor.execute('CREATE TABLE IF NOT EXISTS MEASUREMENTS (ID INTEGER PRIMARY KEY, AX TEXT, NOM REAL, "+TOL" REAL, "-TOL" REAL, BONUS REAL, MEAS REAL, DEV REAL, OUTTOL REAL, HEADER TEXT, REPORT_ID INTEGER, FOREIGN KEY (REPORT_ID) REFERENCES REPORTS(ID))')
                cursor.execute('CREATE TABLE IF NOT EXISTS REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT, FILELOC TEXT, FILENAME TEXT, DATE TEXT)')

                cursor.execute('SELECT COUNT(*) FROM REPORTS WHERE REFERENCE = ? AND FILELOC = ? AND FILENAME = ? AND DATE = ?', (self.pdf_reference, self.pdf_file_path, self.pdf_file_name, self.pdf_date))
                count = cursor.fetchone()[0]

                if count > 0:
                    print(f'Report ({self.pdf_file_name}) already exists in database.')
                    return

                cursor.execute('INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE) VALUES (?, ?, ?, ?)', (self.pdf_reference, self.pdf_file_path, self.pdf_file_name, self.pdf_date))
                report_id = cursor.lastrowid

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
                    
                print(f'Report ({self.pdf_file_name}) and measurements inserted into database.')
                           
    def show_df(self):
        """Method to print dataframe with measurements"""
        print(f"{self.df}")
                  
    def export_to_excel(self):
        """Method to export generated DataFrame to Excel file"""
        ###TODO: something more elegant
        self.df.to_excel("dump.xlsx", index=False)
