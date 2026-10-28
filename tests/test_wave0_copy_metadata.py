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
    planner.metadata_menu.aboutToShow.emit()
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
    if scope == "all":
        before["c.pdf"].ocr_suggestion = None  # Undo never writes OCR fields.
    assert {key: row.cells["reference"] for key, row in planner.model.metadata_rows.items()} == before
    assert not planner.model.can_undo_copy


@pytest.mark.parametrize("mutation", ["edit", "reset", "ocr", "accept_ocr", "fast"])
def test_copy_undo_preserves_changes_after_copy(planner, mutation):
    from metroliza.parsing.metadata_review import MODE_OCR, READING_OK, MetadataReading

    model = planner.model
    model.copy_value_to_checked("reference", "P-100")
    row = model.metadata_row("b.pdf")
    if mutation == "edit":
        index = model.index(1, model.column_for_field("reference"))
        assert model.setData(index, "P-101")
    elif mutation == "reset":
        model.reset_row("b.pdf")
    elif mutation == "fast":
        row.apply_fast(make_selection({"reference": "NEW-DETECTED", "comment": "NOK after copy"}))
    else:
        model.apply_reading(MetadataReading(
            occurrence_id="b.pdf", mode=MODE_OCR, status=READING_OK,
            selection=make_selection({"reference": "OCR-101", "comment": "NOK OCR"}),
        ))
        if mutation == "accept_ocr":
            row.accept_ocr_suggestions()
    after = replace(row.cells["reference"])
    planner.undo_copy()
    assert row.cells["reference"] == after, "Undo must preserve the cell changed after copying"
    assert model.metadata_row("c.pdf").value("reference") == "DETECTED"
    assert "1 skipped" in planner.metadata_status_text
    assert not model.can_undo_copy


def test_copy_undo_restores_only_manual_fields_and_never_ocr_suggestions(planner):
    row = planner.model.metadata_row("c.pdf")
    planner.model.copy_value_to_checked("reference", "SOURCE")
    assert row.cells["reference"].ocr_suggestion is None
    planner.undo_copy()
    assert row.value("reference") == "DETECTED"
    assert not row.cells["reference"].user_set
    assert row.cells["reference"].ocr_suggestion is None


def test_copy_counts_exclude_checked_noneditable_rows_and_normalize_values(planner):
    from metroliza.reports.report_metadata_review import ROW_CHANGED

    planner.model.metadata_row("c.pdf").state = ROW_CHANGED
    counts = planner.model.copy_scope_counts("reference", {"a.pdf"}, "  PREVIOUS  ")
    assert counts == {"checked": 2, "hidden": 1, "overwrites": 1}


def test_current_cell_changes_do_not_walk_proxy_for_copy_counts(planner, monkeypatch):
    walks = []
    original = planner._visible_report_ids
    monkeypatch.setattr(planner, "_visible_report_ids", lambda: walks.append(True) or original())
    planner._update_metadata_actions()
    planner.table.setCurrentIndex(planner.proxy.index(0, planner.model.column_for_field("comment")))
    assert walks == [], "Current-cell action updates must not scan the filtered table"
    planner.metadata_menu.aboutToShow.emit()
    assert len(walks) == 1
    assert "2 hidden" in planner.copy_to_checked.text()


def test_copy_undo_preserves_other_fields_and_later_review_clears_snapshot(planner):
    model = planner.model
    model.copy_value_to_checked("reference", "P-100")
    row = model.metadata_row("b.pdf")
    assert model.setData(model.index(1, model.column_for_field("comment")), "NOK manual after copy")
    assert model.undo_copy() == 3
    assert row.value("reference") == "PREVIOUS"
    assert row.value("comment") == "NOK manual after copy"
    model.copy_value_to_checked("reference", "P-100")
    model.set_review(review_result(("a.pdf", "b.pdf", "c.pdf")))
    assert not model.can_undo_copy
    model.copy_value_to_checked("reference", "P-100")
    model.invalidate()
    assert not model.can_undo_copy
