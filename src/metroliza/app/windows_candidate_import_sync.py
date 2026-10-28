"""Observe the exact UI-requested import, including a deferred or fast start."""
from __future__ import annotations

import time

IMPORT_FAILURES = frozenset({
    "import_not_accepted", "import_start_deadline", "import_deadline",
    "import_worker_error", "import_cancelled", "import_result_missing",
    "import_worker_join_deadline",
})


class ImportSyncFailure(ValueError):
    """Closed, path-free import observation failure."""


def click_import(workspace):
    previous = workspace.import_operation
    workspace.parse_button.click()
    operation = workspace.import_operation
    if operation is None or operation is previous:
        raise ImportSyncFailure("import_not_accepted")
    return operation


def wait_import_started(app, operation, *, seconds=45.0):
    from metroliza.app.windows_candidate_qualification import _wait

    _wait(app, lambda: operation.worker is not None or operation.terminal,
          deadline_s=seconds, stage="import_start")
    if operation.worker is None:
        raise ImportSyncFailure("import_cancelled" if operation.cancelled else "import_worker_error")
    return operation.worker


def wait_import_finished(app, operation, *, seconds=45.0, require_success=True):
    from metroliza.app.windows_candidate_qualification import _wait
    from PyQt6.QtCore import QDeadlineTimer, Qt

    deadline = time.monotonic() + seconds
    _wait(app, lambda: operation.terminal, deadline_s=seconds, stage="import")
    worker = operation.worker
    if worker is not None:
        _wait(app, lambda: worker.wait(QDeadlineTimer.current(Qt.TimerType.PreciseTimer)),
              deadline_s=max(0, deadline - time.monotonic()),
              stage="import_worker_join")
    if require_success:
        if operation.failed:
            raise ImportSyncFailure("import_worker_error")
        if operation.cancelled:
            raise ImportSyncFailure("import_cancelled")
        if operation.result is None:
            raise ImportSyncFailure("import_result_missing")
    return operation.result


def run_ui_import(workspace, app):
    from metroliza.app.windows_candidate_qualification import DEADLINES_S

    deadline = time.monotonic() + DEADLINES_S["import"]
    operation = click_import(workspace)
    wait_import_started(app, operation, seconds=max(0, deadline - time.monotonic()))
    return wait_import_finished(app, operation, seconds=max(0, deadline - time.monotonic()))


def slice_failure_codes(error, failure_type, *, import_code, cleanup_code):
    """Project import/cleanup errors to fixed slice codes without private text."""
    from metroliza.app.windows_candidate_native_check import CLEANUP_FAILURES, ReportOwnerCleanupFailure
    from metroliza.app.windows_candidate_qualification import ScenarioFailure

    cleanup = []
    if isinstance(error, ReportOwnerCleanupFailure):
        code = error.cleanup_failure
        cleanup = [cleanup_code, code if type(code) is str and code in CLEANUP_FAILURES
                   else "candidate_report_cleanup_failed"]
        error = error.primary
    if error is None:
        return cleanup
    if isinstance(error, failure_type):
        primary = [str(error)]
    elif isinstance(error, (ImportSyncFailure, ScenarioFailure)):
        code = str(error)
        primary = [import_code, code if code in IMPORT_FAILURES else "import_worker_error"]
    else:
        primary = ["unexpected_exception"]
    return primary + cleanup
