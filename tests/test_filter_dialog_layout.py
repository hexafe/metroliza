import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class TestFilterDialogLayout(unittest.TestCase):
    def _run_probe(self, script):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_STYLE_OVERRIDE"] = "Fusion"

        try:
            result = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(script)],
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
                "libEGL.so.1",
                "Could not load the Qt platform plugin",
                "no Qt platform plugin could be initialized",
                "qt.qpa.plugin",
            )
            if any(marker in stderr for marker in headless_runtime_markers):
                self.skipTest(f"PyQt runtime dependency missing in test environment: {stderr}")
            self.fail(
                "FilterDialog probe subprocess failed unexpectedly.\n"
                f"Return code: {exc.returncode}\n"
                f"STDOUT:\n{(exc.stdout or '').strip()}\n"
                f"STDERR:\n{stderr}"
            )

        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_default_layout_fits_screen_and_uses_scroll_sections(self):
        payload = self._run_probe(
            """
            import json
            from PyQt6.QtWidgets import QApplication
            from modules.filter_dialog import FilterDialog

            FilterDialog.populate_list_widgets = lambda self: None

            app = QApplication.instance() or QApplication([])
            dialog = FilterDialog(parent=None, db_file="")
            dialog.show()
            app.processEvents()

            available = app.primaryScreen().availableGeometry()
            sections = [name for name, _fields in dialog._build_filter_sections()]
            print(json.dumps({
                "dialog_size": [dialog.width(), dialog.height()],
                "available": [available.width(), available.height()],
                "has_scroll_area": hasattr(dialog, "filter_scroll_area"),
                "sections": sections,
                "max_section_fields": max(len(fields) for _name, fields in dialog._build_filter_sections()),
            }, sort_keys=True))
            dialog.close()
            app.processEvents()
            """
        )

        self.assertLessEqual(payload["dialog_size"][0], payload["available"][0])
        self.assertLessEqual(payload["dialog_size"][1], payload["available"][1])
        self.assertTrue(payload["has_scroll_area"])
        self.assertEqual(payload["sections"], ["Measurement", "Report metadata", "Source"])
        self.assertGreater(payload["max_section_fields"], 3)


if __name__ == "__main__":
    unittest.main()
