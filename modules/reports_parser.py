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
        self.data_dict = {}

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
        """
        
        text_block = []
        for line in self.pdf_raw_text:
            if line[0] != "#" and line[0] != "*":
                temp_line_split = line.split()
                if len(temp_line_split) == 3:
                    continue

            if len(text_block) > 0:
                if line[0] == "#" or line[0] == "*":
                    if text_block[-1][0][0] == "#" or text_block[-1][0][0] == "*":
                        text_block.append([line])
                    else:
                        self.pdf_blocks_text.append(text_block)
                        text_block = []
                        text_block.append([line])
                elif line[0:3] == "DIM":
                    text_block.append([line])
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
                    
                    if line[0] == "AX":
                        temp_line = ["AX",  "NOM", "+TOL", "-TOL", "BONUS", "MEAS", "DEV", "OUTTOL"]

                    elif (line[0] == "X" or line[0] == "Y" or line[0] == "Z") and len(line) == 4:
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
                    
                    # else:
                    #     temp_line.append(line[0])
                    #     for item in line[1:]:
                    #         if item.isnumeric():
                    #             temp_line.append(float(item))
                    #         else:
                    #             temp_line.append(item)
                    text_block.append(temp_line)
            else:
                if line[0] == "#" or line[0] == "*" or line[0:3] == "DIM":
                    text_block.append([line])
                else:
                    text_block.append(line.split())

    def headers(self):
        """Method to return list of headers from CMM report

        Returns:
            (str) list: headers
        """
        
        return self.headers_list

    def cmm_to_df(self):
        """Method to convert parsed pdf CMM report into Pandas' DataFrame
        """
        
        for block in self.pdf_blocks_text:
            for index, line in enumerate(block):
                if index == 0:
                    temp_dict = {'HEADER_###': line}
                else:
                    if len(line) == 1:
                        temp_dict = {'HEADER_DIM': line}
                    else:
                        if line[0] == "AX":
                            if 'HEADER_MEAS' not in self.data_dict:
                                temp_dict = {'HEADER_MEAS': line}
                        elif line[0] == "DIM":
                            pass #TODO
                        else:
                            if 'HEADER_MEAS' in self.data_dict:
                                # temp_dict = {self.data_dict['HEADER_MEAS'][ind]: item for ind, item in enumerate(line)}
                                for ind, item in enumerate(line):
                                    print(f"Inside creation loop:{ind=}")
                                    td = {self.data_dict['HEADER_MEAS'][ind]: item}
                                    temp_dict.update(td)
                                    print(f"Inside creation loop:{ind=}: {temp_dict=}")

                self.data_dict.update(temp_dict)
                temp_dict.clear()

        print(f"{self.data_dict=}")

    def blocks_to_df(self):
        """This till be method to create Pandas' DataFrame from text blocks
        """
        pass
