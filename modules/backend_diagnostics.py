"""Compatibility shim for ``metroliza.app.backend_diagnostics``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.app.backend_diagnostics")
globals().update(_module.__dict__)
