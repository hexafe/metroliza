"""Compatibility shim for ``metroliza.analytics.group_stats_tests``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.analytics.group_stats_tests")
globals().update(_module.__dict__)
