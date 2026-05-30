"""Compatibility shim for ``metroliza.shared.log_context``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.log_context")
globals().update(_module.__dict__)
