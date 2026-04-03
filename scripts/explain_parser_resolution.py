"""Explain parser-plugin resolution for a sample report.

Usage:
  python scripts/explain_parser_resolution.py samples/sample_report_01.pdf
  python scripts/explain_parser_resolution.py samples/sample_report_01.pdf --paths generated_plugin.py
"""

from __future__ import annotations

import argparse
import importlib.machinery
import os
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

    from modules.parser_plugin_paths import PARSER_EXTERNAL_PLUGIN_PATHS_ENV

    return report_parser_factory, PARSER_EXTERNAL_PLUGIN_PATHS_ENV


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_path", help="Report file to diagnose")
    parser.add_argument(
        "--paths",
        help="Optional parser plugin file or directory paths separated by the OS path separator",
    )
    return parser


def _format_values(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "-"


def _format_candidate(report_parser_factory, candidate) -> str:
    manifest = report_parser_factory.PARSER_MANIFESTS.get(candidate.plugin_id)
    priority = manifest.priority if manifest is not None else "?"
    supported_formats = _format_values(manifest.supported_formats) if manifest is not None else "-"
    template_id = candidate.matched_template_id or "-"
    reasons = _format_values(candidate.reasons)
    warnings = _format_values(candidate.warnings)
    return (
        f"- {candidate.plugin_id} | can_parse={candidate.can_parse} | confidence={candidate.confidence} | "
        f"priority={priority} | formats={supported_formats} | template={template_id} | "
        f"reasons={reasons} | warnings={warnings}"
    )


def _selection_threshold() -> int:
    return 80 if os.getenv("PARSER_STRICT_MATCHING", "false").strip().lower() in {"1", "true", "yes", "on"} else 1


def main(argv: list[str] | None = None) -> int:
    report_parser_factory, env_var_name = _load_runtime_modules()
    parser = build_parser()
    args = parser.parse_args(argv)

    report_path = Path(args.report_path)
    original_env = os.environ.get(env_var_name)
    try:
        if args.paths:
            combined_paths = args.paths if not original_env else os.pathsep.join((args.paths, original_env))
            os.environ[env_var_name] = combined_paths

        diagnostics = report_parser_factory.resolve_parser_with_diagnostics(report_path)
    finally:
        if original_env is None:
            os.environ.pop(env_var_name, None)
        else:
            os.environ[env_var_name] = original_env

    print(f"Source path: {diagnostics.source_path}")
    print(f"Source format: {diagnostics.source_format}")
    print(f"Selection threshold: {_selection_threshold()}")
    print(f"Candidates considered: {len(diagnostics.candidates_considered)}")

    if not report_path.exists():
        print(f"Warning: report file does not exist: {report_path}")

    for candidate in diagnostics.candidates_considered:
        print(_format_candidate(report_parser_factory, candidate))

    if diagnostics.selected is None:
        print(f"Selected: none")
        print(f"Rejected reason: {diagnostics.rejected_reason or 'unknown'}")
        return 1

    selected_manifest = report_parser_factory.PARSER_MANIFESTS.get(diagnostics.selected.plugin_id)
    selected_priority = selected_manifest.priority if selected_manifest is not None else "?"
    print(
        f"Selected: {diagnostics.selected.plugin_id} | confidence={diagnostics.selected.confidence} | "
        f"priority={selected_priority}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
