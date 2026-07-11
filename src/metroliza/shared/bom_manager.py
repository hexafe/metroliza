"""Compatibility alias for the package-owned BOM manager UI.

The implementation moved to :mod:`metroliza.ui.bom_manager`.  Rebinding this
module name preserves the historical module identity, mutable module globals,
and the process-wide deprecation-warning state for compatibility callers.
"""

from importlib import import_module
import sys


_module = import_module("metroliza.ui.bom_manager")
sys.modules[__name__] = _module
globals().update(_module.__dict__)
