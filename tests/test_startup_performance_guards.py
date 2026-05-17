import ast
import json
import os
from pathlib import Path
import subprocess
import sys


def test_main_window_does_not_top_level_import_heavy_feature_stacks():
    module_ast = ast.parse(Path("modules/main_window.py").read_text(encoding="utf-8"))
    blocked = {
        "modules.export_dialog",
        "modules.parsing_dialog",
        "modules.metadata_enrichment_thread",
        "modules.modify_db",
        "modules.about_window",
        "modules.release_notes_dialog",
        "modules.characteristic_mapping_dialog",
        "modules.industrial_data_dialog",
        "modules.industrial_analytics_dialog",
    }

    imported_modules = set()
    for node in module_ast.body:
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert imported_modules.isdisjoint(blocked)


def test_startup_profile_writes_jsonl_events(tmp_path):
    profile_path = tmp_path / "startup-profile.jsonl"
    script = """
from modules.startup_profile import record_event
record_event("test_event", detail="ok")
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        env={
            **os.environ,
            "METROLIZA_STARTUP_PROFILE": "1",
            "METROLIZA_STARTUP_PROFILE_PATH": str(profile_path),
        },
    )

    events = [
        json.loads(line)
        for line in Path(profile_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events
    assert events[-1]["name"] == "test_event"
    assert events[-1]["detail"] == "ok"
    assert events[-1]["elapsed_ms"] >= 0
