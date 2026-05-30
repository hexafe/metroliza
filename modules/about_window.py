"""Compatibility shim for ``metroliza.ui.about_window``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.ui.about_window")
globals().update(_module.__dict__)
