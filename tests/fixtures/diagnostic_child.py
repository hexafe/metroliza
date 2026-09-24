"""Owned synthetic child for real pipe/process supervision tests; no business input."""

import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from metroliza.shared.diagnostic_events import (
    StartupCallsite, StartupDiagnosticEvent, StartupMode, StartupOutcome,
)
from metroliza.shared.diagnostic_transport import attach_child_recorder


def await_authenticated_marker(path: Path) -> bool:
    # A test-owned barrier, never a store file or a production launch behavior.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.is_file():
            return True
        time.sleep(0.01)
    return False


def main():
    scenario = sys.argv[1]
    if scenario == "early_exit":
        return 7
    recorder = attach_child_recorder()
    if recorder is None or not recorder.qualified:
        return 8
    event = StartupDiagnosticEvent(
        recorder.invocation_id, uuid.uuid4(), 1, StartupMode.UNKNOWN,
        StartupCallsite.BOOTSTRAP, StartupOutcome.INVOCATION_STARTED,
    )
    recorder.enqueue(event)
    if scenario in {"normal_after_marker", "hard_exit_after_marker"}:
        if not await_authenticated_marker(Path(sys.argv[2])):
            recorder.close()
            return 10
        scenario = "normal" if scenario == "normal_after_marker" else "hard_exit"
    # Allow the actual transport worker to deliver the safe event before loss.
    time.sleep(0.05)
    if scenario == "duplicate":
        recorder.enqueue(event)
    if scenario == "dropped":
        recorder.dropped = 2
    if scenario == "contended":
        with recorder._lock:
            recorder.enqueue(event)
    if scenario == "full_queue":
        from metroliza.shared.diagnostic_events import (
            WorkflowDiagnosticEvent, WorkflowOperation, WorkflowOutcome, WorkflowStage,
        )

        operation = uuid.uuid4()
        for sequence in range(1, 1001):
            recorder.enqueue(WorkflowDiagnosticEvent(
                recorder.invocation_id, operation, sequence, WorkflowOperation.LOCAL_EXPORT,
                WorkflowStage.OUTPUT_STAGING, WorkflowOutcome.MILESTONE,
            ))
    if scenario == "hard_exit":
        os._exit(9)
    if scenario == "numeric139":
        os._exit(139)
    if scenario == "raw_output":
        os.write(1, b"SYNTHETIC_RAW_SECRET\n" * 10000)
        os.write(2, b"SYNTHETIC_RAW_SECRET\n" * 10000)
    if scenario == "supervisor_loss":
        destination = Path(sys.argv[2])
        destination.with_suffix(".ready").write_text(str(os.getpid()), encoding="ascii")
        time.sleep(1.0)
        # A diagnostic pipe failure must not kill/replay this one product-side write.
        recorder.enqueue(event)
        with destination.open("a", encoding="ascii") as stream:
            stream.write("one_commit\n")
    recorder.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
