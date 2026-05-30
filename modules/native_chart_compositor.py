"""Compatibility shim for ``metroliza.charts.native_chart_compositor``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.native_chart_compositor")
globals().update(_module.__dict__)
