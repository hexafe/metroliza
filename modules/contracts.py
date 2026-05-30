"""Compatibility shim for ``metroliza.shared.contracts``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.contracts")
globals().update(_module.__dict__)
