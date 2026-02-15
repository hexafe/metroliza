import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestPhase1ReliabilityGuardrails(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding='utf-8')

    def test_ui_cancel_handlers_do_not_block_with_wait(self):
        parsing_dialog = self._read('modules/ParsingDialog.py')
        export_dialog = self._read('modules/ExportDialog.py')

        self.assertNotIn('.wait(', parsing_dialog)
        self.assertNotIn('.wait(', export_dialog)

    def test_no_forced_thread_termination_patterns(self):
        app_sources = [
            'modules/ParsingDialog.py',
            'modules/ExportDialog.py',
            'modules/ParseReportsThread.py',
            'modules/ExportDataThread.py',
        ]

        for path in app_sources:
            with self.subTest(path=path):
                self.assertNotIn('.terminate(', self._read(path))

    def test_user_facing_custom_logger_calls_are_non_reraising(self):
        user_flow_sources = [
            'metroliza.py',
            'modules/CMMReportParser.py',
            'modules/DataGrouping.py',
            'modules/ExportDataThread.py',
            'modules/ExportDialog.py',
            'modules/FilterDialog.py',
            'modules/MainWindow.py',
            'modules/ModifyDB.py',
            'modules/ParseReportsThread.py',
            'modules/ParsingDialog.py',
        ]
        logger_call = re.compile(r'CustomLogger\((?P<args>[^)]*)\)')

        for path in user_flow_sources:
            content = self._read(path)
            calls = logger_call.findall(content)
            self.assertTrue(calls, msg=f'Expected at least one CustomLogger call in {path}')
            for args in calls:
                with self.subTest(path=path, args=args):
                    self.assertIn('reraise=False', args)


if __name__ == '__main__':
    unittest.main()
