"""Synthetic scope/state regressions for #1159 Packet D (including NOK rows)."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QListWidgetItem, QMessageBox

from metroliza.industrial.industrial_analytics_state import ProductionMetricSelection
from metroliza.tabular.tabular_analytics_service import TabularAnalyticsLoadResult, TabularColumnFilter
from metroliza.ui import industrial_analytics_dialog as summary_module
from metroliza.ui import tabular_analytics_grouping_dialog as grouping_module
from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog, MetricLimitsDialog
from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog

import pandas as pd

_APP = None


@pytest.fixture
def app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _frame():
    return pd.DataFrame({
        "source_row_number": [11, 22, 33, 44], "part": ["A", "A", "B", "C"],
        "value": [1.0, 99.0, -99.0, 2.0], "result": ["OK", "NOK", "NOK", "OK"],
    })


@pytest.fixture
def grouping(app, monkeypatch):
    dialog = TabularAnalyticsGroupingDialog(dataframe=_frame())
    dialog.selector_columns = ["part"]
    dialog._refresh_all()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    yield dialog
    dialog.close()


def test_pending_text_blocks_assignment_without_enter(grouping, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    grouping.selector_search.setText("part=A")
    grouping.assign_filtered_rows(initial_group_name="A only")
    assert not grouping._temp_assignments(), "unapplied text must never assign the old scope"
    assert "Not applied" in messages[-1]
    assert "Not applied" in grouping.search_scope_label.text()
    assert "4" in grouping.search_scope_label.text()


@pytest.mark.parametrize("text, message", [
    ("part=Z", "No rows match"), ("missing=bad", "Invalid filter"), ("part=", "Invalid filter"),
])
def test_empty_or_invalid_scope_is_explicit_and_assigns_nothing(grouping, monkeypatch, text, message):
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    grouping.selector_search.setText(text)
    grouping._apply_selector_filter()
    grouping.assign_filtered_rows(initial_group_name="bad")
    assert not grouping._temp_assignments()
    assert message in messages[-1]


def test_unchanged_search_is_noop_and_prompt_counts_nok_rows(grouping, monkeypatch):
    grouping.selector_search.setText("part=A")
    grouping._apply_selector_filter()
    monkeypatch.setattr(grouping, "_refresh_selectors", lambda: pytest.fail("unchanged search queried again"))
    grouping._apply_selector_filter()
    prompts = []
    monkeypatch.setattr(grouping_module.QInputDialog, "getText", lambda *a, **k: (prompts.append(a[2]) or "A", True))
    monkeypatch.setattr(grouping, "_refresh_all", lambda **kwargs: None)
    grouping.assign_filtered_rows()
    assert "2 rows" in prompts[0]
    assert set(grouping._temp_assignments()) == {11, 22}


def test_pending_query_revision_ignores_stale_async_result(grouping):
    request = grouping._selector_preview_request_id
    grouping.selector_search.setText("part=A")
    old_items = grouping.selector_list.count()
    grouping._on_sqlite_selector_preview_ready(request, ("part",), 0, [{"key": ("STALE",), "label": "STALE", "row_count": 4}], 1)
    assert grouping.selector_list.count() == old_items, "an older query revision replaced pending scope"


@pytest.fixture
def summary(app, monkeypatch):
    loaded = TabularAnalyticsLoadResult(dataframe=_frame(), metric_candidates=())
    dialog = IndustrialAnalyticsDialog(source_kind="tabular_file", tabular_load_result=loaded)
    dialog.set_df_for_grouping(pd.DataFrame({
        "REPORT_ID": [11, 22, 33], "GROUP": ["first", "first", "second"],
        "GROUP_COLOR": ["#aabbcc", "#aabbcc", "#112233"],
    }))
    dialog.set_grouping_applied(True)
    dialog.groupstats_checkbox.setChecked(True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    yield dialog
    dialog.close()


def _filter_dialog(monkeypatch, filters=(), expression="", accepted=True):
    class Filter:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

        def get_column_filters(self):
            return filters

        def get_filter_expression(self):
            return expression

    monkeypatch.setattr(summary_module, "TabularAnalyticsFilterDialog", Filter)


@pytest.mark.parametrize("accepted", [True, False])
def test_unchanged_apply_and_cancel_keep_groups_colours_groupstats(summary, monkeypatch, accepted):
    before = summary.df_for_grouping
    _filter_dialog(monkeypatch, accepted=accepted)
    summary.open_tabular_filter_dialog()
    assert summary.df_for_grouping is before, "unchanged Apply discarded grouping"
    assert summary.grouping_applied
    assert summary.groupstats_checkbox.isChecked()


def test_canonical_filter_equivalence_keeps_grouping(summary, monkeypatch):
    summary.tabular_column_filters = (TabularColumnFilter("part", selected_values=("B", "A")),)
    summary.tabular_filter_expression = " value > 0 "
    before = summary.df_for_grouping
    _filter_dialog(monkeypatch, (TabularColumnFilter("part", selected_values=("A", "B", "A")),), "value>0")
    summary.open_tabular_filter_dialog()
    assert summary.df_for_grouping is before, "canonical equivalent filter discarded groups"


@pytest.mark.parametrize("confirm", [True, False])
def test_narrowing_reports_lost_members_before_commit_and_preserves_ids(summary, monkeypatch, confirm):
    before = summary.df_for_grouping
    _filter_dialog(monkeypatch, (TabularColumnFilter("part", selected_values=("A",)),))
    prompts = []

    def question(*args):
        assert summary.df_for_grouping is before
        assert summary.tabular_column_filters == ()
        prompts.append(args[2])
        return QMessageBox.StandardButton.Yes if confirm else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", question)
    summary.open_tabular_filter_dialog()
    assert prompts, "membership loss needs confirmation before changing state"
    assert "1 row" in prompts[0] and "1 group" in prompts[0]
    if confirm:
        assert list(summary.df_for_grouping["REPORT_ID"]) == [11, 22]
        assert set(summary.df_for_grouping["GROUP_COLOR"]) == {"#aabbcc"}
        # The surviving single group cannot form groupstats; unchanged Apply
        # above covers preserving the user's selection when it stays available.
        assert not summary.groupstats_checkbox.isChecked()
    else:
        assert summary.df_for_grouping is before
        assert summary.tabular_column_filters == ()


def test_widening_filter_never_guesses_new_row_membership(summary, monkeypatch):
    summary.tabular_column_filters = (TabularColumnFilter("part", selected_values=("A", "B")),)
    _filter_dialog(monkeypatch)
    summary.open_tabular_filter_dialog()
    assert summary.df_for_grouping is not None, "widening discarded compatible assignments"
    assert set(summary.df_for_grouping["REPORT_ID"]) == {11, 22, 33}
    assert 44 not in set(summary.df_for_grouping["REPORT_ID"])


@pytest.mark.parametrize("field, expected", [("B", (2, 8)), ("A", (None, None))])
def test_limits_edit_preserves_omitted_metric_and_explicit_clear(summary, monkeypatch, field, expected):
    metrics = tuple(ProductionMetricSelection(field_name=name, lsl=0, usl=10) for name in ("A", "B"))
    summary.metric_candidates = metrics
    summary.metric_spec_limits = {"A": (1, 9), "B": (2, 8)}
    for metric in metrics:
        item = QListWidgetItem(metric.display_label)
        item.setData(Qt.ItemDataRole.UserRole, metric)
        item.setCheckState(Qt.CheckState.Checked if metric.field_name == "A" else Qt.CheckState.Unchecked)
        summary.metrics_list.addItem(item)

    class EditLimits(MetricLimitsDialog):
        def exec(self):
            self.table.item(0, 1).setText("")
            self.table.item(0, 2).setText("")
            self._accept_if_valid()
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(summary_module, "MetricLimitsDialog", EditLimits)
    summary.open_limits_dialog()
    assert summary.metric_spec_limits.get(field) == expected, "OMITTED must survive and CLEAR must be explicit"
    for index in range(summary.metrics_list.count()):
        summary.metrics_list.item(index).setCheckState(Qt.CheckState.Checked)
    selected = {metric.field_name: metric for metric in summary._selected_metrics()}
    assert (selected[field].lsl, selected[field].usl) == expected


def test_query_revision_change_during_target_prompt_assigns_nothing(grouping, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))

    def prompt(*args, **kwargs):
        grouping.selector_search.setText("part=A")
        return "old scope", True

    monkeypatch.setattr(grouping_module.QInputDialog, "getText", prompt)
    grouping.assign_filtered_rows()
    assert not grouping._temp_assignments(), "target prompt committed an older scope revision"
    assert "Nothing assigned" in messages[-1]


@pytest.mark.parametrize("name", ["column_search", "selected_column_search"])
def test_column_searches_show_consistent_pending_state(grouping, name):
    grouping.selected_selector_keys = {("A",)}
    grouping._sync_status(recompute_counts=False, recompute_scope=False)
    assert grouping.create_group_button.isEnabled()
    getattr(grouping, name).setText("part")
    assert not grouping.assign_filtered_rows_button.isEnabled()
    assert not grouping.create_group_button.isEnabled()
    assert "Not applied" in grouping.search_scope_label.text()
    apply = grouping._apply_column_search if name == "column_search" else grouping._apply_selected_column_search
    apply()
    assert grouping.assign_filtered_rows_button.isEnabled()
    assert grouping.create_group_button.isEnabled()


def test_sqlite_narrowing_keeps_sparse_ids_without_reading_wide_frame(app, tmp_path, monkeypatch):
    from metroliza.tabular.tabular_analytics_service import cleanup_tabular_load_result, load_tabular_analytics_file
    from metroliza.analytics.row_table import RowTable

    path = tmp_path / "scope.csv"
    _frame().drop(columns=["source_row_number"]).to_csv(path, index=False)
    loaded = load_tabular_analytics_file(path, force_sqlite=True)
    dialog = IndustrialAnalyticsDialog(source_kind="tabular_file", tabular_load_result=loaded)
    try:
        dialog.set_df_for_grouping(RowTable(columns=("REPORT_ID", "GROUP", "GROUP_COLOR"),
                                           rows=((1, "A", "#aabbcc"), (2, "A", "#aabbcc"), (3, "B", "#112233"))))
        dialog.set_grouping_applied(True)
        _filter_dialog(monkeypatch, (TabularColumnFilter("part", selected_values=("A",)),))
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(type(loaded.sqlite_store), "read_dataframe", lambda *a, **k: pytest.fail("wide frame read"))
        dialog.open_tabular_filter_dialog()
        assert dialog.grouping_applied, "narrowing discarded sparse assignments"
        assert list(dialog.df_for_grouping["REPORT_ID"]) == [1, 2]
        assert list(dialog.df_for_grouping["GROUP_COLOR"]) == ["#aabbcc", "#aabbcc"]
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


@pytest.mark.parametrize("cancel", [True, False])
def test_scope_worker_keeps_gui_responsive_and_finishes_before_return(app, monkeypatch, cancel):
    from threading import Event, get_ident
    from PyQt6.QtCore import QTimer

    owner = QDialog()
    release = Event()
    calls = []
    gui_thread = get_ident()
    create = grouping_module.create_delayed_worker_progress_dialog

    def make_progress(*args, **kwargs):
        result = create(*args, **kwargs)
        def check_admission():
            assert not owner.isEnabled()
            assert result[0].isEnabled()
            calls.append("gui alive")

        QTimer.singleShot(0, check_admission)
        if cancel:
            QTimer.singleShot(0, kwargs["on_cancel"])
        QTimer.singleShot(30, release.set)
        return result

    def operation():
        assert get_ident() != gui_thread
        assert release.wait(5)
        if not cancel:
            raise ValueError("synthetic scope failure")
        return 42

    monkeypatch.setattr(grouping_module, "create_delayed_worker_progress_dialog", make_progress)
    if cancel:
        assert grouping_module._run_csv_scope_query(owner, operation, "Checking scope") is None
    else:
        with pytest.raises(RuntimeError, match="synthetic scope failure"):
            grouping_module._run_csv_scope_query(owner, operation, "Checking scope")
    assert calls == ["gui alive"]
    assert not owner._scope_query_running
    owner.close()


def test_unchanged_limits_keep_computed_scenario_identical(summary, monkeypatch):
    from metroliza.industrial.industrial_analytics_service import analyze_production_groupstats
    from metroliza.industrial.industrial_analytics_state import ProductionAggregationState

    metric = ProductionMetricSelection(field_name="value", lsl=-1.234567891, usl=9.876543219)
    summary.metric_candidates = (metric,)
    summary._populate_metrics()
    frame = pd.DataFrame({"value": [1 + i / 20 for i in range(20)] + [2 + i / 20 for i in range(19)] + [99],
                          "reference": ["A"] * 20 + ["B"] * 20})

    def calculate():
        return analyze_production_groupstats(frame, summary._selected_metrics(), group_fields=("reference",),
                                            aggregation_state=ProductionAggregationState(group_fields=("reference",)))

    before = calculate()
    assert before.analyzed_metric_count == 1

    class NoEdit(MetricLimitsDialog):
        def exec(self):
            self._accept_if_valid()
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(summary_module, "MetricLimitsDialog", NoEdit)
    summary.open_limits_dialog()
    after = calculate()
    assert summary._selected_metrics() == (summary._metric_with_limits(metric),)
    assert repr(after) == repr(before), "unchanged limits altered computed groupstats"


def test_editing_one_limit_preserves_other_bounds_precision(app):
    metric = ProductionMetricSelection("value", lsl=-1.234567891, usl=9.876543219)
    dialog = MetricLimitsDialog(metrics=(metric,))
    dialog.table.item(0, 2).setText("10")
    dialog._accept_if_valid()
    assert dialog.limits()["value"] == (-1.234567891, 10), "editing USL rounded the untouched LSL"
    dialog.close()


def test_bounded_id_reconciliation_reuses_store_queries(tmp_path, monkeypatch):
    from metroliza.analytics.row_table import RowTable
    from metroliza.tabular.csv_summary_scope import preview_filter_change
    from metroliza.tabular.tabular_analytics_service import cleanup_tabular_load_result, load_tabular_analytics_file

    path = tmp_path / "large_scope.csv"
    pd.concat([_frame()] * 500).drop(columns=["source_row_number"]).to_csv(path, index=False)
    loaded = load_tabular_analytics_file(path, force_sqlite=True)
    store_type = type(loaded.sqlite_store)
    read_ids = store_type.row_ids
    chunks = []

    def bounded_read(store, **kwargs):
        chunk = kwargs["grouping_filter"].params
        assert 0 < len(chunk) <= 900
        chunks.append(len(chunk))
        return read_ids(store, **kwargs)

    monkeypatch.setattr(store_type, "row_ids", bounded_read)
    monkeypatch.setattr(store_type, "read_dataframe", lambda *a, **k: pytest.fail("wide frame read"))
    grouping = RowTable(columns=("REPORT_ID", "GROUP"), rows=tuple((i, "custom") for i in range(1, 2001)))
    try:
        result, lost, groups, total, population = preview_filter_change(
            loaded, grouping, (TabularColumnFilter("part", selected_values=("A",)),), "",
        )
        assert chunks == [900, 900, 200]
        assert len(result) == total == 1000
        assert lost == 1000 and groups == 1
        assert not population
    finally:
        cleanup_tabular_load_result(loaded)
