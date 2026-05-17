import json
import os
from pathlib import Path
import subprocess
import sys


def test_main_window_import_does_not_eagerly_import_heavy_feature_stacks():
    script = """
import json
import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import modules.main_window
blocked = [
    "matplotlib",
    "matplotlib.pyplot",
    "scipy",
    "hexafe_groupstats",
    "modules.export_dialog",
    "modules.tabular_analytics_service",
    "modules.industrial_analytics_workbook_charts",
]
print(json.dumps([name for name in blocked if name in sys.modules]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )

    assert json.loads(completed.stdout.strip()) == []


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
