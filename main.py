from modules import reports_parser
from modules.useful_methods import get_list_of_reports, get_unique_list
import pandas as pd
import xlsxwriter
import sqlite3
from pathlib import Path


REPORT_PATH = Path("./input/")

def sql2xls():
    # Connect to SQLite3 database
    conn = sqlite3.connect('mydatabase.db')
    cursor = conn.cursor()

    # Get list of tables in the database
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()

    # Create Excel writer object
    excel_writer = pd.ExcelWriter('output_sql_to_excel_test.xlsx', engine='xlsxwriter')

    # Loop through tables and add to Excel workbook as separate sheets
    for table in tables:
        table_name = table[0]
        # Fetch all rows and columns from the table
        cursor.execute(f'SELECT * FROM "{table_name}";')
        data = cursor.fetchall()
        # Get column names from cursor description
        column_names = [desc[0] for desc in cursor.description]
        # Convert data to DataFrame
        df = pd.DataFrame(data, columns=column_names) # Pass column names to DataFrame
        # Sanitize the table name by replacing special characters with underscores
        table_name_sanitized = ''.join([c if c.isalnum() or c.isspace() else '' for c in table_name])
        table_name_sanitized = table_name_sanitized[:30]  # Limit to first 30 characters
        if not table_name_sanitized:
            table_name_sanitized = 'Sheet'  # Use a default sheet name if sanitized name is empty
        # Add DataFrame to Excel workbook as a new sheet with sanitized table name as sheet name
        df.to_excel(excel_writer, sheet_name=table_name_sanitized, index=False)
        # Add new columns for each table in the same sheet
        worksheet = excel_writer.sheets[table_name_sanitized] # Get the worksheet object
        worksheet.set_column(len(df.columns), len(df.columns) + len(df.columns), None) # Set the column width
        # print(f"Table '{table_name}' added to Excel workbook as sheet '{table_name_sanitized}'.")

    # Save and close Excel writer
    excel_writer.save()
    excel_writer.close()

    # Close database connection
    cursor.close()
    conn.close()


if __name__ == "__main__":
    list_of_reports = get_list_of_reports(REPORT_PATH)
    
    with open("reports.txt", "w") as file:
        file.write(f"number of reports: {len(list_of_reports)}\n")
        for report in list_of_reports:
            file.write(f"{report}\n")
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
        # pdf_report.show_blocks_text()
        pdf_report.to_sqlite()
        pdf_report.to_df()
        df_list.append(pdf_report.df)
    
    # connect to the database
    conn = sqlite3.connect('mydatabase.db')

    # get a list of all table names in the database
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [table[0] for table in cursor.fetchall()]

    df_list2 = []
    # iterate over the tables and extract data
    for table in tables:
        # extract data from the table and store it in a Pandas DataFrame
        df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
        df_list2.append(df)
        # print(f"Table name: {table}")
        # print(df)

    # close the database connection
    conn.close()
        
    result_df = pd.concat(df_list)
    result_df.to_excel('output.xlsx', index=False)
    
    result_df2 = pd.concat(df_list2)
    result_df2.to_excel('output2.xlsx', index=False)
    
    sql2xls()