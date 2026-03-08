import tempfile
import unittest

from modules.characteristic_alias_service import ensure_characteristic_alias_schema, upsert_characteristic_alias

try:
    from PyQt6.QtWidgets import QApplication
    from modules.characteristic_mapping_dialog import CharacteristicMappingDialog
except ImportError as exc:  # pragma: no cover - environment-dependent import
    QApplication = None
    CharacteristicMappingDialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


class TestCharacteristicMappingDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PYQT_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f'PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}')
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_constructs_and_loads_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='DIAMETER - X',
                scope_type='reference',
                scope_value='REF-1',
            )

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)

            self.assertEqual(dialog.windowTitle(), 'Characteristic Mapping')
            self.assertEqual(dialog.alias_table.rowCount(), 1)
            self.assertEqual(dialog.alias_table.item(0, 0).text(), 'DIA - X')
            self.assertEqual(dialog.alias_table.item(0, 1).text(), 'DIAMETER - X')
            self.assertEqual(dialog.alias_table.item(0, 2).text(), 'reference')
            self.assertEqual(dialog.alias_table.item(0, 3).text(), 'REF-1')
            dialog.close()


if __name__ == '__main__':
    unittest.main()
