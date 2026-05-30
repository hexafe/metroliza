"""Compatibility shim for ``metroliza.charts.matplotlib_iqr_trend_geometry``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.matplotlib_iqr_trend_geometry")
globals().update(_module.__dict__)
