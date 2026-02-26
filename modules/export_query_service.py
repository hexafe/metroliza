import pandas as pd

from modules.db import execute_select_with_columns, read_sql_dataframe


def build_export_dataframe(data, column_names):
    return pd.DataFrame(data, columns=column_names)


def execute_export_query(db_file, export_query, select_reader=execute_select_with_columns):
    return select_reader(db_file, export_query)


def ensure_sample_number_column(df):
    if 'SAMPLE_NUMBER' in df.columns:
        return df

    normalized_df = df.copy()
    normalized_df['SAMPLE_NUMBER'] = [str(index + 1) for index in range(len(normalized_df))]
    return normalized_df


def build_measurement_export_dataframe(df):
    normalized_df = ensure_sample_number_column(df)
    export_df = normalized_df.copy()
    export_df['HEADER - AX'] = export_df['HEADER'] + ' - ' + export_df['AX']
    return export_df


def load_measurement_export_dataframe(db_file, filter_query, dataframe_reader=read_sql_dataframe):
    df = dataframe_reader(db_file, filter_query)
    return build_measurement_export_dataframe(df)
