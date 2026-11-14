from types import SimpleNamespace

import pytest

from metroliza.shared.diagnostic_events import WorkflowOperation
from metroliza.shared.safe_bugreport import BugReportAction
from metroliza.shared.workflow_diagnostics import WorkflowTrace
from metroliza.ui import characteristic_mapping_dialog as mapping_ui
from metroliza.ui import dashboard_visual_options_dialog as dashboard_ui
from metroliza.ui import data_grouping as grouping_ui
from metroliza.ui import export_dialog as export_ui
from metroliza.ui import filter_dialog as filter_ui


@pytest.fixture
def recorded_events(monkeypatch):
    events = []

    def record(action, *, enabled=None):
        events.append((action, enabled))

    monkeypatch.setattr(export_ui._bugreport_recorder, "record", record)
    monkeypatch.setattr(mapping_ui._bugreport_recorder, "record", record)
    monkeypatch.setattr(dashboard_ui._bugreport_recorder, "record", record)
    monkeypatch.setattr(grouping_ui._bugreport_recorder, "record", record)
    monkeypatch.setattr(filter_ui._bugreport_recorder, "record", record)
    monkeypatch.setattr("metroliza.shared.safe_bugreport.recorder.record", record)
    return events


@pytest.mark.parametrize(
    ("operation", "finish", "expected"),
    [
        (WorkflowOperation.SELECTED_IMPORT,
         lambda trace: trace.finish_import(SimpleNamespace(imported_files=2), False),
         ("WORKFLOW_REPORT_IMPORT_STARTED", "WORKFLOW_REPORT_IMPORT_COMPLETED")),
        (WorkflowOperation.SELECTED_IMPORT,
         lambda trace: trace.finish_import(SimpleNamespace(imported_files=1, failed_files=1), False),
         ("WORKFLOW_REPORT_IMPORT_STARTED", "WORKFLOW_REPORT_IMPORT_COMPLETED_WITH_WARNINGS")),
        (WorkflowOperation.SELECTED_IMPORT,
         lambda trace: trace.finish_import(SimpleNamespace(imported_files=0, cancelled_files=1), False),
         ("WORKFLOW_REPORT_IMPORT_STARTED", "WORKFLOW_REPORT_IMPORT_CANCELLED")),
        (WorkflowOperation.LOCAL_EXPORT,
         lambda trace: trace.finish_export(completed=True, cancelled=False, fallback=True),
         ("WORKFLOW_REPORT_EXPORT_STARTED", "WORKFLOW_REPORT_EXPORT_COMPLETED_WITH_FALLBACK")),
        (WorkflowOperation.LOCAL_EXPORT,
         lambda trace: trace.finish_export(completed=True, cancelled=False, omissions=True),
         ("WORKFLOW_REPORT_EXPORT_STARTED", "WORKFLOW_REPORT_EXPORT_COMPLETED_WITH_OMISSIONS")),
        (WorkflowOperation.LOCAL_EXPORT,
         lambda trace: trace.finish_export(completed=False, cancelled=False),
         ("WORKFLOW_REPORT_EXPORT_STARTED", "WORKFLOW_REPORT_EXPORT_FAILED")),
        (WorkflowOperation.LOCAL_EXPORT,
         lambda trace: trace.finish_export(completed=False, cancelled=True),
         ("WORKFLOW_REPORT_EXPORT_STARTED", "WORKFLOW_REPORT_EXPORT_CANCELLED")),
    ],
)
def test_workflow_trace_records_real_operation_outcomes(recorded_events, operation, finish, expected):
    trace = WorkflowTrace(operation)
    finish(trace)

    assert tuple(action.name for action, _enabled in recorded_events) == expected
    assert all(enabled is None for _action, enabled in recorded_events)
    assert trace.finished


def test_export_options_record_only_fixed_booleans(recorded_events):
    options = SimpleNamespace(
        backend_target="google",
        generate_html_dashboard=True,
        include_industrial_context=False,
        hide_ok_results=True,
        private_label="do not retain",
    )

    export_ui._record_export_option_states(options, filters_applied=True, grouping_applied=False)

    assert recorded_events == [
        (BugReportAction.OPTION_EXPORT_CLOUD, True),
        (BugReportAction.OPTION_EXPORT_HTML, True),
        (BugReportAction.OPTION_EXPORT_CONTEXT, False),
        (BugReportAction.OPTION_HIDE_OK, True),
        (BugReportAction.OPTION_EXPORT_FILTERS_APPLIED, True),
        (BugReportAction.OPTION_EXPORT_GROUPING_APPLIED, False),
        (BugReportAction.OPTION_EXPORT_DASHBOARD_VISUALS_ENABLED, True),
    ]
    assert all(type(action) is BugReportAction and type(enabled) is bool for action, enabled in recorded_events)


def test_export_filter_and_grouping_record_confirmed_states(recorded_events):
    label = SimpleNamespace(setText=lambda _text: None, setToolTip=lambda _text: None,
                            toolTip=lambda: "", text=lambda: "")
    dialog = SimpleNamespace(
        filter_state=None,
        select_filter_label=label,
        _refresh_filter_state_summary=lambda: None,
        _refresh_draft_request_summary=lambda: None,
        _sync_html_dashboard_only_state=lambda: None,
        select_group_label=SimpleNamespace(setText=lambda _text: None),
    )

    export_ui.ExportDialog.set_filter_applied(dialog)
    export_ui.ExportDialog.set_grouping_applied(dialog, True)

    assert recorded_events == [
        (BugReportAction.WORKFLOW_EXPORT_FILTER_APPLIED, None),
        (BugReportAction.OPTION_EXPORT_FILTERS_APPLIED, True),
        (BugReportAction.OPTION_EXPORT_GROUPING_APPLIED, True),
        (BugReportAction.WORKFLOW_EXPORT_GROUPING_APPLIED, None),
    ]


@pytest.mark.parametrize("accepted", [True, False])
def test_dashboard_visual_options_record_actual_dialog_outcome(
    monkeypatch, recorded_events, accepted
):
    dashboard_module = __import__(
        "metroliza.ui.dashboard_visual_options_dialog", fromlist=["DashboardVisualOptionsDialog"]
    )

    class FakeVisualDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return accepted

        def visual_settings(self):
            return {"private": "never recorded"}

    monkeypatch.setattr(dashboard_module, "DashboardVisualOptionsDialog", FakeVisualDialog)
    dialog = SimpleNamespace(
        df_for_grouping=None,
        dashboard_visual_settings=None,
        _sync_dashboard_visual_controls=lambda: None,
    )

    export_ui.ExportDialog.open_dashboard_visual_options(dialog)

    terminal = (
        BugReportAction.WORKFLOW_EXPORT_DASHBOARD_VISUAL_OPTIONS_APPLIED
        if accepted
        else BugReportAction.WORKFLOW_EXPORT_DASHBOARD_VISUAL_OPTIONS_CANCELLED
    )
    assert recorded_events == [
        (BugReportAction.WORKFLOW_EXPORT_DASHBOARD_VISUAL_OPTIONS_OPENED, None),
        (terminal, None),
    ]


@pytest.mark.parametrize("result, expected", [
    (3, BugReportAction.WORKFLOW_MAPPING_IMPORT_COMPLETED),
    (None, BugReportAction.WORKFLOW_MAPPING_IMPORT_CANCELLED),
])
def test_mapping_import_records_terminal_state_without_input_values(
    monkeypatch, recorded_events, result, expected
):
    monkeypatch.setattr(mapping_ui.QMessageBox, "information", lambda *_args, **_kwargs: None)
    fake_dialog = SimpleNamespace(load_aliases=lambda: None)

    mapping_ui.CharacteristicMappingDialog._apply_alias_import(fake_dialog, lambda: result)

    assert recorded_events == [(expected, None)]
    assert all(type(action) is BugReportAction for action, _enabled in recorded_events)


def test_mapping_import_failure_records_only_enum(monkeypatch, recorded_events):
    monkeypatch.setattr(mapping_ui, "CustomLogger", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mapping_ui.QMessageBox, "critical", lambda *_args, **_kwargs: None)
    fake_dialog = SimpleNamespace()

    mapping_ui.CharacteristicMappingDialog._apply_alias_import(
        fake_dialog, lambda: (_ for _ in ()).throw(RuntimeError("sensitive payload"))
    )

    assert recorded_events == [(BugReportAction.WORKFLOW_MAPPING_IMPORT_FAILED, None)]


def test_mapping_action_recorder_failure_is_best_effort(monkeypatch):
    monkeypatch.setattr(mapping_ui._bugreport_recorder, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))

    mapping_ui._record_mapping_action(BugReportAction.WORKFLOW_MAPPING_ADD_STARTED)


@pytest.mark.parametrize(
    ("value", "actions", "expected"),
    [
        ("histogram", dashboard_ui._DASHBOARD_CHART_ACTIONS,
         BugReportAction.OPTION_DASHBOARD_CHART_HISTOGRAM),
        ("violin", dashboard_ui._DASHBOARD_CHART_ACTIONS,
         BugReportAction.OPTION_DASHBOARD_CHART_VIOLIN),
        ("iqr", dashboard_ui._DASHBOARD_CHART_ACTIONS,
         BugReportAction.OPTION_DASHBOARD_CHART_IQR),
        ("scatter", dashboard_ui._DASHBOARD_CHART_ACTIONS,
         BugReportAction.OPTION_DASHBOARD_CHART_SCATTER),
    ],
)
def test_dashboard_chart_type_uses_closed_enum(value, actions, expected, recorded_events):
    dashboard_ui._record_closed_dashboard_choice(value, actions)

    assert recorded_events == [(expected, None)]


def test_dashboard_unknown_chart_or_private_recipe_value_is_not_recorded(recorded_events):
    dashboard_ui._record_closed_dashboard_choice(
        "customer chart label", dashboard_ui._DASHBOARD_CHART_ACTIONS
    )
    dashboard_ui._record_closed_dashboard_choice(
        "confidential theme name", dashboard_ui._DASHBOARD_RECIPE_ACTIONS
    )

    assert recorded_events == []


def test_dashboard_settings_record_only_closed_choices_and_booleans(recorded_events):
    dashboard_ui._record_accepted_dashboard_settings(
        {
            "recipe": "professional_contrast",
            "palette_preset": "viridis",
            "theme_name": "confidential local theme",
            "anchor_color": "#010203",
            "stat_lines": {"accent_by_stat": True},
        },
        marker_outline_enabled=False,
    )

    assert recorded_events == [
        (BugReportAction.OPTION_DASHBOARD_RECIPE_PROFESSIONAL_CONTRAST, None),
        (BugReportAction.OPTION_DASHBOARD_PALETTE_VIRIDIS, None),
        (BugReportAction.OPTION_DASHBOARD_STAT_ACCENT_ENABLED, True),
        (BugReportAction.OPTION_DASHBOARD_CUSTOM_PALETTE_ENABLED, False),
        (BugReportAction.OPTION_DASHBOARD_MARKER_OUTLINE_ENABLED, False),
    ]
    assert all(type(action) is BugReportAction for action, _enabled in recorded_events)
    assert all(enabled is None or type(enabled) is bool for _action, enabled in recorded_events)


def test_filter_selection_records_only_added_removed_action(recorded_events):
    class Item:
        def __init__(self, value):
            self.value = value

        def text(self):
            return self.value

    class ListWidget:
        def __init__(self, values):
            self.values = values

        def selectedItems(self):
            return [Item(value) for value in self.values]

    dialog = SimpleNamespace(
        _dimension_selections={},
        _refresh_choice_presentation=lambda _widget: None,
    )
    widget = ListWidget(["confidential value"])
    filter_ui.FilterDialog._normalize_dimension_selection(dialog, widget)
    widget.values = []
    filter_ui.FilterDialog._normalize_dimension_selection(dialog, widget)

    assert recorded_events == [
        (BugReportAction.WORKFLOW_EXPORT_FILTER_CRITERIA_ADDED, None),
        (BugReportAction.WORKFLOW_EXPORT_FILTER_CRITERIA_REMOVED, None),
    ]


def test_filter_submission_records_only_preset_enum_and_boolean(recorded_events):
    filter_ui._record_filter_submission_options(True, "Last 7 days")
    filter_ui._record_filter_submission_options(False, "private date range")

    assert recorded_events == [
        (BugReportAction.OPTION_EXPORT_FILTER_HAS_NOK_ONLY, True),
        (BugReportAction.OPTION_EXPORT_FILTER_DATE_LAST_SEVEN_DAYS, None),
        (BugReportAction.OPTION_EXPORT_FILTER_HAS_NOK_ONLY, False),
    ]


def test_group_member_removal_records_action_without_group_or_member_values(recorded_events):
    class Item:
        def data(self, _role):
            return "confidential member key"

    dialog = SimpleNamespace(
        part_group_list=SimpleNamespace(selectedItems=lambda: [Item()]),
        _selected_group_name=lambda: "confidential group",
        _selected_reference_name=lambda: "confidential reference",
        _reassign_group_keys_to_default=lambda *_args, **_kwargs: True,
    )
    grouping_ui.DataGrouping._delete_selected_parts_from_group(dialog)

    assert recorded_events == [
        (BugReportAction.WORKFLOW_EXPORT_GROUP_MEMBERS_UNASSIGNED, None)
    ]
