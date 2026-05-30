"""Compatibility shim for ``metroliza.native_bridges.group_stats_native``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.native_bridges.group_stats_native")
globals().update(_module.__dict__)
