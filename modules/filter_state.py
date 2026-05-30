"""Compatibility shim for ``metroliza.shared.filter_state``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.filter_state")
globals().update(_module.__dict__)
