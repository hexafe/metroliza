"""Helpers for parser plugin repair-loop artifact generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from metroliza.parsing.llm_plugin_factory import build_llm_contract_packet
from metroliza.parsing.parser_plugin_validation import ValidationCheck, ValidationReport


EXPECTED_RESULTS_COLUMNS = (
    "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
    "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance"
)


@dataclass(frozen=True)
class RepairContext:
    """Inputs required to build a repair-loop prompt package."""

    plugin_id: str
    failed_checks: tuple[ValidationCheck, ...]
    guidance: tuple[str, ...]
    contract_snippets: tuple[str, ...] = ()
    expected_results_columns: str = EXPECTED_RESULTS_COLUMNS
    allowed_outputs: tuple[str, ...] = ("generated_plugin.py", "tests/test_generated_plugin.py")


def _default_contract_snippets(plugin_id: str) -> tuple[str, ...]:
    contract_packet = build_llm_contract_packet(
        plugin_id=plugin_id,
        source_format="unknown",
        workflow="repair",
    )
    return (
        contract_packet["contracts/01_parser_api_contract.md"],
        contract_packet["contracts/03_sqlite_persistence_contract.md"],
        contract_packet["contracts/04_expected_results_contract.md"],
        contract_packet["contracts/05_security_and_safety_contract.md"],
    )


def build_repair_context(
    report: ValidationReport,
    guidance: Iterable[str] = (),
    *,
    contract_snippets: Iterable[str] | None = None,
) -> RepairContext:
    """Build normalized repair context from a failed validation report."""

    failed_checks = tuple(check for check in report.checks if not check.passed)
    return RepairContext(
        plugin_id=report.plugin_id,
        failed_checks=failed_checks,
        guidance=tuple(guidance),
        contract_snippets=tuple(contract_snippets or _default_contract_snippets(report.plugin_id)),
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

    lines.extend(
        [
            "",
            "## Repair constraints",
            "- Do not change plugin_id.",
            "- Keep `probe(...)` deterministic.",
            "- Do not write SQLite or any database code; return `ParseResultV2` and let Metroliza persist it.",
            "- Do not add network calls, shell commands, package installation, or new runtime architecture.",
            "- Preserve existing file names unless the validation output explicitly says otherwise.",
            "",
            "## Expected-results columns",
            context.expected_results_columns,
            "",
            "## Allowed outputs",
        ]
    )
    for output in context.allowed_outputs:
        lines.append(f"- `{output}`")

    if context.guidance:
        lines.append("- Apply project-specific guidance:")
        for item in context.guidance:
            lines.append(f"  - {item}")

    if context.contract_snippets:
        lines.extend(["", "## Contract snippets"])
        for index, snippet in enumerate(context.contract_snippets, start=1):
            lines.extend([f"### Snippet {index}", snippet.strip(), ""])

    lines.extend(
        [
            "",
            "## Required output",
            "1. Complete updated file contents only for every changed allowed output file.",
            "2. Brief change summary mapped to each failed check.",
        ]
    )
    return "\n".join(lines)


def write_repair_prompt(path: str | Path, context: RepairContext) -> Path:
    """Persist repair prompt artifact to disk."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_repair_prompt(context), encoding="utf-8")
    return target
