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

    filters: tuple[IndustrialQueryFilter, ...] = ()
    limit_rows: int | None = 5_000
    fetch_all_confirmed: bool = False

    @property
    def is_bounded(self) -> bool:
        return bool(self.filters) or self.limit_rows is not None or self.fetch_all_confirmed

    def validated(self) -> "IndustrialFetchState":
        filters = tuple(filter_state.validated() for filter_state in self.filters)
        limit_rows = self.limit_rows
        if limit_rows is not None:
            limit_rows = max(1, int(limit_rows))
        if not filters and limit_rows is None and not self.fetch_all_confirmed:
            raise ValueError("Choose filters, set a LIMIT, or explicitly confirm fetch all.")
        return IndustrialFetchState(
            filters=filters,
            limit_rows=limit_rows,
            fetch_all_confirmed=bool(self.fetch_all_confirmed),
        )

    def summary(self) -> str:
        parts: list[str] = []
        if self.filters:
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
        filters: tuple[IndustrialQueryFilter, ...] = ()
        if state.references:
            filters = (
                IndustrialQueryFilter(
                    column=state.reference_column,
                    operator="IN",
                    values=state.references,
                ),
            )
        return cls(
            filters=filters,
            limit_rows=limit_rows,
            fetch_all_confirmed=fetch_all_confirmed,
        ).validated()


@dataclass(frozen=True)
class IndustrialFilterState:
    """User-selected Oznak source filter scope."""

    reference_column: str = "reference"
    references: tuple[str, ...] = ()

    @property
    def is_applied(self) -> bool:
        return bool(self.references)

    def summary(self) -> str:
        if not self.references:
            return "References: none selected"
        preview = ", ".join(self.references[:3])
        if len(self.references) > 3:
            preview = f"{preview}, ..."
        return f"References: {len(self.references)} value(s) in {self.reference_column} ({preview})"

    def validate_for_sync(self) -> None:
        require_identifier("reference column", self.reference_column)
        if not self.references:
            raise ValueError("Enter at least one reference or ID value before syncing industrial data.")


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


def require_identifier(field_name: str, value: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"Invalid {field_name}: '{value}'. Oznak currently accepts simple SQL identifiers "
            "using letters, numbers, and underscores only."
        )
