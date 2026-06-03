"""Compatibility shim for ``metroliza.shared.parse_contracts``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.parse_contracts")
globals().update(_module.__dict__)
