"""Launcher splash: shared animation asset and the application-side bridge (STEP2 PoC)."""

from __future__ import annotations

import base64
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
