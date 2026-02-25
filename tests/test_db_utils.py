import gc
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

import pandas as pd

from modules.db import (
    execute_many_with_retry,
    execute_select_with_columns,
    execute_with_retry,
    read_sql_dataframe,
    run_transaction_with_retry,
)


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
        if not os.path.exists(self.db_path):
            return

        # SQLite file handles can be released asynchronously on Windows runners.
        # Retry cleanup briefly to avoid flaky WinError 32 teardown failures.
        last_error = None
        for _ in range(20):
            try:
                os.remove(self.db_path)
                return
            except PermissionError as exc:
                last_error = exc
                gc.collect()
                time.sleep(0.05)

        raise last_error

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

    def test_read_sql_dataframe_retries_on_transient_lock(self):
        from modules import db as db_module

        original_connect = db_module.connect_sqlite
        attempts = {'count': 0}

        def flaky_connect(path, timeout_s=5.0):
            attempts['count'] += 1
            if attempts['count'] == 1:
                raise sqlite3.OperationalError('database is locked')
            return original_connect(path, timeout_s)

        with mock.patch('modules.db.connect_sqlite', side_effect=flaky_connect), mock.patch('modules.db.time.sleep') as sleep_mock:
            df = read_sql_dataframe(
                self.db_path,
                'SELECT id, name FROM sample ORDER BY id',
                retries=2,
                retry_delay_s=0.001,
            )

        self.assertEqual(attempts['count'], 2)
        sleep_mock.assert_called_once_with(0.001)
        self.assertListEqual(df['name'].tolist(), ['alpha', 'beta'])

    def test_execute_select_with_columns_returns_rows_and_columns(self):
        rows, column_names = execute_select_with_columns(
            self.db_path,
            'SELECT id, name FROM sample ORDER BY id',
        )
        self.assertEqual(rows, [(1, 'alpha'), (2, 'beta')])
        self.assertEqual(column_names, ['id', 'name'])


    def test_execute_many_with_retry_applies_all_statements_in_single_transaction(self):
        execute_many_with_retry(
            self.db_path,
            [
                ("INSERT INTO sample (name) VALUES (?)", ("gamma",)),
                ("UPDATE sample SET name = ? WHERE name = ?", ("alpha-updated", "alpha")),
            ],
        )
        rows = execute_with_retry(self.db_path, 'SELECT name FROM sample ORDER BY id')
        self.assertEqual(rows, [('alpha-updated',), ('beta',), ('gamma',)])

    def test_run_transaction_with_retry_executes_callback_and_commits(self):
        def operation(cursor):
            cursor.execute("INSERT INTO sample (name) VALUES (?)", ("gamma",))
            cursor.execute("SELECT COUNT(*) FROM sample")
            return cursor.fetchone()[0]

        count = run_transaction_with_retry(self.db_path, operation)
        self.assertEqual(count, 3)

        rows = execute_with_retry(self.db_path, 'SELECT name FROM sample ORDER BY id')
        self.assertEqual(rows, [('alpha',), ('beta',), ('gamma',)])

    def test_run_transaction_with_retry_rolls_back_on_mid_transaction_failure(self):
        def failing_operation(cursor):
            cursor.execute("INSERT INTO sample (name) VALUES (?)", ("gamma",))
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            run_transaction_with_retry(self.db_path, failing_operation)

        rows = execute_with_retry(self.db_path, 'SELECT name FROM sample ORDER BY id')
        self.assertEqual(rows, [('alpha',), ('beta',)])

    def test_run_transaction_with_retry_avoids_partial_or_duplicate_rows_after_retry(self):
        execute_with_retry(self.db_path, 'CREATE TABLE retried_writes (name TEXT)')
        attempts = {'count': 0}

        def flaky_operation(cursor):
            attempts['count'] += 1
            cursor.execute('INSERT INTO retried_writes (name) VALUES (?)', ('alpha',))
            cursor.execute('INSERT INTO retried_writes (name) VALUES (?)', ('beta',))
            if attempts['count'] == 1:
                raise sqlite3.OperationalError('database is locked')

        run_transaction_with_retry(
            self.db_path,
            flaky_operation,
            retries=1,
            retry_delay_s=0.001,
        )

        rows = execute_with_retry(self.db_path, 'SELECT name FROM retried_writes ORDER BY name')
        self.assertEqual(rows, [('alpha',), ('beta',)])
        self.assertEqual(attempts['count'], 2)

    def test_execute_many_with_retry_retries_on_transient_lock(self):
        from modules import db as db_module

        original_connect = db_module.connect_sqlite
        attempts = {'count': 0}

        def flaky_connect(path, timeout_s=5.0):
            attempts['count'] += 1
            if attempts['count'] == 1:
                raise sqlite3.OperationalError('database is locked')
            return original_connect(path, timeout_s)

        with mock.patch('modules.db.connect_sqlite', side_effect=flaky_connect), mock.patch('modules.db.time.sleep') as sleep_mock:
            execute_many_with_retry(
                self.db_path,
                [("INSERT INTO sample (name) VALUES (?)", ("gamma",))],
                retries=2,
                retry_delay_s=0.001,
            )

        self.assertEqual(attempts['count'], 2)
        sleep_mock.assert_called_once_with(0.001)

        rows = execute_with_retry(self.db_path, 'SELECT name FROM sample ORDER BY id')
        self.assertEqual(rows, [('alpha',), ('beta',), ('gamma',)])

    def test_run_transaction_with_retry_retries_on_transient_lock(self):
        from modules import db as db_module

        original_connect = db_module.connect_sqlite
        attempts = {'count': 0}

        def flaky_connect(path, timeout_s=5.0):
            attempts['count'] += 1
            if attempts['count'] == 1:
                raise sqlite3.OperationalError('database is locked')
            return original_connect(path, timeout_s)

        with mock.patch('modules.db.connect_sqlite', side_effect=flaky_connect), mock.patch('modules.db.time.sleep') as sleep_mock:
            def operation(cursor):
                cursor.execute("SELECT COUNT(*) FROM sample")
                return cursor.fetchone()[0]

            result = run_transaction_with_retry(
                self.db_path,
                operation,
                retries=2,
                retry_delay_s=0.001,
            )

        self.assertEqual(result, 2)
        self.assertEqual(attempts['count'], 2)
        sleep_mock.assert_called_once_with(0.001)

    def test_execute_many_with_retry_supports_duplicate_safe_writes(self):
        execute_many_with_retry(
            self.db_path,
            [('CREATE TABLE IF NOT EXISTS dedupe (name TEXT UNIQUE)', ())],
        )

        execute_many_with_retry(
            self.db_path,
            [
                ('INSERT OR IGNORE INTO dedupe (name) VALUES (?)', ('alpha',)),
                ('INSERT OR IGNORE INTO dedupe (name) VALUES (?)', ('alpha',)),
                ('INSERT OR IGNORE INTO dedupe (name) VALUES (?)', ('beta',)),
            ],
        )

        rows = execute_with_retry(self.db_path, 'SELECT name FROM dedupe ORDER BY name')
        self.assertEqual(rows, [('alpha',), ('beta',)])


if __name__ == '__main__':
    unittest.main()
