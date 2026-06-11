"""Declarative parser-profile LLM handoff workspace helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from metroliza.parsing.declarative_parser_profiles import (
    ensure_profile_store_dirs,
    expected_sample_paths,
    install_profile,
    list_profiles,
    load_profile_payload,
    parse_profile_result,
    profile_display_name,
    profile_probe,
    profile_source_format,
    profile_store_root,
    profile_version,
    render_profile_template,
    validate_profile_file,
)
from metroliza.parsing.llm_plugin_factory import (
    build_llm_contract_packet,
    build_llm_handoff_manifest,
    build_llm_microtask_prompts,
)
from metroliza.parsing.parser_plugin_contracts import ProbeContext, infer_source_format


@dataclass(frozen=True)
class ProfileStoreSummary:
    root: Path
    total: int
    enabled: int
    approved: int
    disabled: int


@dataclass(frozen=True)
class HandoffWorkspace:
    root: Path
    profile_path: Path
    handoff_path: Path
    expected_results_path: Path


@dataclass(frozen=True)
class HandoffIntegrityCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class HandoffIntegrityReport:
    root: Path
    package_type: str
    plugin_id: str
    passed: bool
    checks: tuple[HandoffIntegrityCheck, ...]


def safe_profile_id(value: str) -> str:
    """Return the filesystem/profile id used for a new handoff workspace."""

    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().casefold()).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"supplier_{normalized or 'profile'}"
    if len(normalized) < 3:
        normalized = f"{normalized}_profile"
    return normalized[:64]


def summarize_profile_store(*, home: Path | None = None) -> ProfileStoreSummary:
    ensure_profile_store_dirs(home=home)
    profiles = list_profiles(home=home)
    enabled = sum(1 for profile in profiles if profile.enabled)
    approved = sum(1 for profile in profiles if profile.approved)
    disabled = sum(1 for profile in profiles if not profile.enabled)
    return ProfileStoreSummary(
        root=profile_store_root(home=home),
        total=len(profiles),
        enabled=enabled,
        approved=approved,
        disabled=disabled,
    )


def _default_handoff_root(*, safe_id: str, home: Path | None, output_dir: Path | None) -> Path:
    if output_dir is not None:
        return output_dir
    return profile_store_root(home=home) / "incoming" / safe_id


def create_profile_handoff_workspace(
    *,
    plugin_id: str,
    display_name: str,
    source_format: str,
    home: Path | None = None,
    output_dir: Path | None = None,
    overwrite_instructions: bool = True,
) -> HandoffWorkspace:
    """Create a data-only profile handoff folder for an external LLM workflow."""

    safe_id = safe_profile_id(plugin_id)
    readable_name = display_name.strip() or safe_id.replace("_", " ").title()
    root = _default_handoff_root(safe_id=safe_id, home=home, output_dir=output_dir)
    samples_dir = root / "samples"
    root.mkdir(parents=True, exist_ok=True)
    samples_dir.mkdir(exist_ok=True)

    profile_path = root / "profile.yaml"
    expected_results_path = root / "expected_results.csv"
    handoff_path = root / "llm_handoff.md"

    if not profile_path.exists():
        profile_path.write_text(
            render_profile_template(
                plugin_id=safe_id,
                display_name=readable_name,
                source_format=source_format,
            ),
            encoding="utf-8",
        )
    if not expected_results_path.exists():
        expected_results_path.write_text(
            "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
            "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n",
            encoding="utf-8",
        )

    contract_packet = build_llm_contract_packet(
        plugin_id=safe_id,
        display_name=readable_name,
        source_format=source_format,
        workflow="declarative_profile",
    )
    microtask_prompts = build_llm_microtask_prompts(
        plugin_id=safe_id,
        display_name=readable_name,
        source_format=source_format,
        workflow="declarative_profile",
    )
    support_files: dict[str, str] = {}
    support_files.update(contract_packet)
    support_files.update(microtask_prompts)

    reference_snippets = "\n\n".join(
        [
            "# Contract Snippets",
            "This compact file is for small or disconnected LLMs. The full version is in `contracts/`.",
            contract_packet["contracts/01_parser_api_contract.md"],
            contract_packet["contracts/02_runtime_selection_contract.md"],
            contract_packet["contracts/03_sqlite_persistence_contract.md"],
            contract_packet["contracts/04_expected_results_contract.md"],
            contract_packet["contracts/05_security_and_safety_contract.md"],
            contract_packet["contracts/07_privacy_redaction_checklist.md"],
        ]
    )
    non_technical_steps = "\n".join(
        [
            "# Non-Technical Steps",
            "",
            "Use this folder to ask an LLM to complete a Metroliza parser profile.",
            "",
            "## Prepare",
            "1. Put reports from this supplier/template into samples/.",
            "2. Fill expected_results.csv with every parsed row for each approval sample.",
            "3. Add supplier notes: visible labels, language, date format, decimal separator, and units.",
            "4. Keep contracts/, reference/contract_snippets.md, and handoff_manifest.json with the package.",
            "",
            "## Ask The LLM One Small Task At A Time",
            "1. Start with prompts/01_identify_template_markers.md.",
            "2. Send only the requested prompt, sample reports, expected_results.csv, profile.yaml, and reference/contract_snippets.md.",
            "3. Save the answer in responses/ before sending the next prompt.",
            "4. Continue through the prompts until the model returns a complete profile.yaml.",
            "",
            "## Hard Boundaries",
            "- Ask for declarative Metroliza parser profile YAML only.",
            "- Do not ask for Python code.",
            "- Do not allow network calls, package changes, shell commands, installers, or database writes.",
            "- If validation fails, send the validation output and prompts/06_fix_validation_failures.md.",
            "",
            "## Validate From The Metroliza Source Checkout",
            "",
            "```bash",
            (
                f'PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate "{profile_path}" '
                f'--expected-results "{expected_results_path}" --workspace "{root}"'
            ),
            (
                f'PYTHONPATH=src:. python scripts/parser_plugin_self_service.py diagnose "{profile_path}" '
                f'"{samples_dir}/<sample-file>"'
            ),
            "```",
            "",
            "Do not install until validation passes and diagnose selects this profile for the intended sample.",
            "",
        ]
    )
    support_files["NON_TECHNICAL_STEPS.md"] = non_technical_steps
    support_files["reference/contract_snippets.md"] = reference_snippets
    support_files["responses/README.md"] = "Save LLM answers here so each later microtask can refer to them.\n"
    support_files["artifacts/README.md"] = "Save validation output, repair prompts, and review evidence here.\n"

    manifest_files = tuple(
        sorted(
            [
                "profile.yaml",
                "expected_results.csv",
                "llm_handoff.md",
                "samples/",
                *support_files,
            ]
        )
    )
    support_files["handoff_manifest.json"] = build_llm_handoff_manifest(
        plugin_id=safe_id,
        display_name=readable_name,
        source_format=source_format,
        workflow="declarative_profile",
        files=manifest_files,
    )
    if overwrite_instructions:
        for relative_path, contents in support_files.items():
            destination = root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")

    expected_columns = (
        "sample_file, reference, report_date, sample_number, block_index, header_normalized, "
        "axis_code, nominal, tol_plus, tol_minus, bonus, measured, deviation, out_of_tolerance"
    )
    handoff_path.write_text(
        "\n".join(
            [
                f"# Parser Profile Handoff: {readable_name}",
                "",
                "Use an approved external LLM workflow or manual review to complete profile.yaml.",
                "Do not paste private reports into an external tool unless your release owner approves it.",
                "",
                "Give the reviewer or assistant:",
                "",
                "- profile.yaml",
                "- contracts/ and reference/contract_snippets.md",
                "- NON_TECHNICAL_STEPS.md",
                "- one prompt file from prompts/ at a time",
                "- reports from samples/",
                "- expected_results.csv with every parsed row from approval samples",
                "- supplier/template notes, including visible labels, date format, and decimal separator",
                "",
                "Ask for a declarative Metroliza parser profile only.",
                "Do not ask for Python code, package changes, network calls, database writes, or installer changes.",
                "",
                "Required profile contract:",
                "",
                "- schema_version: 1",
                "- plugin.plugin_id must stay as " + safe_id,
                "- plugin.source_format must stay as " + source_format,
                "- probe.required_markers must contain supplier/template text visible in every sample",
                "- extraction.report_fields must extract reference, report_date, and sample_number",
                "- extraction.blocks[].pattern must be line-anchored with ^",
                "- measurement row capture names: axis_code, nominal, tol_plus, tol_minus, bonus, measured, deviation, out_of_tolerance",
                "- regexes must avoid Python code, backreferences, nested repeats, and unbounded dot wildcards",
                "",
                "expected_results.csv columns:",
                "",
                expected_columns,
                "",
                "Validation and install commands from the Metroliza source checkout:",
                "",
                (
                    f'PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate "{profile_path}" '
                    f'--expected-results "{expected_results_path}" --workspace "{root}"'
                ),
                (
                    f'PYTHONPATH=src:. python scripts/parser_plugin_self_service.py diagnose "{profile_path}" '
                    f'"{samples_dir}/<sample-file>"'
                ),
                (
                    f'PYTHONPATH=src:. python scripts/parser_plugin_self_service.py install "{profile_path}" '
                    f'--expected-results "{expected_results_path}" --workspace "{root}" --approved-by <approver>'
                ),
                "PYTHONPATH=src:. python scripts/parser_plugin_self_service.py evidence " + safe_id,
                "",
                "Acceptance criteria:",
                "",
                "- validation passes with at least one sample report and expected_results.csv",
                "- diagnose selects this profile and shows the expected reference/date/sample values",
                "- expected_results.csv covers every parsed row for each approval sample",
                "- the profile stays data-only YAML",
                "- approval evidence records validation_passed=true, sample_count greater than zero, and matching checksums",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return HandoffWorkspace(
        root=root,
        profile_path=profile_path,
        handoff_path=handoff_path,
        expected_results_path=expected_results_path,
    )


def _check(name: str, passed: bool, detail: str = "") -> HandoffIntegrityCheck:
    return HandoffIntegrityCheck(name=name, passed=bool(passed), detail=detail)


_PYTHON_FULL_PROMPT_ORDER = (
    "prompts/01_analysis_prompt.md",
    "prompts/02_implementation_prompt.md",
)


def _manifest_path_list(manifest: dict[str, Any], key: str) -> tuple[str, ...] | None:
    value = manifest.get(key)
    if not isinstance(value, list):
        return None
    paths: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        paths.append(item.replace("\\", "/"))
    return tuple(paths)


def _workspace_prompt_files(workspace: Path) -> tuple[str, ...]:
    prompts_dir = workspace / "prompts"
    if not prompts_dir.is_dir():
        return ()
    return tuple(
        sorted(
            path.relative_to(workspace).as_posix()
            for path in prompts_dir.rglob("*.md")
            if path.is_file()
        )
    )


def _expected_full_prompt_order(
    *,
    package_type: str,
    prompt_files: tuple[str, ...],
) -> tuple[str, ...]:
    if package_type == "declarative_profile":
        return ()
    if package_type != "python_plugin":
        return ()
    prompt_file_set = set(prompt_files)
    return tuple(path for path in _PYTHON_FULL_PROMPT_ORDER if path in prompt_file_set)


def _expected_microtask_prompt_order(
    *,
    package_type: str,
    prompt_files: tuple[str, ...],
) -> tuple[str, ...]:
    if package_type == "python_plugin":
        return tuple(path for path in prompt_files if path.startswith("prompts/microtasks/"))
    if package_type == "declarative_profile":
        return tuple(
            path
            for path in prompt_files
            if path.startswith("prompts/")
            and not path.startswith("prompts/microtasks/")
            and path not in _PYTHON_FULL_PROMPT_ORDER
        )
    return ()


def _path_list_detail(expected: tuple[str, ...], actual: tuple[str, ...] | None) -> str:
    actual_value: object = "<invalid>" if actual is None else list(actual)
    return f"expected {list(expected)}, got {actual_value}"


def validate_handoff_workspace(root: str | Path) -> HandoffIntegrityReport:
    """Validate a generated LLM handoff package before sharing it."""

    workspace = Path(root)
    manifest_path = workspace / "handoff_manifest.json"
    checks: list[HandoffIntegrityCheck] = [
        _check("workspace_exists", workspace.is_dir(), str(workspace)),
        _check("manifest_exists", manifest_path.is_file(), str(manifest_path)),
    ]
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            checks.append(_check("manifest_json_readable", True))
        except json.JSONDecodeError as exc:
            checks.append(_check("manifest_json_readable", False, str(exc)))

    package_type = str(manifest.get("package_type") or "")
    plugin_id = str(manifest.get("plugin_id") or "")
    checks.extend(
        [
            _check("manifest_schema_version", manifest.get("schema_version") == 1, "expected schema_version=1"),
            _check(
                "manifest_package_type",
                package_type in {"declarative_profile", "python_plugin"},
                "expected declarative_profile or python_plugin",
            ),
            _check("manifest_plugin_id", bool(plugin_id), "plugin_id must be present"),
            _check("manifest_self_contained", manifest.get("self_contained") is True, "self_contained must be true"),
        ]
    )

    prompt_files = _manifest_path_list(manifest, "prompt_files")
    full_order = _manifest_path_list(manifest, "full_prompt_order")
    microtask_order = _manifest_path_list(manifest, "microtask_prompt_order")
    actual_prompt_files = _workspace_prompt_files(workspace)
    expected_full_order = _expected_full_prompt_order(
        package_type=package_type,
        prompt_files=actual_prompt_files,
    )
    expected_microtask_order = _expected_microtask_prompt_order(
        package_type=package_type,
        prompt_files=actual_prompt_files,
    )

    required_files = [
        "NON_TECHNICAL_STEPS.md",
        "reference/contract_snippets.md",
        *list(manifest.get("contract_files") or ()),
        *list(prompt_files or ()),
        *list(manifest.get("allowed_outputs") or ()),
    ]
    if package_type == "declarative_profile":
        required_files.extend(["expected_results.csv", "llm_handoff.md"])
    elif package_type == "python_plugin":
        required_files.extend(["expected_results_template.csv", "README.md"])

    missing_files = sorted({path for path in required_files if path and not (workspace / path).is_file()})
    checks.append(_check("manifest_referenced_files_exist", not missing_files, ", ".join(missing_files)))
    checks.append(_check("samples_directory_exists", (workspace / "samples").is_dir(), "samples/ is required"))

    installation_path = str(manifest.get("installation_path") or "")
    if package_type == "declarative_profile":
        expected_suffix = f"profiles/approved/{plugin_id}/profile.yaml"
        checks.append(
            _check(
                "manifest_declarative_installation_path",
                expected_suffix in installation_path.replace("\\", "/"),
                f"expected path ending in {expected_suffix}",
            )
        )
        checks.append(_check("manifest_allowed_outputs", manifest.get("allowed_outputs") == ["profile.yaml"]))
    elif package_type == "python_plugin":
        checks.append(
            _check(
                "manifest_python_installation_path",
                installation_path.endswith(f"/{plugin_id}.py") or installation_path.endswith(f"\\{plugin_id}.py"),
                f"expected Python plugin path for {plugin_id}",
            )
        )
        checks.append(
            _check(
                "manifest_allowed_outputs",
                manifest.get("allowed_outputs") == ["generated_plugin.py", "tests/test_generated_plugin.py"],
            )
        )

    checks.append(
        _check(
            "manifest_prompt_files_match_workspace",
            prompt_files == actual_prompt_files,
            _path_list_detail(actual_prompt_files, prompt_files),
        )
    )
    checks.append(
        _check(
            "manifest_full_prompt_order",
            full_order == expected_full_order
            and (package_type == "declarative_profile" or bool(expected_full_order)),
            _path_list_detail(expected_full_order, full_order),
        )
    )
    checks.append(
        _check(
            "manifest_microtask_prompt_order",
            microtask_order == expected_microtask_order and bool(expected_microtask_order),
            _path_list_detail(expected_microtask_order, microtask_order),
        )
    )

    snippets_path = workspace / "reference" / "contract_snippets.md"
    snippets = snippets_path.read_text(encoding="utf-8") if snippets_path.is_file() else ""
    checks.append(_check("snippets_include_parse_result_v2", "ParseResultV2" in snippets))
    checks.append(_check("snippets_include_sqlite_boundary", "Do not write SQLite" in snippets))

    passed = all(check.passed for check in checks)
    return HandoffIntegrityReport(
        root=workspace,
        package_type=package_type or "unknown",
        plugin_id=plugin_id or "unknown",
        passed=passed,
        checks=tuple(checks),
    )


def format_handoff_integrity_report(report: HandoffIntegrityReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    lines = [f"[{status}] {report.plugin_id} ({report.package_type})"]
    for check in report.checks:
        marker = "ok" if check.passed else "x"
        suffix = f" ({check.detail})" if check.detail else ""
        lines.append(f"  - {marker} {check.name}{suffix}")
    return "\n".join(lines)


def _validation_lines(report) -> list[str]:
    status = "PASS" if report.passed else "FAIL"
    lines = [f"[{status}] {report.plugin_id}"]
    for check in report.checks:
        marker = "ok" if check.passed else "x"
        suffix = f" ({check.detail})" if check.detail else ""
        lines.append(f"  - {marker} {check.name}{suffix}")
    for contract_report in report.contract_reports:
        for check in contract_report.checks:
            marker = "ok" if check.passed else "x"
            suffix = f" ({check.detail})" if check.detail else ""
            lines.append(f"  - {marker} contract:{check.name}{suffix}")
    return lines


def validate_profile_handoff(workspace: HandoffWorkspace):
    samples = expected_sample_paths(workspace.root, workspace.expected_results_path)
    return validate_profile_file(
        workspace.profile_path,
        sample_paths=samples,
        expected_results_ref=workspace.expected_results_path,
    )


def write_profile_validation_artifact(workspace: HandoffWorkspace) -> tuple[Path, bool]:
    report = validate_profile_handoff(workspace)
    output = workspace.root / "artifacts" / "profile_validation.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(_validation_lines(report)) + "\n", encoding="utf-8")
    return output, report.passed


def write_profile_diagnose_artifact(workspace: HandoffWorkspace) -> Path:
    samples = expected_sample_paths(workspace.root, workspace.expected_results_path)
    if not samples:
        raise ValueError("diagnose requires at least one sample in expected_results.csv")
    sample = samples[0]
    if not sample.is_file():
        raise FileNotFoundError(f"sample report not found: {sample}")
    payload = load_profile_payload(workspace.profile_path)
    source_format = infer_source_format(sample)
    probe = profile_probe(payload, sample, ProbeContext(source_path=str(sample), source_format=source_format))
    lines = [
        f"Profile: {probe.plugin_id}",
        f"Display name: {profile_display_name(payload)}",
        f"Version: {profile_version(payload)}",
        f"Source format: {profile_source_format(payload)}",
        f"Can parse: {probe.can_parse}",
        f"Confidence: {probe.confidence}",
        f"Template: {probe.matched_template_id or '-'}",
        f"Reasons: {', '.join(probe.reasons) if probe.reasons else '-'}",
        f"Warnings: {', '.join(probe.warnings) if probe.warnings else '-'}",
    ]
    if probe.can_parse:
        parse_result = parse_profile_result(payload, sample)
        row_count = sum(len(block.dimensions) for block in parse_result.blocks)
        lines.extend(
            [
                f"Reference: {parse_result.report.reference or '-'}",
                f"Report date: {parse_result.report.report_date or '-'}",
                f"Sample number: {parse_result.report.sample_number or '-'}",
                f"Blocks: {len(parse_result.blocks)}",
                f"Rows: {row_count}",
            ]
        )
    output = workspace.root / "artifacts" / "profile_diagnose.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def render_profile_repair_prompt(workspace: HandoffWorkspace, validation_output: str) -> str:
    snippets_path = workspace.root / "reference" / "contract_snippets.md"
    snippets = snippets_path.read_text(encoding="utf-8") if snippets_path.is_file() else ""
    return "\n".join(
        [
            f"# Repair request for declarative parser profile: {workspace.profile_path.name}",
            "",
            "The profile failed validation. Return complete corrected `profile.yaml` only.",
            "",
            "## Failed validation",
            validation_output.strip() or "No validation output supplied.",
            "",
            "## Repair constraints",
            "- Keep the profile data-only YAML.",
            "- Do not return Python code.",
            "- Do not add network calls, shell commands, package changes, installers, or database writes.",
            "- Keep plugin.plugin_id and plugin.source_format unless the validation output says they are invalid.",
            "- expected_results.csv must cover every parsed row for each approval sample.",
            "",
            "## Contract snippets",
            snippets.strip(),
            "",
            "## Required output",
            "Complete updated file contents for `profile.yaml` only.",
            "",
        ]
    )


def write_profile_repair_prompt(workspace: HandoffWorkspace) -> Path:
    validation_path, _passed = write_profile_validation_artifact(workspace)
    prompt = render_profile_repair_prompt(
        workspace,
        validation_path.read_text(encoding="utf-8"),
    )
    output = workspace.root / "artifacts" / "profile_repair_prompt.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(prompt, encoding="utf-8")
    return output


def install_profile_handoff(workspace: HandoffWorkspace, *, approved_by: str = "operator", home: Path | None = None):
    samples = expected_sample_paths(workspace.root, workspace.expected_results_path)
    return install_profile(
        workspace.profile_path,
        sample_paths=samples,
        expected_results_ref=workspace.expected_results_path,
        approved_by=approved_by,
        home=home,
    )


def workspace_from_root(root: str | Path) -> HandoffWorkspace:
    workspace = Path(root)
    return HandoffWorkspace(
        root=workspace,
        profile_path=workspace / "profile.yaml",
        handoff_path=workspace / "llm_handoff.md",
        expected_results_path=workspace / "expected_results.csv",
    )


__all__ = [
    "HandoffIntegrityCheck",
    "HandoffIntegrityReport",
    "HandoffWorkspace",
    "ProfileStoreSummary",
    "create_profile_handoff_workspace",
    "format_handoff_integrity_report",
    "install_profile_handoff",
    "render_profile_repair_prompt",
    "safe_profile_id",
    "summarize_profile_store",
    "validate_handoff_workspace",
    "validate_profile_handoff",
    "workspace_from_root",
    "write_profile_diagnose_artifact",
    "write_profile_repair_prompt",
    "write_profile_validation_artifact",
]
