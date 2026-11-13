"""Bridge to the native launcher splash (Windows packaged builds).

The native launcher (``packaging/launcher``) shows its splash before any cache work and passes the
window handle in ``METROLIZA_LAUNCHER_SPLASH_HWND``. When that window exists, the application uses
it instead of creating a second, Qt splash: status texts go to the launcher window, and after the
first paint of the main window the application asks the launcher to bring the main window to the
front and close the splash. The animation keeps running in the launcher process, so it does not
stop while this process imports modules or builds the main window on its GUI thread.

Only ``ctypes`` is imported here, so the supervisor can use the module before Qt is loaded. Every
call is best effort: a missing, closed or foreign window turns the bridge into a no-op.
"""

from __future__ import annotations

import os
import sys

from metroliza.app.startup_profile import record_event

SPLASH_HWND_ENV = "METROLIZA_LAUNCHER_SPLASH_HWND"
SPLASH_CLASS = "MetrolizaLauncherSplash"
WM_APP = 0x8000
MSG_CLOSE = WM_APP + 1
MSG_HANDOFF = WM_APP + 2
WM_COPYDATA = 0x004A
STATUS_MAGIC = 0x4D4C5354
MAX_STATUS_CHARS = 120
# The launcher rejects larger or odd-sized texts (packaging/launcher, MAX_STATUS_BYTES).
MAX_STATUS_BYTES = 512
DEFAULT_STATUS = "Metroliza is loading..."
SMTO_ABORTIFHUNG = 0x0002
SEND_TIMEOUT_MS = 200

_BRIDGE: "LauncherSplash | None" = None
_BRIDGE_RESOLVED = False
_COPYDATASTRUCT = None


def encode_status_text(message: object) -> bytes:
    """UTF-16-LE bytes of a status text, as the launcher accepts them; never raises.

    Text that cannot be encoded (lone surrogates) is replaced, the length is capped at
    ``MAX_STATUS_CHARS`` characters and ``MAX_STATUS_BYTES`` bytes, and is always even.
    """
    text = message if isinstance(message, str) and message else DEFAULT_STATUS
    encoded = text[:MAX_STATUS_CHARS].encode("utf-16-le", errors="replace")
    # 120 characters outside the BMP are 480 bytes, so this cap is a guard only; it stays even.
    return encoded[:MAX_STATUS_BYTES]


def copydata_struct():
    """The Win32 ``COPYDATASTRUCT`` type (created on first use; ``ctypes`` only)."""
    global _COPYDATASTRUCT
    if _COPYDATASTRUCT is None:
        import ctypes

        class COPYDATASTRUCT(ctypes.Structure):
            _fields_ = [
                ("dwData", ctypes.c_size_t),
                ("cbData", ctypes.c_uint32),  # DWORD
                ("lpData", ctypes.c_void_p),
            ]

        _COPYDATASTRUCT = COPYDATASTRUCT
    return _COPYDATASTRUCT


class LauncherSplash:
    """StartupSplash implementation that drives the launcher's native splash window."""

    def __init__(self, hwnd: int, user32) -> None:
        self._hwnd = hwnd
        self._user32 = user32
        self._open = True

    @property
    def is_open(self) -> bool:
        return self._open and bool(self._user32.IsWindow(self._hwnd))

    def show_message(self, message: str, *, phase: str) -> None:
        """Send a status text; never raises (the text is display-only and best effort)."""
        record_event("launcher_splash_message", phase=phase)
        if not self.is_open:
            return
        import ctypes

        try:
            encoded = encode_status_text(message)
            # NUL-terminated copy that stays alive for the synchronous send below.
            buffer = ctypes.create_string_buffer(encoded, len(encoded) + 2)
            data = copydata_struct()(STATUS_MAGIC, len(encoded), ctypes.cast(buffer, ctypes.c_void_p))
            result = ctypes.c_size_t(0)
            self._user32.SendMessageTimeoutW(
                self._hwnd,
                WM_COPYDATA,
                0,
                ctypes.addressof(data),
                SMTO_ABORTIFHUNG,
                SEND_TIMEOUT_MS,
                ctypes.byref(result),
            )
        except Exception as exc:  # defensive packaged-startup guard: a status text never fails startup
            record_event("launcher_splash_message_failed", error_type=type(exc).__name__)

    def finish(self, widget: object) -> None:
        """Hand the foreground to ``widget`` (the painted main window) and close the splash."""
        record_event("launcher_splash_handoff_start")
        if hasattr(widget, "raise_"):
            widget.raise_()
        if hasattr(widget, "activateWindow"):
            widget.activateWindow()
        target = 0
        win_id = getattr(widget, "winId", None)
        if callable(win_id):
            try:
                target = int(win_id())
            except Exception:
                target = 0
        self._post(MSG_HANDOFF, target)
        record_event("launcher_splash_handoff_posted")

    def close(self) -> None:
        self._post(MSG_CLOSE, 0)
        record_event("launcher_splash_close_posted")

    def _post(self, message: int, wparam: int) -> None:
        if not self._open:
            return
        self._open = False
        try:
            self._user32.PostMessageW(self._hwnd, message, wparam, 0)
        except Exception as exc:  # pragma: no cover - defensive packaged-startup guard.
            record_event("launcher_splash_post_failed", error_type=type(exc).__name__)


def _load_user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    return user32


def _parse_handle(raw: str | None) -> int | None:
    if not raw or not raw.strip().isdigit():
        return None
    value = int(raw.strip())
    return value if 0 < value < 2**63 else None


def launcher_splash_from_environment(environ=os.environ, platform: str = sys.platform):
    """Return the bridge when a live launcher splash window was handed to this process.

    The handle is removed from ``environ`` so worker processes started later never talk to it.
    The window class is checked before the handle is used.
    """
    global _BRIDGE, _BRIDGE_RESOLVED
    if _BRIDGE_RESOLVED:
        return _BRIDGE if _BRIDGE is not None and _BRIDGE.is_open else None
    _BRIDGE_RESOLVED = True
    hwnd = _parse_handle(environ.pop(SPLASH_HWND_ENV, None))
    if hwnd is None or platform != "win32":
        return None
    try:
        import ctypes

        user32 = _load_user32()
        if not user32.IsWindow(hwnd):
            record_event("launcher_splash_gone")
            return None
        name = ctypes.create_unicode_buffer(64)
        if user32.GetClassNameW(hwnd, name, 64) <= 0 or name.value != SPLASH_CLASS:
            record_event("launcher_splash_foreign_window")
            return None
    except Exception as exc:  # pragma: no cover - defensive packaged-startup guard.
        record_event("launcher_splash_unavailable", error_type=type(exc).__name__)
        return None
    _BRIDGE = LauncherSplash(hwnd, user32)
    record_event("launcher_splash_attached")
    return _BRIDGE


def reset_for_tests() -> None:
    """Forget the cached bridge (tests only)."""
    global _BRIDGE, _BRIDGE_RESOLVED
    _BRIDGE = None
    _BRIDGE_RESOLVED = False
