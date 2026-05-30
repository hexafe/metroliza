"""Compatibility shim for ``metroliza.native_bridges.cmm_native_parser``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.native_bridges.cmm_native_parser")
globals().update(_module.__dict__)
