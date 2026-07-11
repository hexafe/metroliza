from __future__ import annotations

import ast
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from metroliza.industrial import industrial_data_schema
from metroliza.reports import report_schema
from metroliza.storage import industrial_schema as storage_industrial_schema


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PACKAGE = REPO_ROOT / "src" / "metroliza"

EXPECTED_INDUSTRIAL_TO_REPORTS_EDGES = {
    ("industrial/anomaly/baseline_repository.py", "metroliza.reports.db"),
    ("industrial/anomaly/detector_config_repository.py", "metroliza.reports.db"),
    ("industrial/anomaly/event_repository.py", "metroliza.reports.db"),
    ("industrial/anomaly/model_registry.py", "metroliza.reports.db"),
    ("industrial/industrial_analytics_service.py", "metroliza.reports.db"),
    ("industrial/industrial_data_repository.py", "metroliza.reports.db"),
    ("industrial/industrial_data_schema.py", "metroliza.reports.db"),
    ("industrial/industrial_export_service.py", "metroliza.reports.db"),
    ("industrial/industrial_join_service.py", "metroliza.reports.db"),
    ("industrial/industrial_join_service.py", "metroliza.reports.report_schema"),
    ("industrial/industrial_tabular_bridge.py", "metroliza.reports.db"),
    ("industrial/realtime/event_stream_repository.py", "metroliza.reports.db"),
    ("industrial/realtime/monitor_config.py", "metroliza.reports.db"),
    ("industrial/realtime/offset_store.py", "metroliza.reports.db"),
    ("industrial/realtime/realtime_dashboard_service.py", "metroliza.reports.db"),
    ("industrial/realtime/realtime_service.py", "metroliza.reports.db"),
    ("industrial/realtime/sample_repository.py", "metroliza.reports.db"),
    ("industrial/realtime/source_health_service.py", "metroliza.reports.db"),
}


def _static_package_edges(source: str, target: str) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    target_prefix = f"metroliza.{target}"
    for path in sorted((SRC_PACKAGE / source).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module_name in modules:
                if module_name == target_prefix or module_name.startswith(f"{target_prefix}."):
                    edges.add((path.relative_to(SRC_PACKAGE).as_posix(), module_name))
    return edges


def _subprocess_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": f"{SRC_PACKAGE.parent}{os.pathsep}{REPO_ROOT}",
    }


def test_industrial_reports_dependency_is_one_way_and_explicit() -> None:
    assert _static_package_edges("reports", "industrial") == set()
    assert _static_package_edges("industrial", "reports") == EXPECTED_INDUSTRIAL_TO_REPORTS_EDGES


def test_storage_industrial_schema_cold_import_is_feature_neutral(tmp_path: Path) -> None:
    script = """
import sys
import metroliza.storage.industrial_schema

loaded = sorted(
    name for name in sys.modules
    if name == "metroliza.industrial"
    or name.startswith("metroliza.industrial.")
    or name == "metroliza.reports"
    or name.startswith("metroliza.reports.")
)
assert loaded == [], loaded
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=tmp_path,
        env=_subprocess_env(),
    )


def test_report_schema_cold_import_does_not_load_industrial(tmp_path: Path) -> None:
    script = """
import sys
import metroliza.reports.report_schema

loaded = sorted(
    name for name in sys.modules
    if name == "metroliza.industrial" or name.startswith("metroliza.industrial.")
)
assert loaded == [], loaded
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=tmp_path,
        env=_subprocess_env(),
    )


def test_report_bootstrap_preserves_paired_schema_and_industrial_facade(tmp_path: Path) -> None:
    db_path = str(tmp_path / "paired-schema.db")

    report_schema.ensure_report_schema(db_path)
    industrial_data_schema.ensure_industrial_data_schema(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        schema_versions = dict(connection.execute("SELECT key, value FROM app_schema"))
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert schema_versions["schema_version"] == report_schema.SCHEMA_VERSION
    assert schema_versions["industrial_schema_version"] == industrial_data_schema.SCHEMA_VERSION
    assert industrial_data_schema.SCHEMA_VERSION == storage_industrial_schema.SCHEMA_VERSION
    assert {"parsed_reports", "industrial_records", "industrial_link_candidates"} <= tables


def test_report_bootstrap_preserves_industrial_timestamp_migration(tmp_path: Path) -> None:
    db_path = str(tmp_path / "paired-migration.db")
    with closing(sqlite3.connect(db_path)) as connection:
        industrial_data_schema.ensure_industrial_data_schema(db_path, connection=connection)
        connection.execute(
            """
            INSERT INTO industrial_source_profiles (
                profile_key,
                profile_name,
                source_db_alias,
                database_type,
                source_object_name,
                allowed_columns_json,
                created_at,
                updated_at
            )
            VALUES ('line-a', 'Line A', 'plant', 'sqlite', 'events', '[]', ?, ?)
            """,
            ("2026-07-11 08:00:00", "2026-07-11 08:00:00"),
        )
        connection.execute(
            "DELETE FROM app_schema WHERE key = 'industrial_timestamp_storage_format'"
        )

        report_schema.ensure_report_schema(db_path, connection=connection)

        created_at = connection.execute(
            "SELECT created_at FROM industrial_source_profiles WHERE profile_key = 'line-a'"
        ).fetchone()[0]
        migration_version = connection.execute(
            "SELECT value FROM app_schema WHERE key = 'industrial_timestamp_storage_format'"
        ).fetchone()[0]
    assert created_at == "2026-07-11T08:00:00.000000Z"
    assert migration_version == industrial_data_schema.TIMESTAMP_STORAGE_FORMAT
