"""Launcher splash: shared animation asset and the application-side bridge (STEP2 PoC)."""

from __future__ import annotations

import base64
import ctypes
from pathlib import Path

import pytest

from metroliza.app import launcher_splash
from metroliza.resources import base64_encoded_files

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_GIF = ROOT / "packaging" / "launcher" / "assets" / "metroliza_loading.gif"


@pytest.fixture(autouse=True)
def _fresh_bridge():
    launcher_splash.reset_for_tests()
    yield
    launcher_splash.reset_for_tests()


def test_launcher_embeds_the_application_loading_animation_unchanged():
    assert LAUNCHER_GIF.read_bytes() == base64.b64decode(base64_encoded_files.encoded_loading_gif)


def test_bridge_consumes_the_handle_so_worker_processes_never_inherit_it():
    environ = {launcher_splash.SPLASH_HWND_ENV: "1234"}
    assert launcher_splash.launcher_splash_from_environment(environ=environ, platform="linux") is None
    assert launcher_splash.SPLASH_HWND_ENV not in environ


@pytest.mark.parametrize("raw", [None, "", "abc", "-5", "0", "12x", str(2**64)])
def test_invalid_handles_are_ignored(raw):
    environ = {} if raw is None else {launcher_splash.SPLASH_HWND_ENV: raw}
    assert launcher_splash.launcher_splash_from_environment(environ=environ, platform="win32") is None


class _CopyDataUser32:
    """Records each WM_COPYDATA as the launcher would read it during the synchronous call."""

    def __init__(self):
        self.received = []

    def IsWindow(self, hwnd):  # noqa: N802 - Win32 name
        return True

    def SendMessageTimeoutW(self, hwnd, message, wparam, lparam, flags, timeout, result):  # noqa: N802
        data = launcher_splash.copydata_struct().from_address(lparam)
        # The buffer must hold the text plus a UTF-16 NUL while the call runs.
        raw = ctypes.string_at(data.lpData, data.cbData + 2)
        self.received.append((message, data.dwData, data.cbData, raw))
        return 1


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Checking license...", "Checking license..."),
        ("lone \ud800 surrogate \udfff", "lone ? surrogate ?"),
        ("duck \U0001f986", "duck \U0001f986"),
        ("", launcher_splash.DEFAULT_STATUS),
        (None, launcher_splash.DEFAULT_STATUS),
        ("x" * 500, "x" * launcher_splash.MAX_STATUS_CHARS),
        ("\U0001f986" * 200, "\U0001f986" * launcher_splash.MAX_STATUS_CHARS),
    ],
)
def test_status_text_is_sent_as_bounded_even_nul_terminated_utf16(message, expected):
    user32 = _CopyDataUser32()
    bridge = launcher_splash.LauncherSplash(77, user32)
    bridge.show_message(message, phase="test")  # never raises
    [(sent, magic, size, raw)] = user32.received
    assert sent == launcher_splash.WM_COPYDATA
    assert magic == launcher_splash.STATUS_MAGIC
    assert size == len(expected.encode("utf-16-le"))
    assert size % 2 == 0 and size <= launcher_splash.MAX_STATUS_BYTES
    assert raw[:size].decode("utf-16-le") == expected
    assert raw[size:] == b"\x00\x00"


def test_status_text_failure_is_recorded_not_raised():
    class FailingUser32(_CopyDataUser32):
        def SendMessageTimeoutW(self, *args):  # noqa: N802
            raise OSError("window gone")

    launcher_splash.LauncherSplash(77, FailingUser32()).show_message("text", phase="test")


@pytest.mark.parametrize(
    ("cache", "seen", "disabled", "warned"),
    [
        ("cold", {"launcher_splash": 50}, False, False),
        ("cold", {"launcher_progress": 2600}, False, False),  # current launcher or fallback
        ("verified", {}, False, True),
        ("repair", {"launcher_progress": 90, "qt_splash": 900}, True, False),
        ("cold", {"qt_splash": 900}, True, True),
        ("cold", {"launcher_splash": 50, "launcher_progress": 60}, True, True),
        ("warm", {}, True, False),  # no runtime work: no launcher window expected
    ],
)
def test_timeline_expects_a_launcher_window_for_runtime_work(cache, seen, disabled, warned):
    from scripts.measure_windows_first_run_timeline import launcher_window_check

    windows, warning = launcher_window_check(cache, seen, disabled)
    assert windows == [k for k in ("launcher_splash", "launcher_progress") if k in seen]
    assert (warning is not None) == warned


class _StubTimeline:
    """Stands in for the Windows-only launch: 'extracts' into the root, fails on request."""

    def __init__(self, base: Path, fail_on: str | None):
        self.work, self.temp = base / "work", base / "temp"
        self.work.mkdir()
        self.temp.mkdir()
        self.fail_on = fail_on
        self.seen = []

    def launch(self, variant, scenario, exe, root, **_kwargs):
        self.seen.append((scenario, exe.is_file()))
        if scenario == self.fail_on:
            raise OSError(28, "No space left on device")
        (root / "1.0_abc" / "_internal").mkdir(parents=True, exist_ok=True)
        (root / "1.0_abc" / "_internal" / "python311.dll").write_bytes(b"x" * 8192)
        (self.temp / f"{scenario}.tmp").write_bytes(b"t")
        return {"variant": variant, "scenario": scenario, "status": "ok"}


@pytest.mark.parametrize("fail_on", [None, "warm1"])
def test_timeline_round_removes_its_exe_copies_and_runtime_even_after_a_failure(tmp_path, fail_on):
    from scripts import measure_windows_first_run_timeline as timeline_script

    exe = tmp_path / "metroliza_launcher.exe"
    exe.write_bytes(b"MZ" * 1000)
    following = tmp_path / "next_launcher.exe"
    following.write_bytes(b"MZ" * 1000)
    stub = _StubTimeline(tmp_path, fail_on)
    records = timeline_script.run_variant(stub, "poc", exe, following, 3)

    scenarios = [scenario for scenario, _ in stub.seen]
    assert all(exists for _, exists in stub.seen), "each launch gets its EXE copy"
    if fail_on is None:
        assert scenarios == ["cold", "verified", "warm1", "warm2", "warmup", "corrupt", "new_version"]
        assert all(r["status"] == "ok" for r in records)
    else:
        assert scenarios[-1] == fail_on
        assert records[-1]["status"] == "failed" and records[-1]["scenario"] == "setup"
        assert "No space left" in records[-1]["error"]
    assert list(stub.work.iterdir()) == [], "EXE copies and runtime cache are deleted"
    assert list(stub.temp.iterdir()) == [], "per-launch temporary files are deleted"


def test_timeline_launch_errors_become_failed_records_and_still_render(tmp_path, monkeypatch):
    from scripts import measure_windows_first_run_timeline as timeline_script

    monkeypatch.setattr(timeline_script.tempfile, "tempdir", str(tmp_path))
    timeline = timeline_script.Timeline(tmp_path / "out", frames=False, frame_every_ms=200)
    try:
        def no_space(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(timeline, "_launch", no_space)
        record = timeline.launch("poc#6", "new_version", Path("poc_next.exe"), tmp_path / "root",
                                 smoke=True, expect_cache="cold", frames=True)
    finally:
        timeline.close()
    assert record["status"] == "failed" and "No space left" in record["error"]
    ok = {"variant": "poc#1", "scenario": "warm1", "status": "ok", "cache": "warm",
          "windows": {"first_visible_ms": {"launcher_splash": 40}}, "app": {}, "animation": {},
          "launcher_windows": ["launcher_splash"]}
    timeline_script.write_outputs(tmp_path, [ok, record], quiet=True)
    markdown = (tmp_path / "timeline.md").read_text(encoding="utf-8")
    assert "| poc#1 | warm1 | warm |" in markdown
    assert "Failed launches:" in markdown and "poc#6 new_version" in markdown
    assert (tmp_path / "timeline.json").is_file()


def test_bridge_posts_handoff_with_the_main_window_handle_once():
    class FakeUser32:
        def __init__(self):
            self.posted = []

        def IsWindow(self, hwnd):  # noqa: N802 - Win32 name
            return True

        def PostMessageW(self, hwnd, message, wparam, lparam):  # noqa: N802 - Win32 name
            self.posted.append((hwnd, message, wparam, lparam))
            return True

    class FakeWindow:
        def __init__(self):
            self.raised = self.activated = False

        def raise_(self):
            self.raised = True

        def activateWindow(self):  # noqa: N802 - Qt name
            self.activated = True

        def winId(self):  # noqa: N802 - Qt name
            return 0xBEEF

    user32 = FakeUser32()
    bridge = launcher_splash.LauncherSplash(77, user32)
    window = FakeWindow()
    bridge.finish(window)
    bridge.close()  # already handed off: nothing more is posted
    assert window.raised and window.activated
    assert user32.posted == [(77, launcher_splash.MSG_HANDOFF, 0xBEEF, 0)]
