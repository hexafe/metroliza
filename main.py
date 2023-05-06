from modules import reports_parser
from modules.useful_methods import get_list_of_reports, get_unique_list
import pandas as pd
import xlsxwriter
import sqlite3
from pathlib import Path


REPORT_PATH = Path("./input/")
DATABASE = "mydatabase.db"

def sql2xls():
    # Connect to SQLite3 database
    conn = sqlite3.connect(DATABASE)
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
     
    for report in list_of_reports:
        pdf_report = reports_parser.CMMReport(report, DATABASE)
        # pdf_report.show_blocks_text()
        # pdf_report.to_sqlite()
    
    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [table[0] for table in cursor.fetchall()]

    conn.close()
    
    sql2xls()