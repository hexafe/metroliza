from modules import reports_parser
from modules.useful_methods import get_list_of_reports, get_unique_list
import pandas as pd
import sqlite3


REPORT_PATH = "./input/"


if __name__ == "__main__":
    list_of_reports = get_list_of_reports(REPORT_PATH)
    # for report in list_of_reports:
    #     print(f"{report=}\n")
        
    # file_name = list_of_reports[0]
    # pdf_report = reports_parser.CMMReport(file_name)
    # pdf_report.show_blocks_text2()
    # pdf_report.show_raw_text()
    # pdf_report.blocks_to_df()
    # pdf_report.show_df()
    # pdf_report.export_to_excel()
    # pdf_report.blocks_to_dict()
    # pdf_report.show_dict()
    # pdf_report.blocks_to_sqlite()
    
    # df = pd.DataFrame(pdf_report.dict_list)
    # print(df)
    
    # # dumping blocks to txt, just for testing
    # with open("dump.txt", "w", encoding="utf-8") as f:
    #     for block in pdf_report.pdf_blocks_text:
    #         for line in block:
    #             items_str = ' '.join([str(item) for item in line])
    #             f.write(items_str)
    #             f.write("\n")
    #         f.write("\n")
    
    # def list_to_dict_dataframe(data):
    #     header = [item for sublist in data[0] for item in sublist if isinstance(item, str) and item.startswith(('*', '#', 'DIM'))]
    #     header = ', '.join(header)
    #     columns = ['AX', 'NOM', '+TOL', '-TOL', 'BONUS', 'MEAS', 'DEV', 'OUTTOL']
    #     df = pd.DataFrame(data[1], columns=columns)
    #     return header, df
    
    # def list_to_dict_dataframe(data):
    #     header = [item for sublist in data[0] for item in sublist if isinstance(item, str) and item.startswith(('*', '#', 'DIM'))]
    #     header = ', '.join(header)
    #     columns = ['AX', 'NOM', '+TOL', '-TOL', 'BONUS', 'MEAS', 'DEV', 'OUTTOL']
    #     df = pd.DataFrame(data[1], columns=columns)
    #     df.columns.name = header
    #     return df
     
    df_list = []
    for report in list_of_reports:
        print(f"{report=}")
        pdf_report = reports_parser.CMMReport(report)
        # pdf_report.show_blocks_text2()
        pdf_report.to_sqlite()
        pdf_report.to_df()
        df_list.append(pdf_report.df)
    
    # connect to the database
    conn = sqlite3.connect('mydatabase.db')

    # get a list of all table names in the database
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [table[0] for table in cursor.fetchall()]

    # iterate over the tables and extract data
    for table in tables:
        # extract data from the table and store it in a Pandas DataFrame
        df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
        # print(f"Table name: {table}")
        print(df)

    # close the database connection
    conn.close()
        
    result_df = pd.concat(df_list)
    result_df.to_excel('output.xlsx', index=False)