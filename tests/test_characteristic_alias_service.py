import csv
import tempfile
import unittest
from sqlite3 import connect

from modules.characteristic_alias_service import (
    CharacteristicAliasCsvSchemaError,
    CharacteristicAliasImportValidationError,
    delete_characteristic_alias,
    ensure_characteristic_alias_schema,
    export_characteristic_aliases_csv,
    fetch_all_characteristic_aliases,
    fetch_characteristic_aliases,
    import_characteristic_aliases_csv,
    normalize_alias_scope,
    resolve_characteristic_alias,
    upsert_characteristic_alias,
    upsert_characteristic_aliases_bulk,
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

    def test_ensure_schema_is_idempotent_and_preserves_existing_rows(self):
        ensure_characteristic_alias_schema(self.db_path)
        ensure_characteristic_alias_schema(self.db_path)

        upsert_characteristic_alias(
            self.db_path,
            alias_name='AX-1',
            canonical_name='CANON-1',
            scope_type='global',
        )

        ensure_characteristic_alias_schema(self.db_path)
        fetched = fetch_all_characteristic_aliases(self.db_path)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0]['alias_name'], 'AX-1')

        with connect(self.db_path) as connection:
            index_rows = connection.execute("PRAGMA index_list('CHARACTERISTIC_ALIASES')").fetchall()
        self.assertTrue(any('characteristic_alias_scope_lookup' in row[1] for row in index_rows))

    def test_ensure_schema_is_migration_safe_on_existing_database(self):
        legacy_db_path = f"{self.temp_dir.name}/legacy.sqlite"
        with connect(legacy_db_path) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS LEGACY_TABLE(id INTEGER PRIMARY KEY, value TEXT)')
            connection.execute("INSERT INTO LEGACY_TABLE(value) VALUES ('legacy-row')")
            connection.commit()

        ensure_characteristic_alias_schema(legacy_db_path)

        with connect(legacy_db_path) as connection:
            legacy_rows = connection.execute('SELECT value FROM LEGACY_TABLE').fetchall()
            alias_table_row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='CHARACTERISTIC_ALIASES'"
            ).fetchone()

        self.assertEqual(legacy_rows, [('legacy-row',)])
        self.assertEqual(alias_table_row, ('CHARACTERISTIC_ALIASES',))

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

    def test_validation_reference_scope_requires_scope_value_global_does_not(self):
        with self.assertRaisesRegex(ValueError, 'scope_value is required for reference scope'):
            upsert_characteristic_alias(
                self.db_path,
                alias_name='AX-2',
                canonical_name='CANON-AX-2',
                scope_type='reference',
                scope_value='  ',
            )

        upsert_characteristic_alias(
            self.db_path,
            alias_name='AX-3',
            canonical_name='CANON-AX-3',
            scope_type='global',
            scope_value=None,
        )
        fetched = fetch_characteristic_aliases(self.db_path, 'AX-3', reference='REF-999')
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0]['scope_type'], 'global')
        self.assertIsNone(fetched[0]['scope_value'])

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

        self.assertEqual(resolve_characteristic_alias('M1 - X', 'REF-001', self.db_path), 'REF-CANON')
        self.assertEqual(resolve_characteristic_alias('M1 - X', 'REF-002', self.db_path), 'GLOBAL-CANON')
        self.assertEqual(resolve_characteristic_alias('UNKNOWN-METRIC', 'REF-001', self.db_path), 'UNKNOWN-METRIC')

    def test_resolver_uses_global_when_reference_scoped_entry_is_missing(self):
        upsert_characteristic_alias(
            self.db_path,
            alias_name='M2 - X',
            canonical_name='GLOBAL-M2',
            scope_type='global',
        )

        self.assertEqual(resolve_characteristic_alias('M2 - X', 'REF-NOT-MAPPED', self.db_path), 'GLOBAL-M2')

    def test_resolver_falls_back_to_original_metric_when_no_mapping_exists(self):
        self.assertEqual(resolve_characteristic_alias('NO-MAPPING', 'REF-100', self.db_path), 'NO-MAPPING')

    def test_resolve_returns_original_when_alias_table_is_missing(self):
        db_path = f"{self.temp_dir.name}/no_alias_schema.sqlite"
        self.assertEqual(resolve_characteristic_alias('M1 - X', 'REF-001', db_path), 'M1 - X')

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
        self.assertEqual(resolve_characteristic_alias('DIA - X', 'REF-101', self.db_path), 'DIA - X')

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
            [(row['alias_name'], row['canonical_name'], row['scope_type'], row['scope_value']) for row in fetched],
            [
                ('A-ALIAS', 'CANON-A0', 'global', None),
                ('A-ALIAS', 'CANON-A1', 'reference', 'REF-2'),
                ('B-ALIAS', 'CANON-B', 'global', None),
            ],
        )

    def test_bulk_upsert_is_atomic_when_validation_fails(self):
        upsert_characteristic_alias(
            self.db_path,
            alias_name='EXISTING',
            canonical_name='CANON-EXISTING',
            scope_type='global',
        )

        with self.assertRaisesRegex(ValueError, 'alias_name is required at row 2'):
            upsert_characteristic_aliases_bulk(
                self.db_path,
                [
                    {'alias_name': 'A1', 'canonical_name': 'C1', 'scope_type': 'global', 'scope_value': None},
                    {'alias_name': ' ', 'canonical_name': 'C2', 'scope_type': 'global', 'scope_value': None},
                ],
            )

        fetched = fetch_all_characteristic_aliases(self.db_path)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0]['alias_name'], 'EXISTING')

    def test_export_and_import_csv_round_trip(self):
        upsert_characteristic_alias(
            self.db_path,
            alias_name='DIA - X',
            canonical_name='DIAMETER - X',
            scope_type='global',
        )
        upsert_characteristic_alias(
            self.db_path,
            alias_name='DIA - X',
            canonical_name='DIAMETER - X REF',
            scope_type='reference',
            scope_value='REF-1',
        )

        csv_path = f"{self.temp_dir.name}/aliases.csv"
        exported_count = export_characteristic_aliases_csv(self.db_path, csv_path)
        self.assertEqual(exported_count, 2)

        with open(csv_path, newline='', encoding='utf-8') as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0].keys()), {'alias_name', 'canonical_name', 'scope_type', 'scope_value'})

        imported_db_path = f"{self.temp_dir.name}/aliases_imported.sqlite"
        ensure_characteristic_alias_schema(imported_db_path)
        imported_count = import_characteristic_aliases_csv(imported_db_path, csv_path)
        self.assertEqual(imported_count, 2)

        imported_rows = fetch_all_characteristic_aliases(imported_db_path)
        self.assertEqual(
            [(row['alias_name'], row['canonical_name'], row['scope_type'], row['scope_value']) for row in imported_rows],
            [
                ('DIA - X', 'DIAMETER - X', 'global', None),
                ('DIA - X', 'DIAMETER - X REF', 'reference', 'REF-1'),
            ],
        )

    def test_import_csv_handles_utf8_bom_header(self):
        csv_path = f"{self.temp_dir.name}/bom_aliases.csv"
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=['alias_name', 'canonical_name', 'scope_type', 'scope_value'])
            writer.writeheader()
            writer.writerow(
                {
                    'alias_name': 'AX-BOM',
                    'canonical_name': 'CANON-BOM',
                    'scope_type': 'global',
                    'scope_value': '',
                }
            )

        imported_count = import_characteristic_aliases_csv(self.db_path, csv_path)
        self.assertEqual(imported_count, 1)
        self.assertEqual(resolve_characteristic_alias('AX-BOM', 'REF', self.db_path), 'CANON-BOM')


    def test_import_csv_reports_structured_row_validation_errors(self):
        csv_path = f"{self.temp_dir.name}/invalid_aliases.csv"
        with open(csv_path, 'w', newline='', encoding='utf-8') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=['alias_name', 'canonical_name', 'scope_type', 'scope_value'])
            writer.writeheader()
            writer.writerow({'alias_name': '', 'canonical_name': 'CAN-1', 'scope_type': 'global', 'scope_value': ''})
            writer.writerow({'alias_name': 'AX-2', 'canonical_name': '', 'scope_type': 'global', 'scope_value': ''})
            writer.writerow({'alias_name': 'AX-3', 'canonical_name': 'CAN-3', 'scope_type': 'local', 'scope_value': ''})
            writer.writerow({'alias_name': 'AX-3', 'canonical_name': 'CAN-3', 'scope_type': 'reference', 'scope_value': ''})
            writer.writerow({'alias_name': 'AX-4', 'canonical_name': 'CAN-4A', 'scope_type': 'global', 'scope_value': ''})
            writer.writerow({'alias_name': 'AX-4', 'canonical_name': 'CAN-4B', 'scope_type': 'global', 'scope_value': ''})

        with self.assertRaises(CharacteristicAliasImportValidationError) as ctx:
            import_characteristic_aliases_csv(self.db_path, csv_path)

        error = ctx.exception
        self.assertEqual(error.total_rows_processed, 6)
        self.assertEqual(len(error.row_errors), 5)
        self.assertIn('alias_name is required at row 2', error.row_errors[0])
        self.assertIn('canonical_name is required at row 3', error.row_errors[1])
        self.assertIn('scope_type must be one of: global, reference at row 4', error.row_errors[2])
        self.assertIn('scope_value is required for reference scope at row 5', error.row_errors[3])
        self.assertIn('duplicate alias/scope key for "AX-4" (global) at row 7; first seen at row 6', error.row_errors[4])

        self.assertEqual(len(error.row_error_details), 5)
        self.assertEqual(error.row_error_details[0]['code'], 'missing_alias_name')
        self.assertEqual(error.row_error_details[0]['category'], 'missing_required_field')
        self.assertEqual(error.row_error_details[1]['code'], 'missing_canonical_name')
        self.assertEqual(error.row_error_details[2]['code'], 'invalid_scope_type')
        self.assertEqual(error.row_error_details[3]['code'], 'reference_scope_requires_scope_value')
        self.assertEqual(error.row_error_details[4]['code'], 'duplicate_key_collision')
        self.assertEqual(error.row_error_details[4]['field'], 'alias_name')
        self.assertEqual(error.row_error_details[4]['category'], 'duplicate_collision')
        self.assertEqual(error.row_error_details[4]['row_number'], 7)
        self.assertIn('Remove or merge duplicate alias rows', error.row_error_details[4]['remediation_hint'])

    def test_import_csv_requires_expected_headers(self):
        csv_path = f"{self.temp_dir.name}/bad_aliases.csv"
        with open(csv_path, 'w', newline='', encoding='utf-8') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=['alias_name', 'canonical_name'])
            writer.writeheader()
            writer.writerow({'alias_name': 'A1', 'canonical_name': 'C1'})

        with self.assertRaises(CharacteristicAliasCsvSchemaError) as ctx:
            import_characteristic_aliases_csv(self.db_path, csv_path)

        error = ctx.exception
        self.assertEqual(error.required_columns, ('alias_name', 'canonical_name', 'scope_type', 'scope_value'))
        self.assertEqual(error.detected_columns, ('alias_name', 'canonical_name'))
        self.assertEqual(error.expected_header_example, 'alias_name,canonical_name,scope_type,scope_value')
        self.assertIn('exactly match this order', error.correction_guidance)


if __name__ == '__main__':
    unittest.main()
