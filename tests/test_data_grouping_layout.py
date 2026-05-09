import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class TestDataGroupingLayout(unittest.TestCase):
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
                "DataGrouping probe subprocess failed unexpectedly.\n"
                f"Return code: {exc.returncode}\n"
                f"STDOUT:\n{(exc.stdout or '').strip()}\n"
                f"STDERR:\n{stderr}"
            )

        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_layout_uses_stretch_panes_and_summary_labels(self):
        payload = self._run_probe(
            """
            import json
            import pandas as pd
            from PyQt6.QtWidgets import QApplication
            from modules.data_grouping import DataGrouping

            DataGrouping.read_data_to_df = lambda self: setattr(
                self,
                "df",
                pd.DataFrame([
                    {
                        "REPORT_ID": 1,
                        "REFERENCE": "R-01",
                        "DATE": "2024-01-01",
                        "SAMPLE_NUMBER": "S-01",
                        "PART_NAME": "Part A",
                        "REVISION": "A",
                        "TEMPLATE_VARIANT": "Header Box",
                        "STATUS_CODE": "OK",
                        "HAS_NOK": 0,
                        "NOK_COUNT": 0,
                        "OPERATOR_NAME": "Jane",
                        "FILENAME": "file_a.csv",
                    },
                    {
                        "REPORT_ID": 2,
                        "REFERENCE": "R-02",
                        "DATE": "2024-01-02",
                        "SAMPLE_NUMBER": "S-02",
                        "PART_NAME": "Part B",
                        "REVISION": "B",
                        "TEMPLATE_VARIANT": "Header Box",
                        "STATUS_CODE": "NOK",
                        "HAS_NOK": 1,
                        "NOK_COUNT": 2,
                        "OPERATOR_NAME": "John",
                        "FILENAME": "file_b.csv",
                    },
                ]),
            )
            DataGrouping._restore_saved_grouping_state = lambda self: None

            app = QApplication.instance() or QApplication([])
            dialog = DataGrouping(parent=None, db_file="")
            dialog.show()
            app.processEvents()

            layout = dialog.layout
            panes = [dialog.reference_list, dialog.part_list, dialog.groups_list, dialog.part_group_list]
            fixed_200 = [
                pane.minimumWidth() == 200 and pane.maximumWidth() == 200
                for pane in panes
            ]
            print(json.dumps({
                "column_stretch": [layout.columnStretch(i) for i in range(4)],
                "column_min_widths": [layout.columnMinimumWidth(i) for i in range(4)],
                "fixed_200": fixed_200,
                "use_grouping_is_default": dialog.use_grouping_button.isDefault(),
                "use_grouping_auto_default": dialog.use_grouping_button.autoDefault(),
                "clear_grouping_is_default": dialog.dont_use_grouping_button.isDefault(),
                "clear_grouping_auto_default": dialog.dont_use_grouping_button.autoDefault(),
                "summary_labels": [
                    hasattr(dialog, "reference_summary_label"),
                    hasattr(dialog, "group_summary_label"),
                    hasattr(dialog, "selection_summary_label"),
                ],
                "summary_texts": [
                    dialog.reference_summary_label.text(),
                    dialog.group_summary_label.text(),
                    dialog.selection_summary_label.text(),
                ],
            }, sort_keys=True))
            dialog.close()
            app.processEvents()
            """
        )

        self.assertEqual(payload["fixed_200"], [False, False, False, False])
        self.assertGreaterEqual(payload["column_stretch"][0], 1)
        self.assertGreaterEqual(payload["column_stretch"][1], 1)
        self.assertGreaterEqual(payload["column_stretch"][2], 1)
        self.assertGreaterEqual(payload["column_stretch"][3], 1)
        self.assertGreaterEqual(payload["column_min_widths"][0], 140)
        self.assertGreaterEqual(payload["column_min_widths"][1], 180)
        self.assertGreaterEqual(payload["column_min_widths"][2], 140)
        self.assertGreaterEqual(payload["column_min_widths"][3], 180)
        self.assertFalse(payload["use_grouping_is_default"])
        self.assertFalse(payload["use_grouping_auto_default"])
        self.assertFalse(payload["clear_grouping_is_default"])
        self.assertFalse(payload["clear_grouping_auto_default"])
        self.assertEqual(payload["summary_labels"], [True, True, True])
        self.assertTrue(payload["summary_texts"][0].startswith("Reference:"))
        self.assertTrue(payload["summary_texts"][1].startswith("Group:"))
        self.assertTrue(payload["summary_texts"][2].startswith("Selected parts:"))


if __name__ == "__main__":
    unittest.main()
