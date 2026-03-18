"""Helpers for parser plugin repair-loop artifact generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from modules.parser_plugin_validation import ValidationCheck, ValidationReport


@dataclass(frozen=True)
class RepairContext:
    """Inputs required to build a repair-loop prompt package."""

    plugin_id: str
    failed_checks: tuple[ValidationCheck, ...]
    guidance: tuple[str, ...]


def build_repair_context(report: ValidationReport, guidance: Iterable[str] = ()) -> RepairContext:
    """Build normalized repair context from a failed validation report."""

    failed_checks = tuple(check for check in report.checks if not check.passed)
    return RepairContext(
        plugin_id=report.plugin_id,
        failed_checks=failed_checks,
        guidance=tuple(guidance),
    )


def render_repair_prompt(context: RepairContext) -> str:
    """Render an actionable text prompt for constrained regeneration."""

    lines = [
        f"# Repair request for parser plugin: {context.plugin_id}",
        "",
        "The candidate plugin failed validation. Regenerate ONLY parser implementation details ",
        "inside approved extension points while preserving contract and manifest identity.",
        "",
        "## Failed checks",
    ]

    if not context.failed_checks:
        lines.append("- No failing checks were supplied.")
    else:
        for check in context.failed_checks:
            detail = f" ({check.detail})" if check.detail else ""
            lines.append(f"- {check.name}{detail}")

    lines.extend(["", "## Repair constraints", "- Do not change plugin_id.", "- Keep `probe(...)` deterministic."])

    if context.guidance:
        lines.append("- Apply project-specific guidance:")
        for item in context.guidance:
            lines.append(f"  - {item}")

    lines.extend(["", "## Required output", "1. Updated plugin code.", "2. Brief change summary mapped to each failed check."])
    return "\n".join(lines)


def write_repair_prompt(path: str | Path, context: RepairContext) -> Path:
    """Persist repair prompt artifact to disk."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_repair_prompt(context), encoding="utf-8")
    return target
