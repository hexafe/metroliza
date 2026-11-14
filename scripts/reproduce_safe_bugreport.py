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
import re
import sys
from dataclasses import dataclass
from pathlib import Path
import tempfile

from metroliza.shared.safe_bugreport import BugReportAction, BugReportCategory, MAX_REPORT_BYTES


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "windows_uiux" / "tabular"
CSV_FIXTURE = FIXTURE_ROOT / "analysis.csv"
ORACLE_FILE = FIXTURE_ROOT / "oracles.json"
FIXTURE_KEY = "analysis.csv"
EXPECTED_SHEETS = ("Table Data", "Metrics", "Diagnostics")
EXPECTED_GROUPS = ("SYNTHETIC_A", "SYNTHETIC_B")
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
_CURRENT_COVERAGE = "Coverage: selected CSV workflow actions. Input data, paths, names, and configuration values are not included."
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
            or lines[6] != _CURRENT_SESSION_BOUNDARIES or lines[7] != _CURRENT_ASYNC_NOTE
            or lines[9:11] != ["Reproduction status: `NOT_RUN`", "External input data: `not included`"]
            or lines[11] != ""):
        return None
    restored = re.fullmatch(
        r"Previous activity restored: `(unknown|available|not_available|loading)`",
        lines[8],
    )
    if restored is None:
        return None
    return _ReportLayout(12, 13, 15, restored.group(1))


def _legacy_report_layout(lines: list[str]) -> _ReportLayout | None:
    if len(lines) < 15 or lines[5:8] != list(_FIXED_LINES_BEFORE_ACTIVITY[5:8]):
        return None
    return _ReportLayout(8, 9, 11, None)


def _report_layout(lines: list[str]) -> _ReportLayout | None:
    if (len(lines) < 15 or lines[:2] != list(_FIXED_LINES_BEFORE_ACTIVITY[:2])
            or not _VERSION_LINE.fullmatch(lines[2])
            or lines[3] != _FIXED_LINES_BEFORE_ACTIVITY[3]):
        return None
    if lines[4] == _CURRENT_COVERAGE:
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
    if len(lines) < layout.activity_index + 4 or lines[-3:] != footer:
        return None
    actions: list[tuple[BugReportAction, bool | None]] = []
    for line in lines[layout.activity_index + 1:-3]:
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


def run_synthetic_csv_grouping_repro() -> ReproductionResult:
    """Exercise product CSV loading, grouping, and XLSX writer on fixed data."""
    if not _fixture_is_pinned():
        return ReproductionResult("FIXTURE_INVALID", "csv_grouping_xlsx_v1", "synthetic", 0, 0, 0)

    loaded = None
    result = ReproductionResult("RUN_FAILED", "csv_grouping_xlsx_v1", "synthetic", 0, 0, 0, False)
    try:
        import pandas as pd
        from openpyxl import load_workbook

        from metroliza.industrial.industrial_analytics_state import ProductionChartSelection
        from metroliza.tabular.tabular_analytics_service import (
            apply_tabular_grouping,
            cleanup_tabular_load_result,
            export_tabular_analytics_workbook,
            load_tabular_analytics_file,
        )

        loaded = load_tabular_analytics_file(CSV_FIXTURE)
        frame = loaded.dataframe
        if not isinstance(frame, pd.DataFrame) or len(frame) != 8:
            result = ReproductionResult("LOAD_MISMATCH", "csv_grouping_xlsx_v1", "synthetic", 0, 0, 0)
        else:
            grouping = pd.DataFrame({
                "REPORT_ID": tuple(range(1, 9)),
                "GROUP": ("SYNTHETIC_A", "SYNTHETIC_B") * 4,
            })
            grouped = apply_tabular_grouping(frame, grouping)
            if not grouped.applied or grouped.group_count != 2:
                result = ReproductionResult("GROUPING_MISMATCH", "csv_grouping_xlsx_v1", "synthetic", len(frame),
                                            grouped.group_count, 0)
            elif "GROUP" not in grouped.dataframe.columns or set(grouped.dataframe["GROUP"]) != set(EXPECTED_GROUPS):
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
                    workbook = load_workbook(output, read_only=True, data_only=True)
                    try:
                        sheets = tuple(workbook.sheetnames)
                        table = workbook["Table Data"]
                        headers = tuple(next(table.iter_rows(values_only=True)))
                        group_column = headers.index("GROUP")
                        groups = {
                            row[group_column]
                            for row in table.iter_rows(min_row=2, values_only=True)
                        }
                        rows = sum(1 for _ in table.iter_rows(min_row=2, values_only=True))
                    finally:
                        workbook.close()
                    if sheets != EXPECTED_SHEETS or groups != set(EXPECTED_GROUPS) or rows != 8:
                        result = ReproductionResult("WORKBOOK_MISMATCH", "csv_grouping_xlsx_v1", "synthetic", len(frame),
                                                    grouped.group_count, len(sheets))
                    elif written.sheet_names != EXPECTED_SHEETS:
                        result = ReproductionResult("WORKBOOK_MISMATCH", "csv_grouping_xlsx_v1", "synthetic", len(frame),
                                                    grouped.group_count, len(sheets))
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
