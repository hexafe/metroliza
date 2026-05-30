"""Compatibility shim for ``metroliza.ui.industrial_analytics_filter_dialog``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.ui.industrial_analytics_filter_dialog")
globals().update(_module.__dict__)
