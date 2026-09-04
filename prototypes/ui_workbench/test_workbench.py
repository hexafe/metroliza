"""Prototype-only native interaction tests; no production pytest configuration."""
import ast
from dataclasses import FrozenInstanceError, replace
import os
from pathlib import Path
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from app import ScopeDialog, Workbench
from state import Destination, Outcome, Session

APP = QApplication.instance() or QApplication([])


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.s = Session(interval=60000)
        self.w = Workbench(self.s)
        self.w.show()
        self.w.activateWindow()
        APP.processEvents()

    def tearDown(self):
        self.s.cancel()
        self.w.close()
        self.w.deleteLater()
        APP.processEvents()

    def review(self, source="Five eligible reports"):
        self.s.change_context(source=source)
        self.s.review()
        self.s.finish_review()
        APP.processEvents()

    def finish(self):
        while self.s.running:
            self.s.step()

    def test_two_of_five_filter_sort_hidden_scope(self):
        self.review()
        self.w.navigate(1)
        for identity in ("report-00000", "report-00003"):
            self.s.select(identity, True)
        self.w.search.setText("00001")
        self.assertEqual(self.w.proxy.rowCount(), 1)
        self.assertIn("1 selected hidden", self.w.selection_label.text())
        self.w.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.assertEqual(self.s.selected, {"report-00000", "report-00003"})
        dialog = ScopeDialog(self.s, 1, self.w)
        self.assertFalse(dialog.run.isEnabled())
        dialog.ack.setChecked(True)
        dialog.confirm()
        self.s.start(dialog.plan)
        self.finish()
        self.assertEqual(set(self.s.results), {"report-00000", "report-00003"})
        self.assertTrue(all(v == Outcome.IMPORTED for v in self.s.results.values()))

    def test_keyboard_space_search_navigation(self):
        self.review()
        w = self.w
        w.navigate(1)
        w.table.setCurrentIndex(w.proxy.index(0, 1))
        w.table.setFocus()
        APP.processEvents()
        QTest.keyClick(w.table, Qt.Key.Key_Space)
        self.assertEqual(len(self.s.selected), 1)
        QTest.keyClick(w.table, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(w.search.hasFocus())
        QTest.keyClicks(w.search, "00002")
        self.assertEqual(w.proxy.rowCount(), 1)
        QTest.keyClick(w.search, Qt.Key.Key_J, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(w.pages.currentIndex(), 6)
        QTest.keyClick(w.nav, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(w.pages.currentIndex(), 0)

    def test_select_visible_excludes_hidden(self):
        self.review()
        self.w.search.setText("00002")
        self.w.select_visible()
        self.assertEqual(self.s.selected, {"report-00001"})

    def test_context_invalidates_approval(self):
        for field, value in (("destination", "Archive"), ("source", "Validation batch"),
                             ("metadata", "Detailed"), ("workspace", "Other")):
            with self.subTest(field=field):
                self.review()
                self.s.select("report-00000", True)
                old = self.s.make_plan()
                self.s.change_context(**{field: value})
                self.assertFalse(self.s.review_current)
                self.assertFalse(self.s.selected)
                with self.assertRaises(ValueError):
                    self.s.start(old)

    def test_source_drift_clears_approval(self):
        self.review()
        self.s.select("report-00000", True)
        self.s.simulate_drift("report-00000")
        self.assertFalse(self.s.review_current)
        self.assertFalse(self.s.selected)
        self.assertIn("Refresh", self.s.reports[0].eligibility)

    def test_destination_only_verify_without_repair(self):
        self.review("Destination matches only")
        self.assertFalse(any(r.destination == Destination.NEW for r in self.s.reports))
        self.w.select_visible()
        self.assertTrue(self.w.import_button.isEnabled())
        self.s.start(self.s.make_plan())
        self.finish()
        self.assertEqual(self.s.results, {"match-0": Outcome.REPAIR_NEEDED,
                                         "match-1": Outcome.PRESENT, "match-2": Outcome.REPAIR_NEEDED})
        self.assertNotIn((self.s.context.destination, "match-0"), self.s.accepted)

    def test_destination_only_repair_preserves_complete_and_subset(self):
        self.review("Destination matches only")
        for identity in ("match-0", "match-1"):
            self.s.select(identity, True)
        self.s.start(self.s.make_plan(allow_repair=True))
        self.finish()
        self.assertEqual(self.s.results, {"match-0": Outcome.REPAIRED, "match-1": Outcome.PRESENT})
        self.assertNotIn("match-2", self.s.results)
        self.s.review()
        self.s.finish_review()
        self.s.select("match-0", True)
        self.s.start(self.s.make_plan(allow_repair=True))
        self.finish()
        self.assertEqual(self.s.results["match-0"], Outcome.PRESENT)
        self.assertEqual(len(self.s.history), 1)

    def test_immutable_execution_navigation_partial_cancel(self):
        self.review()
        self.w.select_visible()
        plan = self.s.make_plan()
        self.s.start(plan)
        with self.assertRaises(FrozenInstanceError):
            plan.allow_repair = True
        with self.assertRaises(ValueError):
            self.s.change_context(destination="Other")
        for index in range(7):
            self.w.navigate(index)
            self.assertIs(self.s.plan, plan)
            self.assertTrue(self.s.running)
            self.assertFalse(self.w.destination.isEnabled())
            self.assertTrue(self.w.cancel_button.isEnabled())
        self.s.step()
        self.s.cancel()
        self.assertEqual(self.s.results["report-00000"], Outcome.IMPORTED)
        self.assertEqual(sum(v == Outcome.CANCELLED for v in self.s.results.values()), 4)

    def test_changed_failed_cancelled_disjoint(self):
        self.review("Validation batch")
        for identity in ("report-00000", "report-00011", "report-00012", "report-00014"):
            self.s.select(identity, True)
        self.s.start(self.s.make_plan())
        for _ in range(3):
            self.s.step()
        self.s.cancel()
        self.assertEqual(self.s.results, {"report-00000": Outcome.IMPORTED, "report-00011": Outcome.CHANGED,
                                         "report-00012": Outcome.FAILED, "report-00014": Outcome.CANCELLED})
        for text in ("Import outcomes", "Review snapshot", "Changed since review"):
            self.assertIn(text, self.w.task_evidence.toPlainText())

    def test_no_selection_empty_missing_pending(self):
        for scenario in ("Empty source", "Missing source", "Five eligible reports"):
            self.s.change_context(source=scenario)
            self.s.review()
            self.w.navigate(3)
            self.assertTrue(self.s.reviewing)
            self.assertFalse(self.w.import_button.isEnabled())
            self.s.finish_review()
            self.assertFalse(self.w.import_button.isEnabled())
        self.s.review()
        self.s.cancel()
        self.assertFalse(self.s.review_current)

    def test_stale_confirmation(self):
        self.review()
        self.s.select("report-00000", True)
        old = self.s.make_plan()
        self.s.select("report-00001", True)
        with self.assertRaises(ValueError):
            self.s.start(old)
        with self.assertRaises(ValueError):
            self.s.start(replace(old, review_version=999))

    def test_layout_reachable(self):
        self.review()
        for mode in ("light", "dark"):
            self.w.set_theme(mode)
            for width, height in ((1024, 700), (1280, 800), (1600, 1000)):
                with self.subTest(mode=mode, size=(width, height)):
                    self.w.resize(width, height)
                    self.w.navigate(1)
                    APP.processEvents()
                    self.assertEqual((self.w.width(), self.w.height()), (width, height))
                    for control in (self.w.import_button, self.w.review_button, self.w.cancel_button, self.w.search, self.w.destination):
                        self.assertTrue(self.w.rect().contains(control.mapTo(self.w, control.rect().center())))
                        self.assertTrue(control.isVisible())

    def test_close_active_task_blocked(self):
        self.review()
        self.w.select_visible()
        self.s.start(self.s.make_plan())
        self.w.close()
        self.assertTrue(self.w.isVisible())
        self.s.cancel()
        self.w.close()
        self.assertFalse(self.w.isVisible())

    def test_no_backend_imports(self):
        forbidden = {"sqlite3", "socket", "requests", "urllib", "metroliza", "modules", "PyQt6.QtNetwork", "PyQt6.QtWebEngineWidgets"}
        for path in ("app.py", "models.py", "state.py", "theme.py"):
            for node in ast.walk(ast.parse(Path(path).read_text())):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                self.assertFalse(any(n == f or n.startswith(f + ".") for n in names for f in forbidden), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
