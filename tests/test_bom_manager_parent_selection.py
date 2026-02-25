import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from modules.bom_manager import BOMManager


class TestBOMManagerParentSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / 'test_bom.db'
        self.manager = BOMManager(str(self.db_path))

    def tearDown(self):
        self.manager.conn.close()
        self.manager.close()
        self.temp_dir.cleanup()

    def test_modify_bom_entry_sets_parent_by_parent_id(self):
        parent_1_id = self.manager._execute_write(
            'INSERT INTO bom (product_reference, description, part_reference, part_description, parent_id) VALUES (?, ?, ?, ?, ?)',
            ('Parent Product 1', 'desc', 'PARENT-PART-1', 'part desc', None),
        ).lastrowid
        parent_2_id = self.manager._execute_write(
            'INSERT INTO bom (product_reference, description, part_reference, part_description, parent_id) VALUES (?, ?, ?, ?, ?)',
            ('Parent Product 2', 'desc', 'PARENT-PART-2', 'part desc', None),
        ).lastrowid
        child_id = self.manager._execute_write(
            'INSERT INTO bom (product_reference, description, part_reference, part_description, parent_id) VALUES (?, ?, ?, ?, ?)',
            ('Child Product', 'child desc', 'CHILD-PART', 'child part desc', parent_2_id),
        ).lastrowid

        self.manager.refresh_table()

        child_row = None
        for row in range(self.manager.bom_table.rowCount()):
            row_data = self.manager.bom_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if row_data and row_data[0] == child_id:
                child_row = row
                break

        self.assertIsNotNone(child_row)

        self.manager.modify_bom_entry(child_row, 0)

        self.assertEqual(
            self.manager.parent_combo_box.currentData(Qt.ItemDataRole.UserRole),
            parent_2_id,
        )
        self.assertEqual(
            self.manager.parent_combo_box.currentIndex(),
            self.manager.find_parent_index_by_id(parent_2_id),
        )
        self.assertNotEqual(parent_1_id, parent_2_id)


if __name__ == '__main__':
    unittest.main()
