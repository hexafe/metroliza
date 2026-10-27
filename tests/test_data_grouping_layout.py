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
                "action_buttons_default": [
                    button.isDefault()
                    for button in (
                        dialog.create_group_button,
                        dialog.rename_group_button,
                        dialog.remove_from_group_button,
                        dialog.delete_group_button,
                    )
                ],
                "action_buttons_auto_default": [
                    button.autoDefault()
                    for button in (
                        dialog.create_group_button,
                        dialog.rename_group_button,
                        dialog.remove_from_group_button,
                        dialog.delete_group_button,
                    )
                ],
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
        self.assertTrue(payload["use_grouping_is_default"])
        self.assertTrue(payload["use_grouping_auto_default"])
        self.assertFalse(payload["clear_grouping_is_default"])
        self.assertFalse(payload["clear_grouping_auto_default"])
        self.assertEqual(payload["action_buttons_default"], [False, False, False, False])
        self.assertEqual(payload["action_buttons_auto_default"], [False, False, False, False])
        self.assertEqual(payload["summary_labels"], [True, True, True])
        self.assertTrue(payload["summary_texts"][0].startswith("Reference:"))
        self.assertTrue(payload["summary_texts"][1].startswith("Group:"))
        self.assertTrue(payload["summary_texts"][2].startswith("Selected parts:"))


if __name__ == "__main__":
    unittest.main()


class TestGroupingSignalPopulation(unittest.TestCase):
    _run_probe = TestDataGroupingLayout._run_probe

    def test_population_coalesces_callbacks_and_restores_existing_signal_block(self):
        payload = self._run_probe(
            """
            import json
            import pandas as pd
            from PyQt6.QtWidgets import QApplication
            from metroliza.ui.data_grouping import DataGrouping

            class Grouping(DataGrouping):
                def read_data_to_df(self):
                    self.df = pd.DataFrame({'REPORT_ID': [1, 2, 3], 'REFERENCE': ['001', None, ' '],
                                            'SAMPLE_NUMBER': [1, 2, 3], 'PART_NAME': ['A', 'B', 'A']})
                def on_reference_selection_changed(self):
                    self.reference_callbacks = getattr(self, 'reference_callbacks', 0) + 1
                    super().on_reference_selection_changed()
                def on_group_selection_changed(self):
                    self.group_callbacks = getattr(self, 'group_callbacks', 0) + 1
                    super().on_group_selection_changed()

            app = QApplication.instance() or QApplication([])
            dialog = Grouping(parent=None, db_file='')
            initial = [dialog.reference_callbacks, dialog.group_callbacks]
            dialog.reference_callbacks = dialog.group_callbacks = 0
            dialog.reference_list.blockSignals(True)
            emitted = []
            dialog.groups_list.itemSelectionChanged.connect(lambda: emitted.append('group'))
            dialog.reference_list.itemSelectionChanged.connect(lambda: emitted.append('reference'))
            dialog.populate_list_widgets()
            after = [dialog.reference_callbacks, dialog.group_callbacks]
            blocked = [dialog.reference_list.signalsBlocked(), dialog.groups_list.signalsBlocked(),
                       dialog.part_list.signalsBlocked(), dialog.part_group_list.signalsBlocked()]
            print(json.dumps({'initial': initial, 'after': after, 'blocked': blocked, 'emitted': emitted,
                              'parts': dialog.part_list.count(), 'group_parts': dialog.part_group_list.count()}))
            """
        )
        self.assertEqual(payload, {'initial': [1, 1], 'after': [1, 1], 'blocked': [True, False, False, False],
                                   'parts': 1, 'group_parts': 3, 'emitted': []})

    def test_population_errors_restore_all_prior_signal_states_including_partial_construction(self):
        payload = self._run_probe(
            """
            import json
            import pandas as pd
            from unittest.mock import patch
            from PyQt6 import QtCore
            from PyQt6.QtWidgets import QApplication
            from metroliza.ui.data_grouping import DataGrouping
            DataGrouping.read_data_to_df = lambda self: setattr(self, 'df', pd.DataFrame({
                'REPORT_ID': [1, 2], 'REFERENCE': ['A', 'B'], 'SAMPLE_NUMBER': [1, 2],
            }))
            app = QApplication.instance() or QApplication([])
            dialog = DataGrouping(parent=None, db_file='')
            widgets = [getattr(dialog, name) for name in (
                'reference_list', 'part_list', 'all_parts_list', 'groups_list', 'part_group_list',
            )]
            prior = [False, True, False, True, False]
            for widget, blocked in zip(widgets, prior):
                widget.blockSignals(blocked)
            errors = []
            dialog.log_and_exit = lambda error: errors.append(str(error))
            original = QtCore.QSignalBlocker
            attempts = []
            def partial_failure(widget):
                attempts.append(widget)
                if len(attempts) == 2:
                    raise RuntimeError('blocker construction failure')
                return original(widget)
            with patch.object(QtCore, 'QSignalBlocker', partial_failure):
                dialog.populate_list_widgets()
            after_partial = [widget.signalsBlocked() for widget in widgets]
            def population_failure():
                raise RuntimeError('population failure')
            dialog._ensure_group_color_integrity = population_failure
            dialog.populate_list_widgets()
            print(json.dumps({'prior': prior, 'after_partial': after_partial,
                              'after_population': [widget.signalsBlocked() for widget in widgets],
                              'errors': errors, 'construction_attempts': len(attempts)}))
            """
        )
        self.assertEqual(payload['after_partial'], payload['prior'])
        self.assertEqual(payload['after_population'], payload['prior'])
        self.assertEqual(payload['construction_attempts'], 2)
        self.assertEqual(payload['errors'], ['blocker construction failure', 'population failure'])

    def test_native_missing_blocker_preserves_general_output_and_other_import_errors_surface(self):
        payload = self._run_probe(
            """
            import builtins
            import json
            import pandas as pd
            from unittest.mock import patch
            from PyQt6.QtWidgets import QApplication
            from metroliza.ui.data_grouping import DataGrouping
            DataGrouping.read_data_to_df = lambda self: setattr(self, 'df', pd.DataFrame({
                'REPORT_ID': [1, 2], 'REFERENCE': ['A', 'B'], 'SAMPLE_NUMBER': [1, 2],
            }))
            app = QApplication.instance() or QApplication([])
            dialog = DataGrouping(parent=None, db_file='')
            def snapshot():
                lists = []
                for name in ('reference_list', 'part_list', 'all_parts_list', 'groups_list', 'part_group_list'):
                    widget = getattr(dialog, name)
                    lists.append([(widget.item(i).text(), widget.item(i).isSelected(),
                                   widget.item(i).background().color().name()) for i in range(widget.count())])
                return {'lists': lists, 'summaries': [getattr(dialog, name).text() for name in (
                    'reference_summary_label', 'group_summary_label', 'selection_summary_label',
                )]}
            expected = snapshot()
            original_import = builtins.__import__
            attempts = []
            def missing_blocker(name, globals=None, locals=None, fromlist=(), level=0):
                if name == 'PyQt6.QtCore' and 'QSignalBlocker' in fromlist:
                    attempts.append('missing')
                    raise ImportError('blocker deliberately unavailable')
                return original_import(name, globals, locals, fromlist, level)
            errors = []
            dialog.log_and_exit = lambda error: errors.append(str(error))
            with patch('builtins.__import__', side_effect=missing_blocker):
                dialog.populate_list_widgets()
            equal = snapshot() == expected
            def unexpected_error(name, globals=None, locals=None, fromlist=(), level=0):
                if name == 'PyQt6.QtCore' and 'QSignalBlocker' in fromlist:
                    raise RuntimeError('unexpected blocker import error')
                return original_import(name, globals, locals, fromlist, level)
            with patch('builtins.__import__', side_effect=unexpected_error):
                dialog.populate_list_widgets()
            print(json.dumps({'general_identical': equal, 'attempts': attempts, 'errors': errors}))
            """
        )
        self.assertEqual(payload, {'general_identical': True, 'attempts': ['missing'],
                                   'errors': ['unexpected blocker import error']})
