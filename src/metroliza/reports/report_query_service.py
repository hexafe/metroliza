"""View-backed query helpers for report browsing, grouping, and export filters."""

from __future__ import annotations

from datetime import date

from metroliza.shared.grouping_filter_core import (
    DateFilterSpec,
    FilterExpressionGroup,
    MembershipFilterSpec,
    NumberFilterSpec,
    TextFilterSpec,
    membership_value_kind,
    parse_filter_expression,
)


_REPORT_OVERVIEW_VIEW = "vw_report_overview"
_GROUPING_REPORT_VIEW = "vw_grouping_reports"
_MEASUREMENT_EXPORT_VIEW = "vw_measurement_export"
_DEFAULT_DATE_FROM = "1970-01-01"

_MEASUREMENT_FILTER_COLUMNS = {
    "absolute_path",
    "ax",
    "bonus",
    "characteristic_family",
    "characteristic_name",
    "description",
    "dev",
    "directory_path",
    "feature_label",
    "file_name",
    "has_nok",
    "header",
    "is_nok",
    "meas",
    "nok_count",
    "nominal",
    "operator_name",
    "outtol",
    "page_number",
    "parser_id",
    "part_name",
    "reference",
    "report_date",
    "report_time",
    "revision",
    "row_order",
    "sample_number",
    "sample_number_kind",
    "section_name",
    "stats_count_int",
    "stats_count_raw",
    "status_code",
    "template_family",
    "template_variant",
    "tol_minus",
    "tol_plus",
}

_MEASUREMENT_FILTER_ALIASES = {
    "+tol": "tol_plus",
    "-tol": "tol_minus",
    "absolute path": "absolute_path",
    "axis": "ax",
    "characteristic": "characteristic_name",
    "characteristic family": "characteristic_family",
    "date": "report_date",
    "dimension": "header",
    "directory": "directory_path",
    "feature": "feature_label",
    "file": "file_name",
    "filename": "file_name",
    "has nok": "has_nok",
    "header": "header",
    "is nok": "is_nok",
    "measured": "meas",
    "measurement": "meas",
    "nom": "nominal",
    "nominal": "nominal",
    "operator": "operator_name",
    "page": "page_number",
    "parser": "parser_id",
    "part": "part_name",
    "ref": "reference",
    "reference": "reference",
    "rev": "revision",
    "sample": "sample_number",
    "sample kind": "sample_number_kind",
    "section": "section_name",
    "status": "status_code",
    "template": "template_variant",
    "template family": "template_family",
    "time": "report_time",
    "variant": "template_variant",
}

INDUSTRIAL_EXPORT_COLUMNS = (
    "INDUSTRIAL_RECORD_ID",
    "INDUSTRIAL_SOURCE_PROFILE",
    "INDUSTRIAL_SOURCE_DB",
    "INDUSTRIAL_PROCESS_TIMESTAMP",
    "INDUSTRIAL_PART_NUMBER",
    "INDUSTRIAL_SERIAL",
    "INDUSTRIAL_BATCH_LOT",
    "INDUSTRIAL_WORK_ORDER",
    "INDUSTRIAL_STATION",
    "INDUSTRIAL_LINE",
    "INDUSTRIAL_OPERATOR",
    "INDUSTRIAL_STATUS",
    "INDUSTRIAL_LINK_CONFIDENCE",
    "INDUSTRIAL_LINK_RULE",
)


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


def _quote_measurement_filter_column(column_name):
    column = str(column_name or "").strip()
    if column not in _MEASUREMENT_FILTER_COLUMNS:
        raise ValueError(f"Unsupported CMM filter field: {column_name}")
    return f'"{column}"'


def _sql_text(column_name):
    return f"LOWER(CAST({_quote_measurement_filter_column(column_name)} AS TEXT))"


def _sql_literal(value):
    return f"'{_escape_sql_literal(value)}'"


def _sql_text_literal(value):
    return f"LOWER({_sql_literal(value)})"


def _escape_like_literal(value):
    text = str(value)
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("*", "%")
        .replace("?", "_")
    )


def _has_expression_wildcard(value):
    return "*" in str(value or "") or "?" in str(value or "")


def _wildcard_clause(column_name, value, *, negate=False):
    operator = "NOT LIKE" if negate else "LIKE"
    pattern = _escape_like_literal(value)
    comparison = f"{_sql_text(column_name)} {operator} {_sql_text_literal(pattern)} ESCAPE '\\'"
    if negate:
        return f"({_quote_measurement_filter_column(column_name)} IS NULL OR {comparison})"
    return comparison


def _text_expression_clause(spec):
    operator = str(spec.operator or "").strip().lower()
    column = spec.column
    value = "" if spec.value is None else str(spec.value)
    if operator == "equals":
        if spec.wildcards and _has_expression_wildcard(value):
            return _wildcard_clause(column, value)
        return f"{_sql_text(column)} = {_sql_text_literal(value)}"
    if operator == "not_equals":
        if spec.wildcards and _has_expression_wildcard(value):
            return _wildcard_clause(column, value, negate=True)
        return (
            f"({_quote_measurement_filter_column(column)} IS NULL "
            f"OR {_sql_text(column)} <> {_sql_text_literal(value)})"
        )
    if operator == "contains":
        return _wildcard_clause(column, f"*{value}*")
    if operator == "not_contains":
        return _wildcard_clause(column, f"*{value}*", negate=True)
    if operator == "starts_with":
        return _wildcard_clause(column, f"{value}*")
    if operator == "ends_with":
        return _wildcard_clause(column, f"*{value}")
    if operator == "is_blank":
        return (
            f"({_quote_measurement_filter_column(column)} IS NULL "
            f"OR TRIM(CAST({_quote_measurement_filter_column(column)} AS TEXT)) = '')"
        )
    if operator == "is_not_blank":
        return (
            f"({_quote_measurement_filter_column(column)} IS NOT NULL "
            f"AND TRIM(CAST({_quote_measurement_filter_column(column)} AS TEXT)) <> '')"
        )
    raise ValueError(f"Unsupported CMM text filter operator: {spec.operator}")


def _number_expression_clause(spec):
    operator = str(spec.operator or "").strip().lower()
    column = f"CAST({_quote_measurement_filter_column(spec.column)} AS REAL)"
    value = _sql_literal(spec.value)
    if operator in {"equals", "eq"}:
        return f"{column} = CAST({value} AS REAL)"
    if operator in {"not_equals", "ne"}:
        return f"({column} <> CAST({value} AS REAL) OR {_quote_measurement_filter_column(spec.column)} IS NULL)"
    if operator in {"greater_than", "gt"}:
        return f"{column} > CAST({value} AS REAL)"
    if operator in {"greater_or_equal", "gte"}:
        return f"{column} >= CAST({value} AS REAL)"
    if operator in {"less_than", "lt"}:
        return f"{column} < CAST({value} AS REAL)"
    if operator in {"less_or_equal", "lte"}:
        return f"{column} <= CAST({value} AS REAL)"
    if operator == "between":
        first = f"CAST({_sql_literal(spec.value)} AS REAL)"
        second = f"CAST({_sql_literal(spec.second_value)} AS REAL)"
        return f"{column} BETWEEN MIN({first}, {second}) AND MAX({first}, {second})"
    if operator == "is_blank":
        return f"{_quote_measurement_filter_column(spec.column)} IS NULL"
    if operator == "is_not_blank":
        return f"{_quote_measurement_filter_column(spec.column)} IS NOT NULL"
    raise ValueError(f"Unsupported CMM number filter operator: {spec.operator}")


def _date_expression_clause(spec):
    operator = str(spec.operator or "").strip().lower()
    column = f"DATE({_quote_measurement_filter_column(spec.column)})"
    value = f"DATE({_sql_literal(spec.value)})"
    if operator in {"on", "equals", "eq"}:
        return f"{column} = {value}"
    if operator in {"not_on", "not_equals", "ne"}:
        return f"({column} <> {value} OR {_quote_measurement_filter_column(spec.column)} IS NULL)"
    if operator in {"before", "lt"}:
        return f"{column} < {value}"
    if operator in {"on_or_before", "lte"}:
        return f"{column} <= {value}"
    if operator in {"after", "gt"}:
        return f"{column} > {value}"
    if operator in {"on_or_after", "gte"}:
        return f"{column} >= {value}"
    if operator == "between":
        first = f"DATE({_sql_literal(spec.value)})"
        second = f"DATE({_sql_literal(spec.second_value)})"
        return f"{column} BETWEEN MIN({first}, {second}) AND MAX({first}, {second})"
    if operator == "is_blank":
        return f"{_quote_measurement_filter_column(spec.column)} IS NULL"
    if operator == "is_not_blank":
        return f"{_quote_measurement_filter_column(spec.column)} IS NOT NULL"
    raise ValueError(f"Unsupported CMM date filter operator: {spec.operator}")


def _membership_expression_clause(spec):
    values = tuple(value for value in spec.values if str(value).strip())
    if not values:
        raise ValueError("IN filters require at least one value")
    value_kind = membership_value_kind(values, dayfirst=spec.dayfirst)
    quoted_column = _quote_measurement_filter_column(spec.column)
    clauses = []
    missing_clause = f"{quoted_column} IS NULL"
    if value_kind == "number":
        text_column = f"TRIM(CAST({quoted_column} AS TEXT))"
        json_type = (
            f"CASE WHEN json_valid({text_column}) "
            f"THEN json_type({text_column}) ELSE NULL END"
        )
        numeric_guard = (
            f"({quoted_column} IS NOT NULL AND {text_column} <> '' AND ("
            f"COALESCE({json_type} IN ('integer', 'real'), 0) "
            f"OR {text_column} NOT GLOB '*[^0-9]*' "
            f"OR (substr({text_column}, 1, 1) IN ('+', '-') "
            f"AND substr({text_column}, 2) <> '' "
            f"AND substr({text_column}, 2) NOT GLOB '*[^0-9]*')))"
        )
        values_sql = ", ".join(f"CAST({_sql_literal(value)} AS REAL)" for value in values)
        clauses.append(f"({numeric_guard} AND CAST({quoted_column} AS REAL) IN ({values_sql}))")
        missing_clause = f"NOT {numeric_guard}"
    elif value_kind == "date":
        values_sql = ", ".join(f"DATE({_sql_literal(value)})" for value in values)
        clauses.append(f"DATE({quoted_column}) IN ({values_sql})")
        missing_clause = f"DATE({quoted_column}) IS NULL"
    else:
        exact_values = [
            value for value in values if not (spec.wildcards and _has_expression_wildcard(value))
        ]
        if exact_values:
            values_sql = ", ".join(_sql_text_literal(value) for value in exact_values)
            clauses.append(f"{_sql_text(spec.column)} IN ({values_sql})")
        if spec.wildcards:
            clauses.extend(
                _wildcard_clause(spec.column, value)
                for value in values
                if _has_expression_wildcard(value)
            )
    if not clauses:
        clause = "0"
    else:
        clause = "(" + " OR ".join(clauses) + ")"
    negate = bool(spec.negate) or str(spec.operator or "").strip().casefold() == "not_in"
    if negate:
        return f"({missing_clause} OR NOT {clause})"
    return clause


def _filter_expression_spec_to_sql(spec):
    if isinstance(spec, FilterExpressionGroup):
        operator = " OR " if spec.operator == "or" else " AND "
        return "(" + operator.join(_filter_expression_spec_to_sql(child) for child in spec.children) + ")"
    if isinstance(spec, TextFilterSpec):
        return _text_expression_clause(spec)
    if isinstance(spec, NumberFilterSpec):
        return _number_expression_clause(spec)
    if isinstance(spec, DateFilterSpec):
        return _date_expression_clause(spec)
    if isinstance(spec, MembershipFilterSpec):
        return _membership_expression_clause(spec)
    raise ValueError(f"Unsupported CMM filter expression type: {type(spec).__name__}")


def build_measurement_expression_clause(expression_text):
    """Compile a CMM filter expression into a safe SQLite WHERE fragment."""

    expression = str(expression_text or "").strip()
    if not expression:
        return None
    parsed = parse_filter_expression(
        expression,
        _MEASUREMENT_FILTER_COLUMNS,
        aliases=_MEASUREMENT_FILTER_ALIASES,
    )
    if parsed.expression is None:
        return None
    return _filter_expression_spec_to_sql(parsed.expression)


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


def _filter_state_has_values(filter_state, field_names):
    for field_name in field_names:
        value = getattr(filter_state, field_name, ())
        if isinstance(value, bool):
            if value:
                return True
            continue
        if value:
            return True
    return False


def _filter_state_requires_measurement_scope(filter_state):
    if _filter_state_has_values(
        filter_state,
        (
            "ax_values",
            "header_values",
            "revision_values",
            "template_variant_values",
            "sample_number_values",
            "operator_name_values",
            "sample_number_kind_values",
            "status_code_values",
            "filename_values",
            "parser_id_values",
            "template_family_values",
            "has_nok_only",
            "expression_text",
        ),
    ):
        return True
    date_from = str(getattr(filter_state, "date_from", "") or "").strip()
    date_to = str(getattr(filter_state, "date_to", "") or "").strip()
    default_date_to = date.today().isoformat()
    if date_from and date_from != _DEFAULT_DATE_FROM:
        return True
    if date_to and date_to != default_date_to:
        return True
    return False


def build_grouping_scope_query_from_filter_state(filter_state=None):
    """Build the export-grouping initial scope from active export filters."""

    if filter_state is None:
        return None

    if _filter_state_requires_measurement_scope(filter_state):
        return build_grouping_query(
            build_measurement_filter_query(
                ax_values=getattr(filter_state, "ax_values", ()),
                header_values=getattr(filter_state, "header_values", ()),
                reference_values=getattr(filter_state, "reference_values", ()),
                part_name_values=getattr(filter_state, "part_name_values", ()),
                revision_values=getattr(filter_state, "revision_values", ()),
                template_variant_values=getattr(filter_state, "template_variant_values", ()),
                sample_number_values=getattr(filter_state, "sample_number_values", ()),
                operator_name_values=getattr(filter_state, "operator_name_values", ()),
                sample_number_kind_values=getattr(filter_state, "sample_number_kind_values", ()),
                status_code_values=getattr(filter_state, "status_code_values", ()),
                filename_values=getattr(filter_state, "filename_values", ()),
                parser_id_values=getattr(filter_state, "parser_id_values", ()),
                template_family_values=getattr(filter_state, "template_family_values", ()),
                has_nok_only=getattr(filter_state, "has_nok_only", False),
                date_from=getattr(filter_state, "date_from", None),
                date_to=getattr(filter_state, "date_to", None),
                expression_text=getattr(filter_state, "expression_text", ""),
            )
        )

    where_clauses = []
    reference_clause = _build_in_clause("reference", getattr(filter_state, "reference_values", ()))
    part_clause = _build_in_clause("part_name", getattr(filter_state, "part_name_values", ()))
    if reference_clause is not None:
        where_clauses.append(reference_clause)
    if part_clause is not None:
        where_clauses.append(part_clause)
    if not where_clauses:
        return None

    select_clause = (
        "report_id AS REPORT_ID, reference AS REFERENCE, report_date AS DATE, "
        "sample_number AS SAMPLE_NUMBER, part_name AS PART_NAME, revision AS REVISION, "
        "template_variant AS TEMPLATE_VARIANT, has_nok AS HAS_NOK, nok_count AS NOK_COUNT, "
        "file_name AS FILENAME"
    )
    return (
        f"SELECT {select_clause} FROM {_GROUPING_REPORT_VIEW} "
        f"WHERE {' AND '.join(where_clauses)}"
    )


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


def _append_industrial_context_to_export_query(base_query):
    normalized_base_query = _normalize_sql_query(base_query)
    return f"""
        SELECT
            base.*,
            ir.id AS INDUSTRIAL_RECORD_ID,
            isp.profile_name AS INDUSTRIAL_SOURCE_PROFILE,
            ir.source_db_alias AS INDUSTRIAL_SOURCE_DB,
            ir.process_timestamp AS INDUSTRIAL_PROCESS_TIMESTAMP,
            ir.part_number AS INDUSTRIAL_PART_NUMBER,
            ir.serial AS INDUSTRIAL_SERIAL,
            ir.batch_lot AS INDUSTRIAL_BATCH_LOT,
            ir.work_order AS INDUSTRIAL_WORK_ORDER,
            ir.station AS INDUSTRIAL_STATION,
            ir.line AS INDUSTRIAL_LINE,
            ir.operator_name AS INDUSTRIAL_OPERATOR,
            ir.process_status AS INDUSTRIAL_STATUS,
            ilc.confidence AS INDUSTRIAL_LINK_CONFIDENCE,
            ijr.rule_name AS INDUSTRIAL_LINK_RULE
        FROM (
            {normalized_base_query}
        ) AS base
        LEFT JOIN industrial_link_candidates ilc ON ilc.id = (
            SELECT selected_candidate.id
            FROM industrial_link_candidates selected_candidate
            LEFT JOIN industrial_join_rules selected_rule
                ON selected_rule.id = selected_candidate.join_rule_id
            WHERE selected_candidate.report_id = base.REPORT_ID
              AND selected_candidate.measurement_id IS NULL
              AND selected_candidate.status = 'accepted'
            ORDER BY
              CASE WHEN selected_rule.rule_key = 'manual_user_link' THEN 0 ELSE 1 END,
              COALESCE(selected_rule.priority, 100),
              selected_candidate.confidence DESC,
              selected_candidate.id
            LIMIT 1
        )
        LEFT JOIN industrial_records ir ON ir.id = ilc.industrial_record_id
        LEFT JOIN industrial_source_profiles isp ON isp.id = ir.source_profile_id
        LEFT JOIN industrial_join_rules ijr ON ijr.id = ilc.join_rule_id
    """


def build_industrial_measurement_export_query(filter_query=None):
    """Build a measurement export query with optional cached industrial context columns."""

    base_query = build_measurement_export_query(filter_query)
    return _append_industrial_context_to_export_query(base_query)


def build_measurement_export_query(filter_query=None, *, include_industrial_context=False):
    if include_industrial_context:
        return build_industrial_measurement_export_query(filter_query)

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
    expression_text="",
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
    expression_clause = build_measurement_expression_clause(expression_text)
    if expression_clause is not None:
        query += f" AND ({expression_clause})"

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
