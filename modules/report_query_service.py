"""View-backed query helpers for report browsing, grouping, and export filters."""

from __future__ import annotations


_REPORT_OVERVIEW_VIEW = "vw_report_overview"
_GROUPING_REPORT_VIEW = "vw_grouping_reports"
_MEASUREMENT_EXPORT_VIEW = "vw_measurement_export"


def _normalize_sql_query(query):
    if not isinstance(query, str):
        return ""

    normalized = query.strip()
    return normalized.rstrip(";").rstrip()


def _escape_sql_literal(value):
    return str(value).replace("'", "''")


def _build_select_from_view(select_clause, view_name, filter_query=None):
    base_query = f"SELECT {select_clause} FROM {view_name}"
    normalized_filter_query = _normalize_sql_query(filter_query)
    if not normalized_filter_query:
        return base_query
    return f"""
        SELECT {select_clause}
        FROM (
            {normalized_filter_query}
        ) AS filtered_data
    """


def _build_in_clause(column_name, values):
    cleaned_values = []
    for value in values or ():
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        cleaned_values.append(f"'{_escape_sql_literal(text)}'")

    if not cleaned_values:
        return None

    return f'"{column_name}" IN ({", ".join(cleaned_values)})'


def build_report_overview_query(filter_query=None):
    select_clause = (
        "report_id, source_file_id, parser_id, template_family, template_variant, "
        "parse_status, metadata_confidence, reference, report_date, report_time, "
        "part_name, revision, sample_number, sample_number_kind, stats_count_raw, "
        "stats_count_int, operator_name, comment, page_count, measurement_count, "
        "has_nok, nok_count, file_name, directory_path, absolute_path, sha256"
    )
    return _build_select_from_view(select_clause, _REPORT_OVERVIEW_VIEW, filter_query)


def build_grouping_query(filter_query=None):
    select_clause = (
        "DISTINCT "
        "report_id AS REPORT_ID, reference AS REFERENCE, report_date AS DATE, "
        "sample_number AS SAMPLE_NUMBER, part_name AS PART_NAME, revision AS REVISION, "
        "template_variant AS TEMPLATE_VARIANT, has_nok AS HAS_NOK, nok_count AS NOK_COUNT, "
        "file_name AS FILENAME"
    )
    return _build_select_from_view(select_clause, _GROUPING_REPORT_VIEW, filter_query)


def build_measurement_export_query(filter_query=None):
    select_clause = (
        "report_id AS REPORT_ID, reference AS REFERENCE, report_date AS DATE, "
        "report_time AS TIME, part_name AS PART_NAME, revision AS REVISION, "
        "sample_number AS SAMPLE_NUMBER, sample_number_kind AS SAMPLE_NUMBER_KIND, "
        "stats_count_raw AS STATS_COUNT_RAW, stats_count_int AS STATS_COUNT_INT, "
        "operator_name AS OPERATOR_NAME, file_name AS FILENAME, absolute_path AS ABSOLUTE_PATH, "
        "parser_id AS PARSER_ID, template_family AS TEMPLATE_FAMILY, "
        "template_variant AS TEMPLATE_VARIANT, header AS HEADER, section_name AS SECTION_NAME, "
        "feature_label AS FEATURE_LABEL, characteristic_name AS CHARACTERISTIC_NAME, "
        "characteristic_family AS CHARACTERISTIC_FAMILY, description AS DESCRIPTION, "
        "ax AS AX, nominal AS NOM, tol_plus AS \"+TOL\", tol_minus AS \"-TOL\", "
        "bonus AS BONUS, meas AS MEAS, dev AS DEV, outtol AS OUTTOL, is_nok AS IS_NOK, "
        "status_code AS STATUS_CODE, page_number AS PAGE_NUMBER, row_order AS ROW_ORDER, "
        "has_nok AS HAS_NOK"
    )
    return _build_select_from_view(select_clause, _MEASUREMENT_EXPORT_VIEW, filter_query)


def build_measurement_filter_query(
    *,
    ax_values=(),
    header_values=(),
    reference_values=(),
    part_name_values=(),
    revision_values=(),
    template_variant_values=(),
    sample_number_values=(),
    has_nok_only=False,
    date_from=None,
    date_to=None,
):
    select_clause = (
        "report_id AS REPORT_ID, reference AS REFERENCE, report_date AS DATE, "
        "report_time AS TIME, part_name AS PART_NAME, revision AS REVISION, "
        "sample_number AS SAMPLE_NUMBER, sample_number_kind AS SAMPLE_NUMBER_KIND, "
        "stats_count_raw AS STATS_COUNT_RAW, stats_count_int AS STATS_COUNT_INT, "
        "operator_name AS OPERATOR_NAME, file_name AS FILENAME, absolute_path AS ABSOLUTE_PATH, "
        "parser_id AS PARSER_ID, template_family AS TEMPLATE_FAMILY, "
        "template_variant AS TEMPLATE_VARIANT, header AS HEADER, section_name AS SECTION_NAME, "
        "feature_label AS FEATURE_LABEL, characteristic_name AS CHARACTERISTIC_NAME, "
        "characteristic_family AS CHARACTERISTIC_FAMILY, description AS DESCRIPTION, "
        "ax AS AX, nominal AS NOM, tol_plus AS \"+TOL\", tol_minus AS \"-TOL\", "
        "bonus AS BONUS, meas AS MEAS, dev AS DEV, outtol AS OUTTOL, is_nok AS IS_NOK, "
        "status_code AS STATUS_CODE, page_number AS PAGE_NUMBER, row_order AS ROW_ORDER, "
        "has_nok AS HAS_NOK"
    )
    query = f"SELECT {select_clause} FROM {_MEASUREMENT_EXPORT_VIEW} WHERE 1=1"

    for column_name, values in (
        ("AX", ax_values),
        ("HEADER", header_values),
        ("REFERENCE", reference_values),
        ("PART_NAME", part_name_values),
        ("REVISION", revision_values),
        ("TEMPLATE_VARIANT", template_variant_values),
        ("SAMPLE_NUMBER", sample_number_values),
    ):
        clause = _build_in_clause(column_name, values)
        if clause is not None:
            query += f" AND {clause}"

    if has_nok_only:
        query += " AND HAS_NOK = 1"
    if date_from:
        query += f" AND DATE >= '{_escape_sql_literal(date_from)}'"
    if date_to:
        query += f" AND DATE <= '{_escape_sql_literal(date_to)}'"

    return query


def build_distinct_value_query(column_name, *, source_view=_MEASUREMENT_EXPORT_VIEW, filter_query=None):
    normalized_filter_query = _normalize_sql_query(filter_query)
    if normalized_filter_query:
        source = f"({normalized_filter_query}) AS filtered_data"
    else:
        source = source_view

    return (
        f'SELECT DISTINCT "{column_name}" AS value '
        f'FROM {source} '
        f'WHERE "{column_name}" IS NOT NULL AND TRIM(CAST("{column_name}" AS TEXT)) <> \'\' '
        f'ORDER BY value'
    )
