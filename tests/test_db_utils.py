import os
import sqlite3
import tempfile
import unittest

import pandas as pd

from modules.db import execute_with_retry, read_sql_dataframe


class TestDbUtils(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)')
            conn.execute("INSERT INTO sample (name) VALUES ('alpha')")
            conn.execute("INSERT INTO sample (name) VALUES ('beta')")
            conn.commit()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_execute_with_retry_returns_rows(self):
        rows = execute_with_retry(self.db_path, 'SELECT name FROM sample ORDER BY id')
        self.assertEqual(rows, [('alpha',), ('beta',)])

    def test_execute_with_retry_raises_for_non_transient_error(self):
        with self.assertRaises(sqlite3.OperationalError):
            execute_with_retry(self.db_path, 'SELECT * FROM missing_table')

    def test_read_sql_dataframe_returns_dataframe(self):
        df = read_sql_dataframe(self.db_path, 'SELECT id, name FROM sample ORDER BY id')
        self.assertIsInstance(df, pd.DataFrame)
        self.assertListEqual(df['name'].tolist(), ['alpha', 'beta'])


if __name__ == '__main__':
    unittest.main()
