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
        self.assertIn('from modules.db import execute_many_with_retry, execute_select_with_columns', modify_db)

    def test_cmm_and_bom_manager_no_longer_use_direct_sqlite_connect(self):
        cmm_parser = self._read('modules/CMMReportParser.py')
        bom_manager = self._read('modules/bom_manager.py')

        self.assertNotIn('sqlite3.connect(', cmm_parser)
        self.assertNotIn('sqlite3.connect(', bom_manager)

        self.assertIn('from modules.db import execute_with_retry, run_transaction_with_retry', cmm_parser)
        self.assertIn('from modules.db import (', bom_manager)
        self.assertIn('execute_many_with_retry', bom_manager)
        self.assertIn('execute_select_with_columns', bom_manager)


    def test_cmm_parser_uses_shared_transaction_retry_helper_for_writes(self):
        cmm_parser = self._read('modules/CMMReportParser.py')

        self.assertNotIn('while retry_attempt <=', cmm_parser)
        self.assertNotIn('max_retry_attempts =', cmm_parser)
        self.assertIn('was_inserted = run_transaction_with_retry(', cmm_parser)


    def test_bom_manager_write_paths_use_centralized_helpers(self):
        bom_manager = self._read('modules/bom_manager.py')

        self.assertIn('execute_many_with_retry(self.database_path, [(query, params)])', bom_manager)
        self.assertIn('execute_many_with_retry(self.database_path, delete_statements)', bom_manager)
        self.assertNotIn('self.conn.commit()', bom_manager)
        self.assertNotIn('cursor = self.conn.cursor()', bom_manager)

    def test_migrated_result_shape_usage_is_tuple_based(self):
        cmm_parser = self._read('modules/CMMReportParser.py')
        bom_manager = self._read('modules/bom_manager.py')

        self.assertIn('count = count_rows[0][0] if count_rows else 0', cmm_parser)
        self.assertIn('count = count_rows[0][0] if count_rows else 0', cmm_parser)

        self.assertIn('return parent_rows[0][0]', bom_manager)
        self.assertIn('entry_id = entry[0]', bom_manager)
        self.assertIn('product_reference = entry[1]', bom_manager)


if __name__ == '__main__':
    unittest.main()
