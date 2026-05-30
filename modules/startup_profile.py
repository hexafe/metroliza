"""Compatibility shim for ``metroliza.app.startup_profile``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.app.startup_profile")
globals().update(_module.__dict__)
