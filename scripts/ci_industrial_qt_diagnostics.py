"""Observe the existing Linux industrial coverage shard once; never retry it.

Issue #998 permits this diagnostic observation, not a claimed lifecycle repair.
The default path retains sanitized text only. The separately admitted hosted
mode inspects private guest cores after termination, then removes all raw data.
"""

from __future__ import annotations

from datetime import datetime
import importlib.metadata
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import stat
import time


def _sanitize(text: str) -> str:
    from metroliza.industrial.industrial_data_repository import redact_sensitive_text

    roots = {
        str(Path.cwd()): "<checkout>",
        sys.prefix: "<python>",
        sys.base_prefix: "<base-python>",
        str(Path.home()): "<home>",
        tempfile.gettempdir(): "<tmp>",
    }
    for root in sorted(roots, key=len, reverse=True):
        text = text.replace(root, roots[root])
    # Native debug symbols may name a different machine's build-user home.
    text = re.sub(
        r"(?:/(?:home|Users)/|[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/])"
        r"[^\s'\"<>:]+",
        lambda match: "<source>/" + re.split(r"[\\/]", match.group())[-1],
        text,
    )
    return redact_sensitive_text(text, max_len=None)


def _debugger_script(status_path: Path) -> str:
    # These commands execute inside GDB, outside the pytest interpreter. In
    # particular, no Qt imports, signal connections or GC observers are added.
    return f"""set pagination off
set confirm off
set auto-load off
set debuginfod enabled off
set startup-with-shell off
set disable-randomization off
set print frame-arguments none
set print entry-values no
python
import gdb, json
initial_stop_signal = None
def record_stop(event):
    global initial_stop_signal
    if isinstance(event, gdb.SignalEvent) and initial_stop_signal is None:
        initial_stop_signal = event.stop_signal
gdb.events.stop.connect(record_stop)
end
run
python
if gdb.selected_inferior().pid:
    gdb.execute("thread apply all bt 24")
    if initial_stop_signal:
        # Python's faulthandler may re-raise the same signal. Pass it through
        # after the first native stack, so its actual terminal status is read.
        gdb.execute("handle " + initial_stop_signal + " nostop print pass")
        gdb.execute("continue")
def integer(name):
    value = gdb.parse_and_eval(name)
    return None if value.type.code == gdb.TYPE_CODE_VOID else int(value)
with open({str(status_path)!r}, "w", encoding="utf-8") as output:
    json.dump({{"exit_code": integer("$_exitcode"),
               "signal": integer("$_exitsignal"),
               "initial_stop_signal": initial_stop_signal,
               "still_running": bool(gdb.selected_inferior().pid)}}, output)
end
"""


def _exit_code(debugger_exit: int, status_path: Path) -> tuple[int, dict[str, object]]:
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 70, {"diagnostic_error": "missing or invalid debugger receipt"}
    if not isinstance(status, dict):
        return 70, {"diagnostic_error": "invalid debugger receipt type"}
    code, sig = status.get("exit_code"), status.get("signal")
    terminal_code = type(code) is int and 0 <= code <= 255 and sig is None
    terminal_signal = type(sig) is int and 0 < sig < signal.NSIG and code is None
    if (
        debugger_exit != 0
        or status.get("still_running") is not False
        or not (terminal_code or terminal_signal)
    ):
        return 70, {"diagnostic_error": "debugger failed or child terminal status unproven"}
    return (code if terminal_code else 128 + sig), status


def main() -> int:
    import resource

    output_dir = Path("artifacts/industrial-qt-diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pytest", *sys.argv[1:]]
    debugger = shutil.which("gdb")
    receipt: dict[str, object] = {
        "observation_only": True,
        "pytest_arguments": sys.argv[1:],
        "python": platform.python_version(),
        "system": platform.system(),
        "libc": platform.libc_ver(),
        "runner_image": os.environ.get("ImageVersion", "not reported"),
        "debugger": "gdb" if debugger else "unavailable; direct execution once",
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("PyQt6", "PyQt6-Qt6", "PyQt6-sip", "pandas", "numpy",
                         "pytest", "pytest-cov", "coverage")
        },
    }
    # Limit only this launcher and its descendants. Do not generate raw cores.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    environment = os.environ.copy()
    environment["PYTHONFAULTHANDLER"] = "1"
    with tempfile.TemporaryDirectory(prefix="industrial-qt-") as temporary:
        status_path = Path(temporary) / "status.json"
        if debugger:
            script_path = Path(temporary) / "diagnostics.gdb"
            script_path.write_text(_debugger_script(status_path), encoding="utf-8")
            command = [debugger, "-q", "-batch", "-nx", "-iex", "set auto-load off",
                       "-x", str(script_path), "--args", *command]
        with (output_dir / "diagnostics.log").open("w", encoding="utf-8") as log:
            def emit(line: str) -> None:
                sanitized = _sanitize(line)
                print(sanitized, flush=True)
                log.write(sanitized + "\n")
                log.flush()

            emit(json.dumps(receipt, sort_keys=True))
            try:
                with subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", env=environment,
                ) as process:
                    assert process.stdout is not None
                    for line in process.stdout:
                        emit(line)
                    process_exit = process.wait()
                if debugger:
                    result, terminal = _exit_code(process_exit, status_path)
                    receipt.update(terminal)
                    receipt["debugger_exit"] = process_exit
                else:
                    result = process_exit if process_exit >= 0 else 128 - process_exit
                    receipt["child_exit"] = process_exit
            except OSError as error:
                receipt["diagnostic_error"] = type(error).__name__
                result = 70
            receipt["launcher_exit"] = result
            emit(json.dumps(receipt, sort_keys=True))
    (output_dir / "receipt.json").write_text(
        _sanitize(json.dumps(receipt, indent=2, sort_keys=True)) + "\n", encoding="utf-8"
    )
    return result


FROZEN_SHA = "216877364752c20bcdc65752382da470c4f363d5"
FROZEN_TREE = "719b80423271ff59c6fe08ace819fee2ae151fa0"
BRANCH = "fix/998-industrial-qt-recurrence"
PHASE = "5618809967"
APPROVAL_TIME = "2026-09-10T12:39:19Z"
PROBE_VARIANTS = ("async_reference", "async_owned_teardown")
PROBE_PHASES = ("cycle_start", "parent_constructed", "load_started", "ownership_checked",
                "worker_terminal", "load_checked", "parent_close", "boundary", "release",
                "lifetime", "complete")
RUNTIME_PACKAGES = {
    "PyQt6": "6.6.1", "PyQt6-Qt6": "6.6.1", "PyQt6-sip": "13.12.0",
    "numpy": "2.4.6", "pandas": "3.0.5", "pytest": "9.1.1",
    "pytest-cov": "7.1.0", "coverage": "7.16.0",
}
PYTEST_ARGUMENTS = [
    "tests/test_industrial_analytics_dialog.py", "-q", "--cov=src/metroliza",
    "--cov=modules", "--cov=scripts", "--cov-append", "--cov-report=",
    "--cov-fail-under=0",
]
CORE_LIMIT = 2 * 1024**3
OUTPUT_LIMIT = 8 * 1024**2


def _safe_json(value: object) -> str:
    # One prefixed physical log line: values cannot become Actions commands.
    text = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    if len(text) > 60000:
        raise ValueError("safe_output_limit")
    return text


def _emit_hosted(value: object) -> None:
    text = _safe_json(value)
    print("QT998_JSON " + text, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        # JSON is escaped again for Markdown code fences and HTML rendering.
        text = text.replace("`", "\\u0060").replace("<", "\\u003c")
        with Path(summary).open("a", encoding="utf-8") as output:
            output.write("\n```json\n" + text + "\n```\n")


def _github_json(route: str) -> dict:
    connection = http.client.HTTPSConnection("api.github.com", timeout=20)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "qt998-admission"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        connection.request("GET", "/repos/hexafe/metroliza" + route, headers=headers)
        response = connection.getresponse()
        data = response.read(2 * 1024**2 + 1)
        if response.status != 200 or len(data) > 2 * 1024**2:
            raise ValueError("github_admission_unavailable")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("github_admission_invalid")
        return result
    finally:
        connection.close()


def _validate_admission(event, environment, repository, prior_runs, head, tree):
    inputs = event.get("inputs") or {}
    if inputs.get("qt998_phase") != PHASE:
        raise ValueError("unapproved_or_spent_phase")
    sha = inputs.get("qt998_scaffolding_sha", "")
    expected = {
        "GITHUB_REPOSITORY": "hexafe/metroliza", "GITHUB_REPOSITORY_ID": "478225616",
        "GITHUB_ACTOR": "hexafe", "GITHUB_ACTOR_ID": "100516322",
        "GITHUB_TRIGGERING_ACTOR": "hexafe", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/" + BRANCH, "GITHUB_REF_TYPE": "branch",
        "GITHUB_RUN_ATTEMPT": "1", "QT998_RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64",
    }
    if any(environment.get(key) != value for key, value in expected.items()):
        raise ValueError("untrusted_execution_context")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("missing_exact_scaffolding_sha")
    if not (sha == head == environment.get("GITHUB_SHA")
            == environment.get("QT998_WORKFLOW_SHA")):
        raise ValueError("scaffolding_identity_mismatch")
    if (inputs.get("run_industrial_postmortem") != "1"
            or inputs.get("qt998_workload_sha") != FROZEN_SHA
            or inputs.get("run_packaging_smoke", "0") != "0"
            or inputs.get("run_windows_startup_benchmark", "0") != "0"
            or tree != FROZEN_TREE):
        raise ValueError("workload_or_opt_in_mismatch")
    if (repository.get("id") != 478225616 or repository.get("private") is not False
            or repository.get("visibility") != "public"
            or repository.get("full_name") != "hexafe/metroliza"):
        raise ValueError("public_repository_cost_gate_failed")
    run_id = environment.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("missing_run_identity")
    _validate_phase_history(prior_runs, run_id, sha)
    return {"phase": PHASE, "scaffolding_sha": sha, "workload_sha": FROZEN_SHA,
            "workload_tree": tree, "run_id": run_id, "run_attempt": 1}


def _validate_phase_history(prior_runs, run_id, sha):
    current = [run for run in prior_runs if run.get("id") == int(run_id)]
    if (len(current) != 1 or current[0].get("head_sha") != sha
            or current[0].get("run_attempt") != 1
            or current[0].get("event") != "workflow_dispatch"
            or current[0].get("head_branch") != BRANCH):
        raise ValueError("current_run_not_verified_in_history")
    # The whole approval is single-use, even if the first run failed in setup.
    # Serial concurrency makes a queued duplicate observe its predecessor.
    for run in prior_runs:
        if (run["event"] == "workflow_dispatch" and run["head_branch"] == BRANCH
                and run["created_at"] >= APPROVAL_TIME and run["id"] < int(run_id)):
            raise ValueError("approval_already_spent")


def _git(checkout: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(checkout), *arguments],
                            capture_output=True, text=True, check=True, timeout=20)
    return result.stdout.strip()


def _verify_workload(checkout: Path) -> None:
    if (_git(checkout, "rev-parse", "HEAD") != FROZEN_SHA
            or _git(checkout, "rev-parse", "HEAD^{tree}") != FROZEN_TREE
            or _git(checkout, "status", "--porcelain=v1")
            or any(not row.startswith("H ") for row in
                   _git(checkout, "ls-files", "-v").splitlines())):
        raise ValueError("frozen_workload_not_clean")
    # actions/checkout must not leave an HTTP authorization header in this repo.
    config = _git(checkout, "config", "--local", "--list")
    if "extraheader=" in config.lower():
        raise ValueError("persisted_checkout_credentials")


def _probe_file() -> Path:
    return Path(__file__).resolve().parent.parent / "tests/qt_dialog_lifecycle_probe.py"


def _verify_probe() -> str:
    path = _probe_file()
    checkout = path.parent.parent
    relative = path.relative_to(checkout).as_posix()
    if (_git(checkout, "rev-parse", "HEAD") != os.environ.get("GITHUB_SHA")
            or _git(checkout, "status", "--porcelain=v1")
            or _git(checkout, "ls-files", "-v", relative) != "H " + relative
            or _git(checkout, "hash-object", relative) != _git(checkout, "rev-parse", "HEAD:" + relative)):
        raise ValueError("reviewed_probe_not_clean")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _private_root() -> Path:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("missing_run_identity")
    root = Path(tempfile.gettempdir()) / ("qt998-" + run_id)
    if root.exists() or root.is_symlink():
        info = root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise ValueError("unsafe_private_directory")
    return root


def hosted_admit() -> int:
    if (os.getuid() == 0 or platform.machine() != "x86_64"
            or platform.freedesktop_os_release().get("ID") != "ubuntu"
            or platform.freedesktop_os_release().get("VERSION_ID") != "24.04"):
        raise ValueError("standard_ubuntu_guest_required")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    repository = _github_json("")
    prior = []
    for page in range(1, 11):
        result = _github_json(
            "/actions/workflows/237333409/runs?event=workflow_dispatch"
            "&branch=fix%2F998-industrial-qt-recurrence&per_page=100&page=" + str(page))
        runs = result["workflow_runs"]
        prior.extend(runs)
        if len(runs) < 100:
            break
    else:
        raise ValueError("admission_history_incomplete")
    workload = Path.cwd().parent / "frozen-workload"
    _verify_workload(workload)
    receipt = _validate_admission(event, os.environ, repository, prior,
                                  _git(Path.cwd(), "rev-parse", "HEAD"),
                                  _git(workload, "rev-parse", "HEAD^{tree}"))
    current = next(run for run in prior if str(run["id"]) == receipt["run_id"])
    # Use workflow creation (earlier than guest start) conservatively. Leave
    # at least three minutes of the25-minute job ceiling for private cleanup.
    receipt["observation_deadline_epoch"] = (
        datetime.fromisoformat(current["created_at"].replace("Z", "+00:00")).timestamp() + 22 * 60
    )
    receipt["probe_sha256"] = _verify_probe()
    root = _private_root()
    root.mkdir(mode=0o700)  # Existing admission cannot be reused in the same run.
    (root / "admission.json").write_text(_safe_json(receipt), encoding="utf-8")
    _emit_hosted({"admission": "accepted", **receipt})
    return 0


def _child_environment(root: Path) -> dict[str, str]:
    return {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        # setup-python's hosted binary uses its matching shared library directory.
        # Derive this from the interpreter, never inherit an arbitrary loader path.
        "LD_LIBRARY_PATH": str(Path(sys.base_prefix) / "lib"),
        "HOME": str(root / "home"), "TMPDIR": str(root / "temporary"),
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen",
        "PYTHONPATH": "src:.", "PYTHONFAULTHANDLER": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "COVERAGE_FILE": str(root / ".coverage"),
        "DEBUGINFOD_URLS": "",
    }


def _child_limits() -> None:
    import resource

    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (CORE_LIMIT, CORE_LIMIT))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CORE_LIMIT, CORE_LIMIT))


def _postmortem_exit(child_exit: int, diagnostics_ok: bool) -> int:
    if child_exit:
        return child_exit if child_exit > 0 else 128 - child_exit
    return 0 if diagnostics_ok else 70


def _binary_provenance() -> dict:
    result = {}
    for package, suffix in (("PyQt6", "QtCore.abi3.so"),
                            ("PyQt6-Qt6", "libQt6Core.so.6"),
                            ("PyQt6-sip", "sip.cpython-311-x86_64-linux-gnu.so")):
        distribution = importlib.metadata.distribution(package)
        matches = [file for file in distribution.files or () if str(file).endswith(suffix)]
        if len(matches) != 1:
            raise ValueError("runtime_binary_provenance_unavailable")
        binary = Path(distribution.locate_file(matches[0]))
        result[package] = {"binary": suffix,
                           "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
    return result


def _pytest_summary(text: str) -> dict:
    # Require a complete terminal summary, not incidental counts in test text.
    summaries = re.findall(
        r"(?m)^[= ]*(\d+ (?:passed|failed|skipped|error)[^\r\n]*?"
        r" in [0-9.]+s(?: \([0-9:]+\))?)[= ]*$", text,
    )
    summary = summaries[-1] if summaries else ""
    counts = re.findall(r"\b[0-9]+ (?:passed|failed|skipped|errors?|xfailed|xpassed|deselected)\b", summary)
    return {"pytest_counts": counts, "pytest_summary_complete": len(summaries) == 1,
            "pytest_warning_counts": re.findall(r"\b[0-9]+ warnings?\b", summary),
            "pytest_subtest_counts": re.findall(r"\b[0-9]+ subtests passed\b", summary)}


def _lifetime_counters_valid(data: dict, previous: dict) -> bool:
    for key, size in (("gc", 4), ("wrappers", 6)):
        values = data[key]
        if (not isinstance(values, list) or len(values) != size
                or any(type(value) is not int or not 0 <= value <= 1000000 for value in values)):
            return False
        if any(value < old for value, old in zip(values, previous.get(key, [0] * size))):
            return False
    return all(sum(data["wrappers"][index:index + 2]) <= data["cycle"] for index in (0, 2, 4))


def _lifetime_record(line: str, variant: str, previous: dict) -> dict:
    data = json.loads(line.removeprefix("QT998_LIFETIME "))
    flags = ("shown", "parent_deleted", "thread_deleted", "subtree_verified", "store_removed")
    keys = {"variant", "cycle", "load_rows", "gc", "wrappers", *flags}
    if not isinstance(data, dict) or data.keys() != keys:
        raise ValueError("lifetime_schema")
    if (data["variant"] != variant or type(data["cycle"]) is not int
            or not 1 <= data["cycle"] <= 200
            or any(type(data[key]) is not bool for key in flags)
            or type(data["load_rows"]) is not int or data["load_rows"] != 4
            or not data["store_removed"] or not _lifetime_counters_valid(data, previous)):
        raise ValueError("lifetime_values")
    if variant == "async_owned_teardown" and not all(
            data[key] for key in ("parent_deleted", "thread_deleted", "subtree_verified")):
        raise ValueError("unproven_owned_boundary")
    return data


def _lifetime_totals(rows: list[dict]) -> dict:
    final = rows[-1] if rows else {}
    return {"lifetime_snapshots": len(rows),
            "shown_observed_cycles": sum(row["shown"] for row in rows),
            "parent_cpp_deleted_cycles": sum(row["parent_deleted"] for row in rows),
            "thread_cpp_deleted_cycles": sum(row["thread_deleted"] for row in rows),
            "subtree_cpp_verified_cycles": sum(row["subtree_verified"] for row in rows),
            "store_removed_cycles": sum(row["store_removed"] for row in rows),
            "gc_counts": final.get("gc", [0] * 4),
            "wrapper_release_counts": final.get("wrappers", [0] * 6)}


def _probe_observations(text: str, variant: str) -> tuple[list, list]:
    observed, lifetimes = [], []
    for line in text.splitlines():
        if line.startswith("QT998_LIFETIME"):
            row = _lifetime_record(line, variant, lifetimes[-1] if lifetimes else {})
            lifetimes.append(row)
            observed.append((row["cycle"], "lifetime"))
        elif line.startswith("QT998_PROBE"):
            match = re.fullmatch(r"QT998_PROBE ([a-z_]+) ([0-9]{1,3}) ([a-z_]+)", line)
            if not match or match[1] != variant or match[3] == "lifetime":
                raise ValueError("probe_marker")
            observed.append((int(match[2]), match[3]))
    return observed, lifetimes


def _probe_summary(text: str, variant: str) -> dict:
    expected = [(0, "startup"), (0, "application")]
    expected.extend((cycle, phase) for cycle in range(1, 201) for phase in PROBE_PHASES)
    expected.append((200, "process_exit"))
    try:
        observed, lifetimes = _probe_observations(text, variant)
        valid = variant in PROBE_VARIANTS and bool(observed) and observed == expected[:len(observed)]
    except (ValueError, TypeError):
        observed, lifetimes, valid = [], [], False
    completed = sum(phase == "complete" for _, phase in observed) if valid else 0
    started = sum(phase == "cycle_start" for _, phase in observed) if valid else 0
    return {"probe_valid": valid, "probe_complete": valid and observed == expected,
            "variant": variant, "completed_cycles": completed,
            "interrupted_cycles": started - completed,
            "last_completed_phase": observed[-1][1] if valid else "unavailable",
            "last_cycle": observed[-1][0] if valid else None,
            **_lifetime_totals(lifetimes if valid else [])}


def _run_private(command: list[str], cwd: Path, root: Path, label: str, *, timeout: float = 120) -> dict:
    if not 0 < timeout <= 1200:
        raise ValueError("invalid_stage_timeout")
    output = root / (label + ".raw")
    started = time.monotonic()
    with output.open("wb") as log:
        with subprocess.Popen(command, cwd=cwd, env=_child_environment(root),
                              stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                              preexec_fn=_child_limits) as child:
            timed_out = False
            cancelled = False
            try:
                child.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, InterruptedError) as error:
                timed_out = isinstance(error, subprocess.TimeoutExpired)
                cancelled = isinstance(error, InterruptedError)
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # The owned group may have just terminated naturally.
                child.wait()
            except BaseException:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                raise
            code, pid = child.returncode, child.pid
    receipt = {"child_exit": code, "signal": -code if code < 0 else None, "pid": pid,
               "timed_out": timed_out, "cancelled": cancelled, "output_ok": False,
               "elapsed_seconds": round(time.monotonic() - started, 6)}
    try:
        size = output.stat().st_size
        # Only pytest terminal counts are exported, never arbitrary child text.
        with output.open("rb") as stream:
            text = stream.read(OUTPUT_LIMIT).decode("utf-8", errors="replace")
        receipt.update(output_bytes=size, output_truncated=size > OUTPUT_LIMIT,
                       **_pytest_summary(text))
        if label in PROBE_VARIANTS:
            receipt.update(_probe_summary(text, label))
        output.unlink()
        receipt["output_ok"] = True
    except OSError as error:
        # The already observed exit is authoritative even if log processing fails.
        receipt["output_capture_error"] = type(error).__name__
    return receipt


def _core_script(output: Path) -> str:
    # Structured GDB APIs avoid exporting the automatic raw core/argument banner.
    return f'''python
import gdb, json, os
fault = gdb.selected_thread().num
threads = list(gdb.selected_inferior().threads())
threads.sort(key=lambda thread: (thread.num != fault, thread.num))
result = {{"fault_thread": fault, "pid": gdb.selected_inferior().pid,
           "signal": int(gdb.parse_and_eval("$_siginfo.si_signo")),
           "thread_count": len(threads), "truncated": len(threads) > 8, "threads": []}}
for thread in threads[:8]:
    thread.switch()
    frame = gdb.newest_frame()
    frames = []
    limit = 64 if thread.num == fault else 16
    unwind_error = False
    while frame is not None and len(frames) < limit:
        try:
            frames.append({{"function": frame.name() or "??",
                            "module": os.path.basename(gdb.solib_name(frame.pc()) or "")}})
            frame = frame.older()
        except gdb.error:
            unwind_error = True
            break
    result["truncated"] = result["truncated"] or frame is not None
    result["threads"].append({{"thread": thread.num, "frames": frames,
                              "frames_truncated": frame is not None,
                              "unwind_error": unwind_error}})
with open({str(output)!r}, "w", encoding="utf-8") as stream:
    json.dump(result, stream)
end
'''


def _inspect_core(root: Path, child: dict, executable: str) -> dict:
    core = root / ("core." + str(child["pid"]))
    if not core.exists():
        return {"capture": "missing_core", "ok": False}
    result = {"capture": "invalid_core", "ok": False}
    try:
        info = core.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size >= CORE_LIMIT):
            return result
        with core.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                return result
        stack = root / "stack.json"
        script = root / "postmortem.gdb"
        script.write_text(_core_script(stack), encoding="utf-8")
        command = ["/usr/bin/gdb", "-q", "-batch", "-nx", "-nh",
                   "-iex", "set auto-load off", "-iex", "set debuginfod enabled off",
                   "-iex", "set print frame-arguments none", "-iex", "set print pretty off",
                   "-iex", "set print entry-values no", "-se", executable, "-c", str(core),
                   "-x", str(script)]
        debugger = _run_private(command, root, root, "debugger")
        if (debugger["child_exit"] or debugger["timed_out"] or not debugger["output_ok"]
                or debugger.get("output_truncated")):
            return {"capture": "symbolizer_failed", "ok": False}
        if not stack.is_file() or stack.stat().st_size > 60000:
            return {"capture": "missing_or_oversize_stack", "ok": False}
        native = json.loads(stack.read_text())
        if (native["signal"] != child["signal"] or native["pid"] != child["pid"]
                or not native["threads"]):
            return {"capture": "core_identity_mismatch", "ok": False}
        for thread in native["threads"]:
            for frame in thread["frames"]:
                function = _sanitize(frame["function"])
                # Names only: no source paths, argument values or control bytes.
                frame["name_truncated"] = len(function) > 140
                frame["function"] = re.sub(r"[^A-Za-z0-9_:$<>~*. +,()\[\]&=-]", "?",
                                           function)[:140]
                frame["unresolved"] = frame["function"] == "??"
                frame["module_truncated"] = len(frame.get("module", "")) > 80
                frame["module"] = re.sub(r"[^A-Za-z0-9_.+-]", "?", frame.get("module", ""))[:80]
        return {"capture": "postmortem_stack", "ok": True, "core_bytes": info.st_size,
                "native": native}
    finally:
        core.unlink(missing_ok=True)
        for name in ("stack.json", "postmortem.gdb"):
            (root / name).unlink(missing_ok=True)


def _set_core_pattern(value: str) -> None:
    subprocess.run(["sudo", "-n", "/usr/bin/tee", "/proc/sys/kernel/core_pattern"],
                   input=value.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=True, timeout=10)
    if Path("/proc/sys/kernel/core_pattern").read_text().strip() != value:
        raise ValueError("guest_core_route_not_set")


def _cleanup_hosted(root: Path) -> dict:
    if not root.exists():
        return {"ok": True, "private_storage_removed": True, "core_route_restored": None,
                "route_status": "no state remains; see primary cleanup receipt if configured"}
    state = root / "core-route.json"
    restored = True
    if state.exists():
        try:
            original = json.loads(state.read_text())["original"]
            _set_core_pattern(original)
        except Exception:
            # A cleanup failure is reported non-green, never printed verbatim.
            restored = False
    removed = True
    try:
        shutil.rmtree(root)
    except FileNotFoundError:
        pass
    except OSError:
        removed = False
    return {"core_route_restored": restored, "private_storage_removed": removed,
            "ok": restored and removed and not root.exists()}


def _prepare_hosted_capture(root: Path, workload: Path) -> dict:
    os.umask(0o077)
    for name in ("home", "temporary"):
        (root / name).mkdir(mode=0o700)
    _verify_workload(workload)
    if shutil.which("gdb") != "/usr/bin/gdb" or shutil.disk_usage(root).free < 5 * 1024**3:
        raise ValueError("capture_prerequisite_unavailable")
    original = Path("/proc/sys/kernel/core_pattern").read_text().strip()
    (root / "core-route.json").write_text(json.dumps({"original": original}))
    _set_core_pattern(str(root / "core.%p"))
    return {
        "python": platform.python_version(), "kernel": platform.release(),
        "libc": platform.libc_ver(), "runner_image": os.environ.get("ImageVersion", "unknown"),
        "packages": {name: importlib.metadata.version(name) for name in RUNTIME_PACKAGES},
        "python_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "gdb_sha256": hashlib.sha256(Path("/usr/bin/gdb").read_bytes()).hexdigest(),
        "qt_binary_provenance": _binary_provenance(),
        "normalization": "offscreen; private HOME/TMP/coverage; allowlisted env; no Qt theme overrides",
    }


def _validate_runtime(environment: dict) -> None:
    if environment["python"] != "3.11.16" or environment["packages"] != RUNTIME_PACKAGES:
        raise ValueError("material_runtime_mismatch")


def _capture_ready(root: Path) -> None:
    if (Path("/proc/sys/kernel/core_pattern").read_text().strip() != str(root / "core.%p")
            or shutil.which("gdb") != "/usr/bin/gdb"
            or shutil.disk_usage(root).free < CORE_LIMIT + 1024**3):
        raise ValueError("capture_capability_lost")


def _prove_hosted_capture(root: Path, receipt: dict) -> None:
    _capture_ready(root)
    success = _run_private([sys.executable, "-c", "raise SystemExit(0)"], root, root, "success")
    receipt["success_control"] = success
    missing = _inspect_core(root, {"pid": "missing", "signal": 11}, sys.executable)
    receipt["unavailable_control"] = {"kind": "missing-core handler; no second crash",
                                      **missing, "preserved_exit": _postmortem_exit(-11, False)}
    sanitization = _safe_json({"control": _sanitize("password=qt998-synthetic-secret\n::error::x")})
    if (not _complete_stage(success, []) or missing["ok"]
            or "qt998-synthetic-secret" in sanitization):
        raise ValueError("noncrashing_capability_control_failed")
    receipt["sanitization_control"] = "passed; one JSON line, synthetic secret removed"
    source = root / "control.c"
    source.write_text("void qt998_crash_control(void) { *(volatile int *)0 = 998; }\n"
                      "int main(void) { qt998_crash_control(); return 0; }\n")
    binary = root / "control"
    compiled = _run_private(["/usr/bin/gcc", "-g", "-O0", "-o", str(binary), str(source)],
                            root, root, "compiler")
    if not _complete_stage(compiled, []):
        raise ValueError("synthetic_control_compile_failed")
    control = _run_private([str(binary)], root, root, "synthetic")
    receipt["synthetic_control"] = control
    capture = _inspect_core(root, control, str(binary))
    receipt["synthetic_control"] = {**control, **capture,
                                     "core_removed": not (root / ("core." + str(control["pid"]))).exists()}
    if (control["child_exit"] != -11 or not control["output_ok"] or not capture["ok"]
            or control.get("timed_out") or control.get("cancelled")
            or control.get("output_truncated")
            or "qt998_crash_control" not in json.dumps(capture)):
        raise ValueError("native_capability_unproven")
    receipt["capability"] = "proven_by_synthetic_control_only"


def _complete_stage(child: dict, expected: list[str]) -> bool:
    return (child["child_exit"] == 0 and child["output_ok"]
            and not child.get("timed_out") and not child.get("cancelled")
            and not child.get("output_truncated")
            and child.get("pytest_counts") == expected
            and (child.get("pytest_summary_complete") or not expected))


def _probe_private_cleanup(root: Path, label: str, child: dict) -> bool:
    return not any((root / name).exists() for name in (
        label + ".raw", "core." + str(child["pid"]), "debugger.raw", "stack.json", "postmortem.gdb"))


def _emit_preserving_exit(receipt: dict, result: int) -> int:
    try:
        _emit_hosted(receipt)
    except Exception as error:
        # A publication error must never turn an observed SIGSEGV139 into70.
        result = result or 70
        if "acquisition_stage" in receipt:
            receipt["acquisition_stage"]["publication_error"] = type(error).__name__
        try:
            print("QT998_JSON " + _safe_json({"output_error": type(error).__name__,
                                            "launcher_exit": result}), flush=True)
        except Exception:
            pass
    return result


def _acquisition_stage(root, workload, receipt, label, command, expected, timeout, deadline=None):
    display_command = ["python", *command[1:]]
    if label in PROBE_VARIANTS:
        display_command = [arg if arg != str(_probe_file())
                           else "reviewed-tooling/tests/qt_dialog_lifecycle_probe.py"
                           for arg in display_command]
    entry = {"stage": label, "command": display_command,
             "source_tree": FROZEN_TREE, "expected_counts": expected,
             "timeout_seconds": timeout, "started": False, "complete": False}
    receipt["stages"].append(entry)
    result = 70
    try:
        _verify_workload(workload)
        _capture_ready(root)
        if label in PROBE_VARIANTS:
            _verify_probe()
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
            if timeout <= 0:
                raise TimeoutError("acquisition_deadline_expired_before_launch")
            entry["timeout_seconds"] = timeout
        entry["started"] = True
        child = _run_private(command, workload, root, label, timeout=timeout)
        entry.update(child)
        # Set terminal status before post-mortem, source verification or export.
        result = _postmortem_exit(child["child_exit"], False)
        capture = (_inspect_core(root, child, sys.executable) if child["signal"]
                   else {"capture": "not_needed_no_signal", "ok": True})
        entry.update(capture)
        _verify_workload(workload)
        _capture_ready(root)
        entry["source_unchanged"] = True
        entry["complete"] = bool(_complete_stage(child, expected) and capture["ok"])
        if label in PROBE_VARIANTS:
            _verify_probe()
            entry["variant_private_cleanup"] = _probe_private_cleanup(root, label, child)
            entry["complete"] = bool(entry["complete"] and child.get("probe_valid")
                                     and child.get("probe_complete")
                                     and entry["variant_private_cleanup"])
        result = _postmortem_exit(child["child_exit"], entry["complete"])
    except Exception as error:
        entry["diagnostic_error"] = type(error).__name__
    entry["launcher_exit"] = result
    result = _emit_preserving_exit({"acquisition_stage": entry}, result)
    # Native frames are exported in the bounded stage receipt, once. The final
    # cumulative ledger references that stage without duplicating a large stack.
    if "native" in entry:
        entry["native_stack_receipt"] = label
        del entry["native"]
    return result


def _failed_observation(stage: dict) -> str:
    if stage.get("timed_out") or stage.get("cancelled") or not stage.get("child_exit"):
        return "INCOMPLETE_WORKLOAD"
    return "FAILED_WORKLOAD"


def _acquire_sequence(root: Path, workload: Path, receipt: dict) -> int:
    receipt.update(stages=[], observation="INCOMPLETE_WORKLOAD", industrial_limit=10,
                   industrial_aggregate_limit_seconds=600,
                   context="prefix once; fresh processes; shared cumulative coverage")
    coverage = PYTEST_ARGUMENTS[2:]
    prefix = [
        ("coverage_erase", [sys.executable, "-m", "coverage", "erase"], [], 60),
        ("main", [sys.executable, "-m", "pytest", "tests", "-q",
                  *[arg for arg in coverage if arg != "--cov-append"]],
         ["4183 passed", "62 skipped"], 1200),
        ("dashboard", [sys.executable, "-m", "pytest",
                       "tests/test_dashboard_visual_options_dialog.py", "-q", *coverage],
         ["24 passed"], 120),
    ]
    for label, command, expected, timeout in prefix:
        result = _acquisition_stage(root, workload, receipt, label, command, expected, timeout)
        if result:
            receipt["observation"] = _failed_observation(receipt["stages"][-1])
            return result
    deadline = time.monotonic() + 600
    for sample in range(1, 11):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            receipt["acquisition_budget_expired"] = True
            return 70
        result = _acquisition_stage(
            root, workload, receipt, "industrial_" + str(sample),
            [sys.executable, "-m", "pytest", *PYTEST_ARGUMENTS], ["42 passed"], min(120, remaining),
            deadline=deadline,
        )
        if result:
            receipt["observation"] = _failed_observation(receipt["stages"][-1])
            return result
        if time.monotonic() > deadline:
            receipt["acquisition_budget_expired"] = True
            return 70
    receipt["observation"] = "NON-REPRODUCTION"
    return 0


def _usable_probe_failure(stage: dict) -> bool:
    return (stage.get("signal") in (6, 11) and stage.get("ok") and stage.get("probe_valid")
            and stage.get("source_unchanged") and stage.get("variant_private_cleanup")
            and stage.get("output_ok") and not stage.get("output_truncated")
            and not stage.get("timed_out") and not stage.get("cancelled")
            and not stage.get("diagnostic_error") and not stage.get("publication_error"))


def _acquire_reduction(root: Path, workload: Path, receipt: dict) -> int:
    receipt.update(stages=[], observation="REDUCTION_INCOMPLETE", variant_limit=2,
                   cycles_per_variant=200, aggregate_limit_seconds=360,
                   context="two predeclared async variants; fresh processes; cumulative coverage")
    deadline = time.monotonic() + 360
    first_failure = 0
    for variant in PROBE_VARIANTS:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            receipt["acquisition_budget_expired"] = True
            return first_failure or 70
        command = [sys.executable, "-m", "coverage", "run", "--append",
                   "--source=src/metroliza,modules,scripts", str(_probe_file()),
                   "--variant", variant, "--cycles", "200"]
        result = _acquisition_stage(root, workload, receipt, variant, command, [],
                                    min(180, remaining), deadline=deadline)
        first_failure = first_failure or result
        receipt["reduction_exit"] = first_failure
        if result and not _usable_probe_failure(receipt["stages"][-1]):
            return first_failure
        if time.monotonic() > deadline:
            receipt["acquisition_budget_expired"] = True
            return first_failure or 70
    receipt["observation"] = ("REDUCTION_FAILED_WORKLOAD" if first_failure
                              else "REDUCTION_NON_REPRODUCTION")
    return first_failure


def hosted_observe() -> int:
    root = _private_root()
    admission = json.loads((root / "admission.json").read_text())
    if (admission["run_id"] != os.environ.get("GITHUB_RUN_ID")
            or admission["scaffolding_sha"] != os.environ.get("GITHUB_SHA")
            or admission.get("phase") != PHASE
            or admission.get("workload_sha") != FROZEN_SHA
            or admission.get("workload_tree") != FROZEN_TREE
            or os.environ.get("GITHUB_RUN_ATTEMPT") != "1" or os.getuid() == 0):
        raise ValueError("admission_not_applicable")
    receipt = {"identity": admission, "observation": "not_started", "capability": "unproven"}
    result = 70
    def interrupt(signum, frame):
        if signum == signal.SIGALRM:
            receipt["job_budget_expired"] = True
        raise InterruptedError("hosted_parent_cancelled")

    handlers = {sig: signal.signal(sig, interrupt)
                for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)}
    try:
        remaining = int(admission["observation_deadline_epoch"] - time.time())
        if remaining <= 0:
            receipt["job_budget_expired"] = True
            raise TimeoutError("cleanup_reserve_reached")
        signal.alarm(remaining)
        workload = Path.cwd().parent / "frozen-workload"
        receipt["environment"] = _prepare_hosted_capture(root, workload)
        _validate_runtime(receipt["environment"])
        _prove_hosted_capture(root, receipt)
        result = _acquire_reduction(root, workload, receipt)
    except Exception as error:
        receipt["diagnostic_error"] = type(error).__name__
        result = receipt.get("reduction_exit", result) or 70
    finally:
        signal.alarm(0)
        try:
            receipt["cleanup"] = _cleanup_hosted(root)
        except Exception as error:
            receipt["cleanup"] = {"ok": False, "cleanup_error": type(error).__name__}
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        if not receipt["cleanup"]["ok"] and result == 0:
            result = 70
        receipt["launcher_exit"] = result
        result = _emit_preserving_exit(receipt, result)
    return result


def hosted_main(mode: str) -> int:
    try:
        if (os.environ.get("QT998_RUNNER_ENVIRONMENT") != "github-hosted"
                or platform.system() != "Linux" or os.getuid() == 0
                or platform.freedesktop_os_release().get("ID") != "ubuntu"
                or platform.freedesktop_os_release().get("VERSION_ID") != "24.04"):
            raise ValueError("standard_ubuntu_guest_required")
        if mode == "--hosted-admit":
            return hosted_admit()
        if mode == "--hosted-cleanup":
            cleanup = _cleanup_hosted(_private_root())
            _emit_hosted({"always_cleanup": cleanup})
            return 0 if cleanup["ok"] else 70
        return hosted_observe()
    except Exception as error:
        _emit_hosted({"hosted_diagnostic_error": type(error).__name__,
                      "mode": mode, "observation_status": "consult primary receipt; unknown at outer boundary"})
        return 70


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in {
        "--hosted-admit", "--hosted-observe", "--hosted-cleanup",
    }:
        raise SystemExit(hosted_main(sys.argv[1]))
    raise SystemExit(main())
