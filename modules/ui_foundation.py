"""Compatibility shim for ``metroliza.ui.ui_foundation``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.ui.ui_foundation")
globals().update(_module.__dict__)
