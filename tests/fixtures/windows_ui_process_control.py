"""Closed synthetic observation of processes started by the real source window."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

STAGES = ("bootstrap_import", "window_import", "window_construct", "show_close")
counts = {stage: {"cmd_ver": 0, "other": 0} for stage in STAGES}
stage = STAGES[0]


def observe(event, arguments):
    if event != "subprocess.Popen":
        return
    executable, command = arguments[:2]
    expected = str(Path(os.environ["SYSTEMROOT"]) / "System32" / "cmd.exe")
    recognized = (
        type(executable) is str and os.path.normcase(executable) == os.path.normcase(expected)
        and type(command) is str
        and command.casefold() == (expected + ' /c "ver"').casefold()
    )
    key = "cmd_ver" if recognized else "other"
    counts[stage][key] = min(16, counts[stage][key] + 1)


def main():
    global stage
    sys.addaudithook(observe)
    result = {"status": "failed", "audit": counts, "window_seen": False, "closed": False}
    try:
        from metroliza.app.bootstrap import get_or_create_qapplication
        stage = "window_import"
        from PyQt6.QtCore import QSettings, QTimer
        from metroliza.ui.main_window import MainWindow
        from metroliza.ui.ui_preferences import UiPreferences
        app = get_or_create_qapplication()
        stage = "window_construct"
        settings = QSettings(str(Path.cwd() / "isolated.ini"), QSettings.Format.IniFormat)
        window = MainWindow("native-process-control", None, ui_preferences=UiPreferences(settings))
        stage = "show_close"
        window.show()
        app.processEvents()
        result["window_seen"] = window.isVisible()

        def close():
            result["closed"] = bool(window.close()) and not window.isVisible()
            app.quit()

        QTimer.singleShot(250, close)
        code = app.exec()
        result["status"] = "passed" if code == 0 and result["closed"] and result["window_seen"] else "failed"
    except Exception:
        result["status"] = "failed"
    with (Path.cwd() / "ui-process-control.json").open("x", encoding="ascii") as stream:
        json.dump(result, stream, sort_keys=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
