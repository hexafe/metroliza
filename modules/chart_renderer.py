"""Compatibility shim for ``metroliza.charts.chart_renderer``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.chart_renderer")
globals().update(_module.__dict__)
