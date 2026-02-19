import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestPhase2DbMigrationGuardrails(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding='utf-8')

    def test_parse_and_modify_use_shared_db_helpers(self):
        parse_thread = self._read('modules/ParseReportsThread.py')
        modify_db = self._read('modules/ModifyDB.py')

        self.assertNotIn('sqlite3.connect(', parse_thread)
        self.assertNotIn('sqlite3.connect(', modify_db)

        self.assertIn('from modules.db import execute_with_retry', parse_thread)
        self.assertIn('from modules.db import connect_sqlite, execute_select_with_columns', modify_db)


if __name__ == '__main__':
    unittest.main()
