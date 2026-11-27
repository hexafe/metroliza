"""Pure group-label normalization shared by analytics and export flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal


DEFAULT_GROUP_LABEL = "POPULATION"
POPULATION_GROUP_ID = "population"


@dataclass(frozen=True, slots=True)
class GroupDescriptor:
    """Stable group identity and presentation, with order given by the containing tuple."""

    group_id: str
    label: str
    color: str | None
    role: Literal["rule", "population"]


def group_definition_rows(groups: tuple[GroupDescriptor, ...]) -> list[dict[str, str | None]]:
    """Project the ordered definitions to one presentation shape."""
    return [
        {"Group": group.label, "Group ID": group.group_id, "Role": group.role, "Color": group.color}
        for group in groups
    ]


def normalize_default_group_label(value: Any, *, fallback: str = DEFAULT_GROUP_LABEL) -> str:
    """Return a non-empty default group label for grouped-analysis fallbacks."""
    label = str(value or "").strip()
    return label or str(fallback or DEFAULT_GROUP_LABEL)


def normalize_group_labels(
    series: Iterable[Any] | None,
    *,
    missing_label: str = "UNGROUPED",
    normalize_blank: bool = False,
) -> list[str]:
    """Return normalized labels without requiring pandas."""
    values = [] if series is None else list(series)
    normalized = [
        str(missing_label if _is_missing_value(value) else value) for value in values
    ]
    if not normalize_blank:
        return normalized
    return [label if label.strip() else str(missing_label) for label in normalized]


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        missing = value != value
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool):
        return missing
    module_name = type(value).__module__
    type_name = type(value).__name__
    return module_name.startswith(("pandas", "numpy")) and type_name in {
        "NAType",
        "NaTType",
    }
