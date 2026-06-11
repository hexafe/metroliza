"""Self-service CLI for declarative parser profiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from metroliza.parsing.parser_plugin_contracts import ProbeContext, infer_source_format  # noqa: E402
from metroliza.parsing.declarative_parser_profiles import (  # noqa: E402
    PROFILE_FILE_NAME,
    disable_profile,
    enable_profile,
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
    rollback_profile,
    sha256_file,
    validate_profile_file,
)
from metroliza.parsing.parser_profile_handoff import (  # noqa: E402
    HandoffWorkspace,
    create_profile_handoff_workspace,
    format_handoff_integrity_report,
    render_profile_repair_prompt,
    validate_handoff_workspace,
)


def _path(value: str | None) -> Path | None:
    return None if value is None else Path(value).expanduser()


def _sample_paths(args: argparse.Namespace) -> tuple[Path, ...]:
    samples = tuple(Path(path) for path in getattr(args, "sample", ()) or ())
    expected_results = getattr(args, "expected_results", None)
    if samples or not expected_results:
        return samples

    workspace = Path(getattr(args, "workspace", None) or Path(args.profile).parent)
    return expected_sample_paths(workspace, expected_results)


def _format_validation_report(report) -> str:
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
    return "\n".join(lines)


def _print_validation_report(report) -> None:
    print(_format_validation_report(report))


def _add_validation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("profile", help="Declarative parser profile YAML")
    parser.add_argument(
        "--sample",
        action="append",
        default=(),
        help="Sample report path; may be passed more than once",
    )
    parser.add_argument("--expected-results", help="Expected-results CSV for semantic validation")
    parser.add_argument(
        "--workspace",
        help="Workspace root used to derive samples/ from --expected-results when --sample is omitted",
    )


def _cmd_init(args: argparse.Namespace) -> int:
    output = Path(args.output)
    if output.exists() and not args.force:
        print(f"Refusing to overwrite existing profile: {output}")
        return 2

    display_name = args.display_name or args.plugin_id.replace("_", " ").title()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_profile_template(
            plugin_id=args.plugin_id,
            display_name=display_name,
            source_format=args.source_format,
        ),
        encoding="utf-8",
    )
    print(f"Wrote profile template: {output}")
    return 0


def _cmd_handoff(args: argparse.Namespace) -> int:
    workspace = create_profile_handoff_workspace(
        plugin_id=args.plugin_id,
        display_name=args.display_name or args.plugin_id.replace("_", " ").title(),
        source_format=args.source_format,
        home=_path(args.home),
        output_dir=_path(args.output_dir),
    )
    print(f"Handoff folder: {workspace.root}")
    print(f"Profile: {workspace.profile_path}")
    print(f"Expected results: {workspace.expected_results_path}")
    print(f"Next: open {workspace.root / 'NON_TECHNICAL_STEPS.md'}")
    print(f"Check: PYTHONPATH=src:. python scripts/parser_plugin_self_service.py integrity {workspace.root}")
    return 0


def _cmd_integrity(args: argparse.Namespace) -> int:
    report = validate_handoff_workspace(args.workspace)
    print(format_handoff_integrity_report(report))
    return 0 if report.passed else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    samples = _sample_paths(args)
    report = validate_profile_file(
        args.profile,
        sample_paths=samples,
        expected_results_ref=args.expected_results,
    )
    _print_validation_report(report)
    return 0 if report.passed else 1


def _cmd_diagnose(args: argparse.Namespace) -> int:
    profile_path = Path(args.profile)
    report_path = Path(args.report)
    if not profile_path.exists():
        print(f"Profile not found: {profile_path}")
        return 2
    if not report_path.exists():
        print(f"Report not found: {report_path}")
        return 2

    payload = load_profile_payload(profile_path)
    source_format = infer_source_format(report_path)
    probe = profile_probe(
        payload,
        report_path,
        ProbeContext(source_path=str(report_path), source_format=source_format),
    )
    print(f"Profile: {probe.plugin_id}")
    print(f"Display name: {profile_display_name(payload)}")
    print(f"Version: {profile_version(payload)}")
    print(f"Source format: {profile_source_format(payload)}")
    print(f"Can parse: {probe.can_parse}")
    print(f"Confidence: {probe.confidence}")
    print(f"Template: {probe.matched_template_id or '-'}")
    print(f"Reasons: {', '.join(probe.reasons) if probe.reasons else '-'}")
    print(f"Warnings: {', '.join(probe.warnings) if probe.warnings else '-'}")
    if not probe.can_parse:
        return 1

    parse_result = parse_profile_result(payload, report_path)
    row_count = sum(len(block.dimensions) for block in parse_result.blocks)
    print(f"Reference: {parse_result.report.reference or '-'}")
    print(f"Report date: {parse_result.report.report_date or '-'}")
    print(f"Sample number: {parse_result.report.sample_number or '-'}")
    print(f"Blocks: {len(parse_result.blocks)}")
    print(f"Rows: {row_count}")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    samples = _sample_paths(args)
    try:
        result = install_profile(
            args.profile,
            sample_paths=samples,
            expected_results_ref=args.expected_results,
            approved_by=args.approved_by,
            home=_path(args.home),
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(str(exc))
        if args.expected_results and samples:
            report = validate_profile_file(
                args.profile,
                sample_paths=samples,
                expected_results_ref=args.expected_results,
            )
            _print_validation_report(report)
        return 1

    verb = "Would install" if args.dry_run else "Installed"
    print(f"{verb}: {result.plugin_id}")
    print(f"Profile: {result.profile_path}")
    print(f"Approval: {result.approval_path}")
    print(f"SHA256: {result.sha256}")
    if result.backup_dir is not None:
        print(f"Backup: {result.backup_dir}")
    return 0


def _cmd_repair(args: argparse.Namespace) -> int:
    samples = _sample_paths(args)
    report = validate_profile_file(
        args.profile,
        sample_paths=samples,
        expected_results_ref=args.expected_results,
    )
    print(_format_validation_report(report))
    if report.passed:
        print("Validation passed; no repair prompt was written.")
        return 0

    workspace_root = Path(args.workspace) if args.workspace else Path(args.profile).parent
    expected_results = (
        Path(args.expected_results) if args.expected_results else workspace_root / "expected_results.csv"
    )
    workspace = HandoffWorkspace(
        root=workspace_root,
        profile_path=Path(args.profile),
        handoff_path=workspace_root / "llm_handoff.md",
        expected_results_path=expected_results,
    )
    prompt = render_profile_repair_prompt(workspace, _format_validation_report(report))
    output = Path(args.output) if args.output else workspace_root / "artifacts" / "profile_repair_prompt.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(prompt, encoding="utf-8")
    print(f"Repair prompt: {output}")
    return 1


def _cmd_list(args: argparse.Namespace) -> int:
    ensure_profile_store_dirs(home=_path(args.home))
    profiles = list_profiles(home=_path(args.home))
    if not profiles:
        print(f"No declarative parser profiles installed under {profile_store_root(home=_path(args.home))}.")
        return 0

    for profile in profiles:
        state = "enabled" if profile.enabled else "disabled"
        approved = "approved" if profile.approved else "unapproved"
        print(f"{profile.plugin_id}\t{state}\t{approved}\t{profile.profile_path}\t{profile.detail}")
    return 0


def _run_store_action(action, plugin_id: str, *, home: str | None, label: str, **kwargs) -> int:
    try:
        target = action(plugin_id, home=_path(home), **kwargs)
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        print(str(exc))
        return 1
    print(f"{label}: {plugin_id} -> {target}")
    return 0


def _cmd_disable(args: argparse.Namespace) -> int:
    return _run_store_action(disable_profile, args.plugin_id, home=args.home, label="Disabled")


def _cmd_enable(args: argparse.Namespace) -> int:
    return _run_store_action(enable_profile, args.plugin_id, home=args.home, label="Enabled")


def _cmd_rollback(args: argparse.Namespace) -> int:
    return _run_store_action(
        rollback_profile,
        args.plugin_id,
        home=args.home,
        label="Rolled back",
        backup_name=args.backup_name,
    )


def _approval_evidence(profile) -> dict[str, object]:
    approval_payload: dict[str, object] = {}
    if profile.approval_path and profile.approval_path.exists():
        approval_payload = json.loads(profile.approval_path.read_text(encoding="utf-8"))
    return {
        "plugin_id": profile.plugin_id,
        "enabled": profile.enabled,
        "approved": profile.approved,
        "detail": profile.detail,
        "profile_path": str(profile.profile_path),
        "approval_path": str(profile.approval_path) if profile.approval_path else None,
        "profile_sha256": sha256_file(profile.profile_path) if profile.profile_path.exists() else None,
        "approval": approval_payload,
    }


def _cmd_evidence(args: argparse.Namespace) -> int:
    profiles = list_profiles(home=_path(args.home))
    if args.plugin_id:
        profiles = tuple(profile for profile in profiles if profile.plugin_id == args.plugin_id)
    if not profiles:
        print(f"No profile evidence found for {args.plugin_id or 'installed profiles'}.")
        return 1

    evidence = [_approval_evidence(profile) for profile in profiles]
    print(json.dumps(evidence[0] if args.plugin_id else evidence, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        help="Override home directory for the declarative profile store; defaults to the current user home",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a starter declarative profile YAML")
    init_parser.add_argument("--plugin-id", required=True)
    init_parser.add_argument("--display-name")
    init_parser.add_argument("--source-format", default="pdf", choices=("pdf", "excel", "csv"))
    init_parser.add_argument("--output", default=PROFILE_FILE_NAME)
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=_cmd_init)

    handoff_parser = subparsers.add_parser("handoff", help="Create a complete LLM handoff folder")
    handoff_parser.add_argument("--plugin-id", required=True)
    handoff_parser.add_argument("--display-name")
    handoff_parser.add_argument("--source-format", default="pdf", choices=("pdf", "excel", "csv"))
    handoff_parser.add_argument(
        "--output-dir",
        help="Optional handoff output directory; defaults to the incoming profile store",
    )
    handoff_parser.set_defaults(func=_cmd_handoff)

    integrity_parser = subparsers.add_parser("integrity", help="Check that a handoff folder is self-contained")
    integrity_parser.add_argument("workspace", help="Handoff workspace root")
    integrity_parser.set_defaults(func=_cmd_integrity)

    check_handoff_parser = subparsers.add_parser(
        "check-handoff",
        help="Alias for integrity",
    )
    check_handoff_parser.add_argument("workspace", help="Handoff workspace root")
    check_handoff_parser.set_defaults(func=_cmd_integrity)

    validate_parser = subparsers.add_parser("validate", help="Validate a declarative profile")
    _add_validation_args(validate_parser)
    validate_parser.set_defaults(func=_cmd_validate)

    diagnose_parser = subparsers.add_parser("diagnose", help="Probe and parse a sample report with one profile")
    diagnose_parser.add_argument("profile", help="Declarative parser profile YAML")
    diagnose_parser.add_argument("report", help="Sample report to diagnose")
    diagnose_parser.set_defaults(func=_cmd_diagnose)

    install_parser = subparsers.add_parser("install", help="Validate and approve a profile into the user store")
    _add_validation_args(install_parser)
    install_parser.add_argument("--approved-by", default="operator")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.set_defaults(func=_cmd_install)

    repair_parser = subparsers.add_parser("repair", help="Write a profile-only repair prompt after validation fails")
    _add_validation_args(repair_parser)
    repair_parser.add_argument("--output", help="Repair prompt output path")
    repair_parser.set_defaults(func=_cmd_repair)

    list_parser = subparsers.add_parser("list", help="List installed declarative profiles")
    list_parser.set_defaults(func=_cmd_list)

    disable_parser = subparsers.add_parser("disable", help="Disable an approved profile")
    disable_parser.add_argument("plugin_id")
    disable_parser.set_defaults(func=_cmd_disable)

    enable_parser = subparsers.add_parser("enable", help="Enable a disabled profile")
    enable_parser.add_argument("plugin_id")
    enable_parser.set_defaults(func=_cmd_enable)

    rollback_parser = subparsers.add_parser("rollback", help="Restore the latest or named profile backup")
    rollback_parser.add_argument("plugin_id")
    rollback_parser.add_argument("--backup-name")
    rollback_parser.set_defaults(func=_cmd_rollback)

    evidence_parser = subparsers.add_parser("evidence", help="Print installed approval evidence as JSON")
    evidence_parser.add_argument("plugin_id", nargs="?")
    evidence_parser.set_defaults(func=_cmd_evidence)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
