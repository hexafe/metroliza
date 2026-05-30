import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestPhase1ReliabilityGuardrails(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding='utf-8')

    def test_ui_cancel_handlers_do_not_block_with_wait(self):
        parsing_dialog = self._read('src/metroliza/ui/parsing_dialog.py')
        export_dialog = self._read('src/metroliza/ui/export_dialog.py')

        self.assertNotIn('.wait(', parsing_dialog)
        self.assertNotIn('.wait(', export_dialog)

    def test_no_forced_thread_termination_patterns(self):
        app_sources = [
            'src/metroliza/ui/parsing_dialog.py',
            'src/metroliza/ui/export_dialog.py',
            'src/metroliza/parsing/parse_reports_thread.py',
            'src/metroliza/exporting/export_data_thread.py',
        ]

        for path in app_sources:
            with self.subTest(path=path):
                self.assertNotIn('.terminate(', self._read(path))

    def test_user_facing_custom_logger_calls_are_non_reraising(self):
        user_flow_sources = [
            'metroliza.py',
            'src/metroliza/parsing/cmm_report_parser.py',
            'src/metroliza/ui/data_grouping.py',
            'src/metroliza/exporting/export_data_thread.py',
            'src/metroliza/ui/export_dialog.py',
            'src/metroliza/ui/filter_dialog.py',
            'src/metroliza/ui/main_window.py',
            'src/metroliza/ui/modify_db.py',
            'src/metroliza/parsing/parse_reports_thread.py',
            'src/metroliza/ui/parsing_dialog.py',
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
