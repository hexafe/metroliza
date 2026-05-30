"""Compatibility shim for ``metroliza.shared.runtime_backend_policy``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.runtime_backend_policy")
globals().update(_module.__dict__)
