import pdfplumber
import pandas


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
        self.df_measurements = pandas.DataFrame()

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

    def split_text_to_blocks(self):
        """Method to split raw text from pdf to blocks - split by measurements
            Each block is created as follows:
            block[0] - headers list
            block[1] - headers names list
            block[2:] - dimensions
        """
        text_block = []
        block_headers = []
        dim_block = []
        prev_line = " "
        
        for line in self.pdf_raw_text:
            if line[0] != "#" and line[0] != "*":
                temp_line_split = line.split()
                if len(temp_line_split)==3:
                    continue

            if len(text_block) > 0:
                if line[0] == "#" or line[0] == "*":
                    if prev_line[0] == "#" or prev_line[0] == "*":
                        block_headers.append([line])
                        
                    else:
                        text_block.append(dim_block)
                        text_block.insert(1, block_headers)
                        text_block.pop(0)
                                                
                        self.pdf_blocks_text.append(text_block)
                                                
                        text_block = []
                        block_headers = []
                        dim_block = []
                        
                        block_headers.append([line])
    
                elif line[0:3] == "DIM":
                    if len(dim_block) > 0:
                        text_block.append(dim_block)
                        dim_block = []
                        
                    block_headers.append([line])
                    block_headers.append(["AX",  "NOM", "+TOL", "-TOL", "BONUS", "MEAS", "DEV", "OUTTOL"])
                    
                else:
                    temp_line = []
                    line = line.split()
                    
                    for item in line:
                        if item[0:2] == "--" or item[0:2] == "-#" or item[0:2] == "#-":
                            line.remove(item)

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
                        temp_line = [line[0], line[1], float(line[2]), "", float(line[3]), float(line[4]), float(line[5]), float(line[6])]

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
                if line[0] == "#" or line[0] == "*":
                    block_headers.append([line])
                        
                elif line[0:3] == "DIM":
                    block_headers.append([line])
                    block_headers.append(["AX",  "NOM", "+TOL", "-TOL", "BONUS", "MEAS", "DEV", "OUTTOL"])
                
                text_block.append([])

            prev_line = line
                
    def headers(self):
        """Method to return list of headers from CMM report

        Returns:
            (str) list: headers
        """
        
        return self.headers_list

    def blocks_to_df(self):
        """This till be method to create Pandas' DataFrame from text blocks
        """
        for block in self.pdf_blocks_text:            
            block_headers = []
            for element in block[0]:
                tmp_header = []
                
                if element[0] != "AX":
                    tmp_header = (element[0], "", "", "", "", "", "", "")
                else:
                    tmp_header = (element[0], element[1], element[2], element[3], element[4], element[5], element[6], element[7])
                    
                block_headers.append(tmp_header)
                                    
            block_df = pandas.DataFrame(block[1:][0])
            block_df.columns = pandas.MultiIndex.from_arrays(block_headers)
                        
            self.df_measurements = pandas.concat([self.df_measurements, block_df], axis=1)
                           
    def show_df(self):
        """Method to print dataframe with measurements
        """
        print(f"{self.df_measurements}")
                  
    def export_to_excel(self):
        """Method to export generated DataFrame to Excel file
        """
        ###TODO: something more elegant
        self.df_measurements.to_excel("dump.xlsx")
