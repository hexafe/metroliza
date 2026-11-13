"""Platform exit-code conversion shared by the supervisor and portable envelope."""

import os


def system_exit_code(code: int, *, windows: bool | None = None) -> int:
    """Preserve DWORD bits through CPython's signed C exit argument on Windows.

    POSIX and values outside the unsigned DWORD range retain their existing
    behavior, including CPython/platform handling of out-of-range integers.
    """
    if windows is None:
        windows = os.name == "nt"
    return code - 2**32 if windows and 2**31 <= code <= 2**32 - 1 else code
