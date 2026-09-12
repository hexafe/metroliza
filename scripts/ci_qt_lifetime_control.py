"""Temporary #998 hosted-only, no-core lifecycle discriminator; never a product tool."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

LIMIT = 65536
PHASES = {"bootstrap", "preflight", "a_loaded", "b_visible", "a_closed", "collected", "complete", "cleanup_incomplete"}
MODES = {"exit0", "exit23", "output", "cancel", "timeout", "preflight", "reference", "worker_gc"}
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
        "PATH": "/usr/bin:/bin", "HOME": str(folder), "TMPDIR": str(folder),
        "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": "src:.",
        "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1", "MPLCONFIGDIR": str(folder / "mpl"),
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
                stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                env=environment, start_new_session=True, close_fds=True,
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
    observations = state.get("observations", [])
    if not isinstance(observations, list):
        observations = []
    observations = [item for item in observations[:4] if item in
                    ["parent:gui", "parent:worker", "parent:other", "progress:gui", "progress:worker", "progress:other", "control:gui"]]
    no_core = state.get("no_core") is True
    credentials_absent = state.get("credentials_absent") is True
    receipt = dict(mode=mode, phase=phase, returncode=code,
                   signal=-code if code is not None and code < 0 else None,
                   reason=reason, tree_empty=empty, no_core_verified=no_core,
                   credentials_absent=credentials_absent, observations=observations,
                   elapsed_s=round(time.monotonic() - began), output_sizes=sizes)
    try:
        shutil.rmtree(folder)
    except OSError:
        reason = "cleanup_failed"
        receipt["reason"] = reason
    receipt["cleanup_complete"] = empty and not folder.exists()
    print(json.dumps(receipt, sort_keys=True), flush=True)
    if code not in (None, 0):
        return (128 - code if code < 0 else code), receipt
    status = 0 if code == 0 and reason == "completed" and receipt["cleanup_complete"] and no_core and credentials_absent else 70
    return status, receipt


def _child(mode, folder, parent_pid):
    _secure_child(parent_pid)
    state = {"phase": "bootstrap", "no_core": resource.getrlimit(resource.RLIMIT_CORE) == (0, 0),
             "credentials_absent": not any(key.startswith(("GITHUB", "ACTIONS", "GH_")) or "TOKEN" in key or "SECRET" in key for key in os.environ),
             "observations": []}

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
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QTimer, Qt
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    gui_ident = threading.get_ident()
    worker_ident = [None]
    callbacks = []

    def watch(obj, label):
        def destroyed():
            ident = threading.get_ident()
            affinity = "gui" if ident == gui_ident else "worker" if ident == worker_ident[0] else "other"
            state["observations"].append(label + ":" + affinity)
        callbacks.append(destroyed)
        obj.destroyed.connect(destroyed, Qt.ConnectionType.DirectConnection)

    if mode == "preflight":
        control = QObject()
        watch(control, "control")
        control.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert state["observations"] == ["control:gui"]
        record("preflight")
        return 0

    from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog, SOURCE_TABULAR_FILE
    from metroliza.industrial import industrial_workers
    original_loader = industrial_workers.load_tabular_analytics_files
    release = threading.Event()
    collected = threading.Event()
    active = [False]

    def gated_loader(*args, **kwargs):
        worker_ident[0] = threading.get_ident()
        if not release.wait(15):
            raise RuntimeError("barrier_timeout")
        if active[0] and mode == "worker_gc":
            import gc
            gc.collect()
        collected.set()
        return original_loader(*args, **kwargs)

    industrial_workers.load_tabular_analytics_files = gated_loader
    source = folder / "synthetic.csv"
    source.write_text("TraceCode,Batch,Length mm\nTC-001,B1,10.0\nTC-002,B1,10.2\nTC-003,B2,10.4\n")

    def wait_until(predicate):
        loop = QEventLoop()
        poller = QTimer()
        timeout = QTimer()
        timeout.setSingleShot(True)
        poller.timeout.connect(lambda: loop.quit() if predicate() else None)
        timeout.timeout.connect(loop.quit)
        poller.start(10)
        timeout.start(10000)
        if not predicate():
            loop.exec()
        poller.stop()
        timeout.stop()
        assert predicate(), "gui_barrier_timeout"

    def start_load():
        dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
        dialog.input_file = str(source)
        dialog.load_metrics()
        wait_until(lambda: dialog.loading_dialog.isVisible())
        return dialog

    a = b = None
    try:
        a = start_load()
        watch(a, "parent")
        watch(a.loading_dialog, "progress")
        release.set()
        wait_until(lambda: a.tabular_load_thread is None)
        assert a.tabular_load_result.row_count == 3
        record("a_loaded")
        release.clear()
        collected.clear()
        active[0] = True
        b = start_load()
        record("b_visible")
        assert a.close(), "close_failed"
        a = None
        record("a_closed")
        release.set()
        # Scheduling control only: let the gated worker collect before GUI allocations.
        assert collected.wait(10), "collection_timeout"
        record("collected")
        wait_until(lambda: b.tabular_load_thread is None)
        assert b.tabular_load_result.row_count == 3
        record("complete")
        return 42 if any(item.endswith((":worker", ":other")) for item in state["observations"]) else 0
    finally:
        release.set()
        industrial_workers.load_tabular_analytics_files = original_loader
        # Child cleanup is useful on normal exits; the controller owns crash cleanup.
        for dialog in (a, b):
            if dialog is not None and not sip.isdeleted(dialog):
                thread = dialog.tabular_load_thread
                if thread is not None and not sip.isdeleted(thread):
                    try:
                        thread.cancel()
                        joined = thread.wait(10000)
                    except Exception:
                        joined = False
                    if not joined:
                        try:
                            record("cleanup_incomplete")
                        finally:
                            os._exit(71)
                dialog.close()
                dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _github(route):
    request = urllib.request.Request("https://api.github.com/" + route, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "metroliza-998-public-admission",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("admission_response_limit")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("admission_schema")
        return result


def _admit():
    env = os.environ
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "hexafe/metroliza",
                "GITHUB_ACTOR": "hexafe", "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_REF": "refs/heads/fix/998-qt-stability",
                "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux", "ImageOS": "ubuntu24"}
    if sys.platform != "linux" or any(env.get(key) != value for key, value in expected.items()):
        return False
    def git(*args):
        return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL, text=True).strip()
    if git("rev-parse", "HEAD") != env["QT_CONTROL_HEAD"] or env["GITHUB_SHA"] != env["QT_CONTROL_HEAD"] or git("rev-parse", "HEAD^{tree}") != env["QT_CONTROL_TREE"]:
        return False
    credentials = subprocess.run(["git", "config", "--local", "--get-regexp", "extraheader"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if credentials.returncode != 1:
        return False
    repository = _github("repos/hexafe/metroliza")
    if repository.get("private") is not False or repository.get("owner", {}).get("login") != "hexafe":
        return False
    phase = env["QT_CONTROL_PHASE"]
    if phase not in {"lifetime-1"}:
        return False
    title = "Qt lifetime " + phase + " "
    current = int(env["GITHUB_RUN_ID"])
    seen_current = False
    # Bounded complete recent history; refuse if pagination cannot prove uniqueness.
    for page in range(1, 6):
        rows = _github(f"repos/hexafe/metroliza/actions/workflows/ci.yml/runs?event=workflow_dispatch&per_page=100&page={page}")["workflow_runs"]
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
        for mode, expected in (("exit0", "completed"), ("exit23", "completed"),
                               ("output", "output_limit"), ("cancel", "cancelled"),
                               ("timeout", "timeout")):
            _status, receipt = _run(mode, root)
            expected_code = 23 if mode == "exit23" else 0 if mode == "exit0" else -signal.SIGTERM
            if receipt["reason"] != expected or receipt["returncode"] != expected_code or not receipt["cleanup_complete"] or not receipt["no_core_verified"] or not receipt["credentials_absent"]:
                return 70
        for mode in ("preflight", "reference", "worker_gc"):
            result, _receipt = _run(mode, root)
            if result or _CANCELLED:
                return result or 130
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
