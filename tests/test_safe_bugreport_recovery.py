"""Recovery of already-durable, content-free events after abrupt process exit."""

import os
from pathlib import Path
import subprocess
import sys

from metroliza.shared.safe_bugreport import BugReportAction, SafeBugReportRecorder


def test_durable_events_recovered_after_abrupt_process_exit(tmp_path):
    root = tmp_path / "history"
    code = '''
import os
from pathlib import Path
import sys
from metroliza.shared.safe_bugreport import BugReportAction, SafeBugReportRecorder
r = SafeBugReportRecorder()
assert r.configure_history(Path(sys.argv[1]))
assert r.record(BugReportAction.CSV_LOAD_FINISHED)
assert r.flush(5)
os._exit(0)
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(root)], cwd=Path(__file__).resolve().parents[1],
        env=os.environ.copy(), capture_output=True, timeout=15, check=False,
    )
    assert result.returncode == 0
    assert result.stdout == b"" and result.stderr == b""
    restored = SafeBugReportRecorder()
    try:
        assert restored.configure_history(root)
        assert restored.flush(5)
        snapshot = restored.snapshot()
        assert snapshot.previous_session_state == "available"
        assert any(e.action is BugReportAction.CSV_LOAD_FINISHED for e in snapshot.events)
    finally:
        assert restored.close_history(5)
