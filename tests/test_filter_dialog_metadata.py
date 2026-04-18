import importlib
import sys
import types
import unittest
from unittest.mock import patch


class _FakeSignal:
    def connect(self, *_args, **_kwargs):
        return None


class _FakeQt:
    ItemDataRole = types.SimpleNamespace(UserRole=0)


class _FakeDialog:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get("parent")

    def parent(self):
        return self._parent


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get("parent")


class _FakeItem:
    def __init__(self, text):
        self._text = text
        self._selected = False

    def text(self):
        return self._text

    def setSelected(self, selected):
        self._selected = bool(selected)

    def isSelected(self):
        return self._selected


class _FakeListWidget:
    def __init__(self, items=None):
        self._items = list(items or [])
        self.cleared = False

    def addItem(self, item):
        if isinstance(item, str):
            item = _FakeItem(item)
        self._items.append(item)

    def clear(self):
        self.cleared = True
        self._items = []

    def selectedItems(self):
        return [item for item in self._items if item.isSelected()]

    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]


class _FakeCalendar:
    def __init__(self, value):
        self._value = value

    def date(self):
        return self

    def toString(self, *_args, **_kwargs):
        return self._value


class _FakeButton:
    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _FakeParent:
    def __init__(self):
        self.filter_query = None
        self.applied = False

    def set_filter_query(self, query):
        self.filter_query = query

    def set_filter_applied(self):
        self.applied = True


def _install_qt_stubs():
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QDate = type("QDate", (), {})
    qtcore.Qt = _FakeQt

    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtwidgets.QDialog = _FakeDialog
    qtwidgets.QDateEdit = _FakeWidget
    qtwidgets.QGridLayout = _FakeWidget
    qtwidgets.QGroupBox = _FakeWidget
    qtwidgets.QHBoxLayout = _FakeWidget
    qtwidgets.QLabel = _FakeWidget
    qtwidgets.QLineEdit = _FakeWidget
    qtwidgets.QListWidget = _FakeListWidget
    qtwidgets.QListWidgetItem = _FakeItem
    qtwidgets.QMessageBox = _FakeWidget
    qtwidgets.QPushButton = _FakeWidget
    qtwidgets.QScrollArea = _FakeWidget
    qtwidgets.QTabWidget = _FakeWidget
    qtwidgets.QVBoxLayout = _FakeWidget
    qtwidgets.QWidget = _FakeWidget
    qtwidgets.QAbstractItemView = types.SimpleNamespace(SelectionMode=types.SimpleNamespace(MultiSelection=2))

    qtgui = types.ModuleType("PyQt6.QtGui")

    pyqt6 = types.ModuleType("PyQt6")
    pyqt6.QtWidgets = qtwidgets

    return pyqt6, qtcore, qtwidgets, qtgui


class TestFilterDialogMetadata(unittest.TestCase):
    def _load_module(self):
        sys.modules.pop("modules.filter_dialog", None)
        return importlib.import_module("modules.filter_dialog")

    def test_populate_list_widgets_includes_metadata_columns(self):
        pyqt6, qtcore, qtwidgets, qtgui = _install_qt_stubs()
        fake_db = types.ModuleType("modules.db")
        fake_db.execute_with_retry = lambda *_args, **_kwargs: []

        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "PyQt6.QtGui": qtgui,
                "modules.db": fake_db,
            },
            clear=False,
        ):
            module = self._load_module()
            dialog = module.FilterDialog.__new__(module.FilterDialog)
            dialog.db_file = "memory.db"
            dialog.filter_query = "SELECT * FROM vw_measurement_export WHERE 1=1"
            dialog.ax_list = object()
            dialog.header_list = object()
            dialog.all_headers_list = object()
            dialog.reference_list = object()
            dialog.part_name_list = object()
            dialog.revision_list = object()
            dialog.template_variant_list = object()
            dialog.sample_number_list = object()
            dialog.operator_name_list = object()
            dialog.sample_number_kind_list = object()
            dialog.status_code_list = object()
            dialog.filename_list = object()
            dialog.parser_id_list = object()
            dialog.template_family_list = object()

            calls = []

            def fake_populate(list_widget, column_name, *, source_view="vw_measurement_export", filter_query=None):
                calls.append((list_widget, column_name, source_view, filter_query))

            dialog._populate_distinct_values = fake_populate
            dialog.populate_list_widgets()

            self.assertIn((dialog.operator_name_list, "OPERATOR_NAME", "vw_report_overview", dialog.filter_query), calls)
            self.assertIn((dialog.sample_number_kind_list, "SAMPLE_NUMBER_KIND", "vw_report_overview", dialog.filter_query), calls)
            self.assertIn((dialog.status_code_list, "STATUS_CODE", "vw_measurement_export", dialog.filter_query), calls)
            self.assertIn((dialog.filename_list, "FILENAME", "vw_report_overview", dialog.filter_query), calls)
            self.assertIn((dialog.parser_id_list, "PARSER_ID", "vw_report_overview", dialog.filter_query), calls)
            self.assertIn((dialog.template_family_list, "TEMPLATE_FAMILY", "vw_report_overview", dialog.filter_query), calls)

    def test_apply_filters_appends_metadata_clauses(self):
        pyqt6, qtcore, qtwidgets, qtgui = _install_qt_stubs()
        fake_db = types.ModuleType("modules.db")
        fake_db.execute_with_retry = lambda *_args, **_kwargs: []

        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "PyQt6.QtGui": qtgui,
                "modules.db": fake_db,
            },
            clear=False,
        ):
            module = self._load_module()
            dialog = module.FilterDialog.__new__(module.FilterDialog)
            dialog.ax_list = _FakeListWidget([_FakeItem("SELECT ALL")])
            dialog.header_list = _FakeListWidget([_FakeItem("SELECT ALL")])
            dialog.reference_list = _FakeListWidget([_FakeItem("SELECT ALL")])
            dialog.part_name_list = _FakeListWidget([_FakeItem("SELECT ALL")])
            dialog.revision_list = _FakeListWidget([_FakeItem("SELECT ALL")])
            dialog.template_variant_list = _FakeListWidget([_FakeItem("SELECT ALL")])
            dialog.sample_number_list = _FakeListWidget([_FakeItem("SELECT ALL")])

            operator_a = _FakeItem("Jane Doe")
            operator_a.setSelected(True)
            dialog.operator_name_list = _FakeListWidget([_FakeItem("SELECT ALL"), operator_a])

            sample_kind = _FakeItem("stats_count")
            sample_kind.setSelected(True)
            dialog.sample_number_kind_list = _FakeListWidget([_FakeItem("SELECT ALL"), sample_kind])

            status_all = _FakeItem("SELECT ALL")
            status_all.setSelected(True)
            dialog.status_code_list = _FakeListWidget([status_all])

            filename = _FakeItem("part.csv")
            filename.setSelected(True)
            dialog.filename_list = _FakeListWidget([_FakeItem("SELECT ALL"), filename])

            parser_id = _FakeItem("cmm")
            parser_id.setSelected(True)
            dialog.parser_id_list = _FakeListWidget([_FakeItem("SELECT ALL"), parser_id])

            template_family = _FakeItem("cmm_pdf_header_box")
            template_family.setSelected(True)
            dialog.template_family_list = _FakeListWidget([_FakeItem("SELECT ALL"), template_family])

            dialog.has_nok_button = _FakeButton(checked=True)
            dialog.date_from_calendar = _FakeCalendar("2024-01-01")
            dialog.date_to_calendar = _FakeCalendar("2024-12-31")

            parent = _FakeParent()
            dialog.parent = lambda: parent
            dialog.hide = lambda: None
            dialog.log_and_exit = lambda *_args, **_kwargs: None

            build_calls = {}

            real_build_measurement_filter_query = module.build_measurement_filter_query

            def fake_build_measurement_filter_query(**kwargs):
                build_calls.update(kwargs)
                return real_build_measurement_filter_query(**kwargs)

            with patch.object(module, "build_measurement_filter_query", side_effect=fake_build_measurement_filter_query):
                dialog.apply_filters()

            self.assertTrue(parent.applied)
            self.assertTrue(build_calls["has_nok_only"])
            self.assertIn("operator_name IN ('Jane Doe')", parent.filter_query)
            self.assertIn("sample_number_kind IN ('stats_count')", parent.filter_query)
            self.assertIn("file_name IN ('part.csv')", parent.filter_query)
            self.assertIn("parser_id IN ('cmm')", parent.filter_query)
            self.assertIn("template_family IN ('cmm_pdf_header_box')", parent.filter_query)
            self.assertIn("has_nok = 1", parent.filter_query)
            self.assertNotIn("status_code IN", parent.filter_query)

    def test_filter_sections_group_metadata_without_single_horizontal_row(self):
        pyqt6, qtcore, qtwidgets, qtgui = _install_qt_stubs()
        fake_db = types.ModuleType("modules.db")
        fake_db.execute_with_retry = lambda *_args, **_kwargs: []

        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "PyQt6.QtGui": qtgui,
                "modules.db": fake_db,
            },
            clear=False,
        ):
            module = self._load_module()
            sections = module.FilterDialog._build_filter_sections()

        section_names = [name for name, _fields in sections]
        flattened_fields = [field for _name, fields in sections for field in fields]

        self.assertEqual(section_names, ["Measurement", "Report metadata", "Source"])
        self.assertIn(("operator_name_label", "operator_name_search_input", "operator_name_list"), flattened_fields)
        self.assertIn(("template_family_label", "template_family_search_input", "template_family_list"), flattened_fields)
        self.assertIn(("selected_headers_label", None, "selected_headers_list"), flattened_fields)

    def test_ensure_schema_ready_refreshes_views_for_selected_database(self):
        pyqt6, qtcore, qtwidgets, qtgui = _install_qt_stubs()
        fake_db = types.ModuleType("modules.db")
        fake_db.execute_with_retry = lambda *_args, **_kwargs: []

        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "PyQt6.QtGui": qtgui,
                "modules.db": fake_db,
            },
            clear=False,
        ):
            module = self._load_module()
            dialog = module.FilterDialog.__new__(module.FilterDialog)
            dialog.db_file = "reports.db"

            with patch.object(module, "ensure_report_schema") as ensure_report_schema:
                dialog._ensure_schema_ready()

            ensure_report_schema.assert_called_once_with("reports.db")

            dialog.db_file = ""
            with patch.object(module, "ensure_report_schema") as ensure_report_schema:
                dialog._ensure_schema_ready()

            ensure_report_schema.assert_not_called()

    def test_reference_selection_change_clears_selected_headers(self):
        pyqt6, qtcore, qtwidgets, qtgui = _install_qt_stubs()
        fake_db = types.ModuleType("modules.db")
        fake_db.execute_with_retry = lambda *_args, **_kwargs: []

        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "PyQt6.QtGui": qtgui,
                "modules.db": fake_db,
            },
            clear=False,
        ):
            module = self._load_module()
            dialog = module.FilterDialog.__new__(module.FilterDialog)
            ref = _FakeItem("REF1")
            ref.setSelected(True)
            dialog.reference_list = _FakeListWidget([_FakeItem("SELECT ALL"), ref])
            dialog.header_list = _FakeListWidget([_FakeItem("SELECT ALL"), _FakeItem("OLD")])
            dialog.all_headers_list = _FakeListWidget([_FakeItem("SELECT ALL"), _FakeItem("ALL")])
            dialog.selected_headers_list = _FakeListWidget([_FakeItem("STALE")])

            cleared = {"count": 0}
            dialog.selected_headers_list.clear = lambda: cleared.__setitem__("count", cleared["count"] + 1)

            captured = {"query": None}
            dialog._populate_distinct_values = lambda list_widget, column_name, *, source_view="vw_measurement_export", filter_query=None: captured.__setitem__("query", filter_query)
            dialog.log_and_exit = lambda *_args, **_kwargs: None

            with patch.object(module, "build_measurement_filter_query", return_value="SELECT * FROM vw_measurement_export WHERE 1=1 AND reference IN ('REF1')"):
                dialog.on_reference_selection_changed()

            self.assertEqual(cleared["count"], 1)
            self.assertIn("reference IN ('REF1')", captured["query"])


if __name__ == "__main__":
    unittest.main()
