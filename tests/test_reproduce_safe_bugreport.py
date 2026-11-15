from dataclasses import fields, replace
import json
from io import StringIO
from pathlib import Path
import sys
import tempfile

import pytest

from scripts import reproduce_safe_bugreport
from scripts.reproduce_safe_bugreport import (
    match_safe_bugreport,
    run_report_matched_synthetic_repro,
    run_synthetic_csv_grouping_repro,
)
from metroliza.shared.safe_bugreport import (
    BugReportAction,
    BugReportCategory,
    SafeBugReportRecorder,
    build_bug_report_markdown,
)


def _grouping_workbook_report(extra_actions=()):
    recorder = SafeBugReportRecorder()
    for action in (BugReportAction.CSV_LOAD_STARTED, BugReportAction.CSV_LOAD_FINISHED,
                   BugReportAction.GROUPING_APPLIED):
        recorder.record(action)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    for action in extra_actions:
        recorder.record(action, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    return build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, recorder.snapshot())


def test_synthetic_csv_grouping_xlsx_reference_uses_product_pipeline():
    result = run_synthetic_csv_grouping_repro()

    assert result.status == "REFERENCE_PASS"
    assert result.scenario == "csv_grouping_xlsx_v1"
    assert result.input_kind == "synthetic"
    assert result.row_count == 8
    assert result.group_count == 2
    assert result.workbook_sheet_count == 3
    assert result.reproduced_report is False
    assert {item.name for item in fields(result)} == {
        "status", "scenario", "input_kind", "row_count", "group_count",
        "workbook_sheet_count", "reproduced_report",
    }


def test_synthetic_reference_rejects_swapped_row_group_assignments(monkeypatch):
    from metroliza.tabular import tabular_analytics_service as service

    real_grouping = service.apply_tabular_grouping

    def swapped_grouping(*args, **kwargs):
        result = real_grouping(*args, **kwargs)
        dataframe = result.dataframe.copy()
        dataframe["GROUP"] = dataframe["GROUP"].map({
            "SYNTHETIC_A": "SYNTHETIC_B",
            "SYNTHETIC_B": "SYNTHETIC_A",
        })
        assert len(dataframe) == 8
        assert set(dataframe["GROUP"]) == {"SYNTHETIC_A", "SYNTHETIC_B"}
        return replace(result, dataframe=dataframe)

    monkeypatch.setattr(service, "apply_tabular_grouping", swapped_grouping)

    result = run_synthetic_csv_grouping_repro()

    assert result.status == "GROUPING_MISMATCH"
    assert result.row_count == 8
    assert result.group_count == 2
    assert result.reproduced_report is False


def test_synthetic_reference_rejects_boolean_grouping_row_identity(monkeypatch):
    from metroliza.tabular import tabular_analytics_service as service

    real_grouping = service.apply_tabular_grouping

    def boolean_row_identity(*args, **kwargs):
        result = real_grouping(*args, **kwargs)
        dataframe = result.dataframe.copy()
        dataframe["source_row_number"] = dataframe["source_row_number"].astype(object)
        dataframe.at[dataframe.index[0], "source_row_number"] = True
        assert dataframe.iloc[0]["source_row_number"] is True
        assert len(dataframe) == 8 and set(dataframe["GROUP"]) == {"SYNTHETIC_A", "SYNTHETIC_B"}
        return replace(result, dataframe=dataframe)

    monkeypatch.setattr(service, "apply_tabular_grouping", boolean_row_identity)

    result = run_synthetic_csv_grouping_repro()

    assert result.status == "GROUPING_MISMATCH"
    assert result.row_count == 8
    assert result.group_count == 2
    assert result.reproduced_report is False


def test_synthetic_reference_rejects_wrong_exported_value_with_same_shape(monkeypatch):
    from openpyxl import load_workbook
    from metroliza.tabular import tabular_analytics_service as service

    real_export = service.export_tabular_analytics_workbook

    def export_with_wrong_value(*args, **kwargs):
        written = real_export(*args, **kwargs)
        output = kwargs["output_file"]
        workbook = load_workbook(output)
        sheet = workbook["Table Data"]
        value_column = next(
            index for index, cell in enumerate(sheet[1], start=1) if cell.value == "value"
        )
        sheet.cell(row=2, column=value_column).value = 0
        workbook.save(output)
        workbook.close()
        old_check = load_workbook(output, read_only=True, data_only=True)
        try:
            table = old_check["Table Data"]
            headers = tuple(next(table.iter_rows(values_only=True)))
            groups = {row[headers.index("GROUP")] for row in table.iter_rows(min_row=2, values_only=True)}
            rows = sum(1 for _ in table.iter_rows(min_row=2, values_only=True))
            assert tuple(old_check.sheetnames) == reproduce_safe_bugreport.EXPECTED_SHEETS
            assert groups == set(reproduce_safe_bugreport.EXPECTED_GROUPS)
            assert rows == 8
        finally:
            old_check.close()
        return written

    monkeypatch.setattr(service, "export_tabular_analytics_workbook", export_with_wrong_value)

    result = run_synthetic_csv_grouping_repro()

    assert result.status == "WORKBOOK_MISMATCH"
    assert result.row_count == 8
    assert result.group_count == 2
    assert result.workbook_sheet_count == 3
    assert result.reproduced_report is False


def test_synthetic_reference_rejects_boolean_xlsx_row_identity(monkeypatch):
    from openpyxl import load_workbook
    from metroliza.tabular import tabular_analytics_service as service

    real_export = service.export_tabular_analytics_workbook

    def export_with_boolean_identity(*args, **kwargs):
        written = real_export(*args, **kwargs)
        output = kwargs["output_file"]
        workbook = load_workbook(output)
        sheet = workbook["Table Data"]
        row_column = next(
            index for index, cell in enumerate(sheet[1], start=1)
            if cell.value == "source_row_number"
        )
        sheet.cell(row=2, column=row_column).value = True
        workbook.save(output)
        workbook.close()
        return written

    monkeypatch.setattr(service, "export_tabular_analytics_workbook", export_with_boolean_identity)

    result = run_synthetic_csv_grouping_repro()

    assert result.status == "WORKBOOK_MISMATCH"
    assert result.row_count == 8
    assert result.group_count == 2
    assert result.workbook_sheet_count == 3
    assert result.reproduced_report is False


def test_closed_report_codes_select_only_prebuilt_synthetic_scenario():
    report = _grouping_workbook_report()
    match = match_safe_bugreport(report)

    assert match.status == "SCENARIO_MATCHED"
    assert match.scenario == "csv_grouping_xlsx_v1"
    assert match.category == "wrong_output"
    assert match.action_count == 6

    result = run_report_matched_synthetic_repro(report)
    assert result.match_status == "SCENARIO_MATCHED"
    assert result.reference_status == "REFERENCE_PASS"
    assert result.input_kind == "synthetic"
    assert result.reproduced_report is False


def test_report_without_required_actions_does_not_run_a_scenario(monkeypatch):
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.CSV_OPENED)
    report = build_bug_report_markdown(BugReportCategory.OTHER, recorder.snapshot())
    monkeypatch.setattr(
        reproduce_safe_bugreport,
        "run_synthetic_csv_grouping_repro",
        lambda: pytest.fail("unmatched reports must not launch a scenario"),
    )

    result = run_report_matched_synthetic_repro(report)

    assert result.match_status == "NO_SCENARIO_MATCH"
    assert result.reference_status == "NOT_RUN"
    assert result.reproduced_report is False


def test_later_non_csv_workflow_does_not_match_stale_csv_activity():
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    recorder.record(BugReportAction.ANALYSIS_FINISHED)
    recorder.record(BugReportAction.WORKSPACE_REALTIME_OPENED)
    recorder.record(BugReportAction.REALTIME_TEMPORARY_STORAGE, enabled=True)
    recorder.record(BugReportAction.REALTIME_POLL_FAILED)

    result = match_safe_bugreport(
        build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, recorder.snapshot())
    )

    assert result.status == "NO_SCENARIO_MATCH"
    assert result.scenario == "none"


def test_preloaded_source_can_match_from_analysis_event_without_csv_load():
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)

    result = match_safe_bugreport(
        build_bug_report_markdown(BugReportCategory.MISSING_OUTPUT, recorder.snapshot())
    )

    assert result.status == "SCENARIO_MATCHED"
    assert result.scenario == "csv_grouping_xlsx_v1"


@pytest.mark.parametrize("restored_state", ["unknown", "loading"])
def test_restored_or_unknown_prior_history_never_selects_a_scenario(restored_state):
    recorder = SafeBugReportRecorder()
    for action in (BugReportAction.GROUPING_APPLIED, BugReportAction.OPTION_WORKBOOK,
                   BugReportAction.OPTION_GROUPING, BugReportAction.ANALYSIS_STARTED):
        if action in {BugReportAction.OPTION_WORKBOOK, BugReportAction.OPTION_GROUPING}:
            recorder.record(action, enabled=True)
        else:
            recorder.record(action)
    snapshot = replace(recorder.snapshot(), previous_session_state=restored_state)

    result = match_safe_bugreport(build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, snapshot))

    assert result.status == "NO_SCENARIO_MATCH"
    assert result.scenario == "none"


def test_restored_available_matches_only_after_current_app_open_marker():
    recorder = SafeBugReportRecorder()
    # Persisted events from an earlier launch must not supply current options.
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    recorder.record(BugReportAction.APP_OPENED)
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    snapshot = replace(recorder.snapshot(), previous_session_state="available")

    result = match_safe_bugreport(build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, snapshot))

    assert result.status == "SCENARIO_MATCHED"
    assert result.scenario == "csv_grouping_xlsx_v1"


def test_restored_available_can_match_last_analysis_before_restart():
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.APP_OPENED)
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    recorder.record(BugReportAction.ANALYSIS_FINISHED)
    recorder.record(BugReportAction.APP_OPENED)
    snapshot = replace(recorder.snapshot(), previous_session_state="available")

    result = match_safe_bugreport(build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, snapshot))

    assert result.status == "SCENARIO_MATCHED"
    assert result.scenario == "csv_grouping_xlsx_v1"


def test_restored_available_never_uses_prior_session_options_after_restart():
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    recorder.record(BugReportAction.APP_OPENED)
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=False)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    snapshot = replace(recorder.snapshot(), previous_session_state="available")

    result = match_safe_bugreport(build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, snapshot))

    assert result.status == "NO_SCENARIO_MATCH"
    assert result.scenario == "none"
    run_result = run_report_matched_synthetic_repro(
        build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, snapshot)
    )
    assert run_result.reference_status == "NOT_RUN"


def test_prior_session_grouping_cannot_complete_current_session():
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.APP_OPENED)
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    recorder.record(BugReportAction.APP_OPENED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    snapshot = replace(recorder.snapshot(), previous_session_state="available")

    result = match_safe_bugreport(build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, snapshot))

    assert result.status == "NO_SCENARIO_MATCH"


def test_restored_available_without_app_open_marker_does_not_match():
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    snapshot = replace(recorder.snapshot(), previous_session_state="available")

    result = match_safe_bugreport(build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, snapshot))

    assert result.status == "NO_SCENARIO_MATCH"
    assert result.scenario == "none"


def test_untrusted_text_in_current_metadata_blank_line_is_rejected():
    marker = "SECRET_PATH_MARKER=/private/customer.csv"
    report = _grouping_workbook_report().replace(
        "External input data: `not included`\n\nCategory:",
        f"External input data: `not included`\n{marker}\nCategory:",
    )

    result = match_safe_bugreport(report)

    assert result.status == "REPORT_REJECTED"
    assert marker not in json.dumps({field.name: getattr(result, field.name) for field in fields(result)})


def test_lost_activity_never_selects_a_scenario():
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    snapshot = replace(recorder.snapshot(), events_lost=True)

    result = match_safe_bugreport(build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, snapshot))

    assert result.status == "NO_SCENARIO_MATCH"
    assert result.scenario == "none"


def test_latest_analysis_uses_only_its_own_options_when_workbook_was_turned_off():
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    recorder.record(BugReportAction.ANALYSIS_FINISHED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=False)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)

    result = match_safe_bugreport(build_bug_report_markdown(
        BugReportCategory.WRONG_OUTPUT, recorder.snapshot()
    ))

    assert result.status == "NO_SCENARIO_MATCH"
    assert result.scenario == "none"


def test_later_analysis_reuses_grouping_applied_earlier_in_same_session():
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    recorder.record(BugReportAction.ANALYSIS_FINISHED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(BugReportAction.ANALYSIS_STARTED)

    result = match_safe_bugreport(
        build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, recorder.snapshot())
    )

    assert result.status == "SCENARIO_MATCHED"
    assert result.scenario == "csv_grouping_xlsx_v1"


@pytest.mark.parametrize(
    "marker",
    [
        "SECRET_PATH_MARKER=/home/private/customer.csv",
        "SECRET_COMMAND_MARKER=rm -rf /",
        "SECRET_VALUE_MARKER=confidential-product-value",
    ],
)
def test_untrusted_report_text_is_rejected_without_echo_or_scenario_run(monkeypatch, marker):
    report = _grouping_workbook_report().replace(
        "- `csv_load_started`", f"- `csv_load_started`\n{marker}"
    )
    monkeypatch.setattr(
        reproduce_safe_bugreport,
        "run_synthetic_csv_grouping_repro",
        lambda: pytest.fail("rejected report must not launch a scenario"),
    )

    result = run_report_matched_synthetic_repro(report)
    rendered = json.dumps(result.__dict__ if hasattr(result, "__dict__") else {
        field.name: getattr(result, field.name) for field in fields(result)
    })

    assert result.match_status == "REPORT_REJECTED"
    assert result.reference_status == "NOT_RUN"
    assert marker not in rendered


def test_unrecognized_action_or_boolean_shape_fails_closed():
    report = _grouping_workbook_report().replace(
        "- `csv_load_started`", "- `csv_load_started` (enabled: `true`)"
    )
    result = match_safe_bugreport(report)
    assert result.status == "REPORT_REJECTED"
    assert result.scenario == "none"


@pytest.mark.parametrize(
    "action",
    [
        BugReportAction.OPTION_CHARTS,
        BugReportAction.CHECK_CHARTS_PRESENT,
        BugReportAction.CHECK_WORKBOOK_REQUEST_MATCH,
        BugReportAction.CHECK_CHART_REQUEST_MATCH,
        BugReportAction.CHECK_FILTER_REQUEST_MATCH,
        BugReportAction.CHECK_GROUPING_REQUEST_MATCH,
    ],
)
def test_ui_boolean_actions_with_exact_boolean_state_are_accepted(action):
    report = _grouping_workbook_report((action,))

    match = match_safe_bugreport(report)

    assert match.status == "SCENARIO_MATCHED"
    assert match.action_count == 7


@pytest.mark.parametrize(
    "action",
    [
        BugReportAction.OPTION_CHARTS,
        BugReportAction.CHECK_CHARTS_PRESENT,
        BugReportAction.CHECK_WORKBOOK_REQUEST_MATCH,
        BugReportAction.CHECK_CHART_REQUEST_MATCH,
        BugReportAction.CHECK_FILTER_REQUEST_MATCH,
        BugReportAction.CHECK_GROUPING_REQUEST_MATCH,
    ],
)
def test_ui_boolean_actions_without_boolean_state_are_rejected(action):
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.CSV_LOAD_FINISHED)
    recorder.record(BugReportAction.GROUPING_APPLIED)
    recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    recorder.record(BugReportAction.OPTION_GROUPING, enabled=True)
    recorder.record(action)
    recorder.record(BugReportAction.ANALYSIS_STARTED)
    report = build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, recorder.snapshot())

    assert match_safe_bugreport(report).status == "REPORT_REJECTED"


def test_report_cli_reads_only_bounded_stdin_and_reports_reference_status(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", StringIO(_grouping_workbook_report()))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        reproduce_safe_bugreport,
        "run_synthetic_csv_grouping_repro",
        lambda: reproduce_safe_bugreport.ReproductionResult(
            "REFERENCE_PASS", "csv_grouping_xlsx_v1", "synthetic", 8, 2, 3, False
        ),
    )

    assert reproduce_safe_bugreport.main(["--report-stdin"]) == 0
    output = capsys.readouterr().out
    assert '"reference_status": "REFERENCE_PASS"' in output
    assert '"reproduced_report": false' in output


@pytest.mark.parametrize("oracle_contents", [None, "{broken json", "{}"])
def test_missing_or_invalid_oracle_returns_fixed_code_without_path_or_traceback(
    monkeypatch, tmp_path, capsys, oracle_contents
):
    oracle = tmp_path / "controlled-oracle.json"
    if oracle_contents is not None:
        oracle.write_text(oracle_contents, encoding="utf-8")
    monkeypatch.setattr(reproduce_safe_bugreport, "ORACLE_FILE", oracle)

    assert reproduce_safe_bugreport.main([]) == 1

    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "FIXTURE_INVALID"
    assert str(tmp_path) not in output
    assert "Traceback" not in output


@pytest.mark.parametrize("fail_after_load", [False, True])
def test_product_loader_result_is_cleaned_after_success_and_post_load_error(monkeypatch, fail_after_load):
    from metroliza.tabular import tabular_analytics_service as service

    loaded_results = []
    cleanup_calls = []
    temporary_directories = []
    store_paths = []
    real_load = service.load_tabular_analytics_file
    real_cleanup = service.cleanup_tabular_load_result
    real_temporary_directory = tempfile.TemporaryDirectory

    def temporary_directory_and_track(*args, **kwargs):
        directory = real_temporary_directory(*args, **kwargs)
        temporary_directories.append(directory.name)
        return directory

    def load_and_track(*args, **kwargs):
        kwargs["force_sqlite"] = True
        loaded = real_load(*args, **kwargs)
        loaded_results.append(loaded)
        return loaded

    def cleanup_and_track(loaded):
        cleanup_calls.append(loaded)
        if loaded.sqlite_store is not None:
            store_paths.extend(Path(loaded.sqlite_store.path + suffix)
                               for suffix in ("", "-wal", "-shm", "-journal"))
        real_cleanup(loaded)

    monkeypatch.setattr(service, "load_tabular_analytics_file", load_and_track)
    monkeypatch.setattr(service, "cleanup_tabular_load_result", cleanup_and_track)
    monkeypatch.setattr(reproduce_safe_bugreport.tempfile, "TemporaryDirectory", temporary_directory_and_track)
    if fail_after_load:
        monkeypatch.setattr(
            service,
            "apply_tabular_grouping",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic controlled failure")),
        )

    result = run_synthetic_csv_grouping_repro()

    assert len(loaded_results) == 1
    assert cleanup_calls == loaded_results
    assert loaded_results[0].sqlite_store is not None
    assert store_paths
    assert all(not path.exists() for path in store_paths)
    assert all(not Path(path).exists() for path in temporary_directories)
    assert result.status == ("RUN_FAILED" if fail_after_load else "REFERENCE_PASS")
