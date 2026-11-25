"""Native file publication primitives shared by export and SQLite snapshots."""

import errno
import os


def rename_noreplace(temporary, target):
    """Use Linux renameat2 without replacing target, or report lack of support."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError):
        return False
    at_current_directory = -100
    no_replace = 1
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if renameat2(at_current_directory, os.fsencode(temporary),
                 at_current_directory, os.fsencode(target), no_replace) == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
        return False
    raise OSError(error_number, os.strerror(error_number), str(target))
