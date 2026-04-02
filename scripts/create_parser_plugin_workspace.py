"""Create a ready-to-fill workspace for LLM-assisted parser plugin generation.

Usage:
  python scripts/create_parser_plugin_workspace.py --plugin-id supplier_alpha
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-id", required=True, help="Stable parser plugin id, for example supplier_alpha")
    parser.add_argument("--display-name", help="Optional display name shown in plugin metadata")
    parser.add_argument(
        "--source-format",
        default="pdf",
        choices=("pdf", "excel", "csv"),
        help="Primary source format for this supplier template",
    )
    parser.add_argument(
        "--output-dir",
        help="Workspace output directory (default: artifacts/parser_plugin_workspaces/<plugin-id>)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow writing into a non-empty existing output directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from modules.llm_plugin_factory import write_plugin_workspace
    from modules.parser_plugin_paths import default_external_plugin_dir_display

    parser = build_parser()
    args = parser.parse_args(argv)

    output_dir = args.output_dir or f"artifacts/parser_plugin_workspaces/{args.plugin_id}"
    result = write_plugin_workspace(
        output_dir,
        plugin_id=args.plugin_id,
        display_name=args.display_name,
        source_format=args.source_format,
        overwrite=args.overwrite,
    )

    print(f"Workspace created: {result.output_dir}")
    print(f"Files written: {len(result.written_files)}")
    print("Next steps:")
    print("  1. Put 3-5 sample reports into samples/.")
    print("  2. Fill supplier_intake.md and expected_results_template.csv.")
    print("  3. Run the prompts in prompts/ with your LLM and paste the results back into the workspace.")
    print("  4. Validate the generated parser before installation.")
    print(f"  5. Install the validated plugin into {default_external_plugin_dir_display()}/<plugin-id>.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
