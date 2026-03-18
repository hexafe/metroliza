import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestPhase1ReliabilityGuardrails(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding='utf-8')

    def test_ui_cancel_handlers_do_not_block_with_wait(self):
        parsing_dialog = self._read('modules/parsing_dialog.py')
        export_dialog = self._read('modules/export_dialog.py')

        self.assertNotIn('.wait(', parsing_dialog)
        self.assertNotIn('.wait(', export_dialog)

    def test_no_forced_thread_termination_patterns(self):
        app_sources = [
            'modules/parsing_dialog.py',
            'modules/export_dialog.py',
            'modules/parse_reports_thread.py',
            'modules/export_data_thread.py',
        ]

        for path in app_sources:
            with self.subTest(path=path):
                self.assertNotIn('.terminate(', self._read(path))

    def test_user_facing_custom_logger_calls_are_non_reraising(self):
        user_flow_sources = [
            'metroliza.py',
            'modules/cmm_report_parser.py',
            'modules/data_grouping.py',
            'modules/export_data_thread.py',
            'modules/export_dialog.py',
            'modules/filter_dialog.py',
            'modules/main_window.py',
            'modules/modify_db.py',
            'modules/parse_reports_thread.py',
            'modules/parsing_dialog.py',
        ]
        logger_call = re.compile(r'(?:^|[^\w.])(?:custom_logger\.)?CustomLogger\((?P<args>[^)]*)\)')

        observed_calls = []

        for path in user_flow_sources:
            content = self._read(path)
            calls = logger_call.findall(content)
            observed_calls.extend((path, args) for args in calls)
            for args in calls:
                with self.subTest(path=path, args=args):
                    self.assertIn('reraise=False', args)

        self.assertTrue(observed_calls, msg='Expected at least one CustomLogger call across user-facing flows')


if __name__ == '__main__':
    unittest.main()
