"""Match a closed safe report to a synthetic reference scenario.

Reports can be supplied on stdin, but only the canonical fixed-schema report is
accepted. The matcher reads only the closed action/category codes and boolean
states; it never interprets report text as a command, path, or input data. The
product loader may create a temporary SQLite store; that store and the temporary
XLSX are cleaned after use. A passing run validates a synthetic reference, not
the user's report, which contains no input data.
"""

from __future__ import annotations

import hashlib
import json
import math
import numbers
import re
import sys
import csv
from dataclasses import dataclass
from pathlib import Path
import tempfile

from metroliza.shared.safe_bugreport import (
    AGENT_REPORT_GUIDANCE, ERROR_LOG_NOTE, BugReportAction, BugReportCategory, MAX_REPORT_BYTES,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "windows_uiux" / "tabular"
CSV_FIXTURE = FIXTURE_ROOT / "analysis.csv"
ORACLE_FILE = FIXTURE_ROOT / "oracles.json"
FIXTURE_KEY = "analysis.csv"
EXPECTED_SHEETS = ("Table Data", "Metrics", "Diagnostics")
EXPECTED_GROUPS = ("SYNTHETIC_A", "SYNTHETIC_B")
EXPECTED_ROW_GROUPS = (
    (1, "SYNTHETIC_A"), (2, "SYNTHETIC_B"),
    (3, "SYNTHETIC_A"), (4, "SYNTHETIC_B"),
    (5, "SYNTHETIC_A"), (6, "SYNTHETIC_B"),
    (7, "SYNTHETIC_A"), (8, "SYNTHETIC_B"),
)
SCENARIO = "csv_grouping_xlsx_v1"
_VERSION_LINE = re.compile(r"Application version: `(?:UNKNOWN|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(?:-(?:dev|rc)\.[0-9]{1,3})?)`\Z")
_ACTIVITY_LINE = re.compile(r"- `([a-z_]+)`(?: \(enabled: `(true|false)`\))?\Z")
_BOOLEAN_ACTIONS = frozenset({
    BugReportAction.OPTION_WORKBOOK,
    BugReportAction.OPTION_HTML,
    BugReportAction.OPTION_GROUPING,
    BugReportAction.OPTION_CHARTS,
    BugReportAction.CHECK_CHARTS_PRESENT,
    BugReportAction.CHECK_WORKBOOK_REQUEST_MATCH,
    BugReportAction.CHECK_CHART_REQUEST_MATCH,
    BugReportAction.CHECK_FILTER_REQUEST_MATCH,
    BugReportAction.CHECK_GROUPING_REQUEST_MATCH,
    BugReportAction.OPTION_EXPORT_CLOUD,
    BugReportAction.OPTION_EXPORT_HTML,
    BugReportAction.OPTION_EXPORT_CONTEXT,
    BugReportAction.OPTION_HIDE_OK,
    BugReportAction.REALTIME_TEMPORARY_STORAGE,
    BugReportAction.PARSER_PROFILE_ENABLE_STATE,
    BugReportAction.OPTION_MAPPING_REPLACE_EXISTING,
    BugReportAction.OPTION_INDUSTRIAL_FETCH_ALL,
    BugReportAction.OPTION_INDUSTRIAL_SOURCE_ORDER_BY,
    BugReportAction.OPTION_INDUSTRIAL_LIVE_EXPORT,
    BugReportAction.OPTION_INDUSTRIAL_EXPORT_CHARTS,
    BugReportAction.OPTION_INDUSTRIAL_EXPORT_RAW,
    BugReportAction.OPTION_SYNC_REMEMBER_CREDENTIALS,
    BugReportAction.OPTION_EXPORT_FILTERS_APPLIED,
    BugReportAction.OPTION_EXPORT_GROUPING_APPLIED,
    BugReportAction.OPTION_EXPORT_DASHBOARD_VISUALS_ENABLED,
    BugReportAction.OPTION_INDUSTRIAL_ANALYTICS_WORKBOOK,
    BugReportAction.OPTION_INDUSTRIAL_ANALYTICS_DASHBOARD,
    BugReportAction.OPTION_INDUSTRIAL_ANALYTICS_GROUPING,
    BugReportAction.OPTION_INDUSTRIAL_ANALYTICS_CHARTS,
    BugReportAction.OPTION_EXPORT_FILTER_HAS_NOK_ONLY,
    BugReportAction.OPTION_REPORT_REVIEW_OCR,
    BugReportAction.OPTION_DASHBOARD_STAT_ACCENT_ENABLED,
    BugReportAction.OPTION_DASHBOARD_CUSTOM_PALETTE_ENABLED,
    BugReportAction.OPTION_DASHBOARD_MARKER_OUTLINE_ENABLED,
})
_CSV_SCENARIO_ACTIONS = frozenset({
    BugReportAction.APP_OPENED,
    BugReportAction.CSV_OPENED,
    BugReportAction.WORKSPACE_CSV_OPENED,
    BugReportAction.CSV_LOAD_STARTED,
    BugReportAction.CSV_LOAD_FINISHED,
    BugReportAction.CSV_LOAD_FAILED,
    BugReportAction.CSV_LOAD_CANCELLED,
    BugReportAction.FILTER_APPLIED,
    BugReportAction.GROUPING_APPLIED,
    BugReportAction.OPTION_WORKBOOK,
    BugReportAction.OPTION_HTML,
    BugReportAction.OPTION_GROUPING,
    BugReportAction.OPTION_CHARTS,
    BugReportAction.CHECK_CHARTS_PRESENT,
    BugReportAction.CHECK_WORKBOOK_REQUEST_MATCH,
    BugReportAction.CHECK_FILTER_REQUEST_MATCH,
    BugReportAction.CHECK_GROUPING_REQUEST_MATCH,
    BugReportAction.CHECK_CHART_REQUEST_MATCH,
    BugReportAction.OUTPUT_WITHOUT_REQUESTED_CHARTS,
    BugReportAction.ANALYSIS_STARTED,
    BugReportAction.ANALYSIS_FINISHED,
    BugReportAction.ANALYSIS_FINISHED_WITH_WARNINGS,
    BugReportAction.ANALYSIS_FAILED,
    BugReportAction.ANALYSIS_CANCELLED,
    BugReportAction.EXPORT_STARTED,
    BugReportAction.EXPORT_FINISHED,
    BugReportAction.EXPORT_FAILED,
    BugReportAction.EXPORT_CANCELLED,
    BugReportAction.PROBLEM_REPORTED,
})
_FIXED_LINES_BEFORE_ACTIVITY = (
    "# Metroliza bug report",
    "",
    None,  # validated release version
    "This report serializes only fixed action/category codes and boolean states.",
    "Coverage: selected CSV workflow actions in the current process only. Input data, paths, names, and configuration values are not included.",
    "Reproduction status: `NOT_RUN`",
    "External input data: `not included`",
    "",
    None,  # validated category
    None,  # validated event-loss flag
    "",
    "## Recent activity",
)
_CURRENT_COVERAGE = (
    "Coverage: selected actions across application workflows; not every action is recorded. "
    "Input data, paths, names, and free-text values are not included."
)
_PREVIOUS_COVERAGE = "Coverage: selected CSV workflow actions. Input data, paths, names, and configuration values are not included."
_CURRENT_ACTIVITY_HISTORY = "Activity history: retained local activity may include earlier launches."
_CURRENT_SESSION_BOUNDARIES = "Session boundaries: unknown; prior activity is not evidence of a crash."
_CURRENT_ASYNC_NOTE = "Recent activity is queued asynchronously and may not survive forced exit."


@dataclass(frozen=True)
class ScenarioMatch:
    status: str
    scenario: str
    category: str
    action_count: int


@dataclass(frozen=True)
class _ReportLayout:
    category_index: int
    lost_index: int
    activity_index: int
    previous_activity_state: str | None


@dataclass(frozen=True)
class _ParsedSafeReport:
    category: BugReportCategory
    events_lost: bool
    previous_activity_state: str | None
    actions: tuple[tuple[BugReportAction, bool | None], ...]


def _current_report_layout(lines: list[str]) -> _ReportLayout | None:
    if (len(lines) < 19 or lines[5] != _CURRENT_ACTIVITY_HISTORY
            or lines[6] != _CURRENT_SESSION_BOUNDARIES or lines[7] != _CURRENT_ASYNC_NOTE):
        return None
    offset = int(lines[8] == ERROR_LOG_NOTE)
    if (len(lines) < 19 + offset
            or lines[9 + offset:11 + offset] != [
                "Reproduction status: `NOT_RUN`", "External input data: `not included`"
            ] or lines[11 + offset] != ""):
        return None
    restored = re.fullmatch(
        r"Previous activity restored: `(unknown|available|not_available|loading)`",
        lines[8 + offset],
    )
    if restored is None:
        return None
    return _ReportLayout(12 + offset, 13 + offset, 15 + offset, restored.group(1))


def _legacy_report_layout(lines: list[str]) -> _ReportLayout | None:
    if len(lines) < 15 or lines[5:8] != list(_FIXED_LINES_BEFORE_ACTIVITY[5:8]):
        return None
    return _ReportLayout(8, 9, 11, None)


def _report_layout(lines: list[str]) -> _ReportLayout | None:
    if (len(lines) < 15 or lines[:2] != list(_FIXED_LINES_BEFORE_ACTIVITY[:2])
            or not _VERSION_LINE.fullmatch(lines[2])
            or lines[3] != _FIXED_LINES_BEFORE_ACTIVITY[3]):
        return None
    if lines[4] in {_CURRENT_COVERAGE, _PREVIOUS_COVERAGE}:
        return _current_report_layout(lines)
    if lines[4] == _FIXED_LINES_BEFORE_ACTIVITY[4]:
        return _legacy_report_layout(lines)
    return None


def _report_metadata(lines: list[str], layout: _ReportLayout):
    category_match = re.fullmatch(r"Category: `([a-z_]+)`", lines[layout.category_index])
    lost_match = re.fullmatch(r"Recorded events lost: `(true|false)`", lines[layout.lost_index])
    if (category_match is None or lost_match is None
            or lines[layout.lost_index + 1] != ""
            or lines[layout.activity_index] != "## Recent activity"):
        return None
    category = next((item for item in BugReportCategory if item.value == category_match.group(1)), None)
    if category is None:
        return None
    return category, lost_match.group(1) == "true"


def _report_actions(lines: list[str], layout: _ReportLayout):
    footer = ["", "## Reproduction", "Reproduction not performed. Input data was not captured."]
    full_footer = footer + list(AGENT_REPORT_GUIDANCE)
    if lines[-len(full_footer):] == full_footer:
        footer_size = len(full_footer)
    elif lines[-len(footer):] == footer:
        footer_size = len(footer)
    else:
        return None
    if len(lines) < layout.activity_index + footer_size + 1:
        return None
    actions: list[tuple[BugReportAction, bool | None]] = []
    for line in lines[layout.activity_index + 1:-footer_size]:
        match = _ACTIVITY_LINE.fullmatch(line)
        if match is None:
            return None
        action = next((item for item in BugReportAction if item.value == match.group(1)), None)
        if action is None:
            return None
        enabled = None if match.group(2) is None else match.group(2) == "true"
        if (action in _BOOLEAN_ACTIONS) != (enabled is not None):
            return None
        actions.append((action, enabled))
    return tuple(actions)


def _parse_safe_report(report: object) -> _ParsedSafeReport | None:
    try:
        if type(report) is not str or len(report.encode("utf-8")) > MAX_REPORT_BYTES:
            return None
        lines = report.splitlines()
        layout = _report_layout(lines)
        if layout is None:
            return None
        metadata = _report_metadata(lines, layout)
        actions = _report_actions(lines, layout)
        if metadata is None or actions is None:
            return None
        category, events_lost = metadata
        return _ParsedSafeReport(category, events_lost, layout.previous_activity_state, actions)
    except Exception:
        return None


def _analysis_bounds(
    actions: tuple[tuple[BugReportAction, bool | None], ...], previous_activity_state: str
) -> tuple[int, int, int] | None:
    analysis_indices = [
        index for index, (action, _enabled) in enumerate(actions)
        if action is BugReportAction.ANALYSIS_STARTED
    ]
    if not analysis_indices:
        return None
    analysis_index = analysis_indices[-1]
    session_start = -1
    if previous_activity_state == "available":
        app_open_indices = [
            index for index, (action, _enabled) in enumerate(actions)
            if action is BugReportAction.APP_OPENED and index < analysis_index
        ]
        if not app_open_indices:
            return None
        session_start = app_open_indices[-1]
    previous_indices = [
        index for index in analysis_indices if session_start < index < analysis_index
    ]
    previous_analysis_index = previous_indices[-1] if previous_indices else session_start
    return session_start, previous_analysis_index, analysis_index


def _operation_has_grouping_workbook(
    actions: tuple[tuple[BugReportAction, bool | None], ...],
    session_start: int,
    previous_analysis_index: int,
    analysis_index: int,
) -> bool:
    operation = actions[previous_analysis_index + 1:analysis_index]
    last_options: dict[BugReportAction, bool] = {}
    for action, enabled in operation:
        if action in {BugReportAction.OPTION_WORKBOOK, BugReportAction.OPTION_GROUPING}:
            assert enabled is not None
            last_options[action] = enabled
    grouping_applied = any(
        action is BugReportAction.GROUPING_APPLIED
        for action, _enabled in actions[session_start + 1:analysis_index]
    )
    return (grouping_applied
            and last_options.get(BugReportAction.OPTION_WORKBOOK) is True
            and last_options.get(BugReportAction.OPTION_GROUPING) is True)


def _scenario_matches(report: _ParsedSafeReport) -> bool:
    state = report.previous_activity_state
    if report.events_lost or state not in {"available", "not_available"}:
        return False
    bounds = _analysis_bounds(report.actions, state)
    if bounds is None:
        return False
    # A later action in another module means the observed problem may have
    # occurred there. Do not silently match stale CSV activity to that report.
    if any(action not in _CSV_SCENARIO_ACTIONS for action, _ in report.actions[bounds[2] + 1:]):
        return False
    return _operation_has_grouping_workbook(report.actions, *bounds)


def match_safe_bugreport(report: object) -> ScenarioMatch:
    """Match canonical report codes only; never return any input text."""
    parsed = _parse_safe_report(report)
    if parsed is None:
        return ScenarioMatch("REPORT_REJECTED", "none", "unknown", 0)
    if _scenario_matches(parsed):
        return ScenarioMatch("SCENARIO_MATCHED", SCENARIO, parsed.category.value, len(parsed.actions))
    return ScenarioMatch("NO_SCENARIO_MATCH", "none", parsed.category.value, len(parsed.actions))


@dataclass(frozen=True)
class ReproductionResult:
    status: str
    scenario: str
    input_kind: str
    row_count: int
    group_count: int
    workbook_sheet_count: int
    reproduced_report: bool = False


@dataclass(frozen=True)
class ReportRunResult:
    match_status: str
    scenario: str
    input_kind: str
    reference_status: str
    category: str
    action_count: int
    reproduced_report: bool = False


def _fixture_is_pinned() -> bool:
    try:
        oracle = json.loads(ORACLE_FILE.read_text(encoding="utf-8"))
        expected = oracle.get("files", {}).get(FIXTURE_KEY)
        if type(expected) is not str or len(expected) != 64:
            return False
        digest = hashlib.sha256(CSV_FIXTURE.read_bytes()).hexdigest()
        return digest == expected
    except Exception:
        # Paths and parser details are intentionally excluded from the report.
        return False


def _expected_fixture_rows() -> tuple[tuple[object, ...], ...]:
    """Read the pinned synthetic input independently of the product loader."""
    with CSV_FIXTURE.open(newline="", encoding="utf-8-sig") as stream:
        rows = tuple(csv.DictReader(stream))
    if len(rows) != len(EXPECTED_ROW_GROUPS):
        return ()
    expected_groups = dict(EXPECTED_ROW_GROUPS)
    return tuple(
        (
            index,
            row["Operator lot code"],
            row["Captured at"],
            row["Line"],
            float(row["Value"]),
            expected_groups[index],
        )
        for index, row in enumerate(rows, start=1)
    )


def _is_exact_numeric_identifier(value: object, expected: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    return math.isfinite(value) and value == expected and int(value) == expected


def _grouped_row_ids_match(dataframe, expected: tuple[tuple[int, str], ...]) -> bool:
    if "GROUP" not in dataframe.columns:
        return False
    rows = tuple(dataframe[["source_row_number", "GROUP"]].itertuples(index=False, name=None))
    return len(rows) == len(expected) and all(
        _is_exact_numeric_identifier(actual_id, expected_id) and actual_group == expected_group
        for (actual_id, actual_group), (expected_id, expected_group) in zip(rows, expected, strict=True)
    )


def _exported_rows_match(actual_rows: tuple[tuple[object, ...], ...],
                         expected_rows: tuple[tuple[object, ...], ...]) -> bool:
    return len(actual_rows) == len(expected_rows) and all(
        _is_exact_numeric_identifier(actual[0], expected[0]) and actual[1:] == expected[1:]
        for actual, expected in zip(actual_rows, expected_rows, strict=True)
    )


def _workbook_matches_fixture(output: Path, expected_rows: tuple[tuple[object, ...], ...]) -> tuple[bool, int]:
    from openpyxl import load_workbook

    workbook = load_workbook(output, read_only=True, data_only=True)
    try:
        sheets = tuple(workbook.sheetnames)
        if sheets != EXPECTED_SHEETS:
            return False, len(sheets)
        table = workbook["Table Data"]
        headers = tuple(next(table.iter_rows(values_only=True)))
        expected_columns = (
            "source_row_number", "operator_lot_code", "captured_at", "line", "value", "GROUP"
        )
        if any(column not in headers for column in expected_columns):
            return False, len(sheets)
        column_indexes = tuple(headers.index(column) for column in expected_columns)
        actual_rows = tuple(
            tuple(row[index] for index in column_indexes)
            for row in table.iter_rows(min_row=2, values_only=True)
        )
        return _exported_rows_match(actual_rows, expected_rows), len(sheets)
    finally:
        workbook.close()


def run_synthetic_csv_grouping_repro() -> ReproductionResult:
    """Exercise product CSV loading, grouping, and XLSX writer on fixed data."""
    if not _fixture_is_pinned():
        return ReproductionResult("FIXTURE_INVALID", "csv_grouping_xlsx_v1", "synthetic", 0, 0, 0)

    loaded = None
    result = ReproductionResult("RUN_FAILED", "csv_grouping_xlsx_v1", "synthetic", 0, 0, 0, False)
    try:
        import pandas as pd
        from metroliza.industrial.industrial_analytics_state import ProductionChartSelection
        from metroliza.tabular.tabular_analytics_service import (
            apply_tabular_grouping,
            cleanup_tabular_load_result,
            export_tabular_analytics_workbook,
            load_tabular_analytics_file,
        )

        loaded = load_tabular_analytics_file(CSV_FIXTURE)
        frame = loaded.dataframe
        expected_rows = _expected_fixture_rows()
        if not isinstance(frame, pd.DataFrame) or len(frame) != 8 or len(expected_rows) != 8:
            status = "FIXTURE_INVALID" if len(expected_rows) != 8 else "LOAD_MISMATCH"
            result = ReproductionResult(status, "csv_grouping_xlsx_v1", "synthetic", 0, 0, 0)
        else:
            grouping = pd.DataFrame({
                "REPORT_ID": tuple(row_number for row_number, _group in EXPECTED_ROW_GROUPS),
                "GROUP": tuple(group for _row_number, group in EXPECTED_ROW_GROUPS),
            })
            grouped = apply_tabular_grouping(frame, grouping)
            if not grouped.applied or grouped.group_count != 2:
                result = ReproductionResult("GROUPING_MISMATCH", "csv_grouping_xlsx_v1", "synthetic", len(frame),
                                            grouped.group_count, 0)
            elif not _grouped_row_ids_match(grouped.dataframe, EXPECTED_ROW_GROUPS):
                result = ReproductionResult("GROUPING_MISMATCH", "csv_grouping_xlsx_v1", "synthetic", len(frame),
                                            grouped.group_count, 0)
            else:
                with tempfile.TemporaryDirectory(prefix="metroliza-safe-repro-") as temporary:
                    output = Path(temporary) / "synthetic.xlsx"
                    written = export_tabular_analytics_workbook(
                        dataframe=grouped.dataframe,
                        metric_candidates=loaded.metric_candidates,
                        output_file=output,
                        separate_parameter_sheets=False,
                        chart_selection=ProductionChartSelection(
                            time_series=False, histogram=False, violin=False, box=False, groupstats=False,
                        ),
                    )
                    workbook_matches, sheet_count = _workbook_matches_fixture(output, expected_rows)
                    if not workbook_matches:
                        result = ReproductionResult("WORKBOOK_MISMATCH", "csv_grouping_xlsx_v1", "synthetic", len(frame),
                                                    grouped.group_count, sheet_count)
                    elif written.sheet_names != EXPECTED_SHEETS:
                        result = ReproductionResult("WORKBOOK_MISMATCH", "csv_grouping_xlsx_v1", "synthetic", len(frame),
                                                    grouped.group_count, sheet_count)
                    else:
                        result = ReproductionResult("REFERENCE_PASS", "csv_grouping_xlsx_v1", "synthetic", len(frame), 2,
                                                    len(EXPECTED_SHEETS), False)
    except Exception:
        # Error strings may include user-controlled paths or values; report only a fixed status.
        result = ReproductionResult("RUN_FAILED", "csv_grouping_xlsx_v1", "synthetic", 0, 0, 0, False)
    finally:
        if loaded is not None:
            try:
                cleanup_tabular_load_result(loaded)
            except Exception:
                # Cleanup failure is surfaced only as a fixed code as well.
                result = ReproductionResult("RUN_FAILED", "csv_grouping_xlsx_v1", "synthetic", 0, 0, 0, False)
    return result


def run_report_matched_synthetic_repro(report: object) -> ReportRunResult:
    """Run only a prebuilt scenario selected by valid closed report codes."""
    match = match_safe_bugreport(report)
    if match.status != "SCENARIO_MATCHED":
        return ReportRunResult(match.status, "none", "synthetic", "NOT_RUN",
                               match.category, match.action_count, False)
    result = run_synthetic_csv_grouping_repro()
    return ReportRunResult(match.status, match.scenario, "synthetic", result.status,
                           match.category, match.action_count, False)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--report-stdin"]:
        try:
            report = sys.stdin.read(MAX_REPORT_BYTES + 1)
        except Exception:
            report = ""
        result = run_report_matched_synthetic_repro(report)
        print(json.dumps({
            "match_status": result.match_status,
            "scenario": result.scenario,
            "input_kind": result.input_kind,
            "reference_status": result.reference_status,
            "category": result.category,
            "action_count": result.action_count,
            "reproduced_report": result.reproduced_report,
        }, sort_keys=True))
        return 0 if result.reference_status == "REFERENCE_PASS" else 1
    if arguments:
        print(json.dumps({"status": "INVALID_ARGUMENTS"}, sort_keys=True))
        return 2
    result = run_synthetic_csv_grouping_repro()
    print(json.dumps({
        "status": result.status,
        "scenario": result.scenario,
        "input_kind": result.input_kind,
        "row_count": result.row_count,
        "group_count": result.group_count,
        "workbook_sheet_count": result.workbook_sheet_count,
        "reproduced_report": result.reproduced_report,
    }, sort_keys=True))
    return 0 if result.status == "REFERENCE_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
