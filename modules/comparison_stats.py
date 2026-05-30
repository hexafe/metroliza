"""Compatibility shim for ``metroliza.analytics.comparison_stats``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.analytics.comparison_stats")
globals().update(_module.__dict__)
