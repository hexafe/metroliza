"""Synthetic harness fixtures and behavior, including the pre-change identity contract."""

from argparse import Namespace
import re
from zipfile import ZipFile

import pandas as pd
import pytest

from scripts import benchmark_ui_flows as harness
from metroliza.tabular.tabular_xlsx_writer import write_tabular_dataframe


@pytest.mark.parametrize("name", sorted(harness.SCENARIOS))
def test_run_selects_only_grouped_analytics_observation_deadline(monkeypatch, name):
    scenario = harness.SCENARIOS[name]()
    scenario.action = lambda _ctx: None
    runner = harness._Run.__new__(harness._Run)
    runner.scenario = scenario
    runner.sampler = Namespace(start=lambda: None)
    runner.stall = Namespace(reset=lambda: None)
    runner.ctx = Namespace(mark=lambda _name: None)
    runner.poll_timer = Namespace(start=lambda: None)
    runner.profiler = None
    monkeypatch.setattr(harness, "cpu_seconds", lambda: {})
    monkeypatch.setattr(harness.time, "monotonic", lambda: 123.0)
    monkeypatch.setattr(harness.Clock, "start", lambda: None)
    runner.start()
    expected = 3600 if name == "csv_grouped_analytics" else 900
    assert runner.deadline == 123.0 + expected


@pytest.mark.parametrize("name", sorted(harness.SCENARIOS))
@pytest.mark.parametrize("joined_flag", [False, True])
def test_suite_selects_actual_outer_subprocess_deadline(tmp_path, monkeypatch, name, joined_flag):
    import json

    flags = [f"--scenario={name}"] if joined_flag else ["--scenario", name]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"label": "case", "args": flags}]))
    observed = []

    def run(command, **kwargs):
        observed.append((command, kwargs["timeout"]))
        return Namespace(returncode=0, stdout="")

    monkeypatch.setattr(harness.subprocess, "run", run)
    args = Namespace(out_dir=str(tmp_path / "out"), plan=str(plan), only="", runs=1,
                     data_dir=str(tmp_path / "data"))
    assert harness.suite(args) == 0
    expected = 3720 if name == "csv_grouped_analytics" else 1020
    assert len(observed) == 1 and observed[0][1] == expected
    assert observed[0][0][-len(flags):] == flags


def test_existing_csv_fixture_is_repeatable(tmp_path):
    args = Namespace(data_dir=str(tmp_path), csv_rows=24, industrial_rows=12,
                     industrial_db="missing.sqlite")
    harness.prepare(args)
    original = (tmp_path / "csv_0k.csv").read_bytes()
    harness.prepare(args)
    assert (tmp_path / "csv_0k.csv").read_bytes() == original
    assert len(original.splitlines()) == 25


def test_existing_workbook_identity_contract(tmp_path):
    frame = pd.DataFrame({"metric": [1.5, -0.0, float("inf"), None],
                          "label": ["alpha", "=literal", "https://example.invalid", "omega"]})
    paths = [tmp_path / name for name in ("a.xlsx", "b.xlsx")]
    for path in paths:
        with pd.ExcelWriter(path, engine="xlsxwriter", engine_kwargs={"options": {
            "strings_to_formulas": False, "strings_to_urls": False}}) as writer:
            write_tabular_dataframe(frame, writer, "Data")
    with ZipFile(paths[0]) as left, ZipFile(paths[1]) as right:
        assert left.namelist() == right.namelist()
        for name in left.namelist():
            a, b = left.read(name), right.read(name)
            if name == "docProps/core.xml":
                pattern = rb"(<dcterms:(?:created|modified)\b[^>]*>)[^<]*(</dcterms:(?:created|modified)>)"
                a, b = (re.sub(pattern, rb"\1TIME\2", value) for value in (a, b))
            else:
                assert left.getinfo(name).CRC == right.getinfo(name).CRC
            assert a == b, name


def test_prepare_builds_complete_synthetic_fixtures(tmp_path):
    from contextlib import closing
    import sqlite3
    from metroliza.parsing.pdf_backend import require_pdf_backend
    from metroliza.parsing.cmm_report_parser import CMMReportParser

    args = Namespace(data_dir=str(tmp_path), csv_rows=24, industrial_rows=12,
                     industrial_db="db_1500.sqlite", report_count=8, small_count=4,
                     pdf_count=2, measurements_per_report=2, groups=3)
    harness.prepare(args)
    with closing(sqlite3.connect(tmp_path / "db_1500.sqlite")) as connection:
        assert connection.execute("SELECT count(*) FROM report_measurements").fetchone() == (16,)
    assert (tmp_path / "db_small.sqlite").is_file()
    assert (tmp_path / "ind_0k.sqlite").is_file()
    groups = pd.read_csv(tmp_path / "csv_0k_groups.csv")
    assert groups.REPORT_ID.tolist() == list(range(1, 25))
    assert groups.GROUP.nunique() == 3
    pdfs = sorted((tmp_path / "pdf_1500").glob("*.pdf"))
    assert len(pdfs) == 2
    backend = require_pdf_backend()
    with backend.open(pdfs[0]) as document:
        assert "SYNTHETIC CMM" in document[0].get_text()
    from metroliza.parsing.parser_plugin_contracts import ProbeContext

    probe = CMMReportParser.probe(pdfs[0], ProbeContext(source_path=str(pdfs[0]), source_format="pdf"))
    assert probe.can_parse and probe.semantic_row_count == 2


def test_new_scenarios_smoke(tmp_path):
    import json
    from pathlib import Path
    import subprocess
    import sys

    data = tmp_path / "data"
    args = Namespace(data_dir=str(data), csv_rows=24, industrial_rows=12,
                     industrial_db="db_1500.sqlite", report_count=8, small_count=12,
                     pdf_count=2, measurements_per_report=2, groups=3)
    harness.prepare(args)
    # A real SMALL-scale export leaves substantial work after its first completed block.
    harness._prepare_report_db(data / "cancel.sqlite", 50, 3, 144)
    for name in ("csv_grouping_open", "csv_grouped_analytics", "export_cancel",
                 "csv_analytics_cancel", "group_analysis_export"):
        output = tmp_path / f"{name}.json"
        retained = tmp_path / f"{name}-outputs"
        home = tmp_path / f"{name}-home"
        home.mkdir()
        env = harness.private_environment(home)
        env["MPLCONFIGDIR"] = str(home / "mpl")
        command = [sys.executable, str(Path(harness.__file__).resolve()), "run", "--scenario", name,
                   "--data-dir", str(data), "--csv", "csv_0k.csv", "--out", str(output),
                   "--keep-output", str(retained), "--cancel-after-ms", "0"]
        if name == "group_analysis_export":
            command.extend(("--db", "db_small.sqlite"))
        elif name == "export_cancel":
            command.extend(("--db", "cancel.sqlite"))
        run = subprocess.run(command, env=env, cwd=home, capture_output=True, text=True, timeout=120)
        (tmp_path / f"{name}.log").write_text(run.stdout + run.stderr)
        assert run.returncode == 0, (name, run.stdout[-1000:], run.stderr[-2000:])
        result = json.loads(output.read_text())
        assert result["status"] == "ok", result
        assert retained.is_dir()
        assert result["retained_outputs"]
        if name.endswith("cancel"):
            assert result["worker_finished"] and result["output_residues"] == []
            assert result["thread_running_at_cancel"] is True
            assert result["cancel_processing_marker"].endswith(" returned")
            assert result["marks_ms"]["processing_completed"] <= result["marks_ms"]["work_started"]
            assert result["marks_ms"]["work_started"] <= result["marks_ms"]["cancel_requested"]
        elif name == "csv_grouping_open":
            assert result["assigned_rows"] == 24 and result["saved_groups"] == 3
            assert result["populated_groups"] >= 3
        elif name == "group_analysis_export":
            assert result["group_analysis_level"] == "standard"
            assert result["group_analysis_metrics"] > 0
            assert result["output_bytes"] > 0
        else:
            assert result["outputs"] and result["output_bytes"] > 0


def test_synthetic_report_shape_matches_measurement_cardinality():
    for references, expected_metrics in ((37, 2664), (3, 216)):
        reports = [harness._synthetic_report(index, references, 144) for index in range(references)]
        assert len({reference for reference, _ in reports}) == references
        metrics = {(row["header"], row["ax"]) for _, rows in reports for row in rows}
        assert len(metrics) == expected_metrics
        for _, rows in reports:
            assert len(rows) == 144
            assert len({row["header"] for row in rows}) == 18
            assert {row["ax"] for row in rows} == set("XYZD")


def test_retention_refuses_mixed_evidence_and_snapshots_sqlite(tmp_path):
    from contextlib import closing
    import sqlite3
    import pytest

    work = tmp_path / "work"
    work.mkdir()
    source = tmp_path / "source.sqlite"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE data(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO data VALUES (1, 'retained')")
        connection.commit()
    target = tmp_path / "retained"
    ctx = Namespace(work=work, args=Namespace(keep_output=str(target)))
    scenario = Namespace(dialog=Namespace(tabular_load_result=Namespace(sqlite_store=Namespace(path=str(source)))))
    result = {}
    harness._retain_outputs(ctx, scenario, result)
    assert result["retained_outputs"] == ["tabular.sqlite"]
    with closing(sqlite3.connect(target / "tabular.sqlite")) as connection:
        assert connection.execute("SELECT * FROM data").fetchall() == [(1, "retained")]
    with pytest.raises(FileExistsError):
        harness._retain_outputs(ctx, scenario, {})


def test_group_analysis_empty_payload_cannot_be_a_success(tmp_path):
    scenario = harness.GroupAnalysisExport()
    scenario.export = Namespace(export_thread=None)
    scenario.analysis_summary = harness._group_analysis_summary({"status": "ready", "metric_rows": []})
    scenario.analysis_result = Namespace(status="complete", artifacts=())
    ctx = Namespace(marks={"export_finished_end": 1}, work=tmp_path, extra={})
    with pytest.raises(RuntimeError, match="metric"):
        scenario.done(ctx)


def test_group_analysis_observes_real_payload_before_product_cleanup(tmp_path, monkeypatch):
    from metroliza.analytics.group_analysis_service import build_group_analysis_payload
    from metroliza.charts.export_html_dashboard import resolve_html_dashboard_path
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.exporting.export_outcomes import (
        ExportArtifactResult, ExportArtifactStatus, ExportRunResult, ExportRunStatus,
    )
    import metroliza.ui.export_dialog as module

    frame = pd.DataFrame({"REFERENCE": ["REF-1"] * 4, "HEADER - AX": ["DIA - X"] * 4,
                          "GROUP": ["A", "A", "B", "B"], "MEAS": [10.0, 10.2, 9.8, 9.9],
                          "LSL": [9.0] * 4, "NOMINAL": [10.0] * 4, "USL": [11.0] * 4})
    payload = build_group_analysis_payload(frame, requested_scope="single_reference",
                                           analysis_level="light", include_chart_payloads=False)
    assert payload["status"] == "ready" and payload["metric_rows"][0]["group_count"] == 2

    class Worker:
        _cleanup_dashboard_payloads = ExportDataThread._cleanup_dashboard_payloads

    worker = Worker()
    worker._html_group_analysis_payload = payload
    worker._html_dashboard_sections = [object()]
    worker._html_group_analysis_plot_assets = object()
    complete = ExportArtifactStatus.COMPLETE
    final_result = ExportRunResult(ExportRunStatus.COMPLETE, (
        ExportArtifactResult("group_analysis", "Group Analysis", complete, False),
        ExportArtifactResult("workbook", "Workbook", complete, True),
        ExportArtifactResult("html_dashboard", "Dashboard", complete, True),
    ), ())
    worker.export_run_result = None
    marks = {}
    ctx = Namespace(work=tmp_path, marks=marks, extra={}, pump=lambda condition: condition(),
                    mark=lambda name: marks.setdefault(name, 1))
    grouping = Namespace(df=frame.copy(), is_loading_grouping=lambda: False,
                         populate_list_widgets=lambda: None,
                         use_grouping_button=Namespace(click=lambda: None))
    export = Namespace(grouping_window=grouping, open_grouping_window=lambda: None,
                       _selected_group_analysis_level=lambda: "standard",
                       on_export_finished=lambda: marks.setdefault("export_finished_end", 1))
    monkeypatch.setattr(module, "create_export_data_thread", lambda: worker)
    original_factory = module.create_export_data_thread

    def setup(scenario, _ctx):
        scenario.export, scenario.output = export, tmp_path / "export.xlsx"
        scenario.output.write_bytes(b"workbook")
        resolve_html_dashboard_path(scenario.output).write_bytes(b"dashboard")

    def run():
        export.export_thread = module.create_export_data_thread()
        # The product releases the analysis before emitting completed.
        export.export_thread._cleanup_dashboard_payloads()
        assert worker._html_group_analysis_payload is None
        assert not worker._html_dashboard_sections
        assert worker._html_group_analysis_plot_assets is None
        worker.export_run_result = final_result
        export.on_export_finished()
        export.export_thread = None

    export.show_loading_screen = run
    monkeypatch.setattr(harness.ExportRun, "setup", setup)
    scenario = harness.GroupAnalysisExport()
    scenario.setup(ctx)
    scenario.action(ctx)
    assert scenario.done(ctx) and ctx.extra["group_analysis_metrics"] == len(payload["metric_rows"])
    assert module.create_export_data_thread is original_factory
    assert "_cleanup_dashboard_payloads" not in vars(worker)
    assert scenario.analysis_summary == {"status": "ready", "metric_count": 1,
                                         "minimum_group_count": 2}


@pytest.mark.parametrize("instance_override", [False, True])
@pytest.mark.parametrize("failure", [None, "capture", "cleanup"])
def test_group_analysis_observer_preserves_cleanup_and_restoration(instance_override, failure):
    calls = []
    result = object()

    class Worker:
        def _cleanup_dashboard_payloads(self):
            assert ("_cleanup_dashboard_payloads" in vars(self)) is instance_override
            calls.append("cleanup")
            self._html_group_analysis_payload = None
            if failure == "cleanup":
                raise ValueError("original cleanup failed")
            return result

    worker = Worker()
    if instance_override:
        worker._cleanup_dashboard_payloads = worker._cleanup_dashboard_payloads
    original = worker._cleanup_dashboard_payloads
    worker._html_group_analysis_payload = {"status": "ready", "metric_rows": [
        {"group_count": "bad" if failure == "capture" else 2, "image": object()}]}
    summary = harness._observe_group_analysis_cleanup(worker)
    assert not summary
    if failure == "cleanup":
        with pytest.raises(ValueError, match="original cleanup failed"):
            worker._cleanup_dashboard_payloads()
    else:
        assert worker._cleanup_dashboard_payloads() is result
    assert calls == ["cleanup"] and worker._html_group_analysis_payload is None
    assert worker._cleanup_dashboard_payloads == original
    assert ("_cleanup_dashboard_payloads" in vars(worker)) is instance_override
    assert all(value is None or isinstance(value, (str, int)) for value in summary.values())
    if failure == "capture":
        assert summary == {"capture_error": "ValueError"}
        with pytest.raises(RuntimeError, match="metrics"):
            harness._require_group_analysis(summary, None, ())


def test_group_analysis_factory_restored_when_action_fails(monkeypatch):
    import metroliza.ui.export_dialog as module

    original = module.create_export_data_thread

    def fail(*_args):
        assert module.create_export_data_thread is not original
        raise ValueError("action failed")

    monkeypatch.setattr(harness.ExportRun, "action", fail)
    with pytest.raises(ValueError, match="action failed"):
        harness.GroupAnalysisExport().action(None)
    assert module.create_export_data_thread is original


def test_initial_csv_label_does_not_start_cancellation():
    scenario = harness.CsvAnalyticsCancel()
    marks, starts = {}, []
    scenario.cancel_ctx = Namespace(marks=marks, extra={}, args=Namespace(cancel_after_ms=0),
                                    mark=lambda name: marks.setdefault(name, 0))
    scenario.cancel_timer = Namespace(start=lambda delay: starts.append(delay))
    scenario.work_started = False
    scenario._progress("Loading CSV/Excel data...\nChecking loaded rows and metric columns\nETA --")
    assert not starts and not scenario.work_started


def test_group_analysis_groups_are_populated_within_each_reference():
    references = ["A", "B", "A", "B", "A", "B", "A", "B"]
    groups = harness._balanced_reference_groups(references)
    for reference in set(references):
        assert {group for ref, group in zip(references, groups) if ref == reference} == {"G-000", "G-001"}
    with pytest.raises(RuntimeError, match="two reports per reference"):
        harness._balanced_reference_groups(["A", "B"])


@pytest.mark.parametrize("failure", [None, "one_group", "omissions", "group_output", "required_output",
                                    "missing_file", "empty_file", "skipped"])
def test_group_analysis_requires_actual_metrics_and_complete_outputs(tmp_path, failure):
    path = tmp_path / "export.xlsx"
    path.write_bytes(b"exported workbook")
    group = Namespace(artifact_id="group_analysis", status="complete", required=False)
    workbook = Namespace(artifact_id="workbook", status="complete", required=True)
    payload = {"status": "ready", "metric_rows": [{"group_count": 2}]}
    result = Namespace(status="complete", artifacts=(group, workbook))
    if failure == "one_group":
        payload["metric_rows"][0]["group_count"] = 1
    elif failure == "omissions":
        result.status = "complete_with_omissions"
    elif failure == "group_output":
        group.status = "omitted"
    elif failure == "required_output":
        workbook.status = "omitted"
    elif failure == "missing_file":
        path.unlink()
    elif failure == "empty_file":
        path.write_bytes(b"")
    elif failure == "skipped":
        payload["status"] = "skipped"
    scenario = harness.GroupAnalysisExport()
    scenario.export = Namespace(export_thread=None)
    scenario.analysis_summary, scenario.analysis_result = harness._group_analysis_summary(payload), result
    scenario.required_analysis_paths = (path,)
    ctx = Namespace(marks={"export_finished_end": 1}, work=tmp_path, extra={})
    if failure:
        with pytest.raises(RuntimeError):
            scenario.done(ctx)
    else:
        assert scenario.done(ctx) and ctx.extra["group_analysis_metrics"] == 1


def test_processing_probe_is_not_set_by_a_failed_call():
    def fail():
        assert not probe.completed.is_set()
        raise ValueError("processing failed")

    owner = Namespace(process=fail)
    probe = harness._CompletedProcessing(owner, "process")
    try:
        with pytest.raises(ValueError, match="processing failed"):
            owner.process()
        assert not probe.completed.is_set() and probe.completed_at is None
    finally:
        probe.restore()
    assert owner.process is fail


@pytest.mark.parametrize("kind", ["csv", "export"])
def test_cancellation_marker_follows_the_actual_processing_function(tmp_path, monkeypatch, kind):
    import importlib
    import io
    import xlsxwriter

    scenario = harness.CsvAnalyticsCancel() if kind == "csv" else harness.ExportCancel()
    module, name = scenario.processing_target
    owner = importlib.import_module(module)
    original = getattr(owner, name)
    calls = []

    def processing(*args, **kwargs):
        assert not probe.completed.is_set()
        result = original(*args, **kwargs)
        assert not probe.completed.is_set()
        calls.append("real processing returned")
        return result

    monkeypatch.setattr(owner, name, processing)
    probe = harness._CompletedProcessing(owner, name)
    scenario.processing_probe = probe
    scenario.work_started = scenario.worker_finished = False
    scenario.thread = Namespace(isRunning=lambda: True)
    starts, cancellations, marks = [], [], {}
    scenario.cancel_ctx = Namespace(marks=marks, extra={}, args=Namespace(cancel_after_ms=0),
                                    mark=lambda key: marks.setdefault(key, 0))
    scenario.cancel_timer = Namespace(start=lambda delay: starts.append(delay))
    scenario.cancel_callback = lambda: cancellations.append(True)
    scenario._progress("Loading CSV/Excel data...")
    scenario._arm_after_processing()
    scenario._request_cancel()
    assert not starts and not cancellations and not scenario.work_started
    assert scenario.worker_error == "cancellation mark precedes actual processing"
    try:
        if kind == "csv":
            from metroliza.tabular.tabular_analytics_service import (
                cleanup_tabular_load_result, load_tabular_analytics_file,
            )

            csv = tmp_path / "input.csv"
            csv.write_text("PART,DIM_01\nA,1.0\nB,2.0\nC,3.0\n")
            loaded = load_tabular_analytics_file(str(csv))
            try:
                result = getattr(owner, name)(loaded)
                assert len(result.dataframe) == 3
            finally:
                cleanup_tabular_load_result(loaded)
        else:
            from metroliza.exporting.export_sheet_writer import build_measurement_write_bundle

            frame = pd.DataFrame({"DATE": ["2024-01-01", "2024-01-02"], "SAMPLE_NUMBER": ["1", "2"],
                                  "MEAS": [10.1, 10.2], "NOM": [10.0, 10.0],
                                  "+TOL": [0.5, 0.5], "-TOL": [-0.5, -0.5]})
            with xlsxwriter.Workbook(io.BytesIO(), {"in_memory": True}) as workbook:
                worksheet = workbook.add_worksheet("Data")
                formats = {key: workbook.add_format() for key in ("percent", "wrap", "red")}
                result = getattr(owner, name)(worksheet, build_measurement_write_bundle("Metric - X", frame, 0),
                                              formats, base_col=0)
                assert result["data_start_row"] == 21
        assert calls == ["real processing returned"] and probe.completed.is_set()
        scenario.worker_error = None
        scenario._arm_after_processing()
        scenario._request_cancel()
        assert starts == [0] and cancellations == [True] and scenario.work_started
    finally:
        probe.restore()


def test_finished_worker_without_cancellation_ack_fails_promptly(tmp_path):
    import threading

    scenario = harness.ExportCancel()
    scenario.worker_finished = scenario.work_started = True
    scenario.cancelled, scenario.worker_error = False, None
    scenario.processing_probe = Namespace(completed=threading.Event())
    scenario.before = set()
    ctx = Namespace(marks={"cancel_requested": 1}, work=tmp_path)
    button = Namespace(isEnabled=lambda: True)
    with pytest.raises(RuntimeError, match="acknowledg"):
        scenario._idle(ctx, Namespace(loading_dialog=None), button)


@pytest.mark.parametrize("deleted", [False, True])
def test_stopped_thread_cannot_be_recorded_as_live_cancellation(deleted):
    import threading

    def running():
        if deleted:
            raise RuntimeError("wrapped C/C++ object has been deleted")
        return False

    scenario = harness.ExportCancel()
    completed = threading.Event()
    completed.set()
    scenario.processing_probe = Namespace(completed=completed)
    scenario.worker_finished = False
    scenario.thread = Namespace(isRunning=running)
    marks, requests = {}, []
    scenario.cancel_ctx = Namespace(marks=marks, extra={}, mark=lambda name: marks.setdefault(name, 0))
    scenario.cancel_callback = lambda: requests.append(True)
    scenario._request_cancel()
    assert not requests and "cancel_requested" not in marks
    assert "stopped" in scenario.worker_error
