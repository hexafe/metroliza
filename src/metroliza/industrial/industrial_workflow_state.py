"""Pure state objects for Oznak industrial filtering and grouping workflows."""

from __future__ import annotations

from dataclasses import dataclass
import re


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

INDUSTRIAL_GROUPING_FIELDS: tuple[tuple[str, str], ...] = (
    ("source_db_alias", "Source"),
    ("reference", "Reference"),
    ("part_number", "Part number"),
    ("part_name", "Part name"),
    ("revision", "Revision"),
    ("serial", "Serial"),
    ("batch_lot", "Batch / lot"),
    ("work_order", "Work order"),
    ("station", "Station"),
    ("line", "Line"),
    ("operator_name", "Operator"),
    ("process_status", "Process status"),
)
INDUSTRIAL_GROUPING_FIELD_LABELS = dict(INDUSTRIAL_GROUPING_FIELDS)
INDUSTRIAL_GROUPING_ALLOWED_FIELDS = set(INDUSTRIAL_GROUPING_FIELD_LABELS)
INDUSTRIAL_QUERY_FILTER_OPERATORS = frozenset(
    {
        "=",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "LIKE",
        "NOT LIKE",
        "IN",
        "NOT IN",
        "IS NULL",
        "IS NOT NULL",
    }
)


@dataclass(frozen=True)
class IndustrialQueryFilter:
    """One server-side source filter for industrial data fetches."""

    column: str
    operator: str
    values: tuple[str, ...] = ()

    def validated(self) -> "IndustrialQueryFilter":
        require_identifier("filter column", self.column)
        operator = str(self.operator or "").strip().upper()
        if operator not in INDUSTRIAL_QUERY_FILTER_OPERATORS:
            raise ValueError(f"Unsupported industrial filter operator: {self.operator}")
        values = tuple(str(value).strip() for value in self.values if str(value).strip())
        if operator in {"IS NULL", "IS NOT NULL"}:
            values = ()
        elif operator in {"IN", "NOT IN"}:
            if not values:
                raise ValueError(f"{operator} filters require at least one value.")
        elif len(values) != 1:
            raise ValueError(f"{operator} filters require exactly one value.")
        return IndustrialQueryFilter(column=self.column.strip(), operator=operator, values=values)


@dataclass(frozen=True)
class IndustrialFetchState:
    """User-selected fetch scope for database-backed industrial sources."""

    mode: str = "guided"
    filters: tuple[IndustrialQueryFilter, ...] = ()
    limit_rows: int | None = 5_000
    fetch_all_confirmed: bool = False
    sql_text: str = ""
    sql_preview_limit: int = 5
    sql_recipe_path: str | None = None

    @property
    def is_bounded(self) -> bool:
        return bool(self.filters) or self.limit_rows is not None or self.fetch_all_confirmed

    def validated(self) -> "IndustrialFetchState":
        mode = str(self.mode or "guided").strip().lower()
        if mode not in {"guided", "sql"}:
            raise ValueError("Industrial fetch mode must be guided or sql.")
        filters = tuple(filter_state.validated() for filter_state in self.filters)
        limit_rows = self.limit_rows
        if limit_rows is not None:
            limit_rows = max(1, int(limit_rows))
        sql_preview_limit = max(1, min(500, int(self.sql_preview_limit or 5)))
        sql_text = str(self.sql_text or "").strip()
        recipe_path = str(self.sql_recipe_path or "").strip() or None
        if mode == "sql" and not sql_text:
            raise ValueError("Enter a SQL SELECT query before previewing or fetching.")
        if mode == "guided":
            sql_text = ""
            recipe_path = None
        if not filters and limit_rows is None and not self.fetch_all_confirmed:
            raise ValueError("Choose filters, set a LIMIT, or explicitly confirm fetch all.")
        return IndustrialFetchState(
            mode=mode,
            filters=filters,
            limit_rows=limit_rows,
            fetch_all_confirmed=bool(self.fetch_all_confirmed),
            sql_text=sql_text,
            sql_preview_limit=sql_preview_limit,
            sql_recipe_path=recipe_path,
        )

    def summary(self) -> str:
        parts: list[str] = []
        mode = str(self.mode or "guided").strip().lower()
        parts.append("Mode: SQL" if mode == "sql" else "Mode: guided")
        if mode == "sql":
            parts.append("SQL: entered" if str(self.sql_text or "").strip() else "SQL: empty")
        elif self.filters:
            parts.append(f"Filters: {len(self.filters)}")
        else:
            parts.append("Filters: none")
        if self.limit_rows is None:
            parts.append("LIMIT: all rows confirmed" if self.fetch_all_confirmed else "LIMIT: none")
        else:
            parts.append(f"LIMIT: {int(self.limit_rows):,}")
        return "; ".join(parts)

    @classmethod
    def from_reference_state(
        cls,
        state: "IndustrialFilterState",
        *,
        limit_rows: int | None = 5_000,
        fetch_all_confirmed: bool = False,
    ) -> "IndustrialFetchState":
        filters: tuple[IndustrialQueryFilter, ...] = tuple(state.query_filters)
        if state.references:
            filters = (
                *filters,
                IndustrialQueryFilter(
                    column=state.reference_column,
                    operator="IN",
                    values=state.references,
                ),
            )
        return cls(
            mode="guided",
            filters=filters,
            limit_rows=limit_rows,
            fetch_all_confirmed=fetch_all_confirmed,
        ).validated()

    @classmethod
    def from_sql(
        cls,
        sql_text: str,
        *,
        limit_rows: int | None = 5_000,
        fetch_all_confirmed: bool = False,
        sql_preview_limit: int = 5,
        sql_recipe_path: str | None = None,
    ) -> "IndustrialFetchState":
        return cls(
            mode="sql",
            filters=(),
            limit_rows=limit_rows,
            fetch_all_confirmed=fetch_all_confirmed,
            sql_text=sql_text,
            sql_preview_limit=sql_preview_limit,
            sql_recipe_path=sql_recipe_path,
        ).validated()


@dataclass(frozen=True)
class IndustrialFilterState:
    """User-selected Oznak source filter scope."""

    reference_column: str = "reference"
    references: tuple[str, ...] = ()
    query_filters: tuple[IndustrialQueryFilter, ...] = ()

    @property
    def is_applied(self) -> bool:
        return bool(self.references or self.query_filters)

    def summary(self) -> str:
        parts: list[str] = []
        if self.references:
            preview = ", ".join(self.references[:3])
            if len(self.references) > 3:
                preview = f"{preview}, ..."
            parts.append(f"References: {len(self.references)} value(s) in {self.reference_column} ({preview})")
        if self.query_filters:
            parts.append(f"Filters: {len(self.query_filters)}")
        return "; ".join(parts) if parts else "No filters"

    def validate_for_sync(self) -> None:
        require_identifier("reference column", self.reference_column)
        for filter_state in self.query_filters:
            filter_state.validated()
        if not self.references and not self.query_filters:
            raise ValueError("Enter at least one reference/ID value or filter before syncing industrial data.")


@dataclass(frozen=True)
class IndustrialGroupingState:
    """Selected grouping columns for cached industrial export/charts."""

    fields: tuple[str, ...] = ()

    @property
    def is_applied(self) -> bool:
        return bool(self.fields)

    def summary(self) -> str:
        if not self.fields:
            return "Grouping: not applied"
        labels = [INDUSTRIAL_GROUPING_FIELD_LABELS.get(field, field) for field in self.fields]
        return "Grouping: " + ", ".join(labels)

    def validated_fields(self) -> tuple[str, ...]:
        invalid = [field for field in self.fields if field not in INDUSTRIAL_GROUPING_ALLOWED_FIELDS]
        if invalid:
            raise ValueError(f"Unsupported industrial grouping field(s): {', '.join(invalid)}")
        return self.fields


def parse_reference_values(value: str) -> tuple[str, ...]:
    """Parse pasted reference lists separated by comma, semicolon, or whitespace."""

    candidates = re.split(r"[\s,;]+", value or "")
    references: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        reference = candidate.strip()
        if not reference or reference in seen:
            continue
        seen.add(reference)
        references.append(reference)
    return tuple(references)


def parse_industrial_query_filter_lines(value: str) -> tuple[IndustrialQueryFilter, ...]:
    """Parse simple server-side filters entered as one filter per line."""

    filters: list[IndustrialQueryFilter] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        column, operator, value_text = _split_filter_line(line)
        if operator in {"IS NULL", "IS NOT NULL"}:
            values: tuple[str, ...] = ()
        elif operator in {"IN", "NOT IN"}:
            values = parse_reference_values(value_text)
        else:
            stripped_value = _strip_filter_value(value_text)
            values = (stripped_value,) if stripped_value else ()
        filters.append(IndustrialQueryFilter(column=column, operator=operator, values=values).validated())
    return tuple(filters)


def format_industrial_query_filters(filters: tuple[IndustrialQueryFilter, ...]) -> str:
    lines: list[str] = []
    for filter_state in filters:
        if filter_state.operator in {"IS NULL", "IS NOT NULL"}:
            lines.append(f"{filter_state.column} {filter_state.operator}")
        elif filter_state.operator in {"IN", "NOT IN"}:
            lines.append(f"{filter_state.column} {filter_state.operator} {', '.join(filter_state.values)}")
        else:
            value = filter_state.values[0] if filter_state.values else ""
            lines.append(f"{filter_state.column} {filter_state.operator} {value}")
    return "\n".join(lines)


def _split_filter_line(line: str) -> tuple[str, str, str]:
    operators = (
        "IS NOT NULL",
        "IS NULL",
        "NOT LIKE",
        "NOT IN",
        ">=",
        "<=",
        "!=",
        "<>",
        "LIKE",
        "IN",
        "=",
        ">",
        "<",
    )
    upper_line = line.upper()
    for operator in operators:
        if operator in {"IS NULL", "IS NOT NULL"} and upper_line.endswith(f" {operator}"):
            column = line[: -len(operator)].strip()
            return column, operator, ""
        marker = f" {operator} "
        if marker in upper_line:
            index = upper_line.index(marker)
            column = line[:index].strip()
            value = line[index + len(marker) :].strip()
            return column, "!=" if operator == "<>" else operator, value
    raise ValueError(f"Filter line must use a supported operator: {line}")


def _strip_filter_value(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def require_identifier(field_name: str, value: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"Invalid {field_name}: '{value}'. Oznak currently accepts simple SQL identifiers "
            "using letters, numbers, and underscores only."
        )


def require_dotted_identifier(field_name: str, value: str) -> None:
    parts = str(value or "").split(".")
    if not parts or any(not part for part in parts):
        raise ValueError(
            f"Invalid {field_name}: '{value}'. Enter a table or view name like events or dbo.events."
        )
    for part in parts:
        require_identifier(field_name, part)
