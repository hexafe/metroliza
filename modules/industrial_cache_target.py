"""Compatibility shim for ``metroliza.industrial.industrial_cache_target``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.industrial.industrial_cache_target")
globals().update(_module.__dict__)
