"""Compatibility shim for ``metroliza.app.license_bootstrap``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.app.license_bootstrap")
globals().update(_module.__dict__)
