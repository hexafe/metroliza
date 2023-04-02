import pdfplumber
import pandas
import sqlite3


class CMMReport:
    """Class to parse and conver pdf CMM report
    """

    def __init__(self, pdf_file_path: str):
        """Creates object of CMMReport class
        
            Args:
                (str) pdf_file_path: path to pdf file CMM report
        """
        self.pdf_file_path = pdf_file_path
        self.pdf_raw_text = []
        self.pdf_blocks_text = []
        self.headers_list = []
        self.df = pandas.DataFrame()

        self.cmm_open()
        self.split_text_to_blocks()

    def cmm_open(self):
        """Method to open CMM pdf file and store text inside pdf_raw_text attribute
            Combines all the pages
        """
        with pdfplumber.open(f"{self.pdf_file_path}") as pdf_report:
            for page in pdf_report.pages:
                page_text = page.extract_text().splitlines()
                for line in page_text:
                    self.pdf_raw_text.append(line)

    def show_raw_text(self):
        """Method to print raw text inside pdf
        """
        for line in self.pdf_raw_text:
            print(line)

    def show_blocks_text(self):
        """Method to print pdf_blocks_text - blocks of measurements
        """
        for block in self.pdf_blocks_text:
            print("\n___[BEGINNING OF BLOCK]___")
            for line in block:
                print(f"{line} ({len(line)=})")
            print(f"___[END OF BLOCK ({len(block)=})]___\n")
            
    def show_blocks_text2(self):
        """Method to print pdf_blocks_text - blocks of measurements
        """
        for block in self.pdf_blocks_text:
            print("\n___[BEGINNING OF BLOCK]___")
            print(f"{block}")
            print(f"___[END OF BLOCK ({len(block)=})]___\n")

    def split_text_to_blocks(self):
        """Method to split raw text from pdf to blocks - split by measurements
            Each block is created as follows:
            block[0] - header
            block[1] - dimensions
        """
        text_block = []
        block_headers = []
        dim_block = []
        prev_line = " "
        
        for index, line in enumerate(self.pdf_raw_text):
            if index == len(self.pdf_raw_text) - 1:
                if text_block:
                    text_block.append(dim_block)
                    text_block.insert(1, block_headers)
                    text_block.pop(0)
                    self.pdf_blocks_text.append(text_block)
                    text_block, block_headers, dim_block = [], [], []
                    block_headers.append([line])
                    
            if not line.startswith(('#', '*')):
                if len(line.split()) == 3:
                    continue

            if len(text_block) > 0:
                if line[0] in {"#", "*"}:
                    if prev_line and prev_line[0] in {"#", "*"}:
                        block_headers.append([line])
                        
                    else:
                        text_block.append(dim_block)
                        text_block.insert(1, block_headers)
                        text_block.pop(0)
                        self.pdf_blocks_text.append(text_block)
                        text_block, block_headers, dim_block = [], [], []
                        block_headers.append([line])

                elif line.startswith("DIM"):
                    if dim_block:
                        text_block.append(dim_block)
                        dim_block = []
                    block_headers.append([line])
                    
                else:
                    temp_line = []
                    line = line.split()
                    line = [item for item in line if not (item.startswith("--") or item.startswith("-#") or item.startswith("#-") or item.startswith("<-"))]

                    """
                    temp_line[0] = dimension symbol
                    temp_line[1] = NOM
                    temp_line[2] = +TOL
                    temp_line[3] = -TOL
                    temp_line[4] = BONUS
                    temp_line[5] = MEAS
                    temp_line[6] = DEV
                    temp_line[7] = OUTTOL
                    """

                    if (line[0] == "X" or line[0] == "Y" or line[0] == "Z") and len(line) == 4:
                        temp_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]

                    elif (line[0] == "X" or line[0] == "Y" or line[0] == "Z") and len(line) == 7:
                        temp_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                    elif line[0] == "TP" and len(line) == 7:
                        temp_line = [line[0], "", float(line[2]), "", float(line[3]), float(line[4]), float(line[5]), float(line[6])]

                    elif line[0] == "M" and len(line) == 7:
                        temp_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                    elif line[0] == "M" and len(line) == 8:
                        temp_line = [line[0], float(line[1]), float(line[2]), float(line[3]), float(line[4]), float(line[5]), float(line[6]), float(line[7])]

                    elif line[0] == "D" and len(line) == 7:
                        temp_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                    elif line[0] == "RN" and len(line) == 7:
                        temp_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                    elif line[0] == "DF" and len(line) == 8:
                        temp_line = [line[0], float(line[1]), float(line[2]), float(line[3]), float(line[4]), float(line[5]), float(line[6]), float(line[7])]
                        
                    elif line[0] == "DF" and len(line) == 7:
                        temp_line = [line[0], float(line[1]), float(line[2]), "", float(line[3]), float(line[4]), float(line[5]), float(line[6])]

                    elif line[0] == "PR" and len(line) == 7:
                        temp_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), float(line[5]), float(line[6])]

                    elif line[0] == "PR" and len(line) == 4:
                        temp_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]

                    elif line[0] == "PA" and len(line) == 4:
                        temp_line = [line[0], float(line[1]), "", "", "", float(line[2]), float(line[3]), ""]

                    elif line[0] == "D1" and len(line) == 5:
                        temp_line = [line[0], float(line[1]), float(line[2]), float(line[3]), "", float(line[4]), "", ""]
                    
                    if temp_line:
                        dim_block.append(temp_line)
                               
            else:
                if line[0] in {"#", "*"} or line.startswith("DIM"):
                    block_headers.append(line)
                text_block.append(block_headers)

            prev_line = line
                
    def headers(self):
        """Method to return list of headers from CMM report

        Returns:
            (str) list: headers
        """
        
        return self.headers_list
    
    def to_dict(self):
        pass

    def to_df(self):
        """This method converts blocks to dataframe
        """
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
            #header = [item for sublist in block[0] for item in sublist if isinstance(item, str)]
            #header = ', '.join(header)
            header = header[:-2]
            columns = ['AX', 'NOM', '+TOL', '-TOL', 'BONUS', 'MEAS', 'DEV', 'OUTTOL']
            df = pandas.DataFrame(block[1], columns=columns)
            df['Header'] = header
            df['File'] = self.pdf_file_path
            df_list.append(df)

        if df_list:
            self.df = pandas.concat(df_list)
            
    def to_sqlite(self):
        # Define the database connection and cursor
        conn = sqlite3.connect('mydatabase.db')
        cursor = conn.cursor()

        # Loop over the lists and insert them into the database
        for lst in self.pdf_blocks_text:
            table_name = ""
            # Extract the table name from the first sublist
            for sublist in lst[0]:
                if isinstance(sublist, str):
                        table_name += sublist
                        table_name += ", "
                else:
                    for item in sublist:
                        if isinstance(item, str):
                            table_name += item
                            table_name += ", "           
            #table_name = [item for sublist in lst[0] for item in sublist if isinstance(item, str)]
            #table_name = ', '.join(table_name)
            table_name = table_name.replace('"', '')
            table_name = table_name[:-2]
            # print(f"{table_name=}")
            # print(f"{lst=}")
            #table_name = "test"
            
            # Create the table if it does not exist
            cursor.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" (AX TEXT, NOM REAL, PLUSTOL REAL, MINUSTOL REAL, BONUS REAL, MEAS REAL, DEV REAL, OUTTOL REAL)')
            
            # Insert the data into the table
            for row in lst[1]:
                cursor.execute(f'INSERT INTO "{table_name}" VALUES (?, ?, ?, ?, ?, ?, ?, ?)', row)

        # Commit the changes and close the connection
        conn.commit()
        conn.close()
                           
    def show_df(self):
        """Method to print dataframe with measurements
        """
        print(f"{self.df}")
                  
    def export_to_excel(self):
        """Method to export generated DataFrame to Excel file
        """
        ###TODO: something more elegant
        self.df.to_excel("dump.xlsx", index=False)
