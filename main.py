from modules import reports_parser
from modules.useful_methods import get_list_of_reports, get_unique_list


REPORT_PATH = "./INPUT/"


if __name__ == '__main__':
    file_name = "./INPUT/Body_HR12_2021.11.25_LAB0025379_IKD_124_1.PDF"
    pdf_report = reports_parser.CMMReport(file_name)
    pdf_report.show_blocks_text()

    list_of_reports = get_list_of_reports(REPORT_PATH)
    for report in list_of_reports:
        print(f"{report=}\n")

# dumping blocks to txt, just for testing
    with open("dump.txt", "w", encoding="utf-8") as f:
        for block in pdf_report.pdf_blocks_text:
            for line in block:
                items_str = ' '.join([str(item) for item in line])
                f.write(items_str)
                f.write('\n')
            f.write('\n')
