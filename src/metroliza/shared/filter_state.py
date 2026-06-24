"""Structured filter state + compact summary formatting for export UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

NOT_APPLIED_LABEL = "Not applied"
DEFAULT_DATE_FROM = "1970-01-01"


@dataclass(frozen=True)
class FilterState:
    ax_values: tuple[str, ...] = ()
    header_values: tuple[str, ...] = ()
    reference_values: tuple[str, ...] = ()
    part_name_values: tuple[str, ...] = ()
    revision_values: tuple[str, ...] = ()
    template_variant_values: tuple[str, ...] = ()
    sample_number_values: tuple[str, ...] = ()
    operator_name_values: tuple[str, ...] = ()
    sample_number_kind_values: tuple[str, ...] = ()
    status_code_values: tuple[str, ...] = ()
    filename_values: tuple[str, ...] = ()
    parser_id_values: tuple[str, ...] = ()
    template_family_values: tuple[str, ...] = ()
    has_nok_only: bool = False
    date_from: str | None = None
    date_to: str | None = None
    expression_text: str = ""


def _label_count(label: str, values: tuple[str, ...]) -> str | None:
    if not values:
        return None
    if len(values) == 1 and len(values[0]) <= 32:
        return f"{label}: {values[0]}"
    return f"{label}: {len(values)} selected"


def _effective_date_range(filter_state: FilterState) -> str | None:
    date_from = (filter_state.date_from or "").strip()
    date_to = (filter_state.date_to or "").strip()
    today = date.today().isoformat()
    if date_from == DEFAULT_DATE_FROM and (not date_to or date_to == today):
        return None
    if date_from and date_to:
        return f"{date_from} to {date_to}"
    if date_from:
        return f"from {date_from}"
    if date_to:
        return f"through {date_to}"
    return None


def summarize_filter_state(filter_state: FilterState | None) -> tuple[str, str]:
    if filter_state is None:
        return NOT_APPLIED_LABEL, NOT_APPLIED_LABEL

    summary_parts = []
    detail_parts = []
    for label, values in (
        ("AX", filter_state.ax_values),
        ("Reference", filter_state.reference_values),
        ("Header", filter_state.header_values),
        ("Part", filter_state.part_name_values),
        ("Revision", filter_state.revision_values),
        ("Variant", filter_state.template_variant_values),
        ("Sample", filter_state.sample_number_values),
        ("Operator", filter_state.operator_name_values),
        ("Sample kind", filter_state.sample_number_kind_values),
        ("Status", filter_state.status_code_values),
        ("File", filter_state.filename_values),
        ("Parser", filter_state.parser_id_values),
        ("Template family", filter_state.template_family_values),
    ):
        compact = _label_count(label, values)
        if compact is not None:
            summary_parts.append(compact)
            detail_parts.append(f"{label}: {', '.join(values)}")

    if filter_state.has_nok_only:
        summary_parts.append("NOK only")
        detail_parts.append("NOK only: enabled")

    expression_text = str(filter_state.expression_text or "").strip()
    if expression_text:
        if len(expression_text) <= 48:
            summary_parts.append(f"Expression: {expression_text}")
        else:
            summary_parts.append("Expression: custom")
        detail_parts.append(f"Expression: {expression_text}")

    date_range = _effective_date_range(filter_state)
    if date_range is not None:
        summary_parts.append(f"Date: {date_range}")
        detail_parts.append(f"Date: {date_range}")

    if not summary_parts:
        return NOT_APPLIED_LABEL, NOT_APPLIED_LABEL

    return "; ".join(summary_parts), "\n".join(detail_parts)
