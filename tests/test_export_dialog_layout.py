import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class TestExportDialogLayout(unittest.TestCase):
    def test_report_profile_controls_get_minimum_height_buffer(self):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_STYLE_OVERRIDE"] = "Fusion"

        script = textwrap.dedent(
            """
            import json
            from PyQt6.QtWidgets import QApplication
            from modules.export_dialog import ExportDialog

            app = QApplication.instance() or QApplication([])
            dialog = ExportDialog(parent=None, db_file="")
            dialog.show()
            app.processEvents()

            payload = {}
            for name in ("google_sheets_note_label", "html_dashboard_note_label", "sort_measurements_combobox"):
                widget = getattr(dialog, name)
                payload[name] = {
                    "minimum_height": widget.minimumHeight(),
                    "size_hint_height": widget.sizeHint().height(),
                    "actual_height": widget.height(),
                }

            print(json.dumps(payload, sort_keys=True))
            dialog.close()
            app.processEvents()
            """
        )

        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            headless_runtime_markers = (
                "libGL.so.1",
                "Could not load the Qt platform plugin",
                "no Qt platform plugin could be initialized",
                "qt.qpa.plugin",
            )
            if any(marker in stderr for marker in headless_runtime_markers):
                self.skipTest(f"PyQt runtime dependency missing in test environment: {stderr}")
            self.fail(
                "ExportDialog probe subprocess failed unexpectedly.\n"
                f"Return code: {exc.returncode}\n"
                f"STDOUT:\n{(exc.stdout or '').strip()}\n"
                f"STDERR:\n{stderr}"
            )


        payload = json.loads(result.stdout.strip().splitlines()[-1])
        expected_minimums = {
            "google_sheets_note_label": 30,
            "html_dashboard_note_label": 24,
            "sort_measurements_combobox": 22,
        }
        for name in ("google_sheets_note_label", "html_dashboard_note_label", "sort_measurements_combobox"):
            widget_info = payload[name]
            self.assertGreaterEqual(widget_info["minimum_height"], expected_minimums[name])
            self.assertGreaterEqual(widget_info["actual_height"], widget_info["minimum_height"])


if __name__ == "__main__":
    unittest.main()
