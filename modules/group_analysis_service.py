"""Compatibility shim for ``metroliza.analytics.group_analysis_service``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.analytics.group_analysis_service")
globals().update(_module.__dict__)
