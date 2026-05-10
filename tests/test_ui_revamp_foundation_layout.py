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
            import base64
            from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
            from PyQt6.QtGui import QImageReader
            from PyQt6.QtWidgets import QApplication, QPushButton
            from modules import base64_encoded_files
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
            movie_size = movie.scaledSize()
            gif_bytes = base64.b64decode(base64_encoded_files.encoded_loading_gif)
            source_buffer = QBuffer()
            source_buffer.setData(QByteArray(gif_bytes))
            source_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            source_size = QImageReader(source_buffer, b"gif").size()
            cancel_texts = [button.text() for button in progress_dialog.findChildren(QPushButton)]
            print(json.dumps({
                "progress_size": [progress_dialog.width(), progress_dialog.height()],
                "release_size": [release_notes.width(), release_notes.height()],
                "available": [available.width(), available.height()],
                "progress_text": label.text(),
                "bar_max_height": progress_bar.maximumHeight(),
                "movie_size": [movie_size.width(), movie_size.height()],
                "source_size": [source_size.width(), source_size.height()],
                "movie_file_name": movie.fileName(),
                "cancel_texts": cancel_texts,
            }, sort_keys=True))
            progress_dialog.close()
            release_notes.close()
            app.processEvents()
            """
        )

        self.assertLessEqual(payload["progress_size"][0], payload["available"][0])
        self.assertLessEqual(payload["progress_size"][1], payload["available"][1])
        self.assertLessEqual(payload["progress_size"][1], 320)
        self.assertLessEqual(payload["release_size"][0], payload["available"][0])
        self.assertIn("Stage", payload["progress_text"])
        self.assertLessEqual(payload["bar_max_height"], 20)
        self.assertEqual(max(payload["movie_size"]), 168)
        self.assertGreaterEqual(min(payload["movie_size"]), 150)
        self.assertTrue(payload["source_size"][0] > 0 and payload["source_size"][1] > 0)
        self.assertAlmostEqual(
            payload["movie_size"][0] / payload["movie_size"][1],
            payload["source_size"][0] / payload["source_size"][1],
            places=2,
        )
        self.assertEqual(payload["movie_file_name"], "")
        self.assertIn("Cancel", payload["cancel_texts"])

    def test_export_dialog_initial_width_contains_visible_buttons(self):
        payload = self._run_probe(
            """
            import json
            import os
            import tempfile
            from PyQt6.QtCore import QPoint
            from PyQt6.QtWidgets import QApplication, QAbstractButton

            with tempfile.TemporaryDirectory() as home_dir:
                os.environ["HOME"] = home_dir
                from modules.export_dialog import ExportDialog

                app = QApplication.instance() or QApplication([])
                dialog = ExportDialog(None, db_file="/tmp/metroliza-export-layout-check.db")
                dialog.show()
                app.processEvents()

                visible_button_bounds = []
                for button in dialog.findChildren(QAbstractButton):
                    if not button.isVisible():
                        continue
                    top_left = button.mapTo(dialog, QPoint(0, 0))
                    visible_button_bounds.append({
                        "text": button.text(),
                        "left": top_left.x(),
                        "right": top_left.x() + button.width(),
                        "width": button.width(),
                    })

                viewport_width = dialog.content_scroll_area.viewport().width()
                print(json.dumps({
                    "dialog_size": [dialog.width(), dialog.height()],
                    "available": [
                        app.primaryScreen().availableGeometry().width(),
                        app.primaryScreen().availableGeometry().height(),
                    ],
                    "viewport_width": viewport_width,
                    "content_min_width": dialog.content_widget.minimumSizeHint().width(),
                    "button_bounds": visible_button_bounds,
                }, sort_keys=True))
                dialog.close()
                app.processEvents()
            """
        )

        self.assertLessEqual(payload["dialog_size"][0], payload["available"][0])
        self.assertGreaterEqual(payload["viewport_width"], payload["content_min_width"])
        for button in payload["button_bounds"]:
            self.assertGreaterEqual(button["left"], 0, button)
            self.assertLessEqual(button["right"], payload["dialog_size"][0], button)
        self.assertIn("Export", {button["text"] for button in payload["button_bounds"]})


if __name__ == "__main__":
    unittest.main()
