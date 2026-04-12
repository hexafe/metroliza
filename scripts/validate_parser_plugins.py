"""Run parser plugin validation gate checks.

Usage:
  python scripts/validate_parser_plugins.py
  python scripts/validate_parser_plugins.py --plugin-id cmm
  python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf
  python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf --expected-results expected_results_template.csv
"""

from __future__ import annotations

import argparse
import importlib.machinery
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_runtime_modules():
    """Load runtime modules with headless fallback for optional GUI deps."""

    try:  # pragma: no cover - runtime environment dependent
        from modules import report_parser_factory
    except Exception:
        custom_logger_stub = types.ModuleType("modules.custom_logger")
        fitz_stub = types.ModuleType("fitz")

        class _DummyCustomLogger:
            def __init__(self, *_args, **_kwargs):
                pass

        custom_logger_stub.CustomLogger = _DummyCustomLogger
        fitz_stub.__spec__ = importlib.machinery.ModuleSpec("fitz", loader=None)
        fitz_stub.open = lambda *_args, **_kwargs: None
        sys.modules.setdefault("modules.custom_logger", custom_logger_stub)
        sys.modules.setdefault("fitz", fitz_stub)
        from modules import report_parser_factory

    from modules.parser_plugin_validation import validate_plugin_contract

    return report_parser_factory, validate_plugin_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--paths",
        help="Optional parser plugin file or directory paths separated by the OS path separator",
    )
    parser.add_argument("--plugin-id", help="Validate only one registered plugin id")
    parser.add_argument(
        "--sample-input",
        help="Optional sample report used for parse-to-V2 validation; requires --plugin-id",
    )
    parser.add_argument(
        "--expected-results",
        help="Optional CSV with expected rows for semantic comparison; requires --sample-input",
    )
    return parser


def _select_plugins(report_parser_factory, plugin_id: str | None):
    selected = sorted(report_parser_factory.PARSER_MAP.items())
    if plugin_id:
        parser_cls = report_parser_factory.PARSER_MAP.get(plugin_id)
        if parser_cls is None:
            return ()
        return ((plugin_id, parser_cls),)
    return selected


def main(argv: list[str] | None = None) -> int:
    report_parser_factory, validate_plugin_contract = _load_runtime_modules()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.sample_input and not args.plugin_id:
        parser.error("--sample-input requires --plugin-id so validation stays tied to one parser candidate")
    if args.expected_results and not args.sample_input:
        parser.error("--expected-results requires --sample-input so semantic comparison can target one report")

    if args.paths:
        load_result = report_parser_factory.load_external_plugins(paths=args.paths)
    else:
        load_result = report_parser_factory.load_external_plugins()

    if load_result.errors:
        for error in load_result.errors:
            print(f"[LOAD ERROR] {error}")
        return 2

    if load_result.loaded_plugin_ids:
        loaded_ids = ", ".join(load_result.loaded_plugin_ids)
        print(f"Loaded external plugins: {loaded_ids}")

    if args.sample_input:
        sample_input_path = Path(args.sample_input)
        if not sample_input_path.exists():
            print(f"Sample input not found: {sample_input_path}")
            return 2
        sample_input_ref = sample_input_path

        def parse_invoker(parser_instance):
            return parser_instance.parse_to_v2()

    else:
        sample_input_ref = "sample.pdf"
        parse_invoker = None

    selected_plugins = _select_plugins(report_parser_factory, args.plugin_id)
    if not selected_plugins:
        if args.plugin_id:
            print(f"Unknown plugin id: {args.plugin_id}")
            return 2
        print("No parser plugins are registered.")
        return 2

    failures = 0
    for plugin_id, parser_cls in selected_plugins:
        report = validate_plugin_contract(
            parser_cls,
            sample_input_ref=sample_input_ref,
            parse_invoker=parse_invoker,
            expected_results_ref=args.expected_results,
        )
        status = "PASS" if report.passed else "FAIL"
        print(f"[{status}] {plugin_id}")
        for check in report.checks:
            marker = "ok" if check.passed else "x"
            suffix = f" ({check.detail})" if check.detail else ""
            print(f"  - {marker} {check.name}{suffix}")
        if not report.passed:
            failures += 1

    if failures:
        print(f"Validation failed for {failures} plugin(s).")
        return 1

    print("Validation passed for all selected parser plugins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
