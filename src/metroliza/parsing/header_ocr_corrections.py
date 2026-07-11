"""Compatibility alias for :mod:`metroliza.reports.header_ocr_corrections`.

Header correction rules normalize report metadata and now live with that owning package.  The
historical parsing path remains bound to the same module object for plugins and packaged builds.
"""

from importlib import import_module as _import_module
import sys as _sys


_module = _import_module("metroliza.reports.header_ocr_corrections")
_sys.modules[__name__] = _module
globals().update(_module.__dict__)
