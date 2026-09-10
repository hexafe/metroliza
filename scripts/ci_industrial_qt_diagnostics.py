"""Observe the existing Linux industrial coverage shard once; never retry it.

Issue #998 permits this diagnostic observation, not a claimed lifecycle repair.
The default path retains sanitized text only. The separately admitted hosted
mode inspects private guest cores after termination, then removes all raw data.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
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
import types


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


FROZEN_SHA = "b451e7af3153da89c16d09f5b26a7f4799a82da3"
FROZEN_TREE = "1936b583b3ba61b9466d61599b563aabdb3556e7"
BRANCH = "fix/998-industrial-qt-recurrence"
PHASE = "5624613947"
APPROVAL_TIME = "2026-09-10T19:56:21Z"
AUTHORITY_DEADLINE = "2026-09-10T22:54:45+00:00"
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
PRIVATE_LIMIT = 8 * 1024**3
LIBRARY_LIMIT = 512 * 1024**2
SYMBOLIZER_LIMIT = 512 * 1024**2
POSTMORTEM_SECONDS = 600
SYMBOLIZER_PACKAGES = ("gdb", "libdebuginfod1t64", "libdebuginfod-common", "libipt2",
                       "libbabeltrace1", "libsource-highlight4t64", "libsource-highlight-common",
                       "libboost-regex1.83.0")


class PreflightReason(Enum):
    UNKNOWN = ("unknown", "unknown")
    TOOL_UNAVAILABLE = ("reader", "tool_unavailable")
    TOOL_FAILED = ("reader", "tool_failed")
    OUTPUT_UNAVAILABLE = ("reader", "output_unavailable")
    OUTPUT_TRUNCATED = ("reader", "output_truncated")
    TIMED_OUT = ("reader", "timed_out")
    INTERRUPTED = ("reader", "interrupted")
    TABLE_UNSUPPORTED = ("parser", "table_unsupported")
    TABLE_AMBIGUOUS = ("parser", "table_ambiguous")
    TABLE_MALFORMED = ("parser", "table_malformed")
    TABLE_TRUNCATED = ("parser", "table_truncated")
    DELETED_MAPPING = ("parser", "deleted_mapping")
    EXECUTABLE_ABSENT = ("identity", "executable_absent")
    EXECUTABLE_UNAVAILABLE = ("identity", "executable_unavailable")
    BINARY_MISSING = ("identity", "binary_missing")
    BINARY_CHANGED = ("identity", "binary_changed")
    BINARY_UNRECORDED = ("identity", "binary_unrecorded")
    BINARY_UNREADABLE = ("identity", "binary_unreadable")
    INVALID_PATH = ("identity", "invalid_path")
    STORAGE_UNAVAILABLE = ("preservation", "storage_unavailable")
    COPY_FAILED = ("preservation", "copy_failed")
    HASH_MISMATCH = ("preservation", "hash_mismatch")
    HASH_UNAVAILABLE = ("preservation", "hash_unavailable")
    NO_ELF = ("preservation", "no_elf")


def _preflight_tool_status(tool: dict) -> dict:
    # No exception text, arbitrary fields, addresses or mapped paths cross here.
    integers = {key: value for key, value in tool.items()
                if key in ("child_exit", "signal", "pid", "output_bytes")
                and type(value) is int and -(2**31) <= value <= PRIVATE_LIMIT}
    flags = {key: value for key, value in tool.items()
             if key in ("output_ok", "output_truncated", "timed_out", "cancelled", "post_exit_interrupted")
             and type(value) is bool}
    return {**integers, **flags}


class PreflightError(ValueError):
    def __init__(self, reason: PreflightReason, tool: dict | None = None):
        self.reason = reason if isinstance(reason, PreflightReason) else PreflightReason.UNKNOWN
        self.tool = _preflight_tool_status(tool or {})
        super().__init__(self.reason.value[1])


class PreflightInterrupted(InterruptedError):
    def __init__(self, tool: dict | None = None):
        self.reason = PreflightReason.INTERRUPTED
        self.tool = _preflight_tool_status(tool or {})
        super().__init__("preflight_interrupted")


def _preflight_failure(error: Exception) -> dict:
    if not isinstance(error, (PreflightError, PreflightInterrupted)):
        return {"stage": "unknown", "reason": "unknown"}
    reason = error.reason if isinstance(error.reason, PreflightReason) else PreflightReason.UNKNOWN
    result = dict(zip(("stage", "reason"), reason.value))
    tool = _preflight_tool_status(error.tool)
    if tool:
        result["tool"] = tool
    return result


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
    # Reserve five minutes for cleanup, also inside the nonrenewable authority.
    receipt["observation_deadline_epoch"] = min(
        datetime.fromisoformat(current["created_at"].replace("Z", "+00:00")).timestamp() + 40 * 60,
        datetime.fromisoformat(AUTHORITY_DEADLINE).timestamp() - 5 * 60)
    receipt["probe_sha256"] = _verify_probe()
    root = _private_root()
    root.mkdir(mode=0o700)  # Existing admission cannot be reused in the same run.
    (root / "admission.json").write_text(_safe_json(receipt), encoding="utf-8")
    _emit_hosted({"admission": "accepted", **receipt})
    return 0


def _child_environment(root: Path) -> dict[str, str]:
    environment = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        # setup-python's hosted binary uses its matching shared library directory.
        # Derive this from the interpreter, never inherit an arbitrary loader path.
        "LD_LIBRARY_PATH": str(Path(sys.base_prefix) / "lib"),
        "HOME": str(root / "home"), "QT_QPA_PLATFORM": "offscreen",
        "PYTHONPATH": "src:.", "PYTHONFAULTHANDLER": "1",
        "COVERAGE_FILE": str(root / ".coverage"),
        "DEBUGINFOD_URLS": "",
    }
    # Retain ordinary noncredential CI values only within a fixed vocabulary.
    allowed = {"LANG": {"C.UTF-8", "C.utf8", "en_US.UTF-8"},
               "LC_ALL": {"C.UTF-8", "C.utf8", "en_US.UTF-8"},
               "QT_QPA_PLATFORMTHEME": {"gtk3", "qt5ct", "qt6ct"},
               "QT_STYLE_OVERRIDE": {"Fusion", "fusion"},
               "PYTHONDONTWRITEBYTECODE": {"0", "1"},
               "TMPDIR": {"/tmp"}}  # nosec B108: env allowlist; captures use the private root.
    for name, values in allowed.items():
        if os.environ.get(name) in values:
            environment[name] = os.environ[name]
    return environment


def _child_limits() -> None:
    import resource

    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (CORE_LIMIT, CORE_LIMIT))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CORE_LIMIT, CORE_LIMIT))


def _tool_limits() -> None:
    import resource

    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (SYMBOLIZER_LIMIT, SYMBOLIZER_LIMIT))


def _postmortem_exit(child_exit: int, diagnostics_ok: bool) -> int:
    if child_exit:
        return child_exit if child_exit > 0 else 128 - child_exit
    return 0 if diagnostics_ok else 70


def _binary_provenance() -> dict:
    result = {}
    for package, suffix in (("PyQt6", "QtCore.abi3.so"),
                            ("PyQt6", "QtGui.abi3.so"), ("PyQt6", "QtWidgets.abi3.so"),
                            ("PyQt6-Qt6", "libQt6Core.so.6"),
                            ("PyQt6-Qt6", "libQt6Gui.so.6"), ("PyQt6-Qt6", "libQt6Widgets.so.6"),
                            ("PyQt6-sip", "sip.cpython-311-x86_64-linux-gnu.so")):
        distribution = importlib.metadata.distribution(package)
        matches = [file for file in distribution.files or () if str(file).endswith(suffix)]
        if len(matches) != 1:
            raise ValueError("runtime_binary_provenance_unavailable")
        binary = Path(distribution.locate_file(matches[0]))
        result[package + "/" + suffix] = {"binary": suffix,
                                          "sha256": _file_identity(binary)["sha256"]}
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



def _empty_python_context(reason: str, child: dict | None = None) -> dict:
    return {"status": "unavailable", "reason": reason, "complete": False, "threads": [],
            "omitted_frames": 0, "omitted_threads": 0, "log_truncated": bool((child or {}).get("output_truncated"))}


def _fatal_thread_line(line: str, threads: list) -> None:
    if not threads:
        raise ValueError("frame_without_thread")
    thread = threads[-1]
    frame = re.fullmatch(r'  File "([^"\n]{1,500})", line ([1-9][0-9]{0,6}) in ([^\n]{1,500})', line)
    if frame:
        if len(thread["raw_frames"]) >= 100:
            raise ValueError("frame_protocol_limit")
        thread["raw_frames"].append((frame[1], int(frame[2]), frame[3]))
    elif line == "  ...":
        thread["frames_truncated"] = True
    elif line == "  Garbage-collecting" and thread["current"] and not thread["raw_frames"]:
        thread["garbage_collecting"] = True
    elif line in ("  <no Python frame>", "  <tstate is freed>"):
        thread["frames_truncated"] = True
    else:
        raise ValueError("malformed_fatal_block")


def _fatal_threads(text: str, observed_signal: int) -> tuple[list, bool]:
    names = {4: "Illegal instruction", 6: "Aborted", 7: "Bus error",
             8: "Floating point exception", 11: "Segmentation fault"}
    banners = list(re.finditer(r"(?m)^Fatal Python error: ([A-Za-z ]+)\r?$", text))
    if (len(banners) != 1 or text.count("Fatal Python error:") != 1
            or banners[0][1] != names.get(observed_signal)):
        raise ValueError("missing_ambiguous_or_mismatched_fatal_block")
    lines = text[banners[0].end():].splitlines()
    if len(lines) > 12000:
        raise ValueError("fatal_block_protocol_limit")
    threads, tokens, complete = [], set(), False
    for line in lines:
        if not line:
            continue
        if line.startswith("Extension modules: "):
            complete = True
            break  # The extension list is never retained.
        header = re.fullmatch(r"(Current thread|Thread) 0x([0-9a-fA-F]{1,16}) \(most recent call first\):", line)
        if header:
            if int(header[2], 16) in tokens or len(threads) >= 100:
                raise ValueError("ambiguous_thread_block")
            tokens.add(int(header[2], 16))
            threads.append({"ordinal": len(threads) + 1, "current": header[1] == "Current thread",
                            "garbage_collecting": False, "raw_frames": [],
                            "frames_truncated": False})
        elif line == "...":
            complete = False
            break  # CPython's thread cap: the remainder is unavailable.
        else:
            _fatal_thread_line(line, threads)
    if (not threads or sum(t["current"] for t in threads) > 1
            or any(not t["raw_frames"] and not t["frames_truncated"] for t in threads)):
        raise ValueError("missing_or_ambiguous_threads")
    return threads, complete


def _source_scopes(checkout: Path, path: str) -> set:
    # Compile trusted frozen bytes only; never import or execute workload code.
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(checkout), "cat-file", "blob", FROZEN_SHA + ":" + path],
        capture_output=True, check=True, timeout=20)
    pending = [compile(result.stdout, path, "exec", dont_inherit=True, optimize=0)]
    scopes = set()
    while pending:
        code = pending.pop()
        scopes.update((code.co_name, line) for _, _, line in code.co_lines() if line is not None)
        pending.extend(value for value in code.co_consts if isinstance(value, types.CodeType))
    return scopes


def _validated_python_frame(raw: tuple, checkout: Path, inventory: set, scopes: dict) -> dict | None:
    path, line, function = raw
    prefix = str(checkout.resolve()) + "/"
    if path.startswith(prefix):
        path = path[len(prefix):]
    if (not re.fullmatch(r"[A-Za-z0-9_./-]{1,400}", path)
            or any(part in ("", ".", "..") for part in path.split("/"))
            or path not in inventory
            or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*|<(?:module|lambda|listcomp|dictcomp|setcomp|genexpr)>", function)):
        return None
    if path not in scopes:
        scopes[path] = _source_scopes(checkout, path)
    if (function, line) not in scopes[path]:
        return None
    return {"path": path, "line": line, "function": function}


def _bounded_python_threads(threads: list, checkout: Path, inventory: set) -> dict:
    ordered = sorted(threads, key=lambda thread: not thread["current"])
    output, scopes, retained = [], {}, 0
    omitted = sum(len(t["raw_frames"]) for t in ordered[8:])
    for thread in ordered[:8]:
        frames = []
        dropped = 0
        for raw in thread["raw_frames"]:
            frame = _validated_python_frame(raw, checkout, inventory, scopes) if retained < 96 else None
            if frame is None:
                dropped += 1
            else:
                frames.append(frame)
                retained += 1
        omitted += dropped
        output.append({key: thread[key] for key in ("ordinal", "current", "garbage_collecting", "frames_truncated")})
        output[-1].update(frames=frames, omitted_frames=dropped)
    result = {"threads": output, "omitted_frames": omitted, "omitted_threads": max(0, len(threads) - 8)}
    # Reserve more than1KiB for fixed status and controller identity metadata.
    while len(json.dumps(result, ensure_ascii=True, separators=(",", ":"))) > 14000:
        thread = next(t for t in reversed(output) if t["frames"])
        thread["frames"].pop()
        thread["omitted_frames"] += 1
        result["omitted_frames"] += 1
    return result


def _python_workload_stage(label: str) -> bool:
    return label in ("main", "dashboard") or bool(re.fullmatch(r"industrial_(?:[1-9]|10)", label))


def _python_fault_context(text: str, checkout: Path, child: dict, label: str) -> dict:
    sig = child.get("signal")
    if (not _python_workload_stage(label) or sig not in (4, 6, 7, 8, 11) or child.get("child_exit") != -sig
            or child.get("timed_out") or child.get("cancelled")):
        return _empty_python_context("not_an_eligible_native_failure", child)
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 11):
        return _empty_python_context("mapping_compiler_unverified", child)
    try:
        _verify_workload(checkout)
        inventory = {row.split("\t", 1)[1] for row in
                     _git(checkout, "ls-tree", "-rz", FROZEN_SHA).split("\0")
                     if re.match(r"100(?:644|755) blob [0-9a-f]{40}\t", row)
                     and row.endswith(".py")}
    except InterruptedError:
        raise
    except Exception:
        return _empty_python_context("source_unverified", child)
    try:
        threads, terminated = _fatal_threads(text, sig)
        result = _bounded_python_threads(threads, checkout, inventory)
    except InterruptedError:
        raise
    except ValueError:
        return _empty_python_context("malformed_or_untrusted_context", child)
    except Exception:
        return _empty_python_context("source_mapping_unavailable", child)
    frames = sum(len(t["frames"]) for t in result["threads"])
    complete = (terminated and not child.get("output_truncated") and not result["omitted_frames"]
                and not result["omitted_threads"] and any(t["current"] for t in threads)
                and not any(t["frames_truncated"] for t in threads))
    result.update(status=("available" if complete else "partial") if frames else "unavailable",
                  reason="validated_source_coordinates" if frames else "no_validated_source_frames",
                  complete=bool(complete and frames), log_truncated=bool(child.get("output_truncated")))
    return result


def _python_context_receipt(context: dict, child: dict, label: str, receipt: dict) -> dict:
    identity = receipt["identity"]
    # Values originate in verified admission/controller state, never child text.
    value = {"python_fault_context": {"run_id": identity["run_id"], "phase": PHASE,
        "stage": label, "pid": child["pid"], "signal": child["signal"],
        "scaffolding_sha": identity["scaffolding_sha"], "workload_sha": FROZEN_SHA,
        "workload_tree": FROZEN_TREE, "context": context}}
    if len(_safe_json(value).encode("ascii")) > 16384:
        raise ValueError("python_context_output_limit")
    return value


def _extract_python_after_exit(text: str, cwd: Path, receipt: dict, label: str) -> dict:
    try:
        return _python_fault_context(text, cwd, receipt, label)
    except InterruptedError:
        raise
    except Exception:
        return _empty_python_context("extraction_error", receipt)


def _run_private(command: list[str], cwd: Path, root: Path, label: str, *, timeout: float = 120,
                 consume=None, environment=None, core_allowed=True) -> dict:
    if not 0 < timeout <= 1200:
        raise ValueError("invalid_stage_timeout")
    output = root / (label + ".raw")
    started = time.monotonic()
    with output.open("wb") as log:
        with subprocess.Popen(command, cwd=cwd, env=environment or _child_environment(root),
                              stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                              preexec_fn=_child_limits if core_allowed else _tool_limits) as child:
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
        if receipt["signal"] and _python_workload_stage(label):
            receipt["python_context"] = _extract_python_after_exit(text, cwd, receipt, label)
        if consume is not None and not receipt["output_truncated"]:
            consume(text)
        output.unlink()
        receipt["output_ok"] = True
    except InterruptedError:
        # The child has already terminated: preserve its real status and tell
        # every caller to stop before any new post-mortem process. Final cleanup
        # owns the private log/core still present after this interruption.
        receipt["post_exit_interrupted"] = True
        receipt["python_context"] = _empty_python_context("extraction_interrupted", receipt)
    except OSError as error:
        # The already observed exit is authoritative even if log processing fails.
        receipt["output_capture_error"] = type(error).__name__
    return receipt


def _core_script(output: Path, sysroot: Path | None = None) -> str:
    # Structured GDB APIs avoid exporting the automatic raw core/argument banner.
    return f'''python
import gdb, json, os, re
expected_root = {str(sysroot) if sysroot else None!r}
if expected_root is not None:
    for obj in gdb.objfiles():
        virtual = re.fullmatch(r"system-supplied DSO at 0x[0-9a-fA-F]+", obj.filename)
        if not virtual and not os.path.realpath(obj.filename).startswith(expected_root + os.sep):
            raise RuntimeError("target_binary_outside_preserved_sysroot")
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


def _inspect_core(root: Path, child: dict, executable: str, *, symbolizer=None) -> dict:
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
        sysroot = root / "sysroot" if symbolizer else None
        script.write_text(_core_script(stack, sysroot), encoding="utf-8")
        command = [symbolizer["executable"] if symbolizer else "/usr/bin/gdb",
                   "-q", "-batch", "-nx", "-nh",
                   *(["--data-directory=" + str(Path(symbolizer["executable"]).parents[1] / "share/gdb")]
                     if symbolizer else []),
                   "-iex", "set auto-load off", "-iex", "set debuginfod enabled off",
                   "-iex", "set print frame-arguments none", "-iex", "set print pretty off",
                   "-iex", "set print entry-values no",
                   *(["-iex", "set sysroot " + str(sysroot),
                      "-iex", "set solib-search-path " + str(sysroot / "empty"),
                      "-iex", "set debug-file-directory " + str(sysroot / "empty")]
                     if sysroot else []), "-se", executable, "-c", str(core),
                   "-x", str(script)]
        debugger = _run_private(command, root, root, "debugger",
                                **({"environment": symbolizer["environment"], "core_allowed": False}
                                   if symbolizer else {}))
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


def _storage_ready(root: Path, reserve: int = CORE_LIMIT) -> None:
    # Two retained cores, one active raw log and two512MiB private binary sets
    # fit below8GiB. No experiment cache/artifact or unrestricted snapshot.
    total = sum(path.lstat().st_size for path in root.rglob("*") if not path.is_dir())
    if total + reserve > PRIVATE_LIMIT or shutil.disk_usage(root).free < reserve + 1024**3:
        raise ValueError("private_storage_budget_unavailable")


def _file_identity(path: Path) -> dict:
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > LIBRARY_LIMIT:
        raise ValueError("binary_not_bounded_regular_file")
    with path.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise ValueError("binary_not_elf")
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    def identity(info):
        return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    if identity(before) != identity(after):
        raise ValueError("binary_changed_while_reading")
    return {"stat": identity(after), "sha256": digest}


def _loader_paths(text: str) -> set[Path]:
    return {Path(line.split(" => ", 1)[1]) for line in text.splitlines() if " => /" in line}


def _inventory_binaries(root: Path) -> dict:
    candidates = {Path(sys.executable), Path(sys.executable).resolve(),
                  Path("/lib64/ld-linux-x86-64.so.2")}
    checked = _run_private(["/sbin/ldconfig", "-p"], root, root, "loader_inventory",
                           consume=lambda text: candidates.update(_loader_paths(text)), core_allowed=False)
    if not _complete_stage(checked, []):
        raise ValueError("loader_inventory_unavailable")
    for distribution in importlib.metadata.distributions():
        for file in distribution.files or ():
            if ".so" in Path(str(file)).name:
                candidates.add(Path(distribution.locate_file(file)))
    candidates.update((Path(sys.base_prefix) / "lib").glob("libpython*.so*"))
    candidates.update((Path(sys.base_prefix) / "lib/python3.11/lib-dynload").glob("*.so"))
    if len(candidates) > 4096:
        raise ValueError("binary_inventory_limit")
    inventory, identities = {}, {}
    for candidate in sorted(candidates):
        resolved = candidate.resolve(strict=True)
        if str(resolved) not in identities:
            identities[str(resolved)] = _file_identity(resolved)
        inventory[str(candidate.absolute())] = identities[str(resolved)]
        inventory[str(resolved)] = identities[str(resolved)]
    (root / "binaries.json").write_text(json.dumps(inventory))
    return inventory


def _system_packages(root: Path) -> list[list[str]]:
    rows = []
    checked = _run_private(["/usr/bin/dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\n"],
                            root, root, "system_packages", core_allowed=False,
                            consume=lambda text: rows.extend(line.split("\t") for line in text.splitlines()))
    if (not _complete_stage(checked, []) or not 1 <= len(rows) <= 2500
            or any(len(row) != 3 or any(not re.fullmatch(r"[A-Za-z0-9.+:~_-]{1,120}", item)
                                       for item in row) for row in rows)):
        raise ValueError("system_package_provenance_unavailable")
    return sorted(rows)


def _record_package_provenance(root: Path) -> str:
    system = _system_packages(root)
    (root / "system-packages.json").write_text(json.dumps(system))
    python = sorted([distribution.metadata["Name"], distribution.version]
                    for distribution in importlib.metadata.distributions())
    if (len(python) > 250 or any(not re.fullmatch(r"[A-Za-z0-9.+_-]{1,100}", item)
                               for row in python for item in row)):
        raise ValueError("python_package_provenance_unavailable")
    for kind, rows in (("system", system), ("python", python)):
        for offset in range(0, len(rows), 80):
            _emit_hosted({"pre_workload_packages": {"kind": kind, "offset": offset,
                "total": len(rows), "rows": rows[offset:offset + 80]}})
    return hashlib.sha256(json.dumps(system).encode()).hexdigest()


def _collect_core(root: Path, child: dict) -> dict:
    core = root / ("core." + str(child["pid"]))
    if not core.exists():
        return {"capture": "missing_core", "ok": False}
    info = core.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or not 4 < info.st_size < CORE_LIMIT):
        return {"capture": "invalid_core", "ok": False}
    with core.open("rb") as stream:
        header = stream.read(64)
        valid = (len(header) == 64 and header[:7] == b"\x7fELF\x02\x01\x01"
                 and header[16:20] == b"\x04\x00\x3e\x00")
    return {"capture": "collected_not_symbolized" if valid else "invalid_core",
            "ok": valid, "core_bytes": info.st_size}


def _mapped_files(text: str) -> list[str]:
    count = text.count("NT_FILE (mapped files)")
    if count != 1:
        raise PreflightError(PreflightReason.TABLE_AMBIGUOUS if count else PreflightReason.TABLE_UNSUPPORTED)
    table = text.split("NT_FILE (mapped files)", 1)[1]
    table = re.split(r"\n\s*\S+\s+0x[0-9a-fA-F]+\s+NT_", table, maxsplit=1)[0]
    if re.fullmatch(r"\s*Cannot decode 64-bit note in 32-bit build\s*", table):
        raise PreflightError(PreflightReason.TABLE_UNSUPPORTED)
    rows = re.findall(r"(?m)^\s*0x[0-9a-fA-F]+\s+0x[0-9a-fA-F]+\s+0x[0-9a-fA-F]+\s*\n([^\n]+)", table)
    paths = [row.strip() for row in rows]
    if not all(paths) or not paths or len(paths) != len(re.findall(r"(?m)^\s*0x", table)):
        raise PreflightError(PreflightReason.TABLE_TRUNCATED)
    if any(" (deleted)" in path for path in paths):
        raise PreflightError(PreflightReason.DELETED_MAPPING)
    if (len(paths) > 4096 or any(not path.startswith("/") or "\x00" in path
                                or ".." in Path(path).parts for path in paths)):
        raise PreflightError(PreflightReason.TABLE_MALFORMED)
    return sorted(set(paths))


def _matched_elf_identity(source: Path, expected: dict | None) -> dict | None:
    try:
        if expected is not None:
            if _file_identity(source) != expected:
                raise PreflightError(PreflightReason.BINARY_CHANGED)
            return expected
        with source.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                return None  # Mapped data is never copied or named in output.
    except (PreflightError, InterruptedError):
        raise
    except FileNotFoundError:
        raise PreflightError(PreflightReason.BINARY_MISSING) from None
    except ValueError:
        raise PreflightError(PreflightReason.BINARY_CHANGED) from None
    except OSError:
        raise PreflightError(PreflightReason.BINARY_UNREADABLE) from None
    raise PreflightError(PreflightReason.BINARY_UNRECORDED)


def _copy_matched_elf(root: Path, source: Path, expected: dict, copied_bytes: int) -> int:
    target = root / "sysroot" / str(source).lstrip("/")
    if not target.exists():
        try:
            copied_bytes += source.stat().st_size
            if copied_bytes > LIBRARY_LIMIT:
                raise ValueError("preserved_library_limit")
            _storage_ready(root, source.stat().st_size)
        except InterruptedError:
            raise
        except (OSError, ValueError):
            raise PreflightError(PreflightReason.STORAGE_UNAVAILABLE) from None
        try:
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with source.open("rb") as original, target.open("xb") as copy:
                os.chmod(target, 0o600)
                shutil.copyfileobj(original, copy, 1024**2)
        except InterruptedError:
            raise
        except OSError:
            raise PreflightError(PreflightReason.COPY_FAILED) from None
    try:
        digest = _file_identity(target)["sha256"]
    except InterruptedError:
        raise
    except (OSError, ValueError):
        raise PreflightError(PreflightReason.HASH_UNAVAILABLE) from None
    if digest != expected["sha256"]:
        raise PreflightError(PreflightReason.HASH_MISMATCH)
    _matched_elf_identity(source, expected)
    return copied_bytes


def _preserve_mapped_files(root: Path, paths: list[str], inventory: dict) -> list[dict]:
    result = []
    try:
        copied_bytes = sum(path.stat().st_size for path in (root / "sysroot").rglob("*") if path.is_file())
    except InterruptedError:
        raise
    except OSError:
        raise PreflightError(PreflightReason.STORAGE_UNAVAILABLE) from None
    for name in sorted(set(paths)):
        source = Path(name)
        if not source.is_absolute() or ".." in source.parts:
            raise PreflightError(PreflightReason.INVALID_PATH)
        expected = _matched_elf_identity(source, inventory.get(name))
        if expected is None:
            continue
        copied_bytes = _copy_matched_elf(root, source, expected, copied_bytes)
        result.append({"module": re.sub(r"[^A-Za-z0-9_.+-]", "?", source.name)[:100],
                       "sha256": expected["sha256"]})
    if not result:
        raise PreflightError(PreflightReason.NO_ELF)
    return result


def _read_core_notes(root: Path, pid) -> tuple[str, dict]:
    output = []  # Transient bounded text only; never placed in a public receipt.
    try:
        read = _run_private(["/usr/bin/readelf", "-n", "-W", str(root / ("core." + str(pid)))],
                            root, root, "core_notes", consume=output.append,
                            environment={**_child_environment(root), "LC_ALL": "C"}, core_allowed=False)
    except InterruptedError:
        raise PreflightInterrupted() from None
    except FileNotFoundError:
        raise PreflightError(PreflightReason.TOOL_UNAVAILABLE) from None
    except OSError:
        raise PreflightError(PreflightReason.OUTPUT_UNAVAILABLE) from None
    if read.get("cancelled") or read.get("post_exit_interrupted"):
        raise PreflightInterrupted(read)
    for failed, reason in ((read.get("timed_out"), PreflightReason.TIMED_OUT),
                           (read.get("output_truncated"), PreflightReason.OUTPUT_TRUNCATED),
                           (read.get("child_exit") != 0, PreflightReason.TOOL_FAILED),
                           (not _complete_stage(read, []) or len(output) != 1, PreflightReason.OUTPUT_UNAVAILABLE)):
        if failed:
            raise PreflightError(reason, read)
    return output[0], read


def _preserve_core_binaries(root: Path, child: dict, executable: str, inventory: dict) -> list[dict]:
    text, read = _read_core_notes(root, child["pid"])
    try:
        paths = _mapped_files(text)
        try:
            expected = str(Path(executable).resolve(strict=True))
        except InterruptedError:
            raise
        except OSError:
            raise PreflightError(PreflightReason.EXECUTABLE_UNAVAILABLE) from None
        if expected not in paths:
            raise PreflightError(PreflightReason.EXECUTABLE_ABSENT)
        return _preserve_mapped_files(root, [*paths, executable], inventory)
    except PreflightError as error:
        error.tool = _preflight_tool_status(read)
        raise
    except InterruptedError:
        raise PreflightInterrupted(read) from None
    except Exception:
        raise PreflightError(PreflightReason.UNKNOWN, read) from None


def _prepare_symbolizer(root: Path) -> dict:
    # Runs only after the entire workload has stopped and mapped files are saved.
    # Fixed trusted Ubuntu package set; no apt install/upgrade or general resolver.
    packages, extracted = root / "packages", root / "symbolizer"
    packages.mkdir(mode=0o700)
    extracted.mkdir(mode=0o700)
    _storage_ready(root, SYMBOLIZER_LIMIT)
    environment = {**_child_environment(root), "TMPDIR": str(root / "temporary")}
    sizes = []
    metadata = _run_private(["/usr/bin/apt-cache", "show", "--no-all-versions", *SYMBOLIZER_PACKAGES],
                            root, root, "symbolizer_sizes", core_allowed=False,
                            consume=lambda text: sizes.extend(re.findall(r"(?m)^(Size|Installed-Size): ([0-9]+)$", text)))
    if (not _complete_stage(metadata, []) or len(sizes) != 2 * len(SYMBOLIZER_PACKAGES)
            or sum(int(size) * (1024 if kind == "Installed-Size" else 1) for kind, size in sizes) > SYMBOLIZER_LIMIT):
        raise ValueError("symbolizer_package_budget_unavailable")
    download = _run_private(["/usr/bin/apt-get", "download", *SYMBOLIZER_PACKAGES],
                            packages, root, "symbolizer_download", timeout=180,
                            environment=environment, core_allowed=False)
    if not _complete_stage(download, []):
        raise ValueError("isolated_symbolizer_download_failed")
    archives = sorted(packages.glob("*.deb"))
    if len(archives) != len(SYMBOLIZER_PACKAGES):
        raise ValueError("isolated_symbolizer_package_set_incomplete")
    total = sum(path.stat().st_size for path in archives)
    provenance = []
    for archive in archives:
        fields = []
        metadata = _run_private(["/usr/bin/dpkg-deb", "-f", str(archive), "Package", "Version", "Installed-Size"],
                                root, root, "symbolizer_metadata", core_allowed=False,
                                consume=lambda text: fields.extend(text.splitlines()))
        if not _complete_stage(metadata, []):
            raise ValueError("symbolizer_package_metadata_failed")
        parsed = dict(line.split(": ", 1) for line in fields)
        if parsed["Package"] not in SYMBOLIZER_PACKAGES or not re.fullmatch(r"[0-9A-Za-z.+:~_-]{1,100}", parsed["Version"]):
            raise ValueError("symbolizer_package_identity_failed")
        total += int(parsed["Installed-Size"]) * 1024
        if total > SYMBOLIZER_LIMIT:
            raise ValueError("symbolizer_storage_limit")
        provenance.append({"package": parsed["Package"], "version": parsed["Version"],
                           "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()})
        unpack = _run_private(["/usr/bin/dpkg-deb", "-x", str(archive), str(extracted)],
                              root, root, "symbolizer_extract", environment=environment, core_allowed=False)
        if not _complete_stage(unpack, []):
            raise ValueError("isolated_symbolizer_extract_failed")
        _storage_ready(root, 0)
    environment["LD_LIBRARY_PATH"] = str(extracted / "usr/lib/x86_64-linux-gnu") + ":/usr/lib/x86_64-linux-gnu"
    return {"executable": str(extracted / "usr/bin/gdb"), "environment": environment,
            "packages": provenance}


def _preserve_pending_cores(root: Path, pending: list, receipt: dict) -> tuple:
    inventory = json.loads((root / "binaries.json").read_text())
    preserved, usable = {}, []
    for label, child, executable in pending:
        try:
            if not _collect_core(root, child)["ok"]:
                raise ValueError("post_workload_core_unavailable")
            preserved[label] = _preserve_core_binaries(root, child, executable, inventory)
        except InterruptedError:
            raise
        except (OSError, ValueError) as error:
            if label == "synthetic_control":
                raise
            receipt["natural_binary_capture"] = {"stage": label, "ok": False,
                                                  "error": type(error).__name__,
                                                  "failure": _preflight_failure(error)}
            continue
        usable.append((label, child, executable))
    return usable, preserved


def _symbolize_after_workload(root: Path, receipt: dict, result: int) -> int:
    if any(stage.get("cancelled") or stage.get("post_exit_interrupted")
           for stage in receipt.get("stages", [])):
        receipt["symbolization"] = "not_started_after_cancel"
        return result or 70
    pending = [("synthetic_control", receipt["synthetic_control"], str(root / "control"))]
    pending.extend((stage["stage"], stage, sys.executable) for stage in receipt.get("stages", [])
                   if stage.get("signal") and not stage.get("timed_out"))
    usable, preserved = _preserve_pending_cores(root, pending, receipt)
    symbolizer = _prepare_symbolizer(root)
    if _system_packages(root) != json.loads((root / "system-packages.json").read_text()):
        raise ValueError("system_packages_changed_during_symbolizer_preparation")
    receipt["system_packages_unchanged_after_symbolizer"] = True
    receipt["symbolizer_packages"] = symbolizer["packages"]
    for label, child, executable in usable:
        private_executable = root / "sysroot" / executable.lstrip("/")
        native = _inspect_core(root, child, str(private_executable), symbolizer=symbolizer)
        _emit_hosted({"post_workload_native": {"stage": label,
            "pid": child["pid"], "signal": child["signal"], "source_sha": FROZEN_SHA,
            "source_tree": FROZEN_TREE, "matching_binary_count": len(preserved[label]),
            "matching_manifest_sha256": hashlib.sha256(json.dumps(preserved[label], sort_keys=True).encode()).hexdigest(),
            **native}})
        if label == "synthetic_control":
            receipt["control_symbolization_ok"] = bool(native["ok"] and "qt998_crash_control" in json.dumps(native))
            if not receipt["control_symbolization_ok"]:
                raise ValueError("synthetic_symbolization_unproven")
        elif (native["ok"] and child.get("python_context_status") in ("available", "partial")
              and child.get("python_context_receipt") == label
              and not child.get("python_context_publication_error")):
            receipt["observation"] = "CAPTURED"
            receipt["paired_process"] = {"pid": child["pid"], "signal": child["signal"], "stage": label}
        elif child.get("signal"):
            receipt["observation"] = "CAPTURE INCOMPLETE"
    receipt["symbolization"] = "finished"
    return result


def _prepare_hosted_capture(root: Path, workload: Path) -> dict:
    os.umask(0o077)
    for name in ("home", "temporary"):
        (root / name).mkdir(mode=0o700)
    _verify_workload(workload)
    if not Path("/usr/bin/gcc").is_file() or not Path("/usr/bin/readelf").is_file():
        raise ValueError("capture_prerequisite_unavailable")
    _storage_ready(root, 7 * 1024**3)
    package_digest = _record_package_provenance(root)
    inventory = _inventory_binaries(root)
    selected = {"libc.so.6", "ld-linux-x86-64.so.2", "libpython3.11.so.1.0"}
    runtime_binaries = [{"binary": Path(path).name, "sha256": identity["sha256"]}
                        for path, identity in inventory.items() if Path(path).name in selected]
    original = Path("/proc/sys/kernel/core_pattern").read_text().strip()
    (root / "core-route.json").write_text(json.dumps({"original": original}))
    _set_core_pattern(str(root / "core.%p"))
    return {
        "python": platform.python_version(), "kernel": platform.release(),
        "libc": platform.libc_ver(), "runner_image": os.environ.get("ImageVersion", "unknown"),
        "packages": {name: importlib.metadata.version(name) for name in RUNTIME_PACKAGES},
        "python_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "inventory_files": len(inventory),
        "runtime_binary_provenance": runtime_binaries,
        "system_packages_sha256": package_digest,
        "qt_binary_provenance": _binary_provenance(),
        "normalization": "ordinary safe locale/theme/bytecode values; offscreen; private HOME/coverage; allowlisted env; limits; no raw publication",
    }


def _validate_runtime(environment: dict) -> None:
    if environment["python"] != "3.11.16" or environment["packages"] != RUNTIME_PACKAGES:
        raise ValueError("material_runtime_mismatch")


def _capture_ready(root: Path) -> None:
    if (Path("/proc/sys/kernel/core_pattern").read_text().strip() != str(root / "core.%p")
            or shutil.disk_usage(root).free < CORE_LIMIT + 1024**3):
        raise ValueError("capture_capability_lost")
    _storage_ready(root, 2 * CORE_LIMIT)


def _prove_hosted_capture(root: Path, receipt: dict) -> None:
    _capture_ready(root)
    success = _run_private([sys.executable, "-c", "raise SystemExit(0)"], root, root, "success")
    receipt["success_control"] = success
    missing = _collect_core(root, {"pid": "missing", "signal": 11})
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
    inventory = json.loads((root / "binaries.json").read_text())
    inventory[str(binary)] = _file_identity(binary)
    (root / "binaries.json").write_text(json.dumps(inventory))
    control = _run_private([str(binary)], root, root, "synthetic")
    receipt["synthetic_control"] = control
    if control.get("post_exit_interrupted") or control.get("cancelled"):
        raise InterruptedError("control_post_exit_interrupted")
    capture = _collect_core(root, control)
    receipt["synthetic_control"] = {**control, **capture,
                                     "core_removed": not (root / ("core." + str(control["pid"]))).exists()}
    if (control["child_exit"] != -11 or not control["output_ok"] or not capture["ok"]
            or control.get("timed_out") or control.get("cancelled")
            or control.get("output_truncated")):
        raise ValueError("collection_capability_unproven")
    # readelf inspects mapping metadata only; this is still collection, no GDB.
    saved = _preserve_core_binaries(root, control, str(binary), inventory)
    receipt["synthetic_control"]["preserved_binary_count"] = len(saved)
    receipt["capability"] = "collection_proven; symbolization_deferred"


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


def _publish_python_context(context, child, label, receipt, entry, result):
    if context is None:
        return result
    entry["python_context_status"] = context.get("status", "unavailable")
    try:
        _emit_hosted(_python_context_receipt(context, child, label, receipt))
        entry["python_context_receipt"] = label
    except Exception:
        entry["python_context_publication_error"] = True
        result = _emit_preserving_exit({"python_context_output_error": True,
                                       "launcher_exit": result or 70}, result or 70)
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
    result, python_context, child = 70, None, None
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
        if child["signal"] and _python_workload_stage(label):
            python_context = child.pop("python_context", _empty_python_context("private_output_unavailable", child))
        entry.update(child)
        # Set terminal status before post-mortem, source verification or export.
        result = _postmortem_exit(child["child_exit"], False)
        receipt["acquisition_exit"] = result
        if child.get("post_exit_interrupted") or child.get("cancelled"):
            entry.update(capture="not_inspected_after_interrupt", ok=False)
            raise InterruptedError("workload_post_exit_interrupted")
        capture = ((_collect_core(root, child) if receipt.get("deferred_symbolization")
                    else _inspect_core(root, child, sys.executable)) if child["signal"]
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
    result = _publish_python_context(python_context, child, label, receipt, entry, result)
    receipt["acquisition_exit"] = result
    # Native frames are exported in the bounded stage receipt, once. The final
    # cumulative ledger references that stage without duplicating a large stack.
    if "native" in entry:
        entry["native_stack_receipt"] = label
        del entry["native"]
    return result


def _failed_observation(stage: dict) -> str:
    if (stage.get("timed_out") or stage.get("cancelled") or stage.get("post_exit_interrupted")
            or not stage.get("child_exit")):
        return "INCOMPLETE_WORKLOAD"
    return "FAILED_WORKLOAD"


def _acquire_sequence(root: Path, workload: Path, receipt: dict) -> int:
    receipt.update(stages=[], observation="INCOMPLETE_WORKLOAD", industrial_limit=1,
                   industrial_aggregate_limit_seconds=120,
                   context="prefix once; fresh processes; shared cumulative coverage")
    epoch = receipt.get("identity", {}).get("observation_deadline_epoch")
    job_deadline = (time.monotonic() + max(0, epoch - time.time() - POSTMORTEM_SECONDS)
                    if epoch is not None else None)
    coverage = PYTEST_ARGUMENTS[2:]
    prefix = [
        ("coverage_erase", [sys.executable, "-m", "coverage", "erase"], [], 60),
        ("main", [sys.executable, "-m", "pytest", "tests", "-q",
                  *[arg for arg in coverage if arg != "--cov-append"]],
         ["3903 passed", "62 skipped"], 1200),
        ("dashboard", [sys.executable, "-m", "pytest",
                       "tests/test_dashboard_visual_options_dialog.py", "-q", *coverage],
         ["24 passed"], 120),
    ]
    for label, command, expected, timeout in prefix:
        result = _acquisition_stage(root, workload, receipt, label, command, expected, timeout,
                                    deadline=job_deadline)
        if result:
            receipt["observation"] = ("CAPTURE INCOMPLETE" if receipt.get("deferred_symbolization")
                                      else _failed_observation(receipt["stages"][-1]))
            return result
    deadline = time.monotonic() + 120
    if job_deadline is not None:
        deadline = min(deadline, job_deadline)
    for sample in range(1, 2):
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
            receipt["observation"] = ("CAPTURE INCOMPLETE" if receipt.get("deferred_symbolization")
                                      else _failed_observation(receipt["stages"][-1]))
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
    receipt = {"identity": admission, "observation": "not_started", "capability": "unproven",
               "deferred_symbolization": True}
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
        result = _acquire_sequence(root, workload, receipt)
        remaining = min(POSTMORTEM_SECONDS, int(admission["observation_deadline_epoch"] - time.time()))
        if remaining <= 0:
            raise TimeoutError("postmortem_budget_unavailable")
        signal.alarm(remaining)
        result = _symbolize_after_workload(root, receipt, result)
    except Exception as error:
        receipt["diagnostic_error"] = "InterruptedError" if isinstance(error, PreflightInterrupted) else type(error).__name__
        receipt["preflight_failure"] = _preflight_failure(error)
        result = receipt.get("acquisition_exit", result) or 70
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
