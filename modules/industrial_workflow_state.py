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
