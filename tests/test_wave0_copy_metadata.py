"""#1159: explicit hidden-row scope and exact batch undo by occurrence ID."""

from dataclasses import replace

import pytest
from PyQt6.QtCore import Qt

from tests.metadata_review_fakes import make_selection, review_result


@pytest.fixture
def planner(qapplication_session):
    from metroliza.ui.report_planner import ReportPlanner

    planner = ReportPlanner()
    planner.set_review(review_result(("a.pdf", "b.pdf", "c.pdf")))
    for row in planner.model.metadata_rows.values():
        row.apply_fast(make_selection({"reference": "DETECTED", "comment": "NOK observed"}))
    first, second, third = planner.model.metadata_rows.values()
    first.set_user_value("reference", "SOURCE")
    second.set_user_value("reference", "PREVIOUS")
    third.cells["reference"].ocr_suggestion = "SOURCE"
    planner.search.setText("a.pdf")
    planner.table.setCurrentIndex(planner.proxy.index(0, planner.model.column_for_field("reference")))
    yield planner
    planner.deleteLater()


def test_copy_counts_hidden_and_existing_manual_corrections(planner):
    counts = planner.model.copy_scope_counts("reference", {"a.pdf"}, "SOURCE")
    assert counts == {"checked": 3, "hidden": 2, "overwrites": 1}
    planner._update_metadata_actions()
    label = planner.copy_to_checked.text()
    assert all(value in label for value in ("Reference", "SOURCE", "3 checked", "2 hidden", "1 manual"))


def test_copy_menu_recounts_hidden_rows_when_opening(planner):
    planner.search.clear()
    planner.metadata_menu.aboutToShow.emit()
    assert "0 hidden" in planner.copy_to_checked.text()
    planner.search.setText("a.pdf")
    planner.metadata_menu.aboutToShow.emit()
    assert "2 hidden" in planner.copy_to_checked.text()


def test_visible_only_updates_a_visible_target_and_preserves_hidden_row(planner, monkeypatch):
    planner.model.metadata_row("b.pdf").cells["comment"].auto_value = "a.pdf target NOK"
    planner.search.clear()
    planner.search.setText("a.pdf")
    assert planner.proxy.rowCount() == 2
    monkeypatch.setattr(planner, "_choose_copy_scope", lambda *_: "visible", raising=False)
    planner.copy_current_value_to_checked()
    assert [row.value("reference") for row in planner.model.metadata_rows.values()] == [
        "SOURCE", "SOURCE", "DETECTED",
    ]


@pytest.mark.parametrize("scope,expected", [("all", ["SOURCE"] * 3), ("visible", ["SOURCE", "PREVIOUS", "DETECTED"]), ("cancel", ["SOURCE", "PREVIOUS", "DETECTED"])])
def test_copy_deliberate_scope_includes_hidden_or_visible_only_and_undo_restores_flags(planner, monkeypatch, scope, expected):
    before = {key: replace(row.cells["reference"]) for key, row in planner.model.metadata_rows.items()}
    choices = []
    monkeypatch.setattr(planner, "_choose_copy_scope", lambda field, value, counts: choices.append(counts) or scope, raising=False)
    planner.copy_current_value_to_checked()
    assert choices == [{"checked": 3, "hidden": 2, "overwrites": 1}]
    assert [row.value("reference") for row in planner.model.metadata_rows.values()] == expected
    if scope == "cancel":
        assert not planner.model.can_undo_copy
        return
    planner.search.clear()
    planner.proxy.sort(planner.model.LOCATION_COLUMN, Qt.SortOrder.DescendingOrder)
    planner.search.setText("c.pdf")
    planner.undo_copy()
    assert {key: row.cells["reference"] for key, row in planner.model.metadata_rows.items()} == before
    assert not planner.model.can_undo_copy
