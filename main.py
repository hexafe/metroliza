from modules import reports_parser
from modules.useful_methods import get_list_of_reports, get_unique_list
import pandas as pd
import xlsxwriter
import sqlite3
from pathlib import Path
import time


REPORT_PATH = Path("./input/")
DATABASE = "mydatabase.db"

def sql2xls(name: str, database: str):
    # Connect to SQLite3 database
    conn = sqlite3.connect(database)
    cursor = conn.cursor()

    # Get list of tables in the database
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()

    # Create Excel writer object
    excel_writer = pd.ExcelWriter(name, engine='xlsxwriter')

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
    
    # pdfplumber_start_time = time.time()
    # for report in list_of_reports:
    #     pdf_report = reports_parser.CMMReport_pdfplumber(report, DATABASE)
    # sql2xls(name='pdfplumber_output_sql_to_excel_test.xlsx', database='pdfplumber_'+DATABASE)
    # pdfplumber_end_time = time.time()
    # pdfplumber_running_time = pdfplumber_end_time - pdfplumber_start_time
    
    PyMuPDF_start_time = time.time()
    for report in list_of_reports:
        pdf_report = reports_parser.CMMReport_pymupdf(report, DATABASE)
    sql2xls(name='pymupdf_output_sql_to_excel_test.xlsx', database='pymupdf_'+DATABASE)
    PyMuPDF_end_time = time.time()
    PyMuPDF_running_time = PyMuPDF_end_time - PyMuPDF_start_time
    
    # print(f"\nRunning time for pdfplumber: {pdfplumber_running_time} seconds")
    # print(f"Running time for PyMuPDF: {PyMuPDF_running_time} seconds, which is {pdfplumber_running_time/PyMuPDF_running_time}x faster compared to pdfplumber \:D/")
    print(f"Running time for PyMuPDF: {PyMuPDF_running_time} seconds")