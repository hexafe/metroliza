"""Observe the existing Linux industrial coverage shard once; never retry it.

Issue #998 permits this diagnostic observation, not a claimed lifecycle repair.
Only sanitized text and compact receipts are retained; no core or memory capture.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile

from metroliza.industrial.industrial_data_repository import redact_sensitive_text


def _sanitize(text: str) -> str:
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


if __name__ == "__main__":
    raise SystemExit(main())
