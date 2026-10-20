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
