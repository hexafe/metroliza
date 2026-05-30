"""Compatibility shim for ``metroliza.ui.modify_db``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.ui.modify_db")
globals().update(_module.__dict__)
