"""Temporary #998 hosted-only, no-core lifecycle discriminator; never a product tool."""

from __future__ import annotations

import ctypes
import http.client
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time

LIMIT = 65536
PHASES = {"bootstrap", "complete"}
MODES = {"exit0", "exit23", "output", "cancel", "timeout", "functional"}
EXPECTED_COUNTS = {"collected": 18, "passed": 18, "failed": 0, "skipped": 0, "errors": 0}
_CANCELLED = False


def _cancel(_signum, _frame):
    global _CANCELLED
    _CANCELLED = True


def _secure_child(parent_pid):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) or libc.prctl(1, signal.SIGKILL, 0, 0, 0):
        raise RuntimeError("containment_unavailable")
    if libc.prctl(3, 0, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        raise RuntimeError("containment_unavailable")


def _observed_exit(pid):
    # WNOWAIT reserves the leader PID/PGID until group cleanup is complete.
    info = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    if info is None:
        return None
    return info.si_status if info.si_code == os.CLD_EXITED else -info.si_status


def _other_members(pgid):
    members = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == pgid:
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == pgid:
                members.append(int(entry.name))
        except (FileNotFoundError, ProcessLookupError):
            pass
    return members


def _cleanup_group(process):
    # Never poll/reap the leader before the last group inspection/signal.
    deadline = time.monotonic() + 10
    term_deadline = time.monotonic() + 2
    os.killpg(process.pid, signal.SIGTERM)
    killed = False
    empty = False
    while time.monotonic() < deadline:
        if _observed_exit(process.pid) is not None and not _other_members(process.pid):
            empty = True
            break
        if not killed and time.monotonic() >= term_deadline:
            os.killpg(process.pid, signal.SIGKILL)
            killed = True
        time.sleep(0.01)
    code = _observed_exit(process.pid)
    if code is not None:
        process.wait(timeout=max(0.01, deadline - time.monotonic()))
    return code, empty


def _run(mode, root):
    folder = root / mode
    folder.mkdir(mode=0o700)
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(folder),
        "TMPDIR": str(folder),
        "LANG": "C.UTF-8",
        "QT_QPA_PLATFORM": "offscreen",
        "METROLIZA_EXPECT_QT_PLATFORM": "offscreen",
        "PYTHONPATH": "src:.",
        "PYTHONUNBUFFERED": "1",
        "PYTHONNOUSERSITE": "1",
        "MPLCONFIGDIR": str(folder / "mpl"),
    }
    process = None
    reason = "completed"
    code = None
    empty = False
    began = time.monotonic()
    sizes = [0, 0]
    try:
        with (folder / "out").open("xb") as output, (folder / "err").open("xb") as errors:
            process = subprocess.Popen(
                [sys.executable, __file__, "child", mode, str(folder), str(os.getpid())],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors,
                env=environment,
                start_new_session=True,
                close_fds=True,
            )
            deadline = began + (0.2 if mode == "timeout" else 180)
            while True:
                sizes = [os.fstat(stream.fileno()).st_size for stream in (output, errors)]
                if max(sizes) >= LIMIT:
                    reason = "output_limit"
                    break
                if _observed_exit(process.pid) is not None:
                    break
                if _CANCELLED or (mode == "cancel" and time.monotonic() - began > 0.2):
                    reason = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    reason = "timeout"
                    break
                time.sleep(0.01)
            code = _observed_exit(process.pid)
    except (OSError, ValueError):
        reason = "setup_failed"
    finally:
        if process is not None:
            try:
                observed, empty = _cleanup_group(process)
                if code is None:
                    code = observed
            except (OSError, ValueError, subprocess.SubprocessError):
                reason = "cleanup_failed"
        else:
            empty = True
    try:
        sizes = [(folder / name).stat().st_size for name in ("out", "err")]
    except OSError:
        reason = "capture_read_failed"
    if code == -signal.SIGXFSZ:
        reason = "private_file_limit"
    state = {}
    try:
        state_path = folder / "state.json"
        if state_path.stat().st_size <= 4096:
            candidate = json.loads(state_path.read_text())
            if isinstance(candidate, dict):
                state = candidate
    except (OSError, ValueError):
        pass
    # Only closed primitives leave the private directory.
    phase = state.get("phase") if state.get("phase") in PHASES else "bootstrap"
    no_core = state.get("no_core") is True
    credentials_absent = state.get("credentials_absent") is True
    counts = state.get("test_counts", {})
    counts = (
        {
            key: value
            for key, value in counts.items()
            if key in EXPECTED_COUNTS and type(value) is int and 0 <= value <= 1000
        }
        if isinstance(counts, dict)
        else {}
    )
    receipt = dict(
        mode=mode,
        phase=phase,
        returncode=code,
        signal=-code if code is not None and code < 0 else None,
        reason=reason,
        tree_empty=empty,
        no_core_verified=no_core,
        credentials_absent=credentials_absent,
        test_counts=counts,
        elapsed_s=round(time.monotonic() - began),
        output_sizes=sizes,
    )
    try:
        shutil.rmtree(folder)
    except OSError:
        reason = "cleanup_failed"
        receipt["reason"] = reason
    receipt["cleanup_complete"] = empty and not folder.exists()
    print(json.dumps(receipt, sort_keys=True), flush=True)
    if code not in (None, 0):
        return (128 - code if code < 0 else code), receipt
    status = (
        0
        if code == 0
        and reason == "completed"
        and receipt["cleanup_complete"]
        and no_core
        and credentials_absent
        else 70
    )
    if mode == "functional" and (phase != "complete" or counts != EXPECTED_COUNTS):
        status = 70
    return status, receipt


def _child(mode, folder, parent_pid):
    _secure_child(parent_pid)
    state = {
        "phase": "bootstrap",
        "no_core": resource.getrlimit(resource.RLIMIT_CORE) == (0, 0),
        "credentials_absent": not any(
            key.startswith(("GITHUB", "ACTIONS", "GH_")) or "TOKEN" in key or "SECRET" in key
            for key in os.environ
        ),
        "observations": [],
    }

    def record(phase):
        state["phase"] = phase
        (folder / "state.json").write_text(json.dumps(state))

    record("bootstrap")
    if mode in {"exit0", "exit23"}:
        return 23 if mode == "exit23" else 0
    if mode == "output":
        # Fill exactly the permitted bound, then wait for the controller.
        os.write(1, b"x" * LIMIT)
        time.sleep(30)
        return 0
    if mode in {"timeout", "cancel"}:
        time.sleep(30)
        return 0
    import pytest

    class CountReports:
        def __init__(self):
            self.counts = {key: 0 for key in EXPECTED_COUNTS}

        def pytest_collection_finish(self, session):
            self.counts["collected"] = len(session.items)

        def pytest_runtest_logreport(self, report):
            if report.skipped:
                self.counts["skipped"] += 1
            elif report.when == "call":
                self.counts["passed" if report.passed else "failed"] += 1
            elif report.failed:
                self.counts["errors"] += 1

    reports = CountReports()
    result = pytest.main(
        [
            "-q",
            "-s",
            "--tb=no",
            "--disable-warnings",
            "tests/test_export_presets.py::TestExportPresetFlowIntegration::test_selected_preset_changes_payload_deterministically",
            "tests/test_industrial_qt_lifecycle.py",
        ],
        plugins=[reports],
    )
    state["test_counts"] = reports.counts
    record("complete")
    return int(result)


def _github(route):
    connection = http.client.HTTPSConnection("api.github.com", timeout=15)
    try:
        connection.request(
            "GET",
            "/" + route,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "metroliza-998-public-admission",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("admission_http_status")
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("admission_response_limit")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("admission_schema")
        return result
    finally:
        connection.close()


def _admit():
    env = os.environ
    expected = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "hexafe/metroliza",
        "GITHUB_ACTOR": "hexafe",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/heads/fix/998-qt-stability",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux",
        "ImageOS": "ubuntu24",
    }
    if sys.platform != "linux" or any(env.get(key) != value for key, value in expected.items()):
        return False

    def git(*args):
        return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL, text=True).strip()

    if (
        git("rev-parse", "HEAD") != env["QT_CONTROL_HEAD"]
        or env["GITHUB_SHA"] != env["QT_CONTROL_HEAD"]
        or git("rev-parse", "HEAD^{tree}") != env["QT_CONTROL_TREE"]
    ):
        return False
    credentials = subprocess.run(
        ["git", "config", "--local", "--get-regexp", "extraheader"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if credentials.returncode != 1:
        return False
    repository = _github("repos/hexafe/metroliza")
    if (
        repository.get("private") is not False
        or repository.get("owner", {}).get("login") != "hexafe"
    ):
        return False
    phase = env["QT_CONTROL_PHASE"]
    if phase not in {"functional-6"}:
        return False
    title = "Qt lifetime " + phase + " "
    current = int(env["GITHUB_RUN_ID"])
    seen_current = False
    # Bounded complete recent history; refuse if pagination cannot prove uniqueness.
    for page in range(1, 6):
        rows = _github(
            f"repos/hexafe/metroliza/actions/workflows/ci.yml/runs?event=workflow_dispatch&per_page=100&page={page}"
        )["workflow_runs"]
        for row in rows:
            if row["id"] == current:
                seen_current = True
            elif row.get("display_title", "").startswith(title):
                return False
        if len(rows) < 100:
            return seen_current
    return False


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "child" and sys.argv[2] in MODES:
        return _child(sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]))
    root = None
    result = 70
    try:
        if not _admit():
            print('{"reason":"admission_refused"}', flush=True)
            return 70
        # The admission API is public and receives no token. Hide controller state.
        if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0):
            return 70
        signal.signal(signal.SIGTERM, _cancel)
        signal.signal(signal.SIGINT, _cancel)
        root = Path(tempfile.mkdtemp(prefix="qt-lifetime-private-", dir=os.environ["RUNNER_TEMP"]))
        root.chmod(0o700)
        for mode, expected in (
            ("exit0", "completed"),
            ("exit23", "completed"),
            ("output", "output_limit"),
            ("cancel", "cancelled"),
            ("timeout", "timeout"),
        ):
            _status, receipt = _run(mode, root)
            expected_code = 23 if mode == "exit23" else 0 if mode == "exit0" else -signal.SIGTERM
            if (
                receipt["reason"] != expected
                or receipt["returncode"] != expected_code
                or not receipt["cleanup_complete"]
                or not receipt["no_core_verified"]
                or not receipt["credentials_absent"]
            ):
                return 70
        result, receipt = _run("functional", root)
        if result or _CANCELLED:
            return result or 130
        print('{"functional_cases_passed":18,"native_process_completed":true}', flush=True)
        return 0
    except Exception:
        print('{"reason":"controller_incomplete"}', flush=True)
        return result if result else 70
    finally:
        if root is not None:
            try:
                shutil.rmtree(root)
                complete = not root.exists()
            except OSError:
                complete = False
            print(json.dumps({"private_cleanup_complete": complete}), flush=True)
            if not complete:
                # Cleanup failure must fail even after a successful workload.
                raise SystemExit(result if result else 70)


if __name__ == "__main__":
    raise SystemExit(main())
