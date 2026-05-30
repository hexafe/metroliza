"""Compatibility shim for ``metroliza.ui.help_menu``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.ui.help_menu")
globals().update(_module.__dict__)
