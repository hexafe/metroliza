"""Compatibility shim for ``metroliza.ui.ui_theme_tokens``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.ui.ui_theme_tokens")
globals().update(_module.__dict__)
