"""Compatibility shim for ``metroliza.shared.env_utils``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.env_utils")
globals().update(_module.__dict__)
