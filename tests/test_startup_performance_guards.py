import ast
import json
import os
from pathlib import Path
import subprocess
import sys


def _drop_leaked_qt_stubs() -> None:
    for module_name in ("PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets"):
        module = sys.modules.get(module_name)
        if module is not None and getattr(module, "__file__", None) is None:
            sys.modules.pop(module_name, None)


def test_main_window_does_not_top_level_import_heavy_feature_stacks():
    module_ast = ast.parse(Path("src/metroliza/ui/main_window.py").read_text(encoding="utf-8"))
    blocked = {
        "metroliza.ui.export_dialog",
        "metroliza.ui.parsing_dialog",
        "metroliza.parsing.metadata_enrichment_thread",
        "metroliza.ui.modify_db",
        "metroliza.ui.about_window",
        "metroliza.ui.release_notes_dialog",
        "metroliza.ui.characteristic_mapping_dialog",
        "metroliza.ui.industrial_data_dialog",
        "metroliza.ui.industrial_analytics_dialog",
    }

    imported_modules = set()
    for node in module_ast.body:
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert imported_modules.isdisjoint(blocked)


def test_main_window_feature_warmup_uses_canonical_import_paths():
    _drop_leaked_qt_stubs()
    from metroliza.ui.main_window import FEATURE_IMPORT_WARMUP_MODULES

    warmed_modules = [module_name for _label, module_name in FEATURE_IMPORT_WARMUP_MODULES]

    assert warmed_modules
    assert all(module_name.startswith("metroliza.") for module_name in warmed_modules)
    assert all(not module_name.startswith("modules.") for module_name in warmed_modules)


def test_parse_contract_import_does_not_load_heavy_analytics_stacks():
    script = """
import json
import sys
from metroliza.shared.parse_contracts import ParseRequest, validate_parse_request

validate_parse_request(ParseRequest(source_directory="reports", db_file="metroliza.db"))
print(json.dumps({name: name in sys.modules for name in ("pandas", "matplotlib", "scipy")}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        env={**os.environ, "PYTHONPATH": "src:."},
        text=True,
        capture_output=True,
    )

    loaded_modules = json.loads(result.stdout)
    assert loaded_modules == {"pandas": False, "matplotlib": False, "scipy": False}


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


def test_windows_startup_benchmark_fails_on_crash_or_missing_profile_evidence():
    script = Path("scripts/measure_windows_startup.ps1").read_text(encoding="utf-8")

    assert "$RequiredStartupEvents = @(" in script
    assert "'first_event_loop_tick'" in script
    assert "function Assert-StartupRunSucceeded" in script
    assert "Startup run failed with exit code" in script
    assert "Startup profile JSONL was not created" in script
    assert "Startup profile JSONL is empty" in script
    assert "missing required event" in script
    assert "Assert-StartupRunSucceeded -Run $run -ProfilePath $profilePath -Events $events" in script
