"""Compatibility shim for ``metroliza.shared.custom_logger``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.custom_logger")
globals().update(_module.__dict__)
