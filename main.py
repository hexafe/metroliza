import pdfplumber
import pandas
import valeo_cmm_parser
import os

REPORT_PATH = "./INPUT/"


def get_list_of_reports(path: str):
    """
    Function to return list (str) of pdf files in given direction path
    :param path: (str) path to check for pdf files
    :return: list (str) of dir including file name
    """
    list_of_reports = []
    with os.scandir(path) as it:
        for entry in it:
            if (entry.name.endswith(".PDF") or entry.name.endswith(".pdf")) and entry.is_file():
                # print(entry.name, entry.path)
                list_of_reports.append(entry.path)
    return list_of_reports


def get_unique_list(list):
    """
    Function to get list and return only unique elements from that list
    :param list: input list
    :return: list with only unique elements from input list
    """
    unique_list = []
    for element in list:
        if element not in unique_list:
            unique_list.append(element)
    return unique_list


if __name__ == '__main__':
    file_name = "./INPUT/V29123229_001_Overmolded_body_2020.04.21_cav.2_09.PDF"
    pdf_report = valeo_cmm_parser.CMMReport(file_name)
    # pdf_report.show_blocks_text()
    pdf_report.cmm_to_df()

    # headers_list = []
    #
    # report_objects = []
    # for pdf_file in get_list_of_reports(REPORT_PATH):
    #     report = valeo_cmm_parser.CMMReport(pdf_file)
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
