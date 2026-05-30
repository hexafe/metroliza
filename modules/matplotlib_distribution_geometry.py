"""Compatibility shim for ``metroliza.charts.matplotlib_distribution_geometry``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.matplotlib_distribution_geometry")
globals().update(_module.__dict__)
