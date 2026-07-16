"""Scaffold and workspace helpers for LLM-assisted parser plugin creation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from metroliza.parsing.parser_plugin_paths import default_external_plugin_dir_display


@dataclass(frozen=True)
class PluginScaffoldArtifacts:
    analysis_prompt_template: str
    implementation_prompt_template: str
    plugin_template: str
    test_template: str


@dataclass(frozen=True)
class PluginWorkspaceWriteResult:
    output_dir: Path
    written_files: tuple[Path, ...]


_PYTHON_FULL_PROMPT_ORDER = (
    "prompts/01_analysis_prompt.md",
    "prompts/02_implementation_prompt.md",
)
_PYTHON_MICROTASK_PROMPT_ORDER = (
    "prompts/microtasks/01_template_analysis.md",
    "prompts/microtasks/02_manifest_probe.md",
    "prompts/microtasks/03_parser_implementation.md",
    "prompts/microtasks/04_parse_result_v2_mapping.md",
    "prompts/microtasks/05_tests_expected_results.md",
    "prompts/microtasks/06_repair_failed_checks.md",
)
_DECLARATIVE_MICROTASK_PROMPT_ORDER = (
    "prompts/01_identify_template_markers.md",
    "prompts/02_extract_report_identity.md",
    "prompts/03_extract_measurement_rows.md",
    "prompts/04_define_normalization.md",
    "prompts/05_complete_profile_yaml.md",
    "prompts/06_fix_validation_failures.md",
)


def _default_display_name(plugin_id: str) -> str:
    words = [token for token in re.split(r"[_\-\s]+", str(plugin_id).strip()) if token]
    if not words:
        return "Generated Parser Plugin"
    return " ".join(word.capitalize() for word in words) + " Parser"


def _default_class_name(plugin_id: str) -> str:
    words = [token for token in re.split(r"[^A-Za-z0-9]+", str(plugin_id).strip()) if token]
    stem = "".join(word[:1].upper() + word[1:] for word in words) or "Generated"
    return f"{stem}ReportParser"


def _default_sample_name(source_format: str) -> str:
    extension = {
        "pdf": "pdf",
        "excel": "xlsx",
        "csv": "csv",
    }.get(str(source_format).strip().lower(), "txt")
    return f"sample_report_01.{extension}"


def _render_template(template: str, replacements: dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _workspace_replacements(
    *,
    plugin_id: str,
    display_name: str | None = None,
    source_format: str = "pdf",
) -> dict[str, str]:
    normalized_plugin_id = str(plugin_id).strip()
    if not normalized_plugin_id:
        raise ValueError("plugin_id must be non-empty")

    normalized_source_format = str(source_format).strip().lower() or "pdf"
    normalized_display_name = (
        str(display_name).strip() if display_name else _default_display_name(normalized_plugin_id)
    )
    sample_file_name = _default_sample_name(normalized_source_format)
    return {
        "PLUGIN_ID": normalized_plugin_id,
        "DISPLAY_NAME": normalized_display_name,
        "SOURCE_FORMAT": normalized_source_format,
        "FILE_EXTENSION": sample_file_name.rsplit(".", 1)[-1],
        "CLASS_NAME": _default_class_name(normalized_plugin_id),
        "SAMPLE_FILE_NAME": sample_file_name,
        "INSTALL_PATH": f"{default_external_plugin_dir_display()}/{normalized_plugin_id}.py",
    }


def _github_source_url(path: str) -> str:
    return f"https://github.com/hexafe/metroliza/blob/rc2/{path}"


def _prompt_order_from_known_files(
    prompt_files: tuple[str, ...],
    expected_order: tuple[str, ...],
    *,
    prefix: str,
) -> list[str]:
    prompt_file_set = set(prompt_files)
    ordered = [path for path in expected_order if path in prompt_file_set]
    ordered.extend(
        path
        for path in prompt_files
        if path.startswith(prefix) and path not in expected_order
    )
    return ordered


def build_llm_contract_packet(
    *,
    plugin_id: str,
    display_name: str | None = None,
    source_format: str = "pdf",
    workflow: str = "python_plugin",
) -> dict[str, str]:
    """Build self-contained API and runtime contract files for LLM handoff."""

    replacements = _workspace_replacements(
        plugin_id=plugin_id,
        display_name=display_name,
        source_format=source_format,
    )
    workflow_name = str(workflow).strip() or "python_plugin"

    read_this_first = """# Read This First

This contract folder is intentionally self-contained. Give it to the LLM with the task prompt,
sample reports, supplier notes, and expected results. Do not give only the prompt file.

## Target
- Plugin/profile id: `{{PLUGIN_ID}}`
- Display name: `{{DISPLAY_NAME}}`
- Source format: `{{SOURCE_FORMAT}}`
- Workflow: `WORKFLOW_NAME`

## What the LLM must produce
- For declarative profile workflows: a completed `profile.yaml` only.
- For Python plugin workflows: complete `generated_plugin.py` and `tests/test_generated_plugin.py`.

## Non-negotiable rules
- Metroliza owns database writes. Parser output must be `ParseResultV2`; do not write SQLite.
- Keep parsing deterministic and local. No network calls, installers, background services, or new dependencies.
- Preserve `plugin_id`, source format, and manifest identity.
- Use expected results as acceptance checks, not as training data to hard-code one sample.
- When unsure, add a structured warning or ask for another sample instead of guessing.

## Minimum handoff files
- `contracts/00_read_this_first.md`
- `contracts/01_parser_api_contract.md`
- `contracts/02_runtime_selection_contract.md`
- `contracts/03_sqlite_persistence_contract.md`
- `contracts/04_expected_results_contract.md`
- the current prompt from `prompts/`
- `supplier_intake.md` or supplier notes
- `expected_results.csv` or `expected_results_template.csv`
- 3-5 representative sample reports
""".replace("WORKFLOW_NAME", workflow_name)

    parser_api = """# Parser API Contract

This is the stable API between a parser plugin and the rest of Metroliza.
The generated parser should map source data into these dataclasses exactly.

## Required dataclasses

```python
@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    display_name: str
    version: str
    supported_formats: tuple[str, ...]
    supported_locales: tuple[str, ...] = ("*",)
    template_ids: tuple[str, ...] = ()
    priority: int = 100
    capabilities: dict[str, Any] = field(default_factory=dict)

class ProbeOutcome(str, Enum):
    MATCH = "match"
    NO_MATCH = "no_match"
    INSPECTION_ERROR = "inspection_error"

@dataclass(frozen=True)
class ProbeResult:
    plugin_id: str
    can_parse: bool
    confidence: int
    matched_template_id: str | None = None
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    outcome: ProbeOutcome | None = None
    semantic_row_count: int | None = None

@dataclass(frozen=True)
class ParseMetaV2:
    source_file: str
    source_format: str
    plugin_id: str
    plugin_version: str
    template_id: str | None
    parse_timestamp: str
    locale_detected: str | None
    confidence: int

@dataclass(frozen=True)
class ReportInfoV2:
    reference: str
    report_date: str
    sample_number: str
    file_name: str
    file_path: str

@dataclass(frozen=True)
class MeasurementV2:
    axis_code: str
    nominal: float | None
    tol_plus: float | None
    tol_minus: float | None
    bonus: float | None
    measured: float | None
    deviation: float | None
    out_of_tolerance: float | None
    raw_tokens: tuple[str, ...] = ()
    raw_line_refs: tuple[int, ...] = ()
    extensions: dict[str, str | float | int | bool | None] = field(default_factory=dict)

@dataclass(frozen=True)
class MeasurementBlockV2:
    header_raw: tuple[str, ...]
    header_normalized: str
    dimensions: tuple[MeasurementV2, ...]
    block_index: int

@dataclass(frozen=True)
class ParseResultV2:
    meta: ParseMetaV2
    report: ReportInfoV2
    blocks: tuple[MeasurementBlockV2, ...]
    warnings: tuple[ParseWarning, ...] = ()
    errors: tuple[ParseError, ...] = ()
```

## Required Python plugin shape

```python
class GeneratedParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(...)

    @classmethod
    def probe(cls, input_ref: str | Path, context: ProbeContext) -> ProbeResult:
        ...

    def open_report(self):
        ...

    def split_text_to_blocks(self):
        ...

    def parse_to_v2(self) -> ParseResultV2:
        ...

    @staticmethod
    def to_legacy_blocks(parse_result_v2: ParseResultV2):
        ...
```

## Field mapping
- `ReportInfoV2.reference`: report/part/customer reference shown by the supplier.
- `ReportInfoV2.report_date`: normalized date string, preferably `YYYY-MM-DD` when known.
- `ReportInfoV2.sample_number`: supplier sample/cavity/run identifier. Use an empty string if absent.
- `MeasurementBlockV2.header_normalized`: stable group/header label used by CSV summary grouping.
- `MeasurementV2.axis_code`: dimension axis or characteristic code, for example `X`, `Y`, `D1`.
- Numeric fields must be `float` or `None`, never localized strings with comma decimal separators.
- Put source-only extra fields into `MeasurementV2.extensions`; do not add new dataclass fields.
"""

    runtime_selection = """# Runtime Selection Contract

Metroliza selects one parser before parsing a report.

## Probe behavior
- `probe(...)` must be bounded and inspect decoded source contents, never the file name.
- Return `outcome=NO_MATCH`, `can_parse=False`, and confidence `0` for unsupported content.
- Return `outcome=INSPECTION_ERROR` when the source container cannot be decoded reliably.
- Return confidence `80-100` only after at least one row matches the parser's measurement grammar.
- Return confidence below `80` for weak matches; strict runtime selection rejects those by default.
- Report the bounded preflight count in `semantic_row_count`.

## Selection order
1. Source format from the suffix is a transport prefilter only.
2. Only plugins whose manifest supports that source format are considered.
3. Semantic candidates rank before legacy lexical candidates, then by confidence and priority.
4. A remaining tie is rejected as ambiguous instead of being decided by plugin id.
5. Strict matching requires confidence >= 80 by default.

## Manifest guidance for `{{PLUGIN_ID}}`
- `plugin_id`: `{{PLUGIN_ID}}`
- `display_name`: `{{DISPLAY_NAME}}`
- `supported_formats`: (`{{SOURCE_FORMAT}}`,)
- `supported_locales`: use exact locales when known, otherwise `("*",)`.
- `template_ids`: add the supplier/template version names found in samples.
- `priority`: keep `100` unless Metroliza maintainers explicitly choose another value.
"""

    sqlite_persistence = """# SQLite Persistence Contract

The LLM must not write database code. Metroliza converts `ParseResultV2` into local SQLite rows.

## Persistence path
1. The parser produces `ParseResultV2`.
2. Metroliza creates canonical report metadata from `ParseResultV2.report` and `ParseResultV2.meta`.
3. Each `MeasurementV2` becomes one `report_measurements` row.
4. CSV Summary, filtering, grouping, Excel export, and dashboard export read from the same local SQLite schema.

## Measurement mapping into SQLite
- `MeasurementBlockV2.header_normalized` -> `report_measurements.header`, `section_name`, `feature_label`
- `MeasurementV2.axis_code` -> `ax`
- `MeasurementV2.nominal` -> `nominal`
- `MeasurementV2.tol_plus` -> `tol_plus`
- `MeasurementV2.tol_minus` -> `tol_minus`
- `MeasurementV2.bonus` -> `bonus`
- `MeasurementV2.measured` -> `meas`
- `MeasurementV2.deviation` -> `dev`
- `MeasurementV2.out_of_tolerance` -> `outtol`
- `MeasurementV2.extensions["characteristic_name"]` -> `characteristic_name`
- `MeasurementV2.extensions["characteristic_family"]` -> `characteristic_family`
- `MeasurementV2.extensions["description"]` -> `description`
- raw tokens, line refs, extensions, and block index are preserved in `raw_measurement_json`.

## Do not do this
- Do not write SQLite directly.
- Do not open SQLite connections from plugin code.
- Do not create, alter, or query Metroliza database tables.
- Do not write CSV/Excel/dashboard files from parser code.
- Do not bypass `ParseResultV2`; that is the API boundary.
"""

    expected_results = """# Expected Results Contract

Expected results are the human-verified rows used to prove the parser did not drift.

## CSV columns
`sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance`

## Rules
- Include every parsed measurement row for each approval sample.
- Use enough representative samples to cover the supplier/template variants the profile will parse.
- Use normalized numeric values with `.` decimal separators.
- Leave optional numeric cells blank when the report genuinely has no value.
- Every expected row must match one parsed row in the same sample.
- Do not hard-code expected results into parser code; use them only for tests and validation.

## Review checklist for a non-technical user
- Reference/date/sample values match the report header.
- The important measured rows are present.
- Units and decimal separators are interpreted correctly.
- Repeated blocks are not merged accidentally.
- Missing values are blank/None, not fake zeros.
"""

    security = """# Security And Safety Contract

Parser plugins handle local report files. Keep them narrow and predictable.

## Allowed
- Python standard library.
- Existing Metroliza parser contracts and base classes.
- `pandas` only when Metroliza already uses it for workbook/csv parsing.
- Read only the supplied report file and local sample fixtures.

## Forbidden
- Network calls.
- Shell commands.
- Installing packages.
- Reading credentials, tokens, or unrelated user files.
- Database writes from plugin code.
- Dynamic code execution such as `eval`, `exec`, or importing code from report contents.
- Hidden background services or telemetry.

## Failure behavior
- Raise a clear exception for unsupported corrupt input.
- Use `ParseWarning` for recoverable ambiguity.
- Return no measurements only when the sample truly has none or parsing cannot safely identify rows.
"""

    privacy_redaction = """# Privacy Redaction Checklist

Use this checklist before sharing a parser handoff package with any external LLM.

## Keep
- Supplier/template labels that are needed for `probe.required_markers`.
- Column names, visible section headers, units, date examples, and decimal-separator examples.
- Enough anonymized rows to prove the parser can read each measurement shape.

## Remove or replace
- Customer names and addresses.
- Operator names, signatures, emails, phone numbers, and personal identifiers.
- Purchase/order numbers unless they are required parser fields and approved for sharing.
- Credentials, tokens, paths outside the handoff folder, and unrelated report pages.

## Approval rule
- If a real report cannot be redacted safely, use a local/offline LLM or manual profile editing.
- Keep the redacted sample filename stable so `expected_results.csv` still points to the right sample.
"""

    github_references = f"""# GitHub Source References

These links are supplemental. The contract files in this folder contain the minimum API details needed
when the LLM has no repository access.

- Parser contracts: {_github_source_url("src/metroliza/parsing/parser_plugin_contracts.py")}
- Base parser bridge: {_github_source_url("src/metroliza/parsing/base_report_parser.py")}
- Parser factory selection: {_github_source_url("src/metroliza/parsing/report_parser_factory.py")}
- Validation helper: {_github_source_url("src/metroliza/parsing/parser_plugin_validation.py")}
- Declarative profiles: {_github_source_url("src/metroliza/parsing/declarative_parser_profiles.py")}
- Parser plugin docs: {_github_source_url("docs/parser_plugins/parser_plugin_specification.md")}
"""

    contract_files = {
        "contracts/00_read_this_first.md": read_this_first,
        "contracts/01_parser_api_contract.md": parser_api,
        "contracts/02_runtime_selection_contract.md": runtime_selection,
        "contracts/03_sqlite_persistence_contract.md": sqlite_persistence,
        "contracts/04_expected_results_contract.md": expected_results,
        "contracts/05_security_and_safety_contract.md": security,
        "contracts/06_github_references.md": github_references,
        "contracts/07_privacy_redaction_checklist.md": privacy_redaction,
    }
    return {
        path: _render_template(contents, replacements)
        for path, contents in contract_files.items()
    }


def build_llm_microtask_prompts(
    *,
    plugin_id: str,
    display_name: str | None = None,
    source_format: str = "pdf",
    workflow: str = "python_plugin",
) -> dict[str, str]:
    """Build small sequential prompts for cheaper/local LLM workflows."""

    replacements = _workspace_replacements(
        plugin_id=plugin_id,
        display_name=display_name,
        source_format=source_format,
    )
    workflow_name = str(workflow).strip().lower() or "python_plugin"

    if workflow_name in {"declarative_profile", "profile", "yaml"}:
        prompts = {
            "prompts/01_identify_template_markers.md": """# Task 1 - Identify Template Markers

Use only the supplied reports, supplier notes, expected results, and `contracts/`.

Return:
1. Stable phrases or labels present in every sample.
2. Sheet names, section headers, or file cues that identify the template.
3. Markers that must NOT be used because they are variable values.
4. Confidence that these markers distinguish `{{PLUGIN_ID}}` from other suppliers.
""",
            "prompts/02_extract_report_identity.md": """# Task 2 - Extract Report Identity

Complete only the profile fields needed to extract:
- reference
- report_date
- sample_number

Return YAML fragments for `extraction.report_fields` and explain which sample lines prove each rule.
Do not write Python code.
""",
            "prompts/03_extract_measurement_rows.md": """# Task 3 - Extract Measurement Rows

Design line-anchored measurement extraction rules for `{{SOURCE_FORMAT}}` reports.

Return YAML fragments for `extraction.blocks`.
Each row capture must use these names:
axis_code, nominal, tol_plus, tol_minus, bonus, measured, deviation, out_of_tolerance.
Do not write Python code.
""",
            "prompts/04_define_normalization.md": """# Task 4 - Define Normalization

List decimal separators, date formats, blank-value handling, unit assumptions, and header aliases.
Return only profile YAML fields and concise notes that a reviewer can verify in samples.
""",
            "prompts/05_complete_profile_yaml.md": """# Task 5 - Complete Profile YAML

Using the previous answers and `contracts/`, return complete `profile.yaml`.

Hard constraints:
- Keep plugin id `{{PLUGIN_ID}}`.
- Keep source format `{{SOURCE_FORMAT}}`.
- Keep the profile data-only YAML.
- Do not ask for Python code, database code, package changes, network calls, or installer changes.
""",
            "prompts/06_fix_validation_failures.md": """# Task 6 - Fix Validation Failures

Use the validation output, expected results, `profile.yaml`, samples, and `contracts/`.
Return a corrected complete `profile.yaml` only.
For each failed check, state the exact YAML rule that changed.
""",
        }
    else:
        prompts = {
            "prompts/microtasks/01_template_analysis.md": """# Task 1 - Analyze Report Template

Use only supplied reports, supplier notes, expected results, and `contracts/`.

Return:
1. Source format and template family.
2. Stable markers for `probe(...)`.
3. Report identity fields: reference, report_date, sample_number.
4. Measurement block/header structure.
5. Numeric locale rules and blank-value rules.
6. Ambiguities that require another sample.
""",
            "prompts/microtasks/02_manifest_probe.md": """# Task 2 - Write Manifest And Probe

Return only the `PluginManifest` and `probe(...)` implementation for `generated_plugin.py`.

Hard constraints:
- plugin id: `{{PLUGIN_ID}}`
- source format: `{{SOURCE_FORMAT}}`
- return `ProbeResult`
- confidence must be 80-100 only after bounded measurement-row evidence
- report `semantic_row_count` and a typed outcome
- never use the file name as report-family evidence
""",
            "prompts/microtasks/03_parser_implementation.md": """# Task 3 - Write Source Extraction

Return only `open_report(...)`, helper functions, and `split_text_to_blocks(...)`.
Use deterministic local parsing and no new dependencies.
Preserve the legacy row order: [AX, NOM, +TOL, -TOL, BONUS, MEAS, DEV, OUTTOL].
""",
            "prompts/microtasks/04_parse_result_v2_mapping.md": """# Task 4 - Write ParseResultV2 Mapping

Return only `parse_to_v2(...)` and related mapping helpers.
Map every report into `ParseResultV2`, `ReportInfoV2`, `MeasurementBlockV2`, and `MeasurementV2`.
Use `MeasurementV2.extensions` for characteristic names, families, descriptions, units, or supplier-only fields.
Do not write SQLite code.
""",
            "prompts/microtasks/05_tests_expected_results.md": """# Task 5 - Write Legacy Adapter And Tests

Return:
1. `to_legacy_blocks(parse_result_v2)`
2. `tests/test_generated_plugin.py`

Tests must cover probe, parse_to_v2, legacy block shape, and expected-results values.
Do not skip tests for missing sample data; ask for samples if needed.
""",
            "prompts/microtasks/06_repair_failed_checks.md": """# Task 6 - Fix Validation Failures

Use validation output, generated code, expected results, samples, and `contracts/`.
Return complete corrected file contents for changed files only.
Map each change to a failed validation check.
Do not change `plugin_id` unless the user explicitly requests it.
""",
        }

    return {
        path: _render_template(contents, replacements)
        for path, contents in prompts.items()
    }


def build_llm_handoff_manifest(
    *,
    plugin_id: str,
    display_name: str | None = None,
    source_format: str = "pdf",
    workflow: str = "python_plugin",
    files: tuple[str, ...] = (),
) -> str:
    """Return machine-readable handoff metadata for generated workspaces."""

    replacements = _workspace_replacements(
        plugin_id=plugin_id,
        display_name=display_name,
        source_format=source_format,
    )
    workflow_name = str(workflow).strip().lower() or "python_plugin"
    is_declarative = workflow_name in {"declarative_profile", "profile", "yaml"}
    prompt_files = sorted(path for path in files if path.startswith("prompts/"))
    prompt_file_set = set(prompt_files)
    full_prompt_order = (
        []
        if is_declarative
        else [path for path in _PYTHON_FULL_PROMPT_ORDER if path in prompt_file_set]
    )
    microtask_prompt_order = (
        _prompt_order_from_known_files(
            tuple(prompt_files),
            _DECLARATIVE_MICROTASK_PROMPT_ORDER,
            prefix="prompts/",
        )
        if is_declarative
        else _prompt_order_from_known_files(
            tuple(prompt_files),
            _PYTHON_MICROTASK_PROMPT_ORDER,
            prefix="prompts/microtasks/",
        )
    )
    installation_path = (
        f"{default_external_plugin_dir_display()}/profiles/approved/"
        f"{replacements['PLUGIN_ID']}/profile.yaml"
        if is_declarative
        else replacements["INSTALL_PATH"]
    )
    validation_commands = (
        [
            "PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate "
            "profile.yaml --expected-results expected_results.csv --workspace .",
            f"PYTHONPATH=src:. python scripts/parser_plugin_self_service.py diagnose profile.yaml "
            f"samples/{replacements['SAMPLE_FILE_NAME']}",
        ]
        if is_declarative
        else [
            "python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id "
            f"{replacements['PLUGIN_ID']} --sample-input samples/{replacements['SAMPLE_FILE_NAME']} "
            "--expected-results expected_results_template.csv",
            f"python scripts/explain_parser_resolution.py samples/{replacements['SAMPLE_FILE_NAME']} "
            "--paths generated_plugin.py",
        ]
    )
    payload = {
        "schema_version": 1,
        "package_type": workflow,
        "plugin_id": replacements["PLUGIN_ID"],
        "display_name": replacements["DISPLAY_NAME"],
        "source_format": replacements["SOURCE_FORMAT"],
        "workflow": workflow,
        "self_contained": True,
        "contract_files": [
            "contracts/00_read_this_first.md",
            "contracts/01_parser_api_contract.md",
            "contracts/02_runtime_selection_contract.md",
            "contracts/03_sqlite_persistence_contract.md",
            "contracts/04_expected_results_contract.md",
            "contracts/05_security_and_safety_contract.md",
            "contracts/06_github_references.md",
            "contracts/07_privacy_redaction_checklist.md",
        ],
        "prompt_files": prompt_files,
        "prompt_order": prompt_files,
        "full_prompt_order": full_prompt_order,
        "microtask_prompt_order": microtask_prompt_order,
        "sample_file_name": replacements["SAMPLE_FILE_NAME"],
        "installation_path": installation_path,
        "allowed_outputs": (
            ["profile.yaml"] if is_declarative else ["generated_plugin.py", "tests/test_generated_plugin.py"]
        ),
        "validation_commands": validation_commands,
        "runtime_contract": {
            "parser_output": "ParseResultV2",
            "database_owner": "Metroliza ReportRepository",
            "plugin_must_write_sqlite": False,
            "strict_selection_min_confidence": 80,
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def build_plugin_scaffold() -> PluginScaffoldArtifacts:
    """Return baseline templates used by the LLM plugin factory workflow."""

    return PluginScaffoldArtifacts(
        analysis_prompt_template=(
            "# Analysis Prompt\n\n"
            "You are designing a Metroliza parser plugin candidate.\n"
            "You must stay inside the existing parser-plugin contract and must not invent new architecture.\n\n"
            "## Inputs you will receive\n"
            "- `supplier_intake.md`\n"
            "- one or more sample reports\n"
            "- `expected_results_template.csv` filled with every parsed row from approval samples\n\n"
            "## Your job\n"
            "1. Identify the report format, template family, and stable template cues.\n"
            "2. Propose a safe `probe(...)` strategy that works with runtime selection.\n"
            "3. Map source fields into `ParseResultV2` and the legacy row order.\n"
            "4. Call out locale assumptions: decimal separators, dates, units, language, header aliases.\n"
            "5. Explain how to build `raw_text`, `blocks_text`, and final V2 measurement rows.\n"
            "6. Explain how `expected_results_template.csv` should cover every parsed approval row.\n"
            "7. List ambiguities, risks, and any extra samples needed.\n\n"
            "## Required output sections\n"
            "- Template summary\n"
            "- Manifest proposal\n"
            "- Runtime selection notes\n"
            "- Probe strategy\n"
            "- Field mapping table\n"
            "- Parsing algorithm\n"
            "- Expected-results validation notes\n"
            "- Ambiguities and fallback policy\n"
            "- Questions for the user\n"
        ),
        implementation_prompt_template=(
            "# Implementation Prompt\n\n"
            "Implement a Metroliza parser plugin using only the approved scaffold files.\n"
            "Do not add new dependencies and do not change framework architecture.\n\n"
            "## Files you must return\n"
            "- `generated_plugin.py`\n"
            "- `tests/test_generated_plugin.py`\n\n"
            "## Hard constraints\n"
            "- Inherit both `BaseReportParser` and `BaseReportParserPlugin`.\n"
            "- Implement `probe`, `open_report`, `split_text_to_blocks`, `parse_to_v2`, and `to_legacy_blocks`.\n"
            "- Keep parsing deterministic.\n"
            "- Preserve the requested `plugin_id` and supported format.\n"
            "- Set the manifest fields explicitly: `plugin_id`, `display_name`, `supported_formats`, `supported_locales`, `template_ids`, `priority`, and `capabilities`.\n"
            "- Make `probe(...)` bounded and require at least one measurement-row match before returning MATCH.\n"
            "- Report a typed probe outcome and `semantic_row_count`; never use the file name as family evidence.\n"
            "- Replace scaffold TODO template markers with text, sheet names, or header labels visible in every intended supplier sample.\n"
            "- Use `ParseResultV2` and nested dataclasses from `metroliza.parsing.parser_plugin_contracts`.\n"
            "- Use only stdlib plus imports already present in the approved scaffold.\n"
            "- Do not invent new runtime flags, registries, or base classes.\n\n"
            "## Output format\n"
            "Return complete file contents for each required file.\n"
            "Explain any assumptions briefly after the files.\n"
        ),
        plugin_template=(
            "from __future__ import annotations\n\n"
            "from pathlib import Path\n"
            "import re\n"
            "from time import strftime\n\n"
            "from metroliza.parsing.base_report_parser import BaseReportParser\n"
            "from metroliza.parsing.parser_plugin_contracts import (\n"
            "    BaseReportParserPlugin,\n"
            "    MeasurementBlockV2,\n"
            "    MeasurementV2,\n"
            "    ParseMetaV2,\n"
            "    ParseResultV2,\n"
            "    PluginManifest,\n"
            "    ProbeContext,\n"
            "    ProbeOutcome,\n"
            "    ProbeResult,\n"
            "    ReportInfoV2,\n"
            ")\n"
            "from metroliza.parsing.source_inspection import SourceInspectionContext\n\n\n"
            "class {{CLASS_NAME}}(BaseReportParser, BaseReportParserPlugin):\n"
            "    manifest = PluginManifest(\n"
            "        plugin_id=\"{{PLUGIN_ID}}\",\n"
            "        display_name=\"{{DISPLAY_NAME}}\",\n"
            "        version=\"0.1.0\",\n"
            "        supported_formats=(\"{{SOURCE_FORMAT}}\",),\n"
            "        supported_locales=(\"*\",),\n"
            "        template_ids=(\"default\",),\n"
            "        priority=100,\n"
            "        capabilities={\"ocr_required\": False},\n"
            "    )\n\n"
            "    @classmethod\n"
            "    def probe(cls, input_ref: str | Path, context: ProbeContext) -> ProbeResult:\n"
            "        source_format = (context.source_format or \"\").lower()\n"
            "        if source_format and source_format not in cls.manifest.supported_formats:\n"
            "            return ProbeResult(\n"
            "                plugin_id=cls.manifest.plugin_id,\n"
            "                can_parse=False,\n"
            "                confidence=0,\n"
            "                reasons=(\"unsupported_source_format\",),\n"
            "                outcome=ProbeOutcome.NO_MATCH,\n"
            "                semantic_row_count=0,\n"
            "            )\n\n"
            "        # Replace these placeholders with content evidence before installation.\n"
            "        required_markers = (\"TODO_REPLACE_WITH_SUPPLIER_TEMPLATE_MARKER\",)\n"
            "        measurement_row_pattern = r\"TODO_REPLACE_WITH_MEASUREMENT_ROW_REGEX\"\n"
            "        if any(marker.startswith(\"TODO_\") for marker in required_markers) or measurement_row_pattern.startswith(\"TODO_\"):\n"
            "            return ProbeResult(\n"
            "                plugin_id=cls.manifest.plugin_id,\n"
            "                can_parse=False,\n"
            "                confidence=0,\n"
            "                reasons=(\"semantic_probe_not_configured\",),\n"
            "                outcome=ProbeOutcome.NO_MATCH,\n"
            "                semantic_row_count=0,\n"
            "            )\n\n"
            "        inspection = context.source_inspection or SourceInspectionContext.from_path(\n"
            "            input_ref, source_format=source_format or \"{{SOURCE_FORMAT}}\"\n"
            "        )\n"
            "        try:\n"
            "            if (source_format or \"{{SOURCE_FORMAT}}\") == \"pdf\":\n"
            "                sample_text = inspection.get_pdf_text(max_chars=2_000_000)\n"
            "            elif (source_format or \"{{SOURCE_FORMAT}}\") == \"csv\":\n"
            "                sample_text = Path(input_ref).read_text(encoding=\"utf-8\", errors=\"strict\")\n"
            "                if len(sample_text) > 2_000_000:\n"
            "                    raise ValueError(\"decoded source exceeds the semantic probe limit\")\n"
            "            else:\n"
            "                return ProbeResult(\n"
            "                    plugin_id=cls.manifest.plugin_id,\n"
            "                    can_parse=False,\n"
            "                    confidence=0,\n"
            "                    reasons=(\"source_reader_not_configured\",),\n"
            "                    outcome=ProbeOutcome.NO_MATCH,\n"
            "                    semantic_row_count=0,\n"
            "                )\n"
            "        except Exception as exc:\n"
            "            return ProbeResult(\n"
            "                plugin_id=cls.manifest.plugin_id,\n"
            "                can_parse=False,\n"
            "                confidence=0,\n"
            "                reasons=(\"content_inspection_failed\",),\n"
            "                warnings=(f\"{type(exc).__name__}: {exc}\",),\n"
            "                outcome=ProbeOutcome.INSPECTION_ERROR,\n"
            "                semantic_row_count=0,\n"
            "            )\n"
            "        normalized_text = sample_text.casefold()\n"
            "        missing_markers = tuple(marker for marker in required_markers if marker.casefold() not in normalized_text)\n"
            "        semantic_row_count = sum(\n"
            "            1 for line in sample_text.splitlines() if re.match(measurement_row_pattern, line)\n"
            "        )\n"
            "        if not missing_markers and semantic_row_count > 0:\n"
            "            return ProbeResult(\n"
            "                plugin_id=cls.manifest.plugin_id,\n"
            "                can_parse=True,\n"
            "                confidence=85,\n"
            "                matched_template_id=\"default\",\n"
            "                reasons=(\"template_markers\", \"semantic_measurements\"),\n"
            "                outcome=ProbeOutcome.MATCH,\n"
            "                semantic_row_count=semantic_row_count,\n"
            "            )\n"
            "        return ProbeResult(\n"
            "            plugin_id=cls.manifest.plugin_id,\n"
            "            can_parse=False,\n"
            "            confidence=0,\n"
            "            reasons=(\"missing_template_markers\" if missing_markers else \"no_semantic_measurements\",),\n"
            "            warnings=missing_markers,\n"
            "            outcome=ProbeOutcome.NO_MATCH,\n"
            "            semantic_row_count=0,\n"
            "        )\n\n"
            "    def open_report(self):\n"
            "        \"\"\"Populate `raw_text` from the source file deterministically.\"\"\"\n"
            "        report_path = Path(self.file_path) / self.file_name\n"
            "        raise NotImplementedError(f\"Implement raw-text extraction for {report_path}\")\n\n"
            "    def split_text_to_blocks(self):\n"
            "        \"\"\"Populate `blocks_text` using the legacy block shape.\n\n"
            "        Expected legacy row order:\n"
            "        [AX, NOM, +TOL, -TOL, BONUS, MEAS, DEV, OUTTOL]\n"
            "        \"\"\"\n"
            "        raise NotImplementedError(\"Implement deterministic block extraction\")\n\n"
            "    def parse_to_v2(self) -> ParseResultV2:\n"
            "        if not self.raw_text:\n"
            "            self.open_report()\n"
            "        if not self.blocks_text:\n"
            "            self.split_text_to_blocks()\n\n"
            "        blocks_v2: list[MeasurementBlockV2] = []\n"
            "        # TODO: convert `self.blocks_text` into `MeasurementBlockV2` items.\n"
            "        # Use one `MeasurementV2` per measurement row.\n\n"
            "        return ParseResultV2(\n"
            "            meta=ParseMetaV2(\n"
            "                source_file=str(Path(self.file_path) / self.file_name),\n"
            "                source_format=\"{{SOURCE_FORMAT}}\",\n"
            "                plugin_id=self.manifest.plugin_id,\n"
            "                plugin_version=self.manifest.version,\n"
            "                template_id=self.manifest.template_ids[0] if self.manifest.template_ids else None,\n"
            "                parse_timestamp=strftime(\"%Y-%m-%dT%H:%M:%SZ\"),\n"
            "                locale_detected=None,\n"
            "                confidence=85,\n"
            "            ),\n"
            "            report=ReportInfoV2(\n"
            "                reference=self.reference,\n"
            "                report_date=self.date,\n"
            "                sample_number=self.sample_number,\n"
            "                file_name=self.file_name,\n"
            "                file_path=self.file_path,\n"
            "            ),\n"
            "            blocks=tuple(blocks_v2),\n"
            "        )\n\n"
            "    @staticmethod\n"
            "    def to_legacy_blocks(parse_result_v2: ParseResultV2):\n"
            "        legacy_blocks = []\n"
            "        for block in parse_result_v2.blocks:\n"
            "            header = [list(block.header_raw)]\n"
            "            rows = []\n"
            "            for row in block.dimensions:\n"
            "                rows.append([\n"
            "                    row.axis_code,\n"
            "                    row.nominal,\n"
            "                    row.tol_plus,\n"
            "                    row.tol_minus,\n"
            "                    row.bonus,\n"
            "                    row.measured,\n"
            "                    row.deviation,\n"
            "                    row.out_of_tolerance,\n"
            "                ])\n"
            "            legacy_blocks.append([header, rows])\n"
            "        return legacy_blocks\n"
        ),
        test_template=(
            "from metroliza.parsing.parser_plugin_contracts import ParseResultV2, ProbeContext, infer_source_format\n"
            "from generated_plugin import {{CLASS_NAME}}\n\n\n"
            "def test_generated_plugin_contract_conformance(tmp_path):\n"
            "    sample_file = tmp_path / \"{{SAMPLE_FILE_NAME}}\"\n"
            "    sample_file.write_text(\"replace with a real sample during implementation\\n\", encoding=\"utf-8\")\n"
            "    parser = {{CLASS_NAME}}(str(sample_file), database=\":memory:\")\n"
            "    probe_result = {{CLASS_NAME}}.probe(sample_file, ProbeContext(source_path=str(sample_file), source_format=infer_source_format(sample_file)))\n"
            "    assert probe_result.plugin_id == \"{{PLUGIN_ID}}\"\n"
            "    assert 0 <= probe_result.confidence <= 100\n"
            "    assert probe_result.can_parse is True\n"
            "    parse_result = parser.parse_to_v2()\n"
            "    assert isinstance(parse_result, ParseResultV2)\n"
            "    assert parse_result.meta.plugin_id == \"{{PLUGIN_ID}}\"\n"
            "    assert parse_result.meta.source_format == \"{{SOURCE_FORMAT}}\"\n"
            "    assert parse_result.report.file_name == sample_file.name\n"
            "    legacy_blocks = parser.to_legacy_blocks(parse_result)\n"
            "    assert isinstance(legacy_blocks, list)\n"
            "    if legacy_blocks:\n"
            "        assert isinstance(legacy_blocks[0], list)\n"
            "        assert len(legacy_blocks[0]) == 2\n"
        ),
    )


def build_plugin_workspace_bundle(
    *,
    plugin_id: str,
    display_name: str | None = None,
    source_format: str = "pdf",
) -> dict[str, str]:
    """Build a ready-to-fill non-technical workspace bundle for one plugin."""

    replacements = _workspace_replacements(
        plugin_id=plugin_id,
        display_name=display_name,
        source_format=source_format,
    )
    scaffold = build_plugin_scaffold()
    contract_packet = build_llm_contract_packet(
        plugin_id=replacements["PLUGIN_ID"],
        display_name=replacements["DISPLAY_NAME"],
        source_format=replacements["SOURCE_FORMAT"],
        workflow="python_plugin",
    )
    microtask_prompts = build_llm_microtask_prompts(
        plugin_id=replacements["PLUGIN_ID"],
        display_name=replacements["DISPLAY_NAME"],
        source_format=replacements["SOURCE_FORMAT"],
        workflow="python_plugin",
    )

    workspace_readme = """# Parser Plugin Workspace

This folder is the complete working packet for one Metroliza parser plugin.

## What this workspace is for
- A non-technical user can prepare the business context and sample files.
- An LLM can use the prompts and scaffold here to generate the parser code.
- The generated parser can be validated and repaired with explicit commands.

## Step-by-step
1. Put 3-5 real sample reports into `samples/`.
2. Fill `supplier_intake.md`.
3. Fill `expected_results_template.csv` with every parsed row from the approval samples.
4. Upload the sample reports, `supplier_intake.md`, `expected_results_template.csv`, `contracts/`, and `prompts/01_analysis_prompt.md` to your LLM.
5. Save the LLM analysis into `responses/analysis_response.md`.
6. Upload `responses/analysis_response.md`, `contracts/`, `prompts/02_implementation_prompt.md`, `generated_plugin.py`, and `tests/test_generated_plugin.py` to the LLM.
7. Paste the returned file contents into `generated_plugin.py` and `tests/test_generated_plugin.py`.
8. Validate the generated plugin:

```bash
python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id {{PLUGIN_ID}} --sample-input samples/{{SAMPLE_FILE_NAME}} --expected-results expected_results_template.csv
```

9. If validation fails, generate a repair prompt:

```bash
python scripts/build_parser_plugin_repair_prompt.py --paths generated_plugin.py --plugin-id {{PLUGIN_ID}} --sample-input samples/{{SAMPLE_FILE_NAME}} --expected-results expected_results_template.csv --output artifacts/repair_prompt.md
```

10. Check resolver diagnostics before installation:

```bash
python scripts/explain_parser_resolution.py samples/{{SAMPLE_FILE_NAME}} --paths generated_plugin.py
```

11. Re-run the LLM using `artifacts/repair_prompt.md`, then validate again.
12. After validation passes, install the parser by copying `generated_plugin.py` to `{{INSTALL_PATH}}`.
13. Restart Metroliza and load a report from the new supplier. The parser factory will probe the file and select this plugin when it matches.

## Smaller local-LLM workflow
- Use `NON_TECHNICAL_STEPS.md` when you want very small tasks.
- Send one file from `prompts/microtasks/` at a time.
- Always include `reference/contract_snippets.md` and the relevant files named by the prompt.
- Do not let the LLM write database, export, installer, or network code.

## Runtime loading
- Metroliza automatically discovers parser plugins placed in `{{INSTALL_PATH}}`.
- Advanced override: `PARSER_EXTERNAL_PLUGIN_PATHS` can still point to extra plugin files or folders.

## How selection works
- Metroliza uses the file suffix only as a transport prefilter.
- The factory only asks plugins whose manifests declare that format in `supported_formats`.
- Each candidate inspects decoded content through the shared probe context and must recognize measurement rows.
- Semantic matches rank before legacy matches, then by confidence and manifest `priority`; an unresolved tie is rejected as ambiguous.
- Strict matching requires confidence >= 80 by default. If confidence is too weak, the resolver rejects the report instead of guessing.

## Human approval checklist
- Reference, date, and sample number are correct.
- Key measurements match the expected results file.
- The parser won for the intended sample when you checked resolver diagnostics.
- Validation passes.
- Warnings are understandable and acceptable.
- Pilot rollout plan is prepared before broad activation.
"""

    non_technical_steps = """# Non-Technical Steps

Use this file when asking any LLM to help build the parser.

## Prepare the package
1. Put 3-5 reports from the same supplier/template into `samples/`.
2. Fill `supplier_intake.md` in plain language.
3. Fill `expected_results_template.csv` with every parsed row you can verify by looking at the reports.
4. Keep `contracts/`, `reference/contract_snippets.md`, and `handoff_manifest.json` in the package.

## Run the LLM in small tasks
1. Send `prompts/microtasks/01_template_analysis.md` with the reports, intake, expected results, and contract snippets.
2. Save the answer in `responses/01_template_analysis.md`.
3. Continue one prompt at a time, always adding earlier answers and `reference/contract_snippets.md`.
4. Only paste complete returned file contents into `generated_plugin.py` or `tests/test_generated_plugin.py`.

## Validate
Run validation from the Metroliza source checkout:

```bash
python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id {{PLUGIN_ID}} --sample-input samples/{{SAMPLE_FILE_NAME}} --expected-results expected_results_template.csv
```

If validation fails, send `prompts/microtasks/06_repair_failed_checks.md`, the validation output,
the current generated files, expected results, samples, and `reference/contract_snippets.md`.

## Do not approve until
- validation passes,
- resolver diagnostics select this parser for the intended sample,
- expected results match the report,
- the generated code contains no network, installer, shell, or database-writing code.
"""

    supplier_intake = """# Supplier Intake

Fill this before asking the LLM to design the parser.

## Supplier identity
- Supplier name:
- Internal owner:
- Country or region:
- Main language on report:

## Report format
- Source format (`pdf`, `excel`, `csv`):
- Known template name or label:
- Any version string shown on the report:

## Locale and formatting notes
- Decimal separator (`.` or `,`):
- Date format examples:
- Units used in the report:
- Header aliases or multilingual labels:

## Parsing expectations
- Which fields are mandatory:
- Which fields are optional:
- How tolerance is shown:
- How repeated measurement blocks are separated:

## Known risks
- OCR needed or not:
- Known bad samples:
- Known ambiguous labels:
"""

    expected_results_template = """sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance
{{SAMPLE_FILE_NAME}},REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0
"""

    samples_readme = """Place 3-5 representative sample reports in this folder.

Use real reports from the same supplier and same template family when possible.
Include at least one sample that clearly shows dates, tolerances, and multiple measurement rows.
"""

    analysis_response = """# Analysis Response

Paste the LLM analysis here after Step 4.
"""

    review_checklist = """# Review Checklist

- Does the probe strategy look specific enough to avoid false matches?
- Does the manifest document the correct `supported_formats`, `supported_locales`, `template_ids`, and `priority`?
- Does the mapping table cover reference, report date, sample number, headers, and measurements?
- Does the parser avoid new dependencies?
- Does the parser keep deterministic behavior?
- Does the parser avoid direct SQLite/database writes?
- Are the warnings and ambiguities explained clearly?
- Does the expected-results file cover every parsed row from each approval sample?
"""

    reference_snippets = "\n\n".join(
        [
            "# Contract Snippets",
            "This is the compact packet for small or disconnected LLMs. The full version is in `contracts/`.",
            contract_packet["contracts/01_parser_api_contract.md"],
            contract_packet["contracts/02_runtime_selection_contract.md"],
            contract_packet["contracts/03_sqlite_persistence_contract.md"],
            contract_packet["contracts/04_expected_results_contract.md"],
            contract_packet["contracts/05_security_and_safety_contract.md"],
            contract_packet["contracts/07_privacy_redaction_checklist.md"],
        ]
    )

    bundle = {
        "README.md": _render_template(workspace_readme, replacements),
        "NON_TECHNICAL_STEPS.md": _render_template(non_technical_steps, replacements),
        "supplier_intake.md": _render_template(supplier_intake, replacements),
        "expected_results_template.csv": _render_template(expected_results_template, replacements),
        "artifacts/README.md": "Place generated repair prompts and validation evidence in this folder.\n",
        "samples/README.md": _render_template(samples_readme, replacements),
        "responses/analysis_response.md": _render_template(analysis_response, replacements),
        "reference/contract_snippets.md": _render_template(reference_snippets, replacements),
        "prompts/01_analysis_prompt.md": _render_template(scaffold.analysis_prompt_template, replacements),
        "prompts/02_implementation_prompt.md": _render_template(scaffold.implementation_prompt_template, replacements),
        "generated_plugin.py": _render_template(scaffold.plugin_template, replacements),
        "tests/test_generated_plugin.py": _render_template(scaffold.test_template, replacements),
        "review_checklist.md": _render_template(review_checklist, replacements),
    }
    bundle.update(contract_packet)
    bundle.update(microtask_prompts)
    bundle["handoff_manifest.json"] = build_llm_handoff_manifest(
        plugin_id=replacements["PLUGIN_ID"],
        display_name=replacements["DISPLAY_NAME"],
        source_format=replacements["SOURCE_FORMAT"],
        workflow="python_plugin",
        files=tuple(bundle),
    )
    return bundle


def write_plugin_workspace(
    output_dir: str | Path,
    *,
    plugin_id: str,
    display_name: str | None = None,
    source_format: str = "pdf",
    overwrite: bool = False,
) -> PluginWorkspaceWriteResult:
    """Write a parser-plugin workspace bundle to disk."""

    target_dir = Path(output_dir)
    if target_dir.exists() and any(target_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Workspace already exists and is not empty: {target_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_plugin_workspace_bundle(
        plugin_id=plugin_id,
        display_name=display_name,
        source_format=source_format,
    )

    written_files: list[Path] = []
    for relative_path, contents in bundle.items():
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
        written_files.append(destination)

    return PluginWorkspaceWriteResult(
        output_dir=target_dir,
        written_files=tuple(written_files),
    )
