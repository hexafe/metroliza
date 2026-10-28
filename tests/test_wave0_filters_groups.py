"""Scope regressions for #1159 packet B, using synthetic OK and NOK data."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
import pytest
from PyQt6.QtCore import QDate, QEvent, Qt
from PyQt6.QtGui import QFocusEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QListWidgetItem

import metroliza
from metroliza.ui import data_grouping as grouping
from metroliza.ui import filter_dialog as filtering
from metroliza.reports.report_query_service import build_measurement_filter_query


@pytest.fixture(scope="module", autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    source = os.environ.get("W0_EXPECT_SOURCE")
    if source:
        print(f"metroliza.__file__={metroliza.__file__}", flush=True)
        for module in (metroliza, filtering, grouping):
            assert Path(module.__file__).resolve().is_relative_to(Path(source).resolve())
    yield app


class FilterParent(QDialog):
    def __init__(self):
        super().__init__()
        self.query = None
        self.state = None

    def set_filter_query(self, query):
        self.query = query

    def set_filter_state(self, state):
        self.state = state


@pytest.fixture
def filter_dialog(monkeypatch):
    monkeypatch.setattr(filtering.FilterDialog, "populate_list_widgets", lambda self: None)
    parent = FilterParent()
    dialog = filtering.FilterDialog(parent)
    monkeypatch.setattr(dialog, "log_and_exit", lambda exc: pytest.fail(str(exc)))
    yield dialog, parent
    dialog.hide()
    dialog.deleteLater()
    parent.deleteLater()


def select(widget, value):
    matches = widget.findItems(value, Qt.MatchFlag.MatchExactly)
    if not matches:
        widget.addItem(value)
        matches = widget.findItems(value, Qt.MatchFlag.MatchExactly)
    matches[0].setSelected(True)


def selected(widget):
    return [item.text() for item in widget.selectedItems()]


def test_f01_reference_search_preserves_header_predicate(filter_dialog, monkeypatch):
    dialog, parent = filter_dialog
    monkeypatch.setattr(dialog, "_populate_distinct_values", lambda *args, **kwargs: None)
    dialog.reference_list.addItems(["REF-OK", "REF-NOK"])
    select(dialog.reference_list, "REF-NOK")
    select(dialog.header_list, "Diameter-NOK")
    dialog.apply_filters()
    original = parent.query
    dialog.reference_search_input.setText("REF-OK")
    dialog.apply_filters()
    assert parent.query == original
    assert parent.state.header_values == ("Diameter-NOK",)


def test_f01_reference_change_retains_unavailable_and_ignores_stale(filter_dialog, monkeypatch):
    dialog, parent = filter_dialog
    select(dialog.header_list, "Diameter-NOK")

    def request(*args, **kwargs):
        dialog._value_request += 1

    monkeypatch.setattr(dialog, "_populate_distinct_values", request)
    select(dialog.reference_list, "REF-OK")
    assert selected(dialog.header_list) == ["Diameter-NOK"]
    request_id = dialog._value_request
    dialog._receive_filter_values(request_id, {"header_list": ["Width-OK"]})
    assert selected(dialog.header_list) == ["Diameter-NOK"]
    assert "Diameter-NOK" in dialog.header_availability_label.text()
    assert "Unavailable" in dialog.header_availability_label.text()
    assert dialog.header_availability_label.textFormat() == Qt.TextFormat.PlainText
    assert dialog.header_availability_label.wordWrap()
    dialog._receive_filter_values(request_id - 1, {"header_list": ["Stale-NOK"]})
    assert not dialog.header_list.findItems("Stale-NOK", Qt.MatchFlag.MatchExactly)
    dialog.apply_filters()
    assert parent.state.header_values == ("Diameter-NOK",)
    assert "header IN ('Diameter-NOK')" in parent.query
    # Returning to all references also keeps the chosen header.
    dialog.all_headers_list.addItems(["Diameter-NOK", "Width-OK"])
    select(dialog.reference_list, "SELECT ALL")
    assert selected(dialog.header_list) == ["Diameter-NOK"]
    assert dialog.header_availability_label.text() == ""


def test_f05_all_and_values_are_exclusive_and_scope_agrees(filter_dialog):
    dialog, parent = filter_dialog
    select(dialog.status_code_list, "SELECT ALL")
    select(dialog.status_code_list, "NOK")
    assert selected(dialog.status_code_list) == ["NOK"]
    assert dialog._selected_value_count(dialog.status_code_list) == 1
    assert "Selected values: 1" in dialog.filter_summary_label.text()
    dialog.apply_filters()
    assert parent.state.status_code_values == ("NOK",)
    assert "status_code IN ('NOK')" in parent.query
    with closing(sqlite3.connect(":memory:")) as connection, connection:
        extra_columns = (
            "measurement_id, reference, report_time, part_name, revision, sample_number, "
            "sample_number_kind, stats_count_raw, stats_count_int, operator_name, directory_path, "
            "file_name, absolute_path, parser_id, template_family, template_variant, header, "
            "section_name, feature_label, characteristic_name, characteristic_family, description, "
            "ax, nominal, tol_plus, tol_minus, bonus, meas, dev, outtol, is_nok, page_number, "
            "row_order, has_nok, nok_count"
        )
        connection.execute("CREATE TABLE vw_measurement_export(report_id INTEGER, status_code TEXT, "
                           f"report_date TEXT, {extra_columns})")
        connection.executemany("INSERT INTO vw_measurement_export(report_id, status_code, report_date) VALUES (?, ?, ?)",
                               [(1, "OK", "2024-01-01"), (2, "NOK", "2024-01-01")])
        cursor = connection.execute(parent.query)
        rows = [dict(zip((column[0] for column in cursor.description), row, strict=True))
                for row in cursor.fetchall()]
        assert [(row["REPORT_ID"], row["STATUS_CODE"]) for row in rows] == [(2, "NOK")]
    select(dialog.status_code_list, "SELECT ALL")
    assert selected(dialog.status_code_list) == ["SELECT ALL"]
    dialog.apply_filters()
    assert parent.state.status_code_values == ()
    assert "status_code IN" not in parent.query


def test_f01_restoring_draft_retains_headers_missing_from_refreshed_choices(filter_dialog):
    dialog, parent = filter_dialog
    select(dialog.header_list, "Diameter-NOK")
    snapshot = dialog._draft_snapshot()
    dialog.header_list.clearSelection()
    dialog._receive_filter_values(dialog._value_request, {"header_list": ["Width-OK"]})
    dialog._restore_draft_snapshot(snapshot)
    dialog.apply_filters()
    assert parent.state.header_values == ("Diameter-NOK",)
    assert "Diameter-NOK" in dialog.header_availability_label.text()


def test_f05_legacy_mixed_saved_state_prefers_concrete_values(filter_dialog):
    dialog, parent = filter_dialog
    dialog.status_code_list.addItem("NOK")
    snapshot = dialog._draft_snapshot()
    selections, *rest = snapshot
    selections = tuple((name, ("SELECT ALL", "NOK") if name == "status_code_list" else values)
                       for name, values in selections)
    dialog._restore_draft_snapshot((selections, *rest))
    assert selected(dialog.status_code_list) == ["NOK"]
    dialog.apply_filters()
    assert parent.state.status_code_values == ("NOK",)


@pytest.mark.parametrize("path", ["button", "apply", "accept", "enter"])
def test_f10_reversed_dates_refused_without_losing_input(filter_dialog, path):
    dialog, parent = filter_dialog
    start, end = QDate(2024, 2, 2), QDate(2024, 2, 1)
    dialog.date_from_calendar.setDate(start)
    dialog.date_to_calendar.setDate(end)
    if path == "button":
        assert not dialog.apply_button.isEnabled()
        dialog.apply_button.click()
    elif path == "enter":
        dialog.show()
        QApplication.processEvents()
        dialog.apply_button.setFocus()
        QTest.keyClick(dialog.apply_button, Qt.Key.Key_Return)
    else:
        getattr(dialog, "apply_filters" if path == "apply" else "accept")()
    assert parent.query is None
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "From" in dialog.date_error_label.text()
    assert dialog.date_from_calendar.date() == start
    assert dialog.date_to_calendar.date() == end


def test_f10_equal_dates_valid_and_query_builder_guards_reversed(filter_dialog):
    dialog, parent = filter_dialog
    day = QDate(2024, 2, 1)
    dialog.date_from_calendar.setDate(day)
    dialog.date_to_calendar.setDate(day)
    dialog.apply_filters()
    assert parent.state.date_from == parent.state.date_to == "2024-02-01"
    with pytest.raises(ValueError, match="From"):
        build_measurement_filter_query(date_from="2024-02-02", date_to="2024-02-01")


def test_f10_valid_programmatic_accept_keeps_native_dialog_result(filter_dialog):
    dialog, _parent = filter_dialog
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


@pytest.fixture
def group_dialog(monkeypatch):
    # Keep the actual widgets, signal wiring and keyboard path; isolate data loading.
    monkeypatch.setattr(grouping.DataGrouping, "read_data_to_df", lambda self: None)
    monkeypatch.setattr(grouping.DataGrouping, "add_default_group", lambda self: None)
    monkeypatch.setattr(grouping.DataGrouping, "_restore_saved_grouping_state", lambda self: None)
    monkeypatch.setattr(grouping.DataGrouping, "populate_list_widgets", lambda self, **kwargs: None)
    dialog = grouping.DataGrouping()
    dialog.df = pd.DataFrame({"GROUP": ["Lot A", "Lot B", "POPULATION"],
                              "GROUP_COLOR": ["#111111", "#222222", "#ffffff"],
                              "GROUP_KEY": ["left-report", "right-report", "default-report"],
                              "STATUS_CODE": ["OK", "NOK", "NOK"]})
    monkeypatch.setattr(dialog, "log_and_exit", lambda exc: pytest.fail(str(exc)))
    monkeypatch.setattr(dialog, "_selected_reference_name", lambda: "REF")
    yield dialog
    dialog.hide()
    dialog.deleteLater()


@pytest.mark.parametrize("old,new", [("Lot A", " Lot B "), ("POPULATION", "Lot B"),
                                     ("Lot A", " Lot A ")])
def test_f02_rename_collision_and_same_name_preserve_members_colours(group_dialog, monkeypatch, old, new):
    dialog = group_dialog
    before = dialog.df.copy(deep=True)
    warnings, invalidations = [], []
    monkeypatch.setattr(dialog, "_selected_group_name", lambda: old)
    monkeypatch.setattr(grouping.QInputDialog, "getText", lambda *args, **kwargs: (new, True))
    monkeypatch.setattr(grouping.QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(dialog, "_invalidate_grouping_cache", lambda: invalidations.append(True))
    dialog.rename_group()
    pd.testing.assert_frame_equal(dialog.df, before)
    assert bool(warnings) == (old != new.strip())
    assert not invalidations
    assert dialog.default_group == "POPULATION"


def test_f02_case_sensitive_names_match_existing_group_comparison(group_dialog, monkeypatch):
    dialog = group_dialog
    monkeypatch.setattr(dialog, "_selected_group_name", lambda: "Lot A")
    monkeypatch.setattr(grouping.QInputDialog, "getText", lambda *args, **kwargs: ("lot b", True))
    dialog.rename_group()
    assert list(dialog.df.GROUP) == ["lot b", "Lot B", "POPULATION"]


@pytest.mark.parametrize("old,other,new", [("Lot A", " Lot B ", "Lot B"),
                                         (" Lot A ", "Lot B", "Lot A")])
def test_f02_legacy_whitespace_names_use_trimmed_identity(group_dialog, monkeypatch, old, other, new):
    dialog = group_dialog
    dialog.df.loc[0, "GROUP"] = old
    dialog.df.loc[1, "GROUP"] = other
    before = dialog.df.copy(deep=True)
    warnings = []
    monkeypatch.setattr(dialog, "_selected_group_name", lambda: old)
    monkeypatch.setattr(grouping.QInputDialog, "getText", lambda *args, **kwargs: (new, True))
    monkeypatch.setattr(grouping.QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog.rename_group()
    pd.testing.assert_frame_equal(dialog.df, before)
    assert bool(warnings) == (new != old.strip())


@pytest.mark.parametrize("pane,key", [("part_list", "left-report"), ("part_group_list", "right-report")])
@pytest.mark.parametrize("path", ["button", "keyboard"])
def test_f03_create_add_uses_last_active_pane_snapshot(group_dialog, monkeypatch, pane, key, path):
    dialog = group_dialog
    monkeypatch.setattr(dialog, "_selected_group_name", lambda: "Lot A")
    for name, report in [("part_list", "left-report"), ("part_group_list", "right-report")]:
        widget = getattr(dialog, name)
        blocked = widget.blockSignals(True)
        item = QListWidgetItem(report)
        item.setData(Qt.ItemDataRole.UserRole, report)
        widget.addItem(item)
        item.setSelected(True)
        widget.blockSignals(blocked)
    dialog.show()
    QApplication.processEvents()
    source = getattr(dialog, pane)
    source.setFocus()
    QApplication.sendEvent(source, QFocusEvent(QEvent.Type.FocusIn))
    QApplication.processEvents()
    prompts = []

    def prompt(*args, **kwargs):
        prompts.append(args[2])
        # Moving focus or selection during a modal prompt must not change its snapshot.
        getattr(dialog, "part_list").clearSelection()
        return "Target", True

    monkeypatch.setattr(grouping.QInputDialog, "getText", prompt)
    if path == "button":
        dialog.create_group_button.setEnabled(True)
        dialog.create_group_button.setFocus()
        QApplication.processEvents()
        dialog.create_group_button.click()
    else:
        dialog.create_group_button.setEnabled(True)
        dialog.create_group_button.setFocus()
        QApplication.processEvents()
        QTest.keyClick(dialog.create_group_button, Qt.Key.Key_Space)
    assert list(dialog.df.loc[dialog.df.GROUP == "Target", "GROUP_KEY"]) == [key]
    assert "1 selected parts" in prompts[0]
    assert ("selected group" in prompts[0]) == (pane == "part_group_list")
