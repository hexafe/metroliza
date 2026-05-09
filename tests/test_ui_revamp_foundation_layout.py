import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class TestUiRevampFoundationLayout(unittest.TestCase):
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
                "UI revamp probe subprocess failed unexpectedly.\n"
                f"Return code: {exc.returncode}\n"
                f"STDOUT:\n{(exc.stdout or '').strip()}\n"
                f"STDERR:\n{stderr}"
            )

        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_main_and_parsing_surfaces_use_responsive_command_center_layouts(self):
        payload = self._run_probe(
            """
            import json
            from PyQt6.QtWidgets import QApplication, QPushButton
            from modules.main_window import MainWindow
            from modules.parsing_dialog import ParsingDialog

            app = QApplication.instance() or QApplication([])
            main = MainWindow(version_label="test", days_until_expiration=None)
            parsing = ParsingDialog(parent=None, directory="/tmp/reports", db_file="")
            main.show()
            parsing.show()
            app.processEvents()

            available = app.primaryScreen().availableGeometry()
            button_texts = [button.text() for button in main.findChildren(QPushButton)]
            print(json.dumps({
                "main_size": [main.width(), main.height()],
                "parsing_size": [parsing.width(), parsing.height()],
                "available": [available.width(), available.height()],
                "main_buttons": button_texts,
                "source_status": main.source_status_label.text(),
                "database_status": main.database_status_label.text(),
                "parse_ready": parsing.parse_button.isEnabled(),
                "readiness": parsing.readiness_label.text(),
                "directory_tooltip": parsing.directory_text_label.toolTip(),
            }, sort_keys=True))
            parsing.close()
            main.close()
            app.processEvents()
            """
        )

        self.assertLessEqual(payload["main_size"][0], payload["available"][0])
        self.assertLessEqual(payload["parsing_size"][0], payload["available"][0])
        self.assertIn("Parse Reports", payload["main_buttons"])
        self.assertIn("Export Workbook", payload["main_buttons"])
        self.assertIn("Source: not selected", payload["source_status"])
        self.assertIn("Database: not selected", payload["database_status"])
        self.assertFalse(payload["parse_ready"])
        self.assertIn("database", payload["readiness"].lower())
        self.assertIn("/tmp/reports", payload["directory_tooltip"])

    def test_progress_and_release_notes_fit_offscreen_desktop(self):
        payload = self._run_probe(
            """
            import json
            from PyQt6.QtWidgets import QApplication
            from modules.release_notes_dialog import ReleaseNotesDialog
            from modules.worker_progress_dialog import create_worker_progress_dialog

            app = QApplication.instance() or QApplication([])
            progress_dialog, label, progress_bar, movie = create_worker_progress_dialog(
                None,
                window_title="Working",
                initial_status_text="Stage\\nDetail\\nETA --",
                on_cancel=lambda: None,
            )
            release_notes = ReleaseNotesDialog(None, "<p>Short release note</p>")
            progress_dialog.show()
            release_notes.show()
            app.processEvents()
            available = app.primaryScreen().availableGeometry()
            print(json.dumps({
                "progress_size": [progress_dialog.width(), progress_dialog.height()],
                "release_size": [release_notes.width(), release_notes.height()],
                "available": [available.width(), available.height()],
                "progress_text": label.text(),
                "bar_max_height": progress_bar.maximumHeight(),
            }, sort_keys=True))
            progress_dialog.close()
            release_notes.close()
            app.processEvents()
            """
        )

        self.assertLessEqual(payload["progress_size"][0], payload["available"][0])
        self.assertLessEqual(payload["release_size"][0], payload["available"][0])
        self.assertIn("Stage", payload["progress_text"])
        self.assertLessEqual(payload["bar_max_height"], 20)


if __name__ == "__main__":
    unittest.main()
