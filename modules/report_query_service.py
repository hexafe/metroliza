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


def _is_export_scoped_query(query):
    normalized = _normalize_sql_query(query).lower()
    return "vw_measurement_export" in normalized or "measurement_id" in normalized


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

    return f'{column_name} IN ({", ".join(cleaned_values)})'


_MEASUREMENT_EXPORT_SELECT_FROM_VIEW = (
    "report_id AS REPORT_ID, measurement_id AS MEASUREMENT_ID, reference AS REFERENCE, report_date AS DATE, "
    "report_time AS TIME, part_name AS PART_NAME, revision AS REVISION, "
    "sample_number AS SAMPLE_NUMBER, sample_number_kind AS SAMPLE_NUMBER_KIND, "
    "stats_count_raw AS STATS_COUNT_RAW, stats_count_int AS STATS_COUNT_INT, "
    "operator_name AS OPERATOR_NAME, directory_path AS FILELOC, file_name AS FILENAME, "
    "absolute_path AS ABSOLUTE_PATH, parser_id AS PARSER_ID, template_family AS TEMPLATE_FAMILY, "
    "template_variant AS TEMPLATE_VARIANT, header AS HEADER, section_name AS SECTION_NAME, "
    "feature_label AS FEATURE_LABEL, characteristic_name AS CHARACTERISTIC_NAME, "
    "characteristic_family AS CHARACTERISTIC_FAMILY, description AS DESCRIPTION, "
    "ax AS AX, nominal AS NOM, tol_plus AS \"+TOL\", tol_minus AS \"-TOL\", "
    "bonus AS BONUS, meas AS MEAS, dev AS DEV, outtol AS OUTTOL, is_nok AS IS_NOK, "
    "status_code AS STATUS_CODE, page_number AS PAGE_NUMBER, row_order AS ROW_ORDER, "
    "has_nok AS HAS_NOK, nok_count AS NOK_COUNT"
)

_MEASUREMENT_EXPORT_SELECT_FROM_SCOPE = (
    '"REPORT_ID" AS REPORT_ID, "MEASUREMENT_ID" AS MEASUREMENT_ID, "REFERENCE" AS REFERENCE, "DATE" AS DATE, '
    '"TIME" AS TIME, "PART_NAME" AS PART_NAME, "REVISION" AS REVISION, '
    '"SAMPLE_NUMBER" AS SAMPLE_NUMBER, "SAMPLE_NUMBER_KIND" AS SAMPLE_NUMBER_KIND, '
    '"STATS_COUNT_RAW" AS STATS_COUNT_RAW, "STATS_COUNT_INT" AS STATS_COUNT_INT, '
    '"OPERATOR_NAME" AS OPERATOR_NAME, "FILELOC" AS FILELOC, "FILENAME" AS FILENAME, '
    '"ABSOLUTE_PATH" AS ABSOLUTE_PATH, "PARSER_ID" AS PARSER_ID, "TEMPLATE_FAMILY" AS TEMPLATE_FAMILY, '
    '"TEMPLATE_VARIANT" AS TEMPLATE_VARIANT, "HEADER" AS HEADER, "SECTION_NAME" AS SECTION_NAME, '
    '"FEATURE_LABEL" AS FEATURE_LABEL, "CHARACTERISTIC_NAME" AS CHARACTERISTIC_NAME, '
    '"CHARACTERISTIC_FAMILY" AS CHARACTERISTIC_FAMILY, "DESCRIPTION" AS DESCRIPTION, '
    '"AX" AS AX, "NOM" AS NOM, "+TOL" AS "+TOL", "-TOL" AS "-TOL", '
    '"BONUS" AS BONUS, "MEAS" AS MEAS, "DEV" AS DEV, "OUTTOL" AS OUTTOL, "IS_NOK" AS IS_NOK, '
    '"STATUS_CODE" AS STATUS_CODE, "PAGE_NUMBER" AS PAGE_NUMBER, "ROW_ORDER" AS ROW_ORDER, '
    '"HAS_NOK" AS HAS_NOK, "NOK_COUNT" AS NOK_COUNT'
)


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
    normalized_filter_query = _normalize_sql_query(filter_query)
    if normalized_filter_query:
        return f"""
        SELECT DISTINCT
            "REPORT_ID" AS REPORT_ID,
            "REFERENCE" AS REFERENCE,
            "DATE" AS DATE,
            "SAMPLE_NUMBER" AS SAMPLE_NUMBER,
            "PART_NAME" AS PART_NAME,
            "REVISION" AS REVISION,
            "TEMPLATE_VARIANT" AS TEMPLATE_VARIANT,
            "HAS_NOK" AS HAS_NOK,
            "NOK_COUNT" AS NOK_COUNT,
            "FILENAME" AS FILENAME
        FROM (
            {normalized_filter_query}
        ) AS filtered_data
    """

    select_clause = (
        "DISTINCT report_id AS REPORT_ID, reference AS REFERENCE, report_date AS DATE, "
        "sample_number AS SAMPLE_NUMBER, part_name AS PART_NAME, revision AS REVISION, "
        "template_variant AS TEMPLATE_VARIANT, has_nok AS HAS_NOK, nok_count AS NOK_COUNT, "
        "file_name AS FILENAME"
    )
    return _build_select_from_view(select_clause, _GROUPING_REPORT_VIEW)


def build_measurement_export_query(filter_query=None):
    normalized_filter_query = _normalize_sql_query(filter_query)
    if normalized_filter_query:
        if not _is_export_scoped_query(normalized_filter_query):
            return f"""
        SELECT {_MEASUREMENT_EXPORT_SELECT_FROM_VIEW}
        FROM {_MEASUREMENT_EXPORT_VIEW}
        WHERE report_id IN (
            SELECT "REPORT_ID"
            FROM (
                {normalized_filter_query}
            ) AS report_scope
        )
    """

        return f"""
        SELECT {_MEASUREMENT_EXPORT_SELECT_FROM_SCOPE}
        FROM (
            {normalized_filter_query}
        ) AS filtered_data
    """

    return _build_select_from_view(_MEASUREMENT_EXPORT_SELECT_FROM_VIEW, _MEASUREMENT_EXPORT_VIEW)


def build_measurement_filter_query(
    *,
    ax_values=(),
    header_values=(),
    reference_values=(),
    part_name_values=(),
    revision_values=(),
    template_variant_values=(),
    sample_number_values=(),
    operator_name_values=(),
    sample_number_kind_values=(),
    status_code_values=(),
    filename_values=(),
    parser_id_values=(),
    template_family_values=(),
    has_nok_only=False,
    date_from=None,
    date_to=None,
):
    query = f"SELECT {_MEASUREMENT_EXPORT_SELECT_FROM_VIEW} FROM {_MEASUREMENT_EXPORT_VIEW} WHERE 1=1"

    for column_name, values in (
        ("ax", ax_values),
        ("header", header_values),
        ("reference", reference_values),
        ("part_name", part_name_values),
        ("revision", revision_values),
        ("template_variant", template_variant_values),
        ("sample_number", sample_number_values),
        ("operator_name", operator_name_values),
        ("sample_number_kind", sample_number_kind_values),
        ("status_code", status_code_values),
        ("file_name", filename_values),
        ("parser_id", parser_id_values),
        ("template_family", template_family_values),
    ):
        clause = _build_in_clause(column_name, values)
        if clause is not None:
            query += f" AND {clause}"

    if has_nok_only:
        query += " AND has_nok = 1"
    if date_from:
        query += f" AND report_date >= '{_escape_sql_literal(date_from)}'"
    if date_to:
        query += f" AND report_date <= '{_escape_sql_literal(date_to)}'"

    return query


def build_distinct_value_query(column_name, *, source_view=_MEASUREMENT_EXPORT_VIEW, filter_query=None):
    normalized_filter_query = _normalize_sql_query(filter_query)
    if normalized_filter_query:
        if source_view == _MEASUREMENT_EXPORT_VIEW and not _is_export_scoped_query(normalized_filter_query):
            source = f"({build_measurement_export_query(normalized_filter_query)}) AS filtered_data"
        else:
            source = f"({normalized_filter_query}) AS filtered_data"
    else:
        source = source_view

    return (
        f'SELECT DISTINCT "{column_name}" AS value '
        f'FROM {source} '
        f'WHERE "{column_name}" IS NOT NULL AND TRIM(CAST("{column_name}" AS TEXT)) <> \'\' '
        f'ORDER BY value'
    )
