import pdfplumber
import pandas
import os
from modules import reports_parser
from modules.useful_methods import get_list_of_reports, get_unique_list


REPORT_PATH = "./INPUT/"


if __name__ == '__main__':
    file_name = "./INPUT/Body_HR12_2021.11.25_LAB0025379_IKD_124_1.PDF"
    pdf_report = reports_parser.CMMReport(file_name)
    pdf_report.show_blocks_text()
    pdf_report.cmm_to_df()

    # headers_list = []
    #
    # report_objects = []
    # for pdf_file in get_list_of_reports(REPORT_PATH):
    #     report = reports_parser.CMMReport(pdf_file)
    #     report_objects.append(report)
    #     for header in report.headers_list:
    #         headers_list.append(header)
    #
    # print("\n")
    # for header in headers_list:
    #     print(f"{header}")
    #
    # unique_headers = get_unique_list(headers_list)
    # print("\n")
    # for header in unique_headers:
    #     print(f"{header}")

    #
    # print(f"{len(report_objects)=}")
    #
    # for report in report_objects:
    #     report.show_blocks_text()
    #
    # print(f"{len(report_objects)=}")


    # print(get_list_of_reports(REPORT_PATH))
