"""Generate parser-plugin repair prompt artifacts from validation failures.

Usage:
  python scripts/build_parser_plugin_repair_prompt.py --plugin-id cmm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    from modules import report_parser_factory
    from modules.parser_plugin_repair_loop import build_repair_context, write_repair_prompt
    from modules.parser_plugin_validation import validate_plugin_contract

    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-id", required=True, help="Registered parser plugin id")
    parser.add_argument(
        "--output",
        default="artifacts/parser_plugin_repair_prompt.md",
        help="Output markdown artifact path",
    )
    args = parser.parse_args()

    parser_cls = report_parser_factory.PARSER_MAP.get(args.plugin_id)
    if parser_cls is None:
        print(f"Unknown plugin id: {args.plugin_id}")
        return 2

    report = validate_plugin_contract(parser_cls)
    if report.passed:
        print(f"Plugin '{args.plugin_id}' passed validation; no repair artifact created.")
        return 0

    context = build_repair_context(
        report,
        guidance=(
            "Preserve existing manifest version unless schema mapping changed.",
            "Add/adjust fixtures for newly handled edge cases.",
        ),
    )
    artifact = write_repair_prompt(args.output, context)
    print(f"Repair prompt written to: {artifact}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
