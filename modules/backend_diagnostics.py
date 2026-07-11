"""Compatibility shim for ``metroliza.exporting.backend_diagnostics``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.exporting.backend_diagnostics")
globals().update(_module.__dict__)
