"""Windows first-run timeline: what the user sees from the double-click to the usable window.

STEP2 instrumentation (Performance Boost STEP2). For each launcher variant (for example the
current launcher and the splash PoC, both packing the SAME onedir) this runs the real application
through these scenarios, in order, on private runtime roots:

* ``cold``: a fresh copy of the EXE (new file, so antivirus scans it again) and an empty cache;
* ``verified``: the second launch of that cache (hash and flush of every file);
* ``warm``: later launches (existence and size checks only);
* ``new_version``: an EXE of another version on the same root (cold extraction plus cleanup);
* ``corrupt``: a truncated runtime DLL in the warm cache (detected by size, re-extracted);
* ``warmup``: a warm launch without the UI smoke exit that leaves after the feature warmup, to
  time the first USABLE window and the GUI-thread stalls after first paint.

Sources of truth per launch, all on the same wall clock (epoch milliseconds):

* the launcher log ``timing event=<name> epoch_ms=<ms>`` lines (PoC launchers only; the current
  launcher logs only ``cache=`` facts);
* the application startup profile (``METROLIZA_STARTUP_PROFILE``);
* a window sampler (every 20 ms): every visible top-level window of the launcher, supervisor and
  application processes, classified as launcher splash, launcher progress window, Qt splash or
  main window, plus the foreground window;
* optional screenshots (``--frames``) for a frame chronology, and a per-frame signature of the
  splash animation area, so a frozen animation is visible as identical consecutive frames.

Every launch that extracts or verifies (cache ``cold``, ``verified`` or ``repair``) must show a
launcher window: the splash, or the plain progress window (the current launcher, and the splash
launcher's fallback when ``METROLIZA_LAUNCHER_SPLASH=0`` or the splash cannot be shown). A launch
without one, or a splash-disabled launch without the progress window, gets a warning.

Derived metrics: time to the first visible Metroliza window, the longest interval without any
Metroliza window before the main window, overlap of two splash windows, main window visible,
foreground owner when the main window appeared, launcher ``main`` relative to process creation
(the OS and antivirus delay before launcher code runs), and the application stall summary.
Hosted-runner numbers are indicative; they are not clean-laptop numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.measure_windows_startup_routes import (  # noqa: E402
    _kill_tree,
    build_environment,
    launcher_cache_outcome,
    load_events,
)

SAMPLE_MS = 20
LAUNCH_TIMEOUT_S = 240.0
SPLASH_CLASS = "MetrolizaLauncherSplash"
PROGRESS_CLASS = "MetrolizaLauncherProgress"
APP_PROCESS_NAMES = {"metroliza.exe", "metroliza_application.exe"}
CORRUPT_TARGET = "_internal/python311.dll"


# ---------------------------------------------------------------- Win32 window sampling


class WindowSampler:
    """Polls visible top-level windows of the launch's processes every ``SAMPLE_MS``."""

    def __init__(self, launcher_name: str, frames_dir: Path | None, frame_every_ms: int) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.names = {launcher_name.lower(), *APP_PROCESS_NAMES}
        self.frames_dir = frames_dir
        self.frame_every_ms = frame_every_ms
        self.samples: list[dict[str, Any]] = []
        self.frames: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._process_names: dict[int, str] = {}
        self.WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.EnumWindows.argtypes = [self.WNDENUMPROC, wintypes.LPARAM]
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        ]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _process_name(self, pid: int) -> str:
        if pid in self._process_names:
            return self._process_names[pid]
        name = ""
        handle = self.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            buffer = self.ctypes.create_unicode_buffer(1024)
            size = self.wintypes.DWORD(1024)
            if self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, self.ctypes.byref(size)):
                name = Path(buffer.value).name.lower()
            self.kernel32.CloseHandle(handle)
        self._process_names[pid] = name
        return name

    def _windows(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def visit(hwnd, _lparam):
            if not self.user32.IsWindowVisible(hwnd):
                return True
            pid = self.wintypes.DWORD(0)
            self.user32.GetWindowThreadProcessId(hwnd, self.ctypes.byref(pid))
            name = self._process_name(int(pid.value))
            if name not in self.names:
                return True
            cls = self.ctypes.create_unicode_buffer(128)
            self.user32.GetClassNameW(hwnd, cls, 128)
            title = self.ctypes.create_unicode_buffer(256)
            self.user32.GetWindowTextW(hwnd, title, 256)
            rect = self.wintypes.RECT()
            self.user32.GetWindowRect(hwnd, self.ctypes.byref(rect))
            width, height = rect.right - rect.left, rect.bottom - rect.top
            if width <= 1 or height <= 1:
                return True
            found.append({
                "hwnd": int(hwnd or 0), "pid": int(pid.value), "process": name,
                "class": cls.value, "title": title.value,
                "rect": [rect.left, rect.top, rect.right, rect.bottom],
                "kind": classify(cls.value, title.value, width, height),
            })
            return True

        self.user32.EnumWindows(self.WNDENUMPROC(visit), 0)
        return found

    def _grab_frame(self, now_ms: float, windows: list[dict[str, Any]]) -> None:
        try:
            from PIL import ImageGrab
        except ImportError:
            return
        try:
            image = ImageGrab.grab(all_screens=False)
        except Exception as error:  # noqa: BLE001 - a missing desktop is recorded, not fatal
            self.frames.append({"epoch_ms": now_ms, "error": type(error).__name__})
            return
        record: dict[str, Any] = {"epoch_ms": now_ms, "size": list(image.size)}
        splash = next((w for w in windows if w["kind"] in {"launcher_splash", "qt_splash"}), None)
        if splash is not None:
            left, top, right, bottom = splash["rect"]
            # Left third of the splash: the animation area of both splashes.
            crop = image.crop((left, top, left + max(1, (right - left) // 3), bottom))
            record["splash_kind"] = splash["kind"]
            record["animation_signature"] = hashlib.sha256(crop.tobytes()).hexdigest()[:16]
        if self.frames_dir is not None:
            name = f"{int(now_ms)}.png"
            image.resize((image.width // 2, image.height // 2)).save(self.frames_dir / name)
            record["file"] = name
        self.frames.append(record)

    def _run(self) -> None:
        user32 = self.user32
        next_frame = 0.0
        while not self._stop.is_set():
            now_ms = time.time() * 1000
            try:
                windows = self._windows()
                foreground = int(user32.GetForegroundWindow() or 0)
            except Exception as error:  # noqa: BLE001
                windows, foreground = [], 0
                self.samples.append({"epoch_ms": now_ms, "error": type(error).__name__})
            self.samples.append({"epoch_ms": now_ms, "windows": windows, "foreground": foreground})
            if self.frame_every_ms and now_ms >= next_frame:
                self._grab_frame(now_ms, windows)
                next_frame = now_ms + self.frame_every_ms
            self._stop.wait(SAMPLE_MS / 1000)


def classify(cls: str, title: str, width: int, height: int) -> str:
    if cls == SPLASH_CLASS:
        return "launcher_splash"
    if cls == PROGRESS_CLASS or (cls.startswith("MetrolizaLauncher")):
        return "launcher_progress"
    if cls.startswith("Qt"):
        # The Qt startup splash is the only small frameless application window (500x190
        # logical px; its title is the executable name). The main window is much larger.
        if width <= 900 and height <= 400:
            return "qt_splash"
        return "main_window"
    if cls == "#32770":
        return "message_box"
    return "other"


# ---------------------------------------------------------------- analysis


def launcher_marks(log: Path) -> dict[str, float]:
    marks: dict[str, float] = {}
    if not log.is_file():
        return marks
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("timing "):
            continue
        fields = dict(part.split("=", 1) for part in line.split()[1:] if "=" in part)
        try:
            marks.setdefault(fields["event"], float(fields["epoch_ms"]))
        except (KeyError, ValueError):
            continue
    return marks


def window_timeline(samples: list[dict[str, Any]], launched_ms: float) -> dict[str, Any]:
    """Appearance and disappearance of each window kind, gaps and overlaps, relative to launch."""
    first: dict[str, float] = {}
    last: dict[str, float] = {}
    gaps: list[tuple[float, float]] = []
    overlap_ms = 0.0
    main_foreground: bool | None = None
    previous_t = None
    gap_start = launched_ms
    any_visible_before = False
    main_seen = False
    for sample in samples:
        t = sample["epoch_ms"]
        windows = sample.get("windows", [])
        kinds = [w["kind"] for w in windows]
        for kind in set(kinds):
            first.setdefault(kind, t - launched_ms)
            last[kind] = t - launched_ms
        visible = bool(windows)
        if not main_seen:
            if visible:
                if gap_start is not None:
                    gaps.append((gap_start - launched_ms, t - launched_ms))
                    gap_start = None
                any_visible_before = True
            elif gap_start is None:
                gap_start = t
        splashes = sum(1 for k in kinds if k in {"launcher_splash", "qt_splash", "launcher_progress"})
        if splashes >= 2 and previous_t is not None:
            overlap_ms += t - previous_t
        if "main_window" in kinds and not main_seen:
            main_seen = True
            mains = [w["hwnd"] for w in windows if w["kind"] == "main_window"]
            main_foreground = sample.get("foreground") in mains
        previous_t = t
    longest_gap = max((end - start for start, end in gaps[1:]), default=0.0)
    return {
        "first_visible_ms": {kind: round(value) for kind, value in sorted(first.items())},
        "last_visible_ms": {kind: round(value) for kind, value in sorted(last.items())},
        "initial_blank_ms": round(gaps[0][1] - gaps[0][0]) if gaps else None,
        "longest_blank_after_first_window_ms": round(longest_gap),
        "blank_intervals_ms": [[round(a), round(b)] for a, b in gaps[1:]],
        "splash_overlap_ms": round(overlap_ms),
        "main_window_foreground_when_shown": main_foreground,
        "any_window_before_main": any_visible_before,
    }


LAUNCHER_WINDOW_KINDS = ("launcher_splash", "launcher_progress")
# Cache outcomes for which the launcher extracts or verifies before it starts the entry.
RUNTIME_WORK_CACHES = {"cold", "verified", "repair"}


def launcher_window_check(cache: str | None, first_visible: dict[str, Any],
                          splash_disabled: bool) -> tuple[list[str], str | None]:
    """Launcher windows seen in a launch, and a warning when its runtime work had the wrong one.

    Extraction and verification must always show a launcher window: the splash, or the plain
    progress window (the current launcher, and the splash launcher's fallback). With the splash
    disabled the fallback progress window is expected and the splash must not appear.
    """
    seen = [kind for kind in LAUNCHER_WINDOW_KINDS if kind in first_visible]
    if cache not in RUNTIME_WORK_CACHES:
        return seen, None
    if splash_disabled:
        if "launcher_progress" not in seen:
            return seen, "splash disabled: expected the fallback progress window during runtime work"
        if "launcher_splash" in seen:
            return seen, "splash disabled, but the launcher splash was shown"
        return seen, None
    if not seen:
        return seen, "runtime work without any launcher window"
    return seen, None


def animation_summary(frames: list[dict[str, Any]], launched_ms: float) -> dict[str, Any]:
    """Count consecutive identical animation-area frames while a splash was visible."""
    runs: dict[str, dict[str, Any]] = {}
    previous: dict[str, str] = {}
    for frame in frames:
        kind = frame.get("splash_kind")
        signature = frame.get("animation_signature")
        if not kind or not signature:
            continue
        entry = runs.setdefault(kind, {"frames": 0, "changed": 0, "longest_static_ms": 0.0,
                                       "_static_since": None})
        entry["frames"] += 1
        t = frame["epoch_ms"]
        if previous.get(kind) == signature:
            if entry["_static_since"] is None:
                entry["_static_since"] = t
            entry["longest_static_ms"] = max(entry["longest_static_ms"], t - entry["_static_since"])
        else:
            if kind in previous:
                entry["changed"] += 1
            entry["_static_since"] = None
        previous[kind] = signature
    return {kind: {k: (round(v) if isinstance(v, float) else v) for k, v in entry.items()
                   if not k.startswith("_")} for kind, entry in runs.items()}


def profile_points(events: list[dict[str, Any]], launched_ms: float) -> dict[str, Any]:
    wanted = (
        "supervisor_entry", "supervisor_imported", "supervisor_package_inspection_start",
        "supervisor_package_inspection_done", "supervisor_launch_start",
        "process_entry", "qapplication_create_done", "splash_shown", "splash_launcher_bridge",
        "main_window_import_done", "main_window_construct_done", "main_window_show_called",
        "first_event_loop_tick", "main_window_first_paint_tick", "launcher_splash_handoff_posted",
        "launch_ui_warmup_finished",
    )
    points: dict[str, Any] = {}
    for event in events:
        name = event.get("name")
        if name in wanted and name not in points and "epoch_ms" in event:
            points[name] = round(float(event["epoch_ms"]) - launched_ms)
        if name == "gui_stall_summary":
            points.setdefault("gui_stall", []).append(
                {k: v for k, v in event.items() if k.startswith(("phase", "max_gap", "blocked", "gaps_ge"))}
            )
    return points


# ---------------------------------------------------------------- scenarios


def failed_record(variant: str, scenario: str, exe_name: str, error: str) -> dict[str, Any]:
    """A launch (or round setup) that could not be measured, shaped like a measured record."""
    return {
        "variant": variant, "scenario": scenario, "exe": exe_name, "status": "failed",
        "error": error, "cache": None, "launcher_windows": [], "app": {}, "animation": {},
        "windows": {"first_visible_ms": {}},
    }


def remove_tree(path: Path) -> None:
    """Best-effort removal (a process killed after a timeout may still hold a file briefly)."""
    for attempt in range(3):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(1 + attempt)


def clear_directory(path: Path) -> None:
    for child in path.iterdir() if path.is_dir() else ():
        if child.is_dir() and not child.is_symlink():
            remove_tree(child)
        else:
            child.unlink(missing_ok=True)


class Timeline:
    def __init__(self, out: Path, *, frames: bool, frame_every_ms: int) -> None:
        self.out = out
        self.frames = frames
        # PNG files are kept only while this is set (the first rounds); later rounds still
        # sample the animation area, but keep no screenshots, so disk use stays bounded.
        self.save_frames = frames
        self.frame_every_ms = frame_every_ms
        self.work = Path(tempfile.mkdtemp(prefix="metroliza-timeline-"))
        self.state = self.work / "state"
        self.temp = self.work / "temp"
        self.cwd = self.work / "cwd"
        for directory in (self.state / "Roaming", self.temp, self.cwd, out / "runs"):
            directory.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        remove_tree(self.work)

    def launch(self, variant: str, scenario: str, exe: Path, root: Path, *, smoke: bool,
               expect_cache: str | None, frames: bool,
               extra_env: dict[str, str] | None = None) -> dict[str, Any]:
        """Measure one launch; any error (also a full disk) yields a failed record instead."""
        try:
            return self._launch(variant, scenario, exe, root, smoke=smoke,
                                expect_cache=expect_cache, frames=frames, extra_env=extra_env)
        except Exception as error:  # noqa: BLE001 - one failed launch must not end the run
            record = failed_record(variant, scenario, exe.name, f"{type(error).__name__}: {error}")
            print(f"  {variant}-{scenario}: failed ({record['error']})", flush=True)
            return record

    def _launch(self, variant: str, scenario: str, exe: Path, root: Path, *, smoke: bool,
                expect_cache: str | None, frames: bool,
                extra_env: dict[str, str] | None = None) -> dict[str, Any]:
        tag = f"{variant}-{scenario}"
        run_dir = self.out / "runs" / tag
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True)
        profile, log = run_dir / "profile.jsonl", run_dir / "launcher.log"
        env = build_environment(self.state, self.temp, profile, offscreen=False)
        env.update(
            METROLIZA_RUNTIME_ROOT=str(root),
            METROLIZA_LAUNCHER_LOG=str(log),
            METROLIZA_STARTUP_SPLASH="1",
            METROLIZA_STARTUP_STALL_PROBE="1",
        )
        env.update(extra_env or {})
        if not smoke:
            env.pop("METROLIZA_STARTUP_UI_SMOKE", None)
            env["METROLIZA_STARTUP_EXIT_AFTER_WARMUP"] = "1"
        sample_frames = frames and self.frames
        frames_dir = run_dir / "frames" if sample_frames and self.save_frames else None
        if frames_dir is not None:
            frames_dir.mkdir()
        sampler = WindowSampler(exe.name, frames_dir, self.frame_every_ms if sample_frames else 0)
        record: dict[str, Any] = {"variant": variant, "scenario": scenario, "exe": exe.name,
                                  "status": "ok"}
        sampler.start()
        try:
            launched = time.time() * 1000
            started = time.perf_counter()
            process = subprocess.Popen([str(exe)], env=env, cwd=self.cwd, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                code = process.wait(timeout=LAUNCH_TIMEOUT_S)
                record["exit_code"] = code
                if code != 0:
                    record["status"] = "failed"
            except subprocess.TimeoutExpired:
                _kill_tree(process)
                process.wait(timeout=60)
                record.update(status="failed", error="timeout")
            record["wall_ms"] = round((time.perf_counter() - started) * 1000)
            time.sleep(0.3)
        finally:
            sampler.stop()
        record["cache"] = launcher_cache_outcome(log)
        if expect_cache is not None and record["cache"] != expect_cache:
            record.setdefault("warnings", []).append(f"expected cache={expect_cache}, got {record['cache']}")
        marks = launcher_marks(log)
        record["launcher_marks_ms"] = {k: round(v - launched) for k, v in sorted(marks.items(), key=lambda i: i[1])}
        if "main" in marks:
            record["pre_launcher_code_ms"] = round(marks["main"] - launched)
        record["app"] = profile_points(load_events(profile), launched)
        record["windows"] = window_timeline(sampler.samples, launched)
        splash_disabled = (extra_env or {}).get("METROLIZA_LAUNCHER_SPLASH") == "0"
        record["launcher_windows"], window_warning = launcher_window_check(
            record["cache"], record["windows"]["first_visible_ms"], splash_disabled)
        if window_warning is not None:
            record.setdefault("warnings", []).append(window_warning)
        record["animation"] = animation_summary(sampler.frames, launched)
        (run_dir / "window_samples.json").write_text(
            json.dumps([s for s in sampler.samples if s.get("windows")], indent=0), encoding="utf-8")
        (run_dir / "frames.json").write_text(json.dumps(sampler.frames, indent=0), encoding="utf-8")
        (run_dir / "summary.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"  {tag}: {record['status']} exit={record.get('exit_code')} wall={record['wall_ms']} ms "
              f"cache={record['cache']} first={record['windows']['first_visible_ms']}", flush=True)
        return record


def run_variant(timeline: Timeline, variant: str, exe: Path, next_exe: Path | None,
                round_index: int = 1, extra_env: dict[str, str] | None = None,
                settle_s: float = 0.0) -> list[dict[str, Any]]:
    """One round of one variant. Its EXE copies, runtime cache and temporary files (≈1.5 GB for
    the product) are deleted when the round ends, also after a failure; only the small per-launch
    logs, samples and the kept frames stay in the output directory."""
    records: list[dict[str, Any]] = []
    home = timeline.work / f"{variant}-r{round_index}"
    try:
        _run_round(timeline, home, records, variant, exe, next_exe, round_index, extra_env, settle_s)
    except Exception as error:  # noqa: BLE001 - recorded; the next round still runs
        records.append(failed_record(f"{variant}#{round_index}", "setup", exe.name,
                                     f"{type(error).__name__}: {error}"))
        print(f"{variant} round {round_index}: failed ({records[-1]['error']})", flush=True)
    finally:
        remove_tree(home)
        clear_directory(timeline.temp)
    return records


def _run_round(timeline: Timeline, home: Path, records: list[dict[str, Any]], variant: str,
               exe: Path, next_exe: Path | None, round_index: int,
               extra_env: dict[str, str] | None, settle_s: float) -> None:
    home.mkdir()
    fresh = home / "fresh"
    fresh.mkdir()
    cold_exe = fresh / exe.name
    shutil.copy2(exe, cold_exe)  # a new file: antivirus has not seen this path yet
    root = home / "root"
    print(f"{variant} round {round_index}: {exe.name}", flush=True)
    variant = f"{variant}#{round_index}"
    records.append(timeline.launch(variant, "cold", cold_exe, root, smoke=True, expect_cache="cold", frames=True, extra_env=extra_env))
    # Let the OS write back the cold run's dirty pages, as on a real second start (minutes or days
    # later); otherwise the verification's FlushFileBuffers pays for the previous run's writes.
    if settle_s > 0:
        time.sleep(settle_s)
    records.append(timeline.launch(variant, "verified", cold_exe, root, smoke=True, expect_cache="verified", frames=True, extra_env=extra_env))
    for index in (1, 2):
        records.append(timeline.launch(variant, f"warm{index}", cold_exe, root, smoke=True,
                                       expect_cache="warm", frames=index == 1, extra_env=extra_env))
    records.append(timeline.launch(variant, "warmup", cold_exe, root, smoke=False, expect_cache="warm", frames=True, extra_env=extra_env))
    # Damage: truncate one runtime file of the current version (size check catches it).
    versions = [p for p in root.iterdir() if p.is_dir() and "_" in p.name and not p.name.endswith(".staging")] \
        if root.is_dir() else []
    if versions:
        target = max(versions, key=lambda p: p.stat().st_mtime) / CORRUPT_TARGET
        if target.is_file():
            with target.open("r+b") as handle:
                handle.truncate(max(0, target.stat().st_size - 4096))
            records.append(timeline.launch(variant, "corrupt", cold_exe, root, smoke=True,
                                           expect_cache="repair", frames=True, extra_env=extra_env))
    if next_exe is not None:
        next_copy = fresh / next_exe.name
        shutil.copy2(next_exe, next_copy)
        records.append(timeline.launch(variant, "new_version", next_copy, root, smoke=True,
                                       expect_cache="cold", frames=True, extra_env=extra_env))


def render_markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "## Windows first-run timeline (STEP2)",
        "",
        "Times in ms from process creation. `blank` = no Metroliza window visible. Hosted runner: indicative only.",
        "",
        "| Variant | Scenario | Cache | Launcher code starts | First window (kind) | Launcher windows | Blank before it | Longest blank after it | Splash overlap | Main window visible | Main window foreground | Usable (warmup done) | Longest GUI stall | Splash animation frames changed/total, longest static |",
        "|---|---|---|---:|---|---|---:|---:|---:|---:|---|---:|---:|---|",
    ]
    warnings = [f"- {r['variant']} {r['scenario']}: {w}" for r in records for w in r.get("warnings", [])]
    failures = [
        f"- {r['variant']} {r['scenario']}: exit={r.get('exit_code')} {r.get('error', '')}".rstrip()
        for r in records if r.get("status") != "ok"
    ]
    for r in records:
        w = r.get("windows") or {}
        first = w.get("first_visible_ms") or {}
        first_kind = min(first, key=first.get) if first else "none"
        app = r.get("app") or {}
        stalls = app.get("gui_stall") or [{}]
        anim = "; ".join(
            f"{kind}: {a['changed']}/{a['frames']}, {a['longest_static_ms']} ms"
            for kind, a in (r.get("animation") or {}).items()
        ) or "n/a"
        lines.append(
            f"| {r['variant']} | {r['scenario']} | {r.get('cache')} | {r.get('pre_launcher_code_ms', 'n/a')} "
            f"| {first.get(first_kind, 'n/a')} ({first_kind}) | {', '.join(r.get('launcher_windows', [])) or 'none'} "
            f"| {w.get('initial_blank_ms')} "
            f"| {w.get('longest_blank_after_first_window_ms')} | {w.get('splash_overlap_ms')} "
            f"| {first.get('main_window', 'n/a')} | {w.get('main_window_foreground_when_shown')} "
            f"| {app.get('launch_ui_warmup_finished', 'n/a')} | {stalls[-1].get('max_gap_ms', 'n/a')} | {anim} |"
        )
    if failures:
        lines += ["", "Failed launches:", "", *failures]
    if warnings:
        lines += ["", "Warnings:", "", *warnings]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", action="append", required=True,
                        help="NAME=EXE[,NEXT_VERSION_EXE][;ENV=VALUE,...]; repeat per launcher variant")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frames", action="store_true", help="save half-size screenshots")
    parser.add_argument("--frame-every-ms", type=int, default=200)
    parser.add_argument("--settle-seconds", type=float, default=0.0,
                        help="pause before the second (verified) launch of each cache")
    parser.add_argument("--rounds", type=int, default=1,
                        help="repeat the whole sequence, alternating the variants each round")
    parser.add_argument("--frame-rounds", type=int, default=2,
                        help="keep screenshot files for the first N rounds only (with --frames)")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("Windows only", file=sys.stderr)
        return 2
    # Absolute: the launched processes run in a private working directory, and the launcher log
    # and startup profile paths are handed to them through the environment.
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timeline = Timeline(args.output_dir, frames=args.frames, frame_every_ms=args.frame_every_ms)
    records: list[dict[str, Any]] = []
    try:
        run_rounds(timeline, args, records)
    finally:
        timeline.close()
        # Always written, also after failures, so the CI summary step has a file to show.
        write_outputs(args.output_dir, records)
    return exit_code(records)


# Exit code when the run completed but some samples (launches or round setups) failed; any other
# non-zero exit means the script itself failed.
SAMPLES_FAILED_EXIT = 3


def exit_code(records: list[dict[str, Any]]) -> int:
    return SAMPLES_FAILED_EXIT if any(r.get("status") != "ok" for r in records) else 0


# A round of one variant needs about 1.5 GB (EXE copies plus one or two extracted runtimes).
MIN_FREE_BYTES = 4 * 1024**3


def parse_variant(spec: str) -> tuple[str, Path, Path | None, dict[str, str]]:
    spec, _, env_text = spec.partition(";")
    name, _, paths = spec.partition("=")
    exe_text, _, next_text = paths.partition(",")
    extra_env = dict(item.split("=", 1) for item in env_text.split(",") if "=" in item)
    return name, Path(exe_text), Path(next_text) if next_text else None, extra_env


def run_rounds(timeline: Timeline, args: argparse.Namespace, records: list[dict[str, Any]]) -> None:
    specs = [parse_variant(spec) for spec in args.variant]
    for round_index in range(1, args.rounds + 1):
        timeline.save_frames = timeline.frames and round_index <= args.frame_rounds
        # Alternate the order so neither variant always runs first on a fresh runner.
        ordered = specs if round_index % 2 == 1 else list(reversed(specs))
        for name, exe, next_exe, extra_env in ordered:
            free = shutil.disk_usage(timeline.work).free
            if free < MIN_FREE_BYTES:
                records.append(failed_record(f"{name}#{round_index}", "setup", exe.name,
                                             f"stopped: {free / 1024**3:.1f} GB free"))
                print(f"stopping: only {free / 1024**3:.1f} GB free", flush=True)
                return
            records.extend(run_variant(timeline, name, exe, next_exe, round_index,
                                       extra_env, args.settle_seconds))
        write_outputs(timeline.out, records, quiet=True)  # partial results survive a crash


def write_outputs(out: Path, records: list[dict[str, Any]], *, quiet: bool = False) -> None:
    (out / "timeline.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    markdown = render_markdown(records)
    (out / "timeline.md").write_text(markdown, encoding="utf-8")
    if not quiet:
        print(markdown)


if __name__ == "__main__":
    raise SystemExit(main())
