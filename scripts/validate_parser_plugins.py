"""Run parser plugin validation gate checks.

Usage:
  python scripts/validate_parser_plugins.py

Optional env:
  PARSER_EXTERNAL_PLUGIN_PATHS=/path/to/plugins:/other/path
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_runtime_modules():
    """Load runtime modules with headless fallback for optional GUI deps."""

    # Headless fallback: avoid hard failure when Qt/OpenGL runtime is unavailable.
    try:  # pragma: no cover - runtime environment dependent
        from modules import report_parser_factory
    except Exception:
        custom_logger_stub = types.ModuleType("modules.CustomLogger")

        class _DummyCustomLogger:
            def __init__(self, *_args, **_kwargs):
                pass

        custom_logger_stub.CustomLogger = _DummyCustomLogger
        sys.modules.setdefault("modules.CustomLogger", custom_logger_stub)
        from modules import report_parser_factory

    from modules.parser_plugin_validation import validate_plugin_contract

    return report_parser_factory, validate_plugin_contract


def main() -> int:
    report_parser_factory, validate_plugin_contract = _load_runtime_modules()
    report_parser_factory.load_external_plugins()
    failures = 0

    for plugin_id, parser_cls in sorted(report_parser_factory.PARSER_MAP.items()):
        report = validate_plugin_contract(parser_cls)
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

    print("Validation passed for all parser plugins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
