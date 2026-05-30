"""Compatibility shim for ``metroliza.shared.bom_manager``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.bom_manager")
globals().update(_module.__dict__)
