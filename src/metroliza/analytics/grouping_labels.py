"""Compatibility exports for the shared group identity and label helpers."""

from metroliza.shared.grouping_labels import (
    DEFAULT_GROUP_LABEL,
    POPULATION_GROUP_ID,
    GroupDescriptor,
    group_definition_rows,
    normalize_default_group_label,
    normalize_group_labels,
)

__all__ = [
    "DEFAULT_GROUP_LABEL",
    "POPULATION_GROUP_ID",
    "GroupDescriptor",
    "group_definition_rows",
    "normalize_default_group_label",
    "normalize_group_labels",
]
