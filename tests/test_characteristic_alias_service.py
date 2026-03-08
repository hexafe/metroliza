import tempfile
import unittest

from modules.characteristic_alias_service import (
    delete_characteristic_alias,
    ensure_characteristic_alias_schema,
    fetch_all_characteristic_aliases,
    fetch_characteristic_aliases,
    normalize_alias_scope,
    resolve_characteristic_alias,
    upsert_characteristic_alias,
)


class TestCharacteristicAliasService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = f"{self.temp_dir.name}/aliases.sqlite"
        ensure_characteristic_alias_schema(self.db_path)

    def test_normalize_alias_scope_validates_and_normalizes(self):
        self.assertEqual(normalize_alias_scope('global', 'ignored'), ('global', None))
        self.assertEqual(normalize_alias_scope('reference', 'REF-1'), ('reference', 'REF-1'))

        with self.assertRaisesRegex(ValueError, 'scope_type must be one of'):
            normalize_alias_scope('local', 'x')

        with self.assertRaisesRegex(ValueError, 'scope_value is required'):
            normalize_alias_scope('reference', None)

    def test_upsert_validates_required_fields(self):
        with self.assertRaisesRegex(ValueError, 'alias_name is required'):
            upsert_characteristic_alias(
                self.db_path,
                alias_name='  ',
                canonical_name='CANON',
                scope_type='global',
            )

        with self.assertRaisesRegex(ValueError, 'canonical_name is required'):
            upsert_characteristic_alias(
                self.db_path,
                alias_name='AX-1',
                canonical_name=' ',
                scope_type='global',
            )

    def test_fetch_and_resolve_priority_reference_then_global_then_fallback(self):
        upsert_characteristic_alias(
            self.db_path,
            alias_name='M1 - X',
            canonical_name='GLOBAL-CANON',
            scope_type='global',
            scope_value='SHOULD-BE-CLEARED',
        )
        upsert_characteristic_alias(
            self.db_path,
            alias_name='M1 - X',
            canonical_name='REF-CANON',
            scope_type='reference',
            scope_value='REF-001',
        )

        fetched = fetch_characteristic_aliases(self.db_path, 'M1 - X', reference='REF-001')
        self.assertEqual([row['canonical_name'] for row in fetched], ['REF-CANON', 'GLOBAL-CANON'])
        self.assertEqual(fetched[1]['scope_value'], None)

        self.assertEqual(
            resolve_characteristic_alias('M1 - X', 'REF-001', self.db_path),
            'REF-CANON',
        )
        self.assertEqual(
            resolve_characteristic_alias('M1 - X', 'REF-002', self.db_path),
            'GLOBAL-CANON',
        )
        self.assertEqual(
            resolve_characteristic_alias('UNKNOWN-METRIC', 'REF-001', self.db_path),
            'UNKNOWN-METRIC',
        )


    def test_resolve_returns_original_when_alias_table_is_missing(self):
        db_path = f"{self.temp_dir.name}/no_alias_schema.sqlite"
        self.assertEqual(
            resolve_characteristic_alias('M1 - X', 'REF-001', db_path),
            'M1 - X',
        )

    def test_upsert_updates_existing_scope_row_and_delete_removes_it(self):
        upsert_characteristic_alias(
            self.db_path,
            alias_name='DIA - X',
            canonical_name='DIA-CANON-1',
            scope_type='reference',
            scope_value='REF-101',
        )
        upsert_characteristic_alias(
            self.db_path,
            alias_name='DIA - X',
            canonical_name='DIA-CANON-2',
            scope_type='reference',
            scope_value='REF-101',
        )

        fetched = fetch_characteristic_aliases(self.db_path, 'DIA - X', reference='REF-101')
        self.assertEqual([row['canonical_name'] for row in fetched], ['DIA-CANON-2'])

        deleted_count = delete_characteristic_alias(
            self.db_path,
            alias_name='DIA - X',
            scope_type='reference',
            scope_value='REF-101',
        )
        self.assertEqual(deleted_count, 1)
        self.assertEqual(
            resolve_characteristic_alias('DIA - X', 'REF-101', self.db_path),
            'DIA - X',
        )

    def test_fetch_all_characteristic_aliases_returns_deterministic_rows(self):
        upsert_characteristic_alias(
            self.db_path,
            alias_name='B-ALIAS',
            canonical_name='CANON-B',
            scope_type='global',
        )
        upsert_characteristic_alias(
            self.db_path,
            alias_name='A-ALIAS',
            canonical_name='CANON-A1',
            scope_type='reference',
            scope_value='REF-2',
        )
        upsert_characteristic_alias(
            self.db_path,
            alias_name='A-ALIAS',
            canonical_name='CANON-A0',
            scope_type='global',
        )

        fetched = fetch_all_characteristic_aliases(self.db_path)
        self.assertEqual(
            [
                (row['alias_name'], row['canonical_name'], row['scope_type'], row['scope_value'])
                for row in fetched
            ],
            [
                ('A-ALIAS', 'CANON-A0', 'global', None),
                ('A-ALIAS', 'CANON-A1', 'reference', 'REF-2'),
                ('B-ALIAS', 'CANON-B', 'global', None),
            ],
        )


if __name__ == '__main__':
    unittest.main()
