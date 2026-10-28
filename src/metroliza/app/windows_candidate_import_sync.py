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
    deadline = time.monotonic() + 45.0
    operation = click_import(workspace)
    wait_import_started(app, operation, seconds=max(0, deadline - time.monotonic()))
    return wait_import_finished(app, operation, seconds=max(0, deadline - time.monotonic()))
