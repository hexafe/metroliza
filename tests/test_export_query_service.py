import unittest

from modules.export_query_service import (
    RowTable,
    build_export_dataframe,
    build_measurement_export_dataframe,
    ensure_sample_number_column,
    execute_export_query,
    fetch_partition_header_counts,
    fetch_sql_measurement_summaries,
)
from modules.report_query_service import build_measurement_export_query


class TestExportQueryService(unittest.TestCase):
    def test_execute_export_query_uses_reader_contract(self):
        def fake_reader(db_file, query):
            self.assertEqual(db_file, 'db.sqlite')
            self.assertEqual(query, 'SELECT 1')
            return [(1,)], ['VALUE']

        rows, columns = execute_export_query('db.sqlite', 'SELECT 1', select_reader=fake_reader)
        self.assertEqual(rows, [(1,)])
        self.assertEqual(columns, ['VALUE'])

    def test_build_measurement_export_dataframe_adds_header_ax_and_sample_number(self):
        rows = RowTable(rows=(('H1', 'A', 1.23),), columns=('HEADER', 'AX', 'MEAS'))

        result = build_measurement_export_dataframe(rows)

        self.assertEqual(result.loc[0, 'HEADER - AX'], 'H1 - A')
        self.assertEqual(result.loc[0, 'SAMPLE_NUMBER'], '1')

    def test_ensure_sample_number_column_keeps_existing(self):
        table = RowTable(rows=(('42',),), columns=('SAMPLE_NUMBER',))
        self.assertEqual(ensure_sample_number_column(table).loc[0, 'SAMPLE_NUMBER'], '42')

    def test_build_export_dataframe_preserves_columns(self):
        table = build_export_dataframe([(1, 'A')], ['ID', 'LABEL'])
        self.assertEqual(list(table.columns), ['ID', 'LABEL'])
        self.assertEqual(table.iloc[0]['LABEL'], 'A')

    def test_row_table_groupby_supports_multiple_columns(self):
        table = RowTable(
            rows=(
                ('REF_A', 'H1 - AX', 1.0),
                ('REF_A', 'H1 - AX', 2.0),
                ('REF_B', 'H2 - AX', 3.0),
            ),
            columns=('REFERENCE', 'HEADER - AX', 'MEAS'),
        )

        groups = list(table.groupby(['REFERENCE', 'HEADER - AX'], sort=False))

        self.assertEqual([key for key, _group in groups], [('REF_A', 'H1 - AX'), ('REF_B', 'H2 - AX')])
        self.assertEqual([len(group) for _key, group in groups], [2, 1])

    def test_row_table_sort_values_supports_key_transform(self):
        table = RowTable(
            rows=(('beta', 2), ('Alpha', 1), ('alpha', 3)),
            columns=('LABEL', 'ORDER'),
        )

        sorted_table = table.sort_values(by=['LABEL', 'ORDER'], key=lambda col: col.astype(str).str.lower())

        self.assertEqual([row['ORDER'] for _index, row in sorted_table.iterrows()], [1, 3, 2])

    def test_row_table_membership_is_schema_based_and_rows_require_iloc(self):
        table = RowTable(rows=((1.23,),), columns=('MEAS',))

        self.assertIn('MEAS', table)
        self.assertNotIn('MISSING', table)
        self.assertEqual(table.iloc[0]['MEAS'], 1.23)
        with self.assertRaisesRegex(TypeError, r"use \.iloc for positional row access"):
            table[0]

    def test_fetch_partition_header_counts_uses_sqlite_literal_delimiter(self):
        captured = {}

        def fake_read_sql_query(_db_file, query, *, params=(), connection=None):
            captured['query'] = query
            self.assertEqual(params, ())
            self.assertIsNone(connection)
            return RowTable(rows=(('REF_A', 2),), columns=('partition_value', 'header_count'))

        from modules import export_query_service as service

        previous_reader = service._read_sql_query
        try:
            service._read_sql_query = fake_read_sql_query
            counts = fetch_partition_header_counts('db.sqlite', 'SELECT * FROM vw_measurement_export')
        finally:
            service._read_sql_query = previous_reader

        self.assertEqual(counts, {'REF_A': 2})
        self.assertIn("HEADER || ' - ' || AX", captured['query'])

    def test_fetch_partition_header_counts_rejects_unreviewed_sql_expression(self):
        with self.assertRaisesRegex(ValueError, "Unsupported partition header expression"):
            fetch_partition_header_counts(
                'db.sqlite',
                'SELECT * FROM vw_measurement_export',
                header_expr="HEADER); DROP TABLE REPORTS; --",
            )

    def test_fetch_sql_measurement_summaries_groups_rows_by_reference_header_and_axis(self):
        captured = {}

        def fake_read_sql_query(_db_file, query, *, params=(), connection=None):
            captured['query'] = query
            captured['params'] = params
            self.assertIsNone(connection)
            return RowTable(
                rows=(('REF_A', 'H1', 'AX1', 3, 1.5, 1.0, 2.0, 1, 0.5),),
                columns=(
                    'REFERENCE',
                    'HEADER',
                    'AX',
                    'sample_size',
                    'average',
                    'minimum',
                    'maximum',
                    'nok_count',
                    'sigma',
                ),
            )

        from modules import export_query_service as service

        previous_reader = service._read_sql_query
        try:
            service._read_sql_query = fake_read_sql_query
            summaries = fetch_sql_measurement_summaries('db.sqlite', 'SELECT * FROM vw_measurement_export', reference='REF_A')
        finally:
            service._read_sql_query = previous_reader

        self.assertEqual(captured['params'], ('REF_A',))
        self.assertIn('GROUP BY REFERENCE, HEADER, AX', captured['query'])
        self.assertIn('MEAS > (NOM + "+TOL")', captured['query'])
        self.assertEqual(
            summaries[('REF_A', 'H1', 'AX1')]['sample_size'],
            3,
        )

    def test_build_measurement_export_query_keeps_workbook_alias_columns(self):
        query = build_measurement_export_query()

        self.assertIn('directory_path AS FILELOC', query)
        self.assertIn('file_name AS FILENAME', query)


class TestSnapshotPartitionEquivalence(unittest.TestCase):
    """An independent ordered SQL oracle, also executed before the fast path exists."""

    REFERENCES = (
        'shared', None, '', '   ', '\t', '\n', '01', '1', 1, 1.0,
        1.000000000000001, 0, '0', '00', ' padded ', 'żółć:β',
        'Report 2 (no reference)', 'report:2', 'reference:x', 'shared',
        None, 'shared', b'1',
    )

    @classmethod
    def populate_snapshot(cls, connection, reference_type='TEXT', report_type='INTEGER'):
        connection.execute(
            f'CREATE TABLE source_rows (REPORT_ID {report_type}, REFERENCE {reference_type}, '
            'HEADER TEXT, AX TEXT, MEAS REAL, OCCURRENCE INTEGER)'
        )
        rows = [
            (2 if ref is None or ref in ('', '   ') else index + 1,
             ref, 'H' + str(index % 2), 'X', index / 4, index)
            for index, ref in enumerate(cls.REFERENCES)
        ]
        # A true duplicate is retained; no report join may discard this orphan id.
        rows.extend([rows[0], (9999, None, 'H0', 'X', 2.0, 99)])
        connection.executemany('INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?)', rows)
        connection.execute(
            'CREATE TEMP TABLE snapshot_rows AS SELECT * FROM source_rows '
            'ORDER BY OCCURRENCE % 3, OCCURRENCE DESC'
        )
        connection.execute('CREATE INDEX snapshot_ref ON snapshot_rows(REFERENCE)')
        connection.execute('CREATE INDEX snapshot_report ON snapshot_rows(REPORT_ID)')

    @staticmethod
    def oracle(connection):
        # Deliberately independent of the service's SQL builder and predicates.
        cursor = connection.execute('''
            SELECT *,
                CASE WHEN NULLIF(TRIM(REFERENCE), '') IS NULL
                    THEN 'report:' || CAST(REPORT_ID AS TEXT)
                    ELSE 'reference:' || REFERENCE END AS EXPORT_PARTITION_KEY,
                CASE WHEN NULLIF(TRIM(REFERENCE), '') IS NULL
                    THEN 'Report ' || CAST(REPORT_ID AS TEXT) || ' (no reference)'
                    ELSE REFERENCE END AS EXPORT_PARTITION_LABEL
            FROM snapshot_rows ORDER BY rowid
        ''')
        return cursor.fetchall(), [column[0] for column in cursor.description]

    def check_partitions(self, connection, **loader_options):
        from metroliza.exporting import export_query_service as service

        ordered, columns = self.oracle(connection)
        scope = 'SELECT * FROM temp."snapshot_rows"' if loader_options else 'SELECT * FROM snapshot_rows'
        query = service.build_analytical_partition_query(scope)
        keys = list(dict.fromkeys(row[-2] for row in ordered if row[-2] is not None))
        for key in keys + ['reference:absent', 'report:0002', 'report:bad', 'unsupported:x', 'reference:', None]:
            with self.subTest(key=key):
                expected = [row for row in ordered if key is not None and row[-2] == key]
                actual = service.load_export_partition_dataframe(
                    ':memory:', query, key, partition_column='EXPORT_PARTITION_KEY',
                    connection=connection, **loader_options,
                )
                self.assertEqual(list(actual.columns), columns)
                self.assertEqual(list(actual.iter_rows()), expected)
                self.assertEqual(
                    [[type(value) for value in row] for row in actual.iter_rows()],
                    [[type(value) for value in row] for row in expected],
                )
                measurement = service.load_measurement_export_partition_dataframe(
                    ':memory:', query, key, partition_column='EXPORT_PARTITION_KEY',
                    connection=connection, **loader_options,
                )
                self.assertEqual(list(measurement.columns), columns + ['SAMPLE_NUMBER', 'HEADER - AX'])
                self.assertEqual(
                    list(measurement.iter_rows()),
                    [row + (str(index + 1), f'{row[2]} - {row[3]}') for index, row in enumerate(expected)],
                )
        counts = service.fetch_partition_header_counts(
            ':memory:', query, partition_column='EXPORT_PARTITION_KEY', connection=connection,
        )
        self.assertEqual(list(counts), sorted(keys))
        self.assertEqual(counts, {
            key: len({row[2] + ' - ' + row[3] for row in ordered if row[-2] == key})
            for key in sorted(keys)
        })
        self.assertIn('reference:\t', keys)
        self.assertIn('reference:\n', keys)
        self.assertIn('reference: padded ', keys)
        self.assertIn('reference:Report 2 (no reference)', keys)
        self.assertIn('report:2', keys)
        self.assertEqual(sum(row[-2] == 'reference:shared' for row in ordered), 4)
        generic = service.load_export_partition_dataframe(
            ':memory:', query, 'H0', partition_column='HEADER', connection=connection,
            **loader_options,
        )
        self.assertEqual(list(generic.iter_rows()), [row for row in ordered if row[2] == 'H0'])

    def test_ordered_typed_snapshot_partitions_match_independent_oracle(self):
        import sqlite3
        from contextlib import closing

        for affinity in ('TEXT', ''):
            with self.subTest(affinity=affinity), closing(sqlite3.connect(':memory:')) as connection:
                self.populate_snapshot(connection, reference_type=affinity)
                self.check_partitions(connection)

    def test_snapshot_storage_proof_preserves_all_rows_or_uses_general_path(self):
        import sqlite3
        from contextlib import closing
        from metroliza.exporting import export_query_service as service

        for reference_type, report_type in (('TEXT', 'INTEGER'), ('', 'INTEGER'), ('TEXT', 'TEXT')):
            with self.subTest(reference_type=reference_type, report_type=report_type):
                with closing(sqlite3.connect(':memory:')) as connection:
                    self.populate_snapshot(connection, reference_type, report_type)
                    source = service.prepare_snapshot_partition_source(connection, 'snapshot_rows')
                    # BLOB values disqualify TEXT even though its declared affinity is TEXT.
                    self.assertNotIn('REFERENCE', source.indexed_columns)
                    self.assertEqual('REPORT_ID' in source.indexed_columns, report_type == 'INTEGER')
                    self.check_partitions(connection, snapshot_source=source)

    def test_snapshot_indexed_predicates_keep_literal_rows_and_insertion_order(self):
        import sqlite3
        from contextlib import closing
        from unittest import mock
        from metroliza.exporting import export_query_service as service

        with closing(sqlite3.connect(':memory:')) as connection:
            self.populate_snapshot(connection)
            connection.execute("DELETE FROM snapshot_rows WHERE typeof(REFERENCE) = 'blob'")
            source = service.prepare_snapshot_partition_source(connection, 'snapshot_rows')
            self.assertEqual(source.indexed_columns, frozenset({'REFERENCE', 'REPORT_ID'}))
            self.check_partitions(connection, snapshot_source=source)
            actual_reader = service._read_sql_query
            with mock.patch.object(service, '_read_sql_query', wraps=actual_reader) as reader:
                for key, column, expected_parameter in (
                    ('reference:shared', 'REFERENCE', 'shared'), ('report:2', 'REPORT_ID', 2),
                    ('reference:01', 'REFERENCE', '01'), ('reference:\t', 'REFERENCE', '\t'),
                    ("reference:' OR 1=1 --", 'REFERENCE', "' OR 1=1 --"),
                ):
                    service.load_export_partition_dataframe(
                        ':memory:', service.build_analytical_partition_query('SELECT * FROM temp."snapshot_rows"'),
                        key, partition_column='EXPORT_PARTITION_KEY', connection=connection,
                        snapshot_source=source,
                    )
                    args, kwargs = reader.call_args
                    sql = args[1]
                    self.assertIn(f'WHERE {column} = ?', sql)
                    self.assertIn('ORDER BY export_scope."_rowid_"', sql)
                    self.assertEqual(kwargs['params'], (expected_parameter,))
                    plan = connection.execute('EXPLAIN QUERY PLAN ' + sql, kwargs['params']).fetchall()
                    self.assertTrue(any('SEARCH' in row[3] and 'INDEX snapshot_' in row[3] for row in plan), plan)
                    self.assertFalse(any('TEMP B-TREE' in row[3] for row in plan), plan)

    def test_malformed_typed_keys_and_generic_columns_retain_general_query(self):
        import sqlite3
        from contextlib import closing
        from unittest import mock
        from metroliza.exporting import export_query_service as service

        with closing(sqlite3.connect(':memory:')) as connection:
            self.populate_snapshot(connection)
            source = service.prepare_snapshot_partition_source(connection, 'snapshot_rows')
            actual_reader = service._read_sql_query
            with mock.patch.object(service, '_read_sql_query', wraps=actual_reader) as reader:
                for key in ('report:02', 'report:+2', 'report: 2', 'report:٢', 'report:',
                            'report:9223372036854775808', 'report:-0', 'report:2_0',
                            'report:no', 'unsupported:2', 2, None):
                    result = service.load_export_partition_dataframe(
                        ':memory:', service.build_analytical_partition_query('SELECT * FROM temp."snapshot_rows"'),
                        key, partition_column='EXPORT_PARTITION_KEY', connection=connection,
                        snapshot_source=source,
                    )
                    self.assertTrue(result.empty)
                    self.assertIn('WHERE "EXPORT_PARTITION_KEY" = ?', reader.call_args.args[1])
                service.load_export_partition_dataframe(
                    ':memory:', 'SELECT * FROM snapshot_rows', 'H0', partition_column='HEADER',
                    connection=connection, snapshot_source=source,
                )
                self.assertIn('WHERE "HEADER" = ?', reader.call_args.args[1])

    def test_hidden_rowid_alias_collisions_fall_back_without_extra_columns(self):
        import sqlite3
        from contextlib import closing
        from metroliza.exporting import export_query_service as service

        with closing(sqlite3.connect(':memory:')) as connection:
            connection.execute('CREATE TEMP TABLE collision (REFERENCE TEXT, REPORT_ID INT, "_rowid_" TEXT)')
            source = service.prepare_snapshot_partition_source(connection, 'collision')
            self.assertEqual(source.rowid_column, 'rowid')
            connection.execute('ALTER TABLE collision ADD COLUMN rowid TEXT')
            connection.execute('ALTER TABLE collision ADD COLUMN oid TEXT')
            self.assertIsNone(service.prepare_snapshot_partition_source(connection, 'collision'))

    def test_snapshot_source_cannot_bypass_filtered_or_projected_scope(self):
        import sqlite3
        from contextlib import closing
        from unittest import mock
        from metroliza.exporting import export_query_service as service

        with closing(sqlite3.connect(':memory:')) as connection:
            self.populate_snapshot(connection)
            connection.execute("DELETE FROM snapshot_rows WHERE typeof(REFERENCE) = 'blob'")
            source = service.prepare_snapshot_partition_source(connection, 'snapshot_rows')
            actual_reader = service._read_sql_query
            for scope in (
                'SELECT * FROM temp."snapshot_rows" WHERE OCCURRENCE = 0',
                "SELECT HEADER, AX, REPORT_ID, REFERENCE, CAST(MEAS AS TEXT) AS MEAS, "
                "'stored' AS SAMPLE_NUMBER FROM temp.\"snapshot_rows\" WHERE OCCURRENCE = 0",
            ):
                query = service.build_analytical_partition_query(scope)
                cursor = connection.execute(query)
                expected = [row for row in cursor.fetchall() if row[-2] == 'reference:shared']
                columns = [column[0] for column in cursor.description]
                self.assertEqual(len(expected), 2)
                with mock.patch.object(service, '_read_sql_query', wraps=actual_reader) as reader:
                    result = service.load_export_partition_dataframe(
                        ':memory:', query, 'reference:shared', partition_column='EXPORT_PARTITION_KEY',
                        connection=connection, snapshot_source=source,
                    )
                    self.assertEqual(list(result.iter_rows()), expected)
                    self.assertEqual(list(result.columns), columns)
                    self.assertIn('WHERE "EXPORT_PARTITION_KEY" = ?', reader.call_args.args[1])
                    self.assertNotIn('ORDER BY export_scope.', reader.call_args.args[1])
                measurement = service.load_measurement_export_partition_dataframe(
                    ':memory:', query, 'reference:shared', partition_column='EXPORT_PARTITION_KEY',
                    connection=connection, snapshot_source=source,
                )
                if 'SAMPLE_NUMBER' in columns:
                    self.assertEqual(measurement['SAMPLE_NUMBER'].tolist(), ['stored', 'stored'])
                    self.assertEqual(measurement['MEAS'].tolist(), ['0.0', '0.0'])

    def test_snapshot_source_is_bound_to_actual_connection_identity(self):
        import sqlite3
        from contextlib import closing
        from unittest import mock
        from metroliza.exporting import export_query_service as service

        with closing(sqlite3.connect(':memory:')) as owner, closing(sqlite3.connect(':memory:')) as foreign:
            for connection in (owner, foreign):
                self.populate_snapshot(connection)
                connection.execute("DELETE FROM snapshot_rows WHERE typeof(REFERENCE) = 'blob'")
            foreign.execute("UPDATE snapshot_rows SET MEAS = 50.0 WHERE REFERENCE = 'shared'")
            source = service.prepare_snapshot_partition_source(owner, 'snapshot_rows')
            expected, columns = self.oracle(foreign)
            expected = [row for row in expected if row[-2] == 'reference:shared']
            with mock.patch.object(service, '_read_sql_query', wraps=service._read_sql_query) as reader:
                result = service.load_export_partition_dataframe(
                    ':memory:', service.build_analytical_partition_query('SELECT * FROM temp."snapshot_rows"'),
                    'reference:shared', partition_column='EXPORT_PARTITION_KEY',
                    connection=foreign, snapshot_source=source,
                )
                self.assertEqual(list(result.columns), columns)
                self.assertEqual(list(result.iter_rows()), expected)
                self.assertEqual(result['MEAS'].tolist(), [50.0] * 4)
                self.assertIn('WHERE "EXPORT_PARTITION_KEY" = ?', reader.call_args.args[1])
                self.assertNotIn('ORDER BY export_scope.', reader.call_args.args[1])

    def test_real_report_storage_is_not_admitted_as_integer_identity(self):
        import sqlite3
        from contextlib import closing
        from unittest import mock
        from metroliza.exporting import export_query_service as service

        with closing(sqlite3.connect(':memory:')) as connection:
            self.populate_snapshot(connection)
            connection.execute("UPDATE snapshot_rows SET REPORT_ID = 2.5 WHERE REFERENCE IS NULL")
            source = service.prepare_snapshot_partition_source(connection, 'snapshot_rows')
            self.assertNotIn('REPORT_ID', source.indexed_columns)
            ordered, columns = self.oracle(connection)
            expected = [row for row in ordered if row[-2] == 'report:2.5']
            self.assertGreater(len(expected), 0)
            with mock.patch.object(service, '_read_sql_query', wraps=service._read_sql_query) as reader:
                result = service.load_export_partition_dataframe(
                    ':memory:', service.build_analytical_partition_query('SELECT * FROM temp."snapshot_rows"'),
                    'report:2.5', partition_column='EXPORT_PARTITION_KEY',
                    connection=connection, snapshot_source=source,
                )
                self.assertEqual(list(result.columns), columns)
                self.assertEqual(list(result.iter_rows()), expected)
                self.assertIn('WHERE "EXPORT_PARTITION_KEY" = ?', reader.call_args.args[1])


class TestPartitionStringSubclassCompatibility(unittest.TestCase):
    def check_service(self, service, kind, *, snapshot, callbacks):
        import sqlite3
        from contextlib import closing
        from unittest import mock

        class SQLiteString(str):
            def partition(self, *_args):
                callbacks.append('partition')
                raise RuntimeError('unexpected Python partition callback')

            def __eq__(self, _other):
                callbacks.append('equality')
                raise RuntimeError('unexpected Python equality callback')

            def __ne__(self, _other):
                callbacks.append('inequality')
                raise RuntimeError('unexpected Python inequality callback')

        class Identifier:
            def __str__(self):
                return 'EXPORT_PARTITION_KEY'

            def __eq__(self, _other):
                callbacks.append('identifier equality')
                raise RuntimeError('unexpected identifier equality callback')

        with closing(sqlite3.connect(':memory:')) as connection:
            connection.execute('CREATE TEMP TABLE string_rows (REFERENCE TEXT, REPORT_ID INTEGER)')
            connection.executemany('INSERT INTO string_rows VALUES (?, ?)', [('A', 1), ('A', 2), ('B', 3)])
            connection.execute('CREATE INDEX string_ref ON string_rows(REFERENCE)')
            scope = 'SELECT * FROM temp."string_rows"'
            if kind == 'narrowed_scope':
                scope += ' WHERE REPORT_ID = 1'
            query = service.build_analytical_partition_query(scope)
            value = SQLiteString('reference:A') if kind == 'partition_value' else 'reference:A'
            if kind in ('canonical_scope', 'narrowed_scope'):
                query = SQLiteString(query)
            column = 'EXPORT_PARTITION_KEY'
            if kind == 'partition_column':
                column = SQLiteString(column)
            elif kind == 'identifier_object':
                column = Identifier()
            options = {'snapshot_source': service.prepare_snapshot_partition_source(connection, 'string_rows')} if snapshot else {}
            with mock.patch.object(service, '_read_sql_query', wraps=service._read_sql_query) as reader:
                table = service.load_export_partition_dataframe(
                    ':memory:', query, value, partition_column=column,
                    connection=connection, **options,
                )
                self.assertIn('WHERE "EXPORT_PARTITION_KEY" = ?', reader.call_args.args[1])
                self.assertNotIn('ORDER BY export_scope.', reader.call_args.args[1])
            expected = [('A', 1, 'reference:A', 'A')]
            if kind != 'narrowed_scope':
                expected.append(('A', 2, 'reference:A', 'A'))
            self.assertEqual(list(table.columns), ['REFERENCE', 'REPORT_ID', 'EXPORT_PARTITION_KEY', 'EXPORT_PARTITION_LABEL'])
            self.assertEqual(list(table.iter_rows()), expected)
            self.assertEqual(callbacks, [])
            return {'rows': list(table.iter_rows()), 'columns': list(table.columns), 'callbacks': callbacks}

    def test_subclasses_preserve_sqlite_parameter_and_scope_behavior(self):
        from metroliza.exporting import export_query_service as service

        for kind in ('partition_value', 'canonical_scope', 'narrowed_scope', 'partition_column', 'identifier_object'):
            with self.subTest(kind=kind):
                self.check_service(service, kind, snapshot=True, callbacks=[])


if __name__ == '__main__':
    unittest.main()
