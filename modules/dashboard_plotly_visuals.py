"""Compatibility shim for ``metroliza.charts.dashboard_plotly_visuals``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.dashboard_plotly_visuals")
globals().update(_module.__dict__)
