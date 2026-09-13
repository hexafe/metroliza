import io
import json
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from metroliza.app.diagnostic_supervisor import launch_supervised
from metroliza.shared.diagnostic_events import WorkflowOperation, WorkflowStage
from metroliza.shared.logging_utils import ManagedSafeFormatter
from metroliza.shared.workflow_diagnostics import start_workflow_trace


@pytest.fixture
def events():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(ManagedSafeFormatter())
    logger = logging.getLogger("metroliza.shared.workflow_diagnostics")
    old_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield lambda: [json.loads(line.split(" ", 2)[2]) for line in stream.getvalue().splitlines()]
    logger.removeHandler(handler)
    logger.setLevel(old_level)


@pytest.mark.parametrize("imported,failed,changed,cancelled,outcome,error", [
    (1, 0, 0, False, "completed", "none"),
    (1, 1, 0, False, "completed_with_warnings", "processing_failed"),
    (1, 0, 1, False, "completed_with_warnings", "input_rejected"),
    (0, 0, 1, False, "failed", "input_rejected"),
    (1, 0, 0, True, "cancelled", "none"),
])
def test_import_terminal_preserves_committed_partial_results(events, imported, failed, changed, cancelled, outcome, error):
    trace = start_workflow_trace(WorkflowOperation.SELECTED_IMPORT)
    trace.stage(WorkflowStage.PREFLIGHT_COMPLETE, selected_report_count=imported + failed + changed)
    trace.finish_import(SimpleNamespace(
        imported_files=imported, failed_files=failed, preflight_changed_files=changed,
        cancelled_files=0, already_present_files=0,
    ), cancelled)
    terminal = events()[-1]
    assert terminal["outcome"] == outcome
    assert terminal["error"] == error
    assert terminal["imported_report_count"] == imported
    assert terminal["selected_report_count"] == imported + failed + changed
    assert terminal["validation_status"] == "not_performed"


def test_emission_failure_never_replaces_the_product_result(monkeypatch):
    logger = logging.getLogger("metroliza.shared.workflow_diagnostics")
    def fail(*args, **kwargs):
        raise OSError("SYNTHETIC_SECRET")
    monkeypatch.setattr(logger, "log", fail)
    trace = start_workflow_trace(WorkflowOperation.LOCAL_EXPORT)
    assert trace.finish_export(completed=True, cancelled=False) is None


@pytest.mark.parametrize("scenario,expected", [("normal", 0), ("hard_exit", 9)])
def test_real_selected_import_and_local_export_survive_child_loss(tmp_path, scenario, expected):
    script = Path(__file__).parent / "fixtures" / "diagnostic_workflow_child.py"
    env = dict(os.environ, METROLIZA_STARTUP_SMOKE="1", METROLIZA_LICENSE_VERIFICATION="0")
    root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    result = launch_supervised([sys.executable, str(script), str(tmp_path), scenario], env=env, cwd=tmp_path)
    assert result.exit_code == expected
    history = [json.loads(event) for event in result.history.events]
    assert any(event["event_code"] == "runtime_provenance" for event in history)
    workflows = [event for event in history if event["event_code"] == "workflow_diagnostic"]
    for operation, stages in (
        ("selected_import", ["started", "preflight_complete", "processing", "persistence_complete", "finished"]),
        ("local_export", ["started", "output_staging", "output_published", "finished"]),
    ):
        rows = [event for event in workflows if event["operation"] == operation]
        assert [event["stage"] for event in rows] == stages
        assert rows[-1]["outcome"] == "completed"
        assert all(event["validation_status"] == "not_performed" for event in rows)
        assert len({event["operation_id"] for event in rows}) == 1
    assert "SYNTHETIC_PRIVATE_FILENAME" not in repr(history)
    assert not (tmp_path / "metroliza.log").exists()
