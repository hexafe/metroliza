"""Generate parser-plugin repair prompt artifacts from validation failures.

Usage:
  python scripts/build_parser_plugin_repair_prompt.py --plugin-id cmm
  python scripts/build_parser_plugin_repair_prompt.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf
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

    from modules.parser_plugin_repair_loop import build_repair_context, write_repair_prompt
    from modules.parser_plugin_validation import validate_plugin_contract

    return report_parser_factory, build_repair_context, write_repair_prompt, validate_plugin_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-id", required=True, help="Registered parser plugin id")
    parser.add_argument(
        "--paths",
        help="Optional parser plugin file or directory paths separated by the OS path separator",
    )
    parser.add_argument(
        "--sample-input",
        help="Optional sample report used for parse-to-V2 validation before generating the repair prompt",
    )
    parser.add_argument(
        "--output",
        default="artifacts/parser_plugin_repair_prompt.md",
        help="Output markdown artifact path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    report_parser_factory, build_repair_context, write_repair_prompt, validate_plugin_contract = _load_runtime_modules()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.paths:
        load_result = report_parser_factory.load_external_plugins(paths=args.paths)
    else:
        load_result = report_parser_factory.load_external_plugins()

    if load_result.errors:
        for error in load_result.errors:
            print(f"[LOAD ERROR] {error}")
        return 2

    parser_cls = report_parser_factory.PARSER_MAP.get(args.plugin_id)
    if parser_cls is None:
        print(f"Unknown plugin id: {args.plugin_id}")
        return 2

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

    report = validate_plugin_contract(
        parser_cls,
        sample_input_ref=sample_input_ref,
        parse_invoker=parse_invoker,
    )
    if report.passed:
        print(f"Plugin '{args.plugin_id}' passed validation; no repair artifact created.")
        return 0

    context = build_repair_context(
        report,
        guidance=(
            "Preserve existing manifest version unless schema mapping changed.",
            "Add or adjust tests for every newly handled edge case.",
            "Keep the parser compatible with Metroliza auto-discovery and factory selection.",
        ),
    )
    artifact = write_repair_prompt(args.output, context)
    print(f"Repair prompt written to: {artifact}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
