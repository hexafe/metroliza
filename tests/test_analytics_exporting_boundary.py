from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

from metroliza.analytics.grouping_labels import (
    normalize_default_group_label,
    normalize_group_labels,
)
from metroliza.analytics.row_table import RowTable, coerce_to_row_table
from metroliza.exporting import export_grouping_utils, export_query_service


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PACKAGE = REPO_ROOT / "src" / "metroliza"

EXPECTED_EXPORTING_TO_ANALYTICS_EDGES = {
    ("exporting/export_data_thread.py", "metroliza.analytics.group_analysis_service"),
    ("exporting/export_data_thread.py", "metroliza.analytics.distribution_fit_service"),
    ("exporting/export_group_comparison_writer.py", "metroliza.analytics.comparison_stats"),
    (
        "exporting/export_group_comparison_writer.py",
        "metroliza.analytics.distribution_shape_analysis",
    ),
    ("exporting/export_grouping_utils.py", "metroliza.analytics.grouping_labels"),
    ("exporting/export_query_service.py", "metroliza.analytics.row_table"),
    ("exporting/export_summary_utils.py", "metroliza.analytics.distribution_fit_service"),
    ("exporting/group_analysis_writer.py", "metroliza.analytics.group_analysis_service"),
}


def _static_package_edges(source: str, target: str) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    target_prefix = f"metroliza.{target}"
    for path in sorted((SRC_PACKAGE / source).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            for module_name in imported_modules:
                if module_name == target_prefix or module_name.startswith(f"{target_prefix}."):
                    edges.add((path.relative_to(SRC_PACKAGE).as_posix(), module_name))
    return edges


def test_analytics_exporting_dependency_is_one_way_and_explicit() -> None:
    assert _static_package_edges("analytics", "exporting") == set()
    assert (
        _static_package_edges("exporting", "analytics")
        == EXPECTED_EXPORTING_TO_ANALYTICS_EDGES
    )


def test_export_helpers_preserve_row_table_and_group_label_compatibility() -> None:
    assert export_query_service.RowTable is RowTable
    assert export_query_service._coerce_to_row_table is coerce_to_row_table
    assert export_grouping_utils.normalize_default_group_label is normalize_default_group_label
    assert export_grouping_utils.normalize_group_labels is normalize_group_labels

    table = export_query_service.build_export_dataframe(
        [("A", 1.0), ("B", 2.0)],
        ["GROUP", "MEAS"],
    )
    assert isinstance(table, RowTable)
    assert table["GROUP"].tolist() == ["A", "B"]
    assert normalize_default_group_label("  ") == "POPULATION"
    assert normalize_group_labels(
        ["A", None, "  "],
        missing_label="POPULATION",
        normalize_blank=True,
    ) == ["A", "POPULATION", "POPULATION"]


def test_cold_analytics_import_does_not_load_exporting_or_pandas(tmp_path: Path) -> None:
    script = "\n".join(
        [
            "import sys",
            "import metroliza.analytics.row_table",
            "import metroliza.analytics.group_analysis_service",
            "assert 'pandas' not in sys.modules",
            "assert not any(name.startswith('metroliza.exporting') for name in sys.modules)",
        ]
    )
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": f"{REPO_ROOT / 'src'}{os.pathsep}{REPO_ROOT}",
        },
    )
