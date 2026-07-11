"""Compatibility alias for :mod:`metroliza.exporting.backend_diagnostics`.

Backend diagnostics are owned by the exporting package. Binding this historical app import path
to the canonical module object preserves mutable module state and monkeypatch identity.
"""

from importlib import import_module as _import_module
import sys as _sys


_module = _import_module("metroliza.exporting.backend_diagnostics")
_sys.modules[__name__] = _module
globals().update(_module.__dict__)
